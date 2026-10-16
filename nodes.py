from pathlib import Path

import folder_paths
import numpy as np
from PIL import Image

from .archive import Store
from .capture import capture


def store():
    return Store(Path(folder_paths.get_output_directory()) / 'PromptArchive')


class PromptArchiveDOCX:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'images': ('IMAGE',),
            'enable_archive': ('BOOLEAN', {'default': True}),
            'workflow_label_override': ('STRING', {'default': ''}),
            'output_folder': ('STRING', {'default': 'PromptArchive', 'tooltip': 'Relative to ComfyUI output. Absolute paths must also remain inside ComfyUI output.'}),
            'filename_prefix': ('STRING', {'default': ''}),
            'preview_resolution': ('INT', {'default': 768, 'min': 128, 'max': 1536, 'step': 64}),
            'jpeg_quality': ('INT', {'default': 70, 'min': 10, 'max': 95}),
            'include_negative_prompt': ('BOOLEAN', {'default': True}),
            'include_camera_lighting': ('BOOLEAN', {'default': True}),
        }, 'optional': {'original_image_path': ('STRING', {'default': '', 'tooltip': 'Optional existing output image path, when known. The archive never saves a full-size image.'})}, 'hidden': {'prompt': 'PROMPT', 'extra_pnginfo': 'EXTRA_PNGINFO', 'unique_id': 'UNIQUE_ID'}}

    RETURN_TYPES = ()
    FUNCTION = 'save'
    CATEGORY = 'Prompt Archive'
    OUTPUT_NODE = True
    DESCRIPTION = 'Save one compact DOCX per image and retain settings globally. Browse archives to restore widgets in this same workflow.'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def save(self, images, enable_archive=True, workflow_label_override='', output_folder='PromptArchive', filename_prefix='', preview_resolution=768, jpeg_quality=70, include_negative_prompt=True, include_camera_lighting=True, original_image_path='', prompt=None, extra_pnginfo=None, unique_id=None):
        if not enable_archive:
            return {'ui': {'archive_records': [], 'archive_status': ['Archive disabled']}}
        root = Path(folder_paths.get_output_directory()).resolve()
        target = (root / output_folder).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Archive output folder must remain inside ComfyUI/output.')
        if not 128 <= preview_resolution <= 1536 or not 10 <= jpeg_quality <= 95:
            raise ValueError('Preview resolution or JPEG quality is outside the supported range.')
        record = capture(prompt or {}, extra_pnginfo or {}, str(unique_id), workflow_label_override)
        if original_image_path:
            record['image_path'] = original_image_path
            record['notes'] = [n for n in record['notes'] if not n.startswith('Original image path')]
        record['width'], record['height'] = int(images.shape[2]), int(images.shape[1])
        record['batch_size'] = int(images.shape[0])
        saved = []
        database = store()
        for index, tensor in enumerate(images):
            pixels = np.clip(tensor.detach().cpu().numpy() * 255, 0, 255).astype(np.uint8)
            item = dict(record, batch_index=index)
            image = Image.fromarray(pixels)
            result = database.save(item, image, target, filename_prefix, preview_resolution, jpeg_quality, include_negative_prompt, include_camera_lighting)
            saved.append({key: result[key] for key in ('record_id', 'docx_path', 'docx_bytes', 'workflow_name')})
        return {'ui': {'archive_records': saved, 'archive_status': [f'Saved {len(saved)} archive record(s)']}}


NODE_CLASS_MAPPINGS = {'PromptArchiveDOCX': PromptArchiveDOCX}
NODE_DISPLAY_NAME_MAPPINGS = {'PromptArchiveDOCX': 'Prompt Archive DOCX'}
