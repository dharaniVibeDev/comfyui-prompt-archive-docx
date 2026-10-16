"""Local storage and small, standards-compliant Word documents. No extra dependencies."""
import io
import json
import re
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:100]
    if not value or value.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        return 'Workflow'
    return value


def topology(workflow):
    """Exclude changing values, positions, titles, and the archive node itself."""
    graphs = [('', workflow)] + [(str(g['id']), g) for g in workflow.get('definitions', {}).get('subgraphs', [])]
    result = []
    for path, graph in graphs:
        nodes = {str(n['id']): n for n in graph.get('nodes', []) if n['type'] != 'PromptArchiveDOCX'}
        links = []
        for link in graph.get('links', []):
            if isinstance(link, dict):
                a, b = str(link.get('origin_id')), str(link.get('target_id'))
                slot = link.get('target_slot')
                origin_slot = link.get('origin_slot')
            else:
                a, b = str(link[1]), str(link[3])
                slot, origin_slot = link[4], link[2]
            if a in nodes and b in nodes:
                inputs = nodes[b].get('inputs', [])
                # The frontend compacts unconnected widget inputs when queueing.
                # Socket names survive that compaction; positional indexes do not.
                target = inputs[slot].get('name', str(slot)) if isinstance(slot, int) and slot < len(inputs) else str(slot)
                item = [a, origin_slot, b, target]
                links.append(item)
        result.append([path, sorted([[i, n['type']] for i, n in nodes.items()]), sorted(links, key=str)])
    return sorted(result, key=str)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'archive.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (record_id TEXT PRIMARY KEY, workflow_name TEXT NOT NULL, workflow_hash TEXT NOT NULL, created_at TEXT NOT NULL, checkpoint TEXT, loras TEXT, docx_path TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS workflow_date ON records(workflow_hash, created_at)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, record_id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM records WHERE record_id=?', (record_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def search(self, filters):
        clauses, args = [], []
        if filters.get('workflow_name_exact'):
            clauses.append('workflow_name = ?')
            args.append(filters['workflow_name_exact'])
        for key in ('workflow_name', 'workflow_hash', 'checkpoint', 'loras'):
            if filters.get(key):
                clauses.append(f'instr(lower({key}), lower(?)) > 0')
                args.append(filters[key])
        for key, op in (('date_from', '>='), ('date_to', '<=')):
            if filters.get(key):
                clauses.append(f'substr(created_at, 1, 10) {op} ?')
                args.append(filters[key])
        if filters.get('q'):
            clauses.append('instr(lower(data), lower(?)) > 0')
            args.append(filters['q'])
        limit = min(max(int(filters.get('limit', 100)), 1), 200)
        offset = max(int(filters.get('offset', 0)), 0)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.connect() as db:
            total = db.execute('SELECT count(*) FROM records' + where, args).fetchone()[0]
            rows = db.execute('SELECT record_id,workflow_name,workflow_hash,created_at,checkpoint,docx_path FROM records' + where + ' ORDER BY created_at DESC LIMIT ? OFFSET ?', args + [limit, offset]).fetchall()
        keys = ('record_id', 'workflow_name', 'workflow_hash', 'created_at', 'checkpoint', 'docx_path')
        return {'total': total, 'records': [dict(zip(keys, row)) for row in rows]}

    def save(self, record, image, output_folder, prefix, resolution=768, quality=70, include_negative=True, include_sections=True):
        record = dict(record)
        record['record_id'] = uuid.uuid4().hex
        record['created_at'] = datetime.now(timezone.utc).astimezone().isoformat(timespec='microseconds')
        folder = Path(output_folder).resolve() / safe_name(record['workflow_name']) / record['created_at'][:10]
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{safe_name(prefix or record['workflow_name'])}_{datetime.now():%H%M%S}_{record['record_id'][:10]}.docx"
        record['docx_path'] = str(folder / filename)
        preview = image.convert('RGB')
        preview.thumbnail((resolution, resolution), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        preview.save(buffer, format='JPEG', quality=quality, optimize=True)
        record['preview_width'], record['preview_height'] = preview.size
        record['preview_bytes'] = len(buffer.getvalue())
        path = Path(record['docx_path'])
        temporary = path.with_suffix('.docx.tmp')
        try:
            write_docx(temporary, record, buffer.getvalue(), include_negative, include_sections)
            temporary.replace(path)
            record['docx_bytes'] = path.stat().st_size
            with self.connect() as db:
                db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?)', (record['record_id'], record['workflow_name'], record['workflow_hash'], record['created_at'], record.get('checkpoint'), json.dumps(record.get('loras', []), ensure_ascii=False), str(path), json.dumps(record, ensure_ascii=False)))
        except Exception:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
        return record


def paragraph(text, bold=False):
    # Preserve literal spaces, line breaks, and tabs in WordprocessingML.
    text = str(text if text is not None else 'Unavailable')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
        raise ValueError('Prompt contains control characters that XML/DOCX cannot represent; no text was rewritten.')
    parts = re.split(r'(\r\n|\r|\n|\t)', text)
    runs = ''.join('<w:br/>' if p in ('\r\n', '\r', '\n') else '<w:tab/>' if p == '\t' else '<w:t xml:space="preserve">' + escape(p) + '</w:t>' for p in parts)
    return '<w:p><w:r>' + ('<w:rPr><w:b/></w:rPr>' if bold else '') + runs + '</w:r></w:p>'


def write_docx(path, record, jpeg, include_negative, include_sections):
    body = paragraph('PROMPT ARCHIVE DOCX + WORKFLOW RELOAD', True)
    width = min(6 * 914400, record['preview_width'] * 9525)
    height = int(width * record['preview_height'] / record['preview_width'])
    body += f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="{width}" cy="{height}"/><wp:docPr id="1" name="Compressed preview"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="preview.jpg"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    fields = ['workflow_name', 'workflow_hash', 'workflow_file_name', 'created_at', 'record_id', 'image_path', 'positive_prompt']
    if include_negative:
        fields.append('negative_prompt')
    if include_sections:
        fields += ['camera_prompt', 'lighting_prompt']
    fields += ['checkpoint', 'loras', 'seed', 'steps', 'cfg', 'sampler', 'scheduler', 'width', 'height', 'batch_size', 'notes']
    for key in fields:
        value = record.get(key)
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        body += paragraph(key.replace('_', ' ').title(), True) + paragraph(value)
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>' + body + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/></w:sectPr></w:body></w:document>'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="jpg" ContentType="image/jpeg"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/preview.jpg"/></Relationships>')
        archive.writestr('word/document.xml', document)
        archive.writestr('word/media/preview.jpg', jpeg, compress_type=zipfile.ZIP_STORED)
