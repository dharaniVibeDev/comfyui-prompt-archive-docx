import importlib.util
import json
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('archive_test_package')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
from archive_test_package.archive import Store, safe_name, topology
from archive_test_package.capture import capture


class ArchiveTests(unittest.TestCase):
    def test_document_exact_text_preview_and_persistence(self):
        text = '  café & <light>\nSecond line\tend  '
        with tempfile.TemporaryDirectory() as temp:
            db = Store(temp)
            record = db.save({'workflow_name': 'Workflow A', 'workflow_hash': 'hash-a', 'positive_prompt': text, 'negative_prompt': 'avoid', 'loras': []}, Image.new('RGB', (2048, 1024), '#6699bb'), temp, '', 768, 70)
            with zipfile.ZipFile(record['docx_path']) as archive:
                self.assertEqual(len([n for n in archive.namelist() if n.startswith('word/media/')]), 1)
                with archive.open('word/media/preview.jpg') as stream, Image.open(stream) as preview:
                    self.assertEqual(preview.size, (768, 384))
                root = ET.fromstring(archive.read('word/document.xml'))
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                paragraphs = []
                for paragraph in root.findall('.//w:p', ns):
                    parts = []
                    for item in paragraph.iter():
                        if item.tag == '{' + ns['w'] + '}t': parts.append(item.text or '')
                        elif item.tag == '{' + ns['w'] + '}br': parts.append('\n')
                        elif item.tag == '{' + ns['w'] + '}tab': parts.append('\t')
                    paragraphs.append(''.join(parts))
                self.assertIn(text, paragraphs)
                self.assertFalse(any(name.endswith('.json') for name in archive.namelist()))
            self.assertLess(record['docx_bytes'], 30000)
            reopened = Store(temp)
            self.assertEqual(reopened.get(record['record_id'])['positive_prompt'], text)
            self.assertEqual(reopened.search({'workflow_name': 'Workflow A'})['total'], 1)
            self.assertEqual(reopened.search({'workflow_name': 'Workflow B'})['total'], 0)

    def test_executed_values_linked_primitives_and_sections(self):
        prompt = {
            '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'model.safetensors'}},
            '2': {'class_type': 'PrimitiveString', '_meta': {'title': 'Camera prompt'}, 'inputs': {'value': '  35mm\n camera  '}},
            '3': {'class_type': 'PrimitiveString', '_meta': {'title': 'Lighting prompt'}, 'inputs': {'value': 'soft light'}},
            '4': {'class_type': 'StringConcatenate', 'inputs': {'string_a': ['2', 0], 'string_b': ['3', 0], 'delimiter': '\n'}},
            '5': {'class_type': 'CLIPTextEncode', 'inputs': {'text': ['4', 0]}},
            '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'negative'}},
            '7': {'class_type': 'KSampler', 'inputs': {'model': ['1', 0], 'positive': ['5', 0], 'negative': ['6', 0], 'seed': 123, 'steps': 8, 'cfg': 1.2, 'sampler_name': 'euler', 'scheduler': 'simple'}},
            '8': {'class_type': 'PromptArchiveDOCX', 'inputs': {'images': ['7', 0]}},
            '9': {'class_type': 'KSampler', 'inputs': {'seed': 999}},
        }
        record = capture(prompt, {}, '8', 'A')
        self.assertEqual(record['seed'], 123)
        self.assertEqual(record['checkpoint'], 'model.safetensors')
        self.assertEqual(record['positive_prompt'], '  35mm\n camera  \nsoft light')
        self.assertEqual(record['camera_prompt'], '  35mm\n camera  ')
        self.assertEqual(record['lighting_prompt'], 'soft light')
        self.assertEqual(record['negative_prompt'], 'negative')
        self.assertNotIn('9', [s['node_id'] for s in record['settings']])

    def test_topology_ignores_values_and_archive_but_not_connections(self):
        workflow = {'nodes': [{'id': 1, 'type': 'KSampler', 'widgets_values': [1]}, {'id': 2, 'type': 'PromptArchiveDOCX'}], 'links': [[1, 1, 0, 2, 0, 'IMAGE']]}
        expected = topology(workflow)
        workflow['nodes'][0]['widgets_values'] = [999]
        self.assertEqual(topology(workflow), expected)
        workflow['nodes'][0]['type'] = 'DifferentSampler'
        self.assertNotEqual(topology(workflow), expected)
        self.assertEqual(safe_name('../CON'), '_CON')

    def test_zero_conditioning_does_not_report_positive_as_negative(self):
        prompt = {
            '1': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'exact positive'}},
            '2': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['1', 0]}},
            '3': {'class_type': 'KSampler', 'inputs': {'positive': ['1', 0], 'negative': ['2', 0]}},
            '4': {'class_type': 'PromptArchiveDOCX', 'inputs': {'images': ['3', 0]}},
        }
        record = capture(prompt, {}, '4', 'A')
        self.assertEqual(record['positive_prompt'], 'exact positive')
        self.assertEqual(record['negative_prompt'], '')

    def test_widget_input_compaction_preserves_workflow_identity(self):
        workflow = {'nodes': [{'id': 1, 'type': 'PrimitiveString'}, {'id': 2, 'type': 'StringConcatenate', 'inputs': [{'name': 'string_a'}, {'name': 'string_b'}]}], 'links': [[1, 1, 0, 2, 1, 'STRING']]}
        expected = topology(workflow)
        workflow['nodes'][1]['inputs'] = [{'name': 'string_b'}]
        workflow['links'][0][4] = 0
        self.assertEqual(topology(workflow), expected)

    def test_unknown_text_transform_is_not_treated_as_identity(self):
        prompt = {
            '1': {'class_type': 'UnknownTextTransformer', 'inputs': {'text': 'raw input'}},
            '2': {'class_type': 'CLIPTextEncode', 'inputs': {'text': ['1', 0]}},
            '3': {'class_type': 'KSampler', 'inputs': {'positive': ['2', 0]}},
            '4': {'class_type': 'PromptArchiveDOCX', 'inputs': {'images': ['3', 0]}},
        }
        record = capture(prompt, {}, '4', 'A')
        self.assertIsNone(record['positive_prompt'])


if __name__ == '__main__':
    unittest.main()
