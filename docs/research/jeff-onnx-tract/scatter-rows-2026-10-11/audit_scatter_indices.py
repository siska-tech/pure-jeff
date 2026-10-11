"""Audit exact ONNX ScatterElements metadata and scalar-constant Expand indices."""
import argparse
from collections import Counter
import json
from pathlib import Path

import onnx
from onnx import numpy_helper

from benchmark_pilot import save, sha
from inspect_profile_graph import inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    expected = '4808e28131967e8ed33f8b50d46c4212e11c19b79e6dfb5209cf9b6931cd9b0c'
    if args.output.exists() or sha(args.model) != expected:
        raise ValueError('new output and frozen model required')
    model = onnx.load(args.model, load_external_data=False)
    producers = {v: n for n in model.graph.node for v in n.output}
    result = inspect(model, set())
    rows = []
    for node in result['array_nodes']:
        if node['op'] != 'ScatterElements':
            continue
        producer = producers.get(node['inputs'][1]['name'])
        constant = producers.get(producer.input[0]) if producer and producer.op_type == 'Expand' else None
        scalar = None
        if constant and constant.op_type == 'Constant':
            attrs = {a.name: a for a in constant.attribute}
            if 'value' in attrs:
                value = numpy_helper.to_array(attrs['value'].t)
                if value.size == 1:
                    scalar = int(value.item())
        node.update(index_producer=producer.name if producer else None,
            index_scalar_constant=scalar, scalar_expand_confirmed=scalar is not None,
            runtime_guard_required=True)
        rows.append(node)
    save(args.output, {'model_sha256': expected, 'script_sha256': sha(__file__), 'nodes': rows,
        'count': len(rows), 'axes': dict(Counter(n['attributes']['axis'] for n in rows)),
        'scalar_expand_confirmed': sum(n['scalar_expand_confirmed'] for n in rows),
        'scalar_indices': dict(Counter(n['index_scalar_constant'] for n in rows)),
        'scope': 'Stored ONNX shape metadata and scalar Constant -> Expand provenance only. No external weights, inferred runtime layouts or call counts. Fast path validates actual runtime shapes and indices.'})
    print(json.dumps({'nodes': len(rows), 'scalar_expand_confirmed': sum(n['scalar_expand_confirmed'] for n in rows)}))


if __name__ == '__main__':
    main()
