"""Real overwrite/reduction ScatterElements regression against the frozen control."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from onnx import TensorProto as T, helper as h, numpy_helper as nh


def model(shape, update_shape, axis, indices, dtype, reduction):
    constants = [nh.from_array(np.array(shape, dtype=np.int64), 'shape'),
        nh.from_array(np.array(update_shape, dtype=np.int64), 'update_shape'),
        nh.from_array(np.array([1, 512], dtype=np.int64), 'flat'),
        nh.from_array(indices.astype(np.int64), 'indices'),
        nh.from_array(np.array([0], dtype=np.int64), 'start'),
        nh.from_array(np.array([255], dtype=np.int64), 'end'),
        nh.from_array(np.array([1], dtype=np.int64), 'slice_axis'),
        nh.from_array(np.array([np.prod(update_shape)], dtype=np.int64), 'update_end')]
    nodes = [h.make_node('Cast', ['input_ids'], ['data_cast'], to=dtype),
        h.make_node('Reshape', ['data_cast', 'shape'], ['data']),
        h.make_node('Add', ['attention_mask', 'mm_token_type_ids'], ['sum']),
        h.make_node('Cast', ['sum'], ['updates_cast'], to=dtype),
        h.make_node('Slice', ['updates_cast', 'start', 'update_end', 'slice_axis'], ['short']),
        h.make_node('Reshape', ['short', 'update_shape'], ['updates']),
        h.make_node('ScatterElements', ['data', 'indices', 'updates'], ['scatter'], axis=axis, reduction=reduction),
        h.make_node('Cast', ['scatter'], ['float'], to=T.FLOAT),
        h.make_node('Reshape', ['float', 'flat'], ['flattened']),
        h.make_node('Slice', ['flattened', 'start', 'end', 'slice_axis'], ['logits'])]
    graph = h.make_graph(nodes, 'scatter', [h.make_tensor_value_info(n, T.INT64, [1, 512])
        for n in ['input_ids', 'attention_mask', 'mm_token_type_ids']],
        [h.make_tensor_value_info('logits', T.FLOAT, [1, 255])], constants)
    return h.make_model(graph, opset_imports=[h.make_opsetid('', 18)], ir_version=10)


@unittest.skipUnless(all(os.environ.get(k) for k in ['TRACT_TRILU_BENCH', 'TRACT_SCATTER_BENCH']),
    'set frozen Trilu and isolated Scatter executables')
class ScatterTests(unittest.TestCase):
    def test_actual_operator_matches_control_and_scalar(self):
        inputs = {'input_ids': list(range(-203, 309)), 'attention_mask': [2]*512, 'mm_token_type_ids': [1]*512}
        job = {'mode': 'typed', 'threads': 4, 'profile_forward': False,
            'cases': [{'id': 'a', 'count': 2, 'temperature': 1., 'tokens': 512, 'inputs': inputs}],
            'schedule': [{'case': 0, 'warmup': False}]*2}
        with tempfile.TemporaryDirectory(prefix='scatter-regression-') as directory:
            root = Path(directory)
            (root/'job.json').write_text(json.dumps(job), encoding='utf-8')
            for shape, update_shape, axis in [([4, 8, 16], [4, 3, 16], 1), ([8, 64], [3, 64], 0),
                    ([16, 32], [16, 4], 1), ([2, 8, 32], [1, 3, 32], 1)]:
                for pattern in ['uniform', 'negative', 'duplicate', 'varying']:
                    indices = np.zeros(update_shape, dtype=np.int64)
                    for coords in np.ndindex(*update_shape):
                        index = (coords[axis] if pattern != 'duplicate' else 0) % shape[axis]
                        if pattern == 'varying': index = (index + coords[-1]) % shape[axis]
                        indices[coords] = index - (shape[axis] if pattern == 'negative' else 0)
                    for dtype, numpy_type in [(T.FLOAT, np.float32), (T.INT32, np.int32), (T.INT64, np.int64), (T.BOOL, np.bool_)]:
                        for reduction in (['none'] if dtype == T.BOOL else ['none', 'add', 'mul', 'min', 'max']):
                            with self.subTest(shape=shape, updates=update_shape, axis=axis, pattern=pattern, dtype=dtype, reduction=reduction):
                                graph = model(shape, update_shape, axis, indices, dtype, reduction)
                                onnx.checker.check_model(graph)
                                onnx.save(graph, root/'model.onnx')
                                expected = np.array(inputs['input_ids'], dtype=numpy_type).reshape(shape)
                                for coords in np.ndindex(*update_shape):
                                    dest = list(coords)
                                    dest[axis] = indices[coords]
                                    dest = tuple(dest)
                                    value = numpy_type(3)
                                    if reduction == 'none': expected[dest] = value
                                    elif reduction == 'add': expected[dest] += value
                                    elif reduction == 'mul': expected[dest] *= value
                                    elif reduction == 'min': expected[dest] = min(expected[dest], value)
                                    elif reduction == 'max': expected[dest] = max(expected[dest], value)
                                expected = expected.astype(np.float32).reshape(-1)[:255].tolist()
                                for key in ['TRACT_TRILU_BENCH', 'TRACT_SCATTER_BENCH']:
                                    result = subprocess.run([os.environ[key], str(root/'model.onnx'), str(root/'job.json')],
                                        capture_output=True, timeout=30)
                                    if dtype == T.INT64 and reduction != 'none':
                                        self.assertNotEqual(result.returncode, 0)
                                        self.assertIn('TDim is not a number', result.stderr.decode('utf-8'))
                                        continue
                                    self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
                                    events = [json.loads(line) for line in result.stdout.splitlines()]
                                    for event in events[1:-1]: self.assertEqual(event['raw_logits'], expected)


if __name__ == '__main__':
    unittest.main()
