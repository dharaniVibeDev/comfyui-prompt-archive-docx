import hashlib
import json

from .archive import topology


ALIASES = {'seed': ('seed', 'noise_seed'), 'steps': ('steps',), 'cfg': ('cfg', 'guidance'), 'sampler': ('sampler_name',), 'scheduler': ('scheduler',), 'checkpoint': ('ckpt_name', 'unet_name'), 'width': ('width',), 'height': ('height',), 'batch_size': ('batch_size',)}


def capture(prompt, extra, node_id, label):
    workflow = extra.get('workflow', {})
    metadata = workflow.get('extra', {}).get('prompt_archive', {})
    structure = topology(workflow) if workflow else sorted((str(k), v['class_type']) for k, v in prompt.items() if v['class_type'] != 'PromptArchiveDOCX')
    digest = hashlib.sha256(json.dumps(structure, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    record = dict.fromkeys(['positive_prompt', 'negative_prompt', 'camera_prompt', 'lighting_prompt', 'checkpoint', 'seed', 'steps', 'cfg', 'sampler', 'scheduler', 'width', 'height', 'batch_size', 'image_path'])
    record.update(workflow_name=label or metadata.get('workflow_name') or workflow.get('extra', {}).get('workflow_name') or 'Workflow_' + digest[:8], workflow_hash=digest, workflow_file_name=metadata.get('workflow_file_name'), loras=[], notes=[], settings=[], widget_snapshot=metadata.get('widgets', []), topology=structure, prompt_sources={})

    def link(value):
        return isinstance(value, list) and len(value) == 2 and str(value[0]) in prompt and isinstance(value[1], int)

    def ancestors(start):
        found, pending = set(), [str(start)]
        while pending:
            current = pending.pop()
            if current in found or current not in prompt:
                continue
            found.add(current)
            inputs = prompt[current].get('inputs', {})
            if prompt[current]['class_type'] == 'ComfySwitchNode':
                selected = scalar(inputs.get('switch'))
                values = [inputs.get('switch'), inputs.get('on_true' if selected else 'on_false')] if isinstance(selected, bool) else inputs.values()
            else:
                values = inputs.values()
            pending += [str(v[0]) for v in values if link(v)]
        return found

    def scalar(value, seen=None):
        if not link(value):
            return value
        seen = set() if seen is None else seen
        ident = str(value[0])
        if ident in seen:
            return None
        seen.add(ident)
        source = prompt[ident]
        inputs = source.get('inputs', {})
        if source['class_type'] == 'ComfySwitchNode':
            selected = scalar(inputs.get('switch'), seen.copy())
            return scalar(inputs.get('on_true' if selected else 'on_false'), seen.copy()) if isinstance(selected, bool) else None
        if source['class_type'] == 'StringConcatenate':
            parts = [scalar(inputs[k], seen.copy()) for k in ('string_a', 'string_b', 'delimiter')]
            return parts[2].join(parts[:2]) if all(isinstance(p, str) for p in parts) else None
        # Resolve explicit primitive/value nodes only; never invent output values.
        primitive_types = {'PrimitiveString', 'PrimitiveStringMultiline', 'PrimitiveInt', 'PrimitiveFloat', 'PrimitiveBoolean', 'SeedNode'}
        if source['class_type'] not in primitive_types:
            return None
        for name in ('value', 'text', 'seed', 'noise_seed', 'string'):
            if name in inputs and len(inputs) == 1:
                return scalar(inputs[name], seen)
        return None

    active = ancestors(node_id)
    if str(node_id) not in prompt:
        active = set(prompt)
        record['notes'].append('Archive execution ID unavailable; settings may cover multiple branches.')

    for ident in sorted(active):
        node = prompt[ident]
        if node['class_type'] == 'PromptArchiveDOCX':
            continue
        inputs = node.get('inputs', {})
        values = {k: scalar(v) for k, v in inputs.items()}
        record['settings'].append({'node_id': ident, 'class_type': node['class_type'], 'title': node.get('_meta', {}).get('title', ''), 'inputs': {k: v for k, v in values.items() if v is not None}})
        if 'lora_name' in values:
            record['loras'].append({'name': values['lora_name'], 'strength_model': values.get('strength_model', values.get('strength')), 'strength_clip': values.get('strength_clip')})
        for key, value in values.items():
            if key.startswith('lora_') and isinstance(value, dict) and value.get('lora'):
                record['loras'].append({'name': value['lora'], 'strength_model': value.get('strength'), 'strength_clip': value.get('strengthTwo', value.get('strength')), 'enabled': value.get('on')})

    for field, names in ALIASES.items():
        candidates = [(s['node_id'], name, s['inputs'][name]) for s in record['settings'] for name in names if name in s['inputs']]
        unique = {json.dumps(v, sort_keys=True) for _, _, v in candidates}
        if len(unique) == 1:
            record[field] = candidates[0][2]
        elif len(unique) > 1:
            record['notes'].append(f'{field}: multiple values; per-node values retained: {candidates}')

    for role in ('positive', 'negative'):
        roots = [s['node_id'] for s in record['settings'] if role in prompt[s['node_id']].get('inputs', {}) and link(prompt[s['node_id']]['inputs'][role])]
        sources = set()
        zeroed = False
        for root in roots:
            source_id = str(prompt[root]['inputs'][role][0])
            if prompt[source_id]['class_type'] == 'ConditioningZeroOut':
                zeroed = True
                continue
            sources.update(ancestors(source_id))
        texts = []
        encoders = {i for i in sources if 'TextEncode' in prompt[i]['class_type']}
        for ident in sorted(encoders or sources):
            inputs = prompt[ident].get('inputs', {})
            for key in ('text', 'text_g', 'text_l', 'prompt'):
                if key in inputs and isinstance(scalar(inputs[key]), str):
                    item = {'node_id': ident, 'input': key, 'text': scalar(inputs[key])}
                    if item not in texts:
                        texts.append(item)
        record['prompt_sources'][role] = texts
        if zeroed and not texts:
            record[role + '_prompt'] = ''
            record['notes'].append(f'{role}: ConditioningZeroOut supplies zero conditioning; no independent text prompt.')
        if len(texts) == 1:
            record[role + '_prompt'] = texts[0]['text']
        elif texts:
            # Keep every original string separately in SQLite and visibly labeled in DOCX.
            record[role + '_prompt'] = '\n\n'.join(f"[Node {t['node_id']} / {t['input']}]\n{t['text']}" for t in texts)
            record['notes'].append(f'{role}: multiple text sources; displayed separately without rewriting source text.')

    for section in ('camera', 'lighting', 'positive', 'negative'):
        candidates = []
        for setting in record['settings']:
            if section in setting['title'].lower():
                candidates += [v for k, v in setting['inputs'].items() if k in ('text', 'prompt', 'value', 'string', 'instruction') and isinstance(v, str)]
        if record[section + '_prompt'] is None and len(candidates) == 1:
            record[section + '_prompt'] = candidates[0]
    for field in ('positive_prompt', 'negative_prompt', 'camera_prompt', 'lighting_prompt', 'checkpoint', 'seed', 'steps', 'cfg', 'sampler', 'scheduler'):
        if record[field] is None:
            record['notes'].append(field + ': unavailable or ambiguous; no value guessed.')
    if not record['widget_snapshot']:
        record['notes'].append('No frontend widget snapshot; reload supports matching API node IDs and widget names only.')
    record['notes'].append('Original image path is unavailable on an IMAGE tensor. No full-resolution image was saved by this node.')
    return record
