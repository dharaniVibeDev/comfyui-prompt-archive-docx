"""Package import/save checks using temporary host stubs, without starting ComfyUI."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from aiohttp import web


ROOT = Path(__file__).resolve().parents[1]


class ArrayImage:
    def __init__(self, array):
        self.array = array

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.array


class Batch:
    shape = (2, 128, 256, 3)

    def __iter__(self):
        return iter([ArrayImage(np.zeros(self.shape[1:], dtype=np.float32)) for _ in range(self.shape[0])])


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        paths = types.ModuleType('folder_paths')
        paths.get_output_directory = lambda: self.temp.name
        server = types.ModuleType('server')
        server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=web.RouteTableDef()))
        self.host = patch.dict(sys.modules, {'folder_paths': paths, 'server': server})
        self.host.start()
        self.name = 'prompt_archive_release_test'
        spec = importlib.util.spec_from_file_location(self.name, ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
        self.package = importlib.util.module_from_spec(spec)
        sys.modules[self.name] = self.package
        spec.loader.exec_module(self.package)
        self.node = self.package.NODE_CLASS_MAPPINGS['PromptArchiveDOCX']()

    def tearDown(self):
        for name in list(sys.modules):
            if name == self.name or name.startswith(self.name + '.'):
                del sys.modules[name]
        self.host.stop()
        self.temp.cleanup()

    def test_registration_and_frontend_assets(self):
        self.assertEqual(self.package.NODE_DISPLAY_NAME_MAPPINGS['PromptArchiveDOCX'], 'Prompt Archive DOCX')
        web_root = ROOT / self.package.WEB_DIRECTORY
        for name in ('archive.js', 'archive.css', 'library.js', 'reload.js', 'widgets.js'):
            self.assertTrue((web_root / name).is_file(), name)
        routes = sys.modules['server'].PromptServer.instance.routes
        self.assertTrue(any(route.path == '/prompt-archive/records' for route in routes))

    def test_disabled_archive_does_not_create_storage(self):
        result = self.node.save(Batch(), enable_archive=False)
        self.assertEqual(result['ui']['archive_records'], [])
        self.assertFalse((Path(self.temp.name) / 'PromptArchive').exists())

    def test_batch_documents_and_database_persist(self):
        result = self.node.save(Batch(), workflow_label_override='Release test')
        records = result['ui']['archive_records']
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record['docx_path'] for record in records}), 2)
        module = sys.modules[self.name + '.nodes']
        store = module.store()
        for record in records:
            self.assertTrue(Path(record['docx_path']).is_file())
            item = store.get(record['record_id'])
            self.assertEqual((item['width'], item['height'], item['batch_size']), (256, 128, 2))
        self.assertEqual(store.search({'workflow_name_exact': 'Release test'})['total'], 2)
        self.assertEqual(store.search({'workflow_name_exact': 'Release'})['total'], 0)

    def test_output_cannot_escape_configured_root(self):
        with self.assertRaisesRegex(ValueError, 'inside ComfyUI/output'):
            self.node.save(Batch(), output_folder='..')

    def test_invalid_preview_options_are_rejected(self):
        with self.assertRaises(ValueError):
            self.node.save(Batch(), preview_resolution=32)
        with self.assertRaises(ValueError):
            self.node.save(Batch(), jpeg_quality=100)


if __name__ == '__main__':
    unittest.main()
