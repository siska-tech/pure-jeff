"""Read-only static audit helper; stdlib only, no model execution or runtime dependency.

Decode selected ONNX protobuf fields using the field numbers in ONNX's schema.
This is an inventory reader, not an ONNX checker or an importer compatibility test.
Usage: python -B docs/research/jeff-onnx-tract/inspect_assets.py
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'experiments/runs/onnx-tract-analysis'
OUT = Path(__file__).resolve().parent
TRACT = ROOT.parent / 'tract'
REV = '9e0cfaa9b3a9251f41f74101801dc2c937b1660a'


def varint(buf, pos):
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
        shift += 7
        assert shift < 70


def fields(buf):
    pos = 0
    while pos < len(buf):
        key, pos = varint(buf, pos)
        num, wire = key >> 3, key & 7
        assert num > 0
        if wire == 0:
            value, pos = varint(buf, pos)
        elif wire == 2:
            size, pos = varint(buf, pos)
            value = buf[pos:pos + size]
            pos += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = buf[pos:pos + size]
            pos += size
        else:
            raise ValueError(f'unsupported protobuf wire type {wire}')
        assert pos <= len(buf)
        yield num, wire, value


def one(buf, num, default=None):
    return next((v for n, _, v in fields(buf) if n == num), default)


def string(value):
    return bytes(value).decode('utf-8') if value is not None else ''


def ints(buf, num):
    result = []
    for n, wire, value in fields(buf):
        if n != num:
            continue
        if wire == 0:
            result.append(value)
        else:
            pos = 0
            while pos < len(value):
                item, pos = varint(value, pos)
                result.append(item)
    return result


def value_info(buf):
    tensor = one(one(buf, 2), 1)
    shape = one(tensor, 2)
    dims = []
    for n, _, dim in fields(shape):
        if n == 1:
            dims.append(one(dim, 1, string(one(dim, 2))))
    return {'name': string(one(buf, 1)), 'elem_type': one(tensor, 1), 'shape': dims}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(*args):
    return subprocess.check_output([
        'git', '-c', f'safe.directory={TRACT.as_posix()}', '-C', str(TRACT), *args
    ], text=True, encoding='utf-8')


def main():
    data = memoryview((ASSETS / 'model.onnx').read_bytes())
    graph = one(data, 7)
    counter, tensor_types, external_locations = Counter(), Counter(), Counter()
    attribute_names = {}
    samples, external, nodes = [], [], []
    constants = {}
    graph_count = 0
    raw_bytes = 0

    def walk(g):
        nonlocal graph_count, raw_bytes
        graph_count += 1
        for num, _, node in fields(g):
            if num == 1:
                domain, op = string(one(node, 7)), string(one(node, 4))
                key = f'{domain or "ai.onnx"}::{op}'
                counter[key] += 1
                attrs = []
                details = {}
                inputs = [string(v) for n, _, v in fields(node) if n == 1]
                outputs = [string(v) for n, _, v in fields(node) if n == 2]
                for n, _, attr in fields(node):
                    if n != 5:
                        continue
                    attrs.append(string(one(attr, 1)))
                    attr_name = string(one(attr, 1))
                    if one(attr, 3) is not None:
                        value = one(attr, 3)
                        details[attr_name] = value if value < 2**63 else value - 2**64
                    if op == 'Constant':
                        t = one(attr, 5)
                        if t is not None and one(t, 2) == 7:
                            raw = one(t, 9)
                            vals = list(struct.unpack('<' + 'q' * (len(raw) // 8), raw)) if raw is not None and len(raw) <= 64 else ints(t, 7)
                            if vals and len(vals) <= 8:
                                constants[outputs[0]] = vals
                        elif attr_name == 'value_ints':
                            constants[outputs[0]] = ints(attr, 8)
                        elif attr_name == 'value_int':
                            constants[outputs[0]] = [one(attr, 3)]
                    for an, _, av in fields(attr):
                        if an in (6, 11):
                            walk(av)
                attribute_names.setdefault(key, set()).update(attrs)
                nodes.append({'op': op, 'name': string(one(node, 3)), 'inputs': inputs, 'outputs': outputs, 'attributes': details})
                if len(samples) < 5 or op in ('Trilu', 'CumSum', 'ScatterND') and not any(x['op'] == op for x in samples):
                    samples.append({'op': op, 'name': string(one(node, 3)), 'attributes': attrs})
            elif num == 5:
                dtype = one(node, 2)
                tensor_types[str(dtype)] += 1
                raw_bytes += len(one(node, 9, b''))
                if one(node, 14, 0) == 1:
                    ext = {string(one(v, 1)): string(one(v, 2)) for n, _, v in fields(node) if n == 13}
                    external_locations[ext.get('location', '')] += 1
                    external.append({'name': string(one(node, 8)), 'dims': ints(node, 1), 'dtype': dtype, **ext})

    walk(graph)
    producers = {output: i for i, node in enumerate(nodes) for output in node['outputs']}
    pending = [string(one(v, 1)) for n, _, v in fields(graph) if n == 12]
    reachable = set()
    while pending:
        i = producers.get(pending.pop())
        if i is None or i in reachable:
            continue
        reachable.add(i)
        pending.extend(nodes[i]['inputs'])
    sequence_nodes = []
    for i, node in enumerate(nodes):
        if node['op'] in ('SplitToSequence', 'SequenceAt'):
            sequence_nodes.append({**node, 'reaches_output': i in reachable,
                                   'constant_inputs': {name: constants[name] for name in node['inputs'] if name in constants}})
    source_paths = git('ls-tree', '-r', '--name-only', REV, 'onnx/src/ops').splitlines()
    registry = {}
    for path in source_paths:
        if not path.endswith('.rs'):
            continue
        source = git('show', f'{REV}:{path}')
        # Names may also be registered through loops; record explicit sites here.
        for op in re.findall(r'reg\.insert\(\s*"([^"]+)"', source):
            registry.setdefault(op, []).append(path)
    operators = [
        {'domain_op': key, 'count': count,
         'attributes': sorted(attribute_names[key]),
         'tract_0_23_8_explicit_registration': registry.get(key.split('::')[1], [])}
        for key, count in sorted(counter.items())
    ]
    metadata = json.loads((OUT / 'hf-metadata.json').read_text(encoding='utf-8'))
    result = {
        'checked_on': '2026-10-10',
        'method': 'Static protobuf inventory; no external weights loaded, no ONNX checker or Tract execution',
        'onnx_repository_revision': metadata['sha'],
        'graph_sha256': sha(ASSETS / 'model.onnx'),
        'graph_bytes': len(data),
        'ir_version': one(data, 1),
        'producer': string(one(data, 2)), 'producer_version': string(one(data, 3)),
        'opsets': [{'domain': string(one(v, 1)), 'version': one(v, 2)} for n, _, v in fields(data) if n == 8],
        'local_function_count': sum(n == 25 for n, _, _ in fields(data)),
        'graphs': graph_count,
        'node_count': sum(counter.values()), 'operators': operators,
        'output_reachable_node_count': len(reachable),
        'sequence_nodes': sequence_nodes,
        'final_nodes': nodes[-5:],
        'inputs': [value_info(v) for n, _, v in fields(graph) if n == 11],
        'outputs': [value_info(v) for n, _, v in fields(graph) if n == 12],
        'initializer_dtype_counts': dict(tensor_types),
        'initializer_inline_raw_bytes': raw_bytes,
        'external_locations': dict(external_locations),
        'external_tensor_count': len(external),
        'external_declared_bytes_sum': sum(int(x.get('length', 0)) for x in external),
        'external_max_end': max(int(x.get('offset', 0)) + int(x.get('length', 0)) for x in external),
        'external_samples': external[:3] + [x for x in external if 'readout' in x['name']],
        'tract_source_revision': REV,
        'registry_warning': 'Registration by name is not proof of dtype/shape/attribute/opset compatibility. Sources read via git show of official release commit, not local working tree/cache.',
        'node_samples': samples,
    }
    expected = next(x['lfs']['sha256'] for x in metadata['siblings'] if x['rfilename'] == 'model.onnx')
    assert result['graph_sha256'] == expected
    (OUT / 'onnx-static-inventory.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    lines = [
        '# 公開Jeff ONNXの全演算子', '',
        '2026-10-10。固定graphの静的集計。実行互換性の認定ではない。', '',
        f'Graph SHA-256: `{result["graph_sha256"]}`。opset 18、113,333ノード、48種類。', '',
        '[互換性マトリクス](../../onnx-tract-compatibility.md) / [JSON証跡](onnx-static-inventory.json)', '',
        '| ONNX演算子 | 個数 | Tract 0.23.8の明示登録先 |',
        '| --- | ---: | --- |',
    ]
    for op in operators:
        sites = op['tract_0_23_8_explicit_registration']
        links = ', '.join(f'[{p}](https://github.com/sonos/tract/blob/{REV}/{p})' for p in sites)
        lines.append(f'| {op["domain_op"].split("::")[1]} | {op["count"]:,} | {links or "**登録なし**"} |')
    lines += ['', '登録あり46種類もdtype・shape・attributes・opsetの実条件での試験が必要。',
              '未登録2種類は出力へ到達するため、不要ノードとして削除するだけでは解決しない。', '']
    (OUT / 'operators.md').write_text('\n'.join(lines), encoding='utf-8')
    comparisons = []
    for name in ('decision_config.json', 'chat_template.jinja', 'processor_config.json', 'tokenizer_config.json'):
        comparisons.append({'file': name, 'native_sha256': sha(ROOT / 'models/jeff-checkpoint' / name), 'onnx_sha256': sha(ASSETS / name)})
    keys = ('step', 'base_model', 'revision', 'temperature', 'prompt_layout', 'format_version')
    native = json.loads((ROOT / 'models/jeff-checkpoint/decision_config.json').read_text())
    onnx = json.loads((ASSETS / 'decision_config.json').read_text())
    comparison = {'checked_on': '2026-10-10', 'files': comparisons,
                  'native': {k: native.get(k) for k in keys}, 'onnx': {k: onnx.get(k) for k in keys},
                  'native_provenance': native['provenance'], 'onnx_provenance': onnx['provenance'],
                  'codes_equal': native['codes'] == onnx['codes'], 'token_ids_equal': native['token_ids'] == onnx['token_ids'],
                  'codes_count': len(native['codes']),
                  'tokenizer_sha_equal_to_hf_lfs_metadata': sha(ROOT / 'models/jeff-checkpoint/tokenizer.json') == next(x['lfs']['sha256'] for x in metadata['siblings'] if x['rfilename'] == 'tokenizer.json'),
                  'weights_equal': 'not established; source training provenance and temperature differ',
                  'exporter_sha256': sha(ASSETS / 'export_onnx.py'),
                  'exporter_source_revision': 'cbd9a629f1a3d9b6829399f6f88bd3363693f9bb'}
    (OUT / 'checkpoint-comparison.json').write_text(json.dumps(comparison, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('opsets', 'ir_version', 'node_count', 'graphs', 'inputs', 'outputs', 'external_locations', 'initializer_dtype_counts')}))
    print(json.dumps(operators, indent=2))


if __name__ == '__main__':
    main()
