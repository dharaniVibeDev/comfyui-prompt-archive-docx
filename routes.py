import hashlib
import asyncio
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

from aiohttp import web
from PIL import Image
from server import PromptServer

from .nodes import store
from .archive import topology


routes = PromptServer.instance.routes


@routes.get('/prompt-archive/workflows')
async def workflows(request):
    with store().connect() as db:
        rows = db.execute('SELECT workflow_name,workflow_hash,count(*),max(created_at) FROM records GROUP BY workflow_name,workflow_hash ORDER BY max(created_at) DESC').fetchall()
    return web.json_response({'workflows': [dict(zip(('name', 'hash', 'count', 'latest'), row)) for row in rows]})


@routes.post('/prompt-archive/workflow-hash')
async def workflow_hash(request):
    workflow = await request.json()
    digest = hashlib.sha256(json.dumps(topology(workflow), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return web.json_response({'workflow_hash': digest})


@routes.get('/prompt-archive/records')
async def records(request):
    try:
        return web.json_response(store().search(request.query))
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error))


def get_record(record_id):
    record = store().get(record_id)
    if record is None:
        raise web.HTTPNotFound(text='Archive record not found')
    return record


@routes.get('/prompt-archive/records/{record_id}')
async def record(request):
    return web.json_response(get_record(request.match_info['record_id']))


@routes.get('/prompt-archive/records/{record_id}/preview')
async def preview(request):
    item = get_record(request.match_info['record_id'])
    path = Path(item['docx_path'])
    if not path.is_file():
        raise web.HTTPNotFound(text='DOCX has been moved or removed')
    try:
        size = min(768, max(64, int(request.query.get('size', 768))))
    except ValueError:
        raise web.HTTPBadRequest(text='Preview size must be an integer')
    stat = path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}-{size}"'
    headers = {'ETag': etag, 'Cache-Control': 'private, max-age=300'}
    if request.headers.get('If-None-Match') == etag:
        return web.Response(status=304, headers=headers)
    def read_preview():
        with zipfile.ZipFile(path) as archive:
            data = archive.read('word/media/preview.jpg')
        if size < 768:
            with Image.open(io.BytesIO(data)) as image:
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=65, optimize=True)
                return output.getvalue()
        return data
    try:
        data = await asyncio.to_thread(read_preview)
    except (zipfile.BadZipFile, KeyError, OSError):
        raise web.HTTPNotFound(text='The DOCX preview is unavailable. The archive settings are still accessible.')
    return web.Response(body=data, content_type='image/jpeg', headers=headers)


@routes.get('/prompt-archive/records/{record_id}/docx')
async def document(request):
    item = get_record(request.match_info['record_id'])
    path = Path(item['docx_path'])
    if not path.is_file():
        raise web.HTTPNotFound(text='DOCX has been moved or removed')
    return web.FileResponse(path, headers={'Content-Disposition': 'attachment; filename="archive.docx"'})


def require_local_desktop(request):
    if request.remote not in ('127.0.0.1', '::1'):
        raise web.HTTPForbidden(text='Open folder is available only on this computer.')
    origin = request.headers.get('Origin')
    if origin and origin != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden(text='Cross-origin request rejected')
    if os.name != 'nt':
        raise web.HTTPNotImplemented(text='Opening files is available on Windows. Use Download DOCX or Copy path on this platform.')


@routes.post('/prompt-archive/records/{record_id}/open-docx')
async def open_docx(request):
    require_local_desktop(request)
    item = get_record(request.match_info['record_id'])
    path = Path(item['docx_path'])
    if not path.is_file():
        raise web.HTTPNotFound(text='DOCX has been moved or removed')
    try:
        await asyncio.wait_for(asyncio.to_thread(os.startfile, str(path)), timeout=8)
    except TimeoutError:
        raise web.HTTPRequestTimeout(text='Windows is waiting for a document app. Use Download DOCX or choose a default DOCX reader.')
    except OSError:
        raise web.HTTPConflict(text='Windows could not open this DOCX. Install a DOCX reader or use Download DOCX.')
    return web.json_response({'path': str(path)})


@routes.post('/prompt-archive/records/{record_id}/open-folder')
async def open_folder(request):
    require_local_desktop(request)
    item = get_record(request.match_info['record_id'])
    path = Path(item['docx_path']).parent
    if not path.is_dir():
        raise web.HTTPNotFound(text='Archive folder has been moved or removed')
    try:
        subprocess.Popen([str(Path(os.environ['WINDIR']) / 'explorer.exe'), str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        raise web.HTTPConflict(text='Windows could not open this folder. Use Copy path to open it manually.')
    return web.json_response({'path': str(path)})
