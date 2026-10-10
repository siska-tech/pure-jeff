"""Compare original/lowered small graphs using the CPU development oracle."""
import unittest

import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper, numpy_helper, TensorProto
from normalize_sequences import lower


def model(split, indices, extent=5, axis=-1, keepdims=1, dynamic=False):
    nodes = [helper.make_node("SplitToSequence", ["x", "sizes"], ["seq"], axis=axis, keepdims=keepdims)]
    initializers = [numpy_helper.from_array(np.array(split, dtype=np.int64), "sizes")]
    outputs = []
    inputs = [helper.make_tensor_value_info("x", TensorProto.FLOAT, [2, extent])]
    for n, index in enumerate(indices):
        name, output = f"index{n}", f"y{n}"
        if dynamic:
            inputs.append(helper.make_tensor_value_info(name, TensorProto.INT64, []))
        else:
            initializers.append(numpy_helper.from_array(np.array(index, dtype=np.int64), name))
        nodes.append(helper.make_node("SequenceAt", ["seq", name], [output]))
        outputs.append(helper.make_tensor_value_info(output, TensorProto.FLOAT, [None, None]))
    m = helper.make_model(helper.make_graph(nodes, "test", inputs, outputs, initializers),
                          opset_imports=[helper.make_opsetid("", 18)])
    m.ir_version = 10
    return m


class LoweringTests(unittest.TestCase):
    def compare(self, split, indices):
        original = model(split, indices)
        converted = onnx.ModelProto()
        converted.CopyFrom(original)
        result = lower(converted)
        onnx.checker.check_model(converted, full_check=True)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        x = np.arange(10, dtype=np.float32).reshape(2, 5)
        def run(m):
            return ort.InferenceSession(m.SerializeToString(), sess_options=options,
                                        providers=["CPUExecutionProvider"]).run(None, {"x": x})
        for expected, observed in zip(run(original), run(converted)):
            np.testing.assert_array_equal(expected, observed)
        self.assertEqual(result["sequence_at_lowered"], len(indices))

    def test_vector_repeated_and_negative_indices(self):
        self.compare([2, 1, 2], [2, 0, -2, 0])

    def test_scalar_partial_final_chunk(self):
        self.compare(2, [0, 1, 2, -1])

    def test_reject_dynamic_index(self):
        with self.assertRaisesRegex(ValueError, "constant scalar"):
            lower(model(2, [0], dynamic=True))

    def test_reject_out_of_range(self):
        for index in [3, -4]:
            with self.assertRaisesRegex(ValueError, "out of range"):
                lower(model(2, [index]))

    def test_reject_keepdims_zero(self):
        with self.assertRaisesRegex(ValueError, "keepdims"):
            lower(model(2, [0], keepdims=0))

    def test_reject_unknown_extent(self):
        m = model(2, [0])
        m.graph.input[0].type.tensor_type.shape.dim[1].dim_param = "unknown"
        with self.assertRaisesRegex(ValueError, "static positive"):
            lower(m)

    def test_reject_other_consumer(self):
        m = model(2, [0])
        m.graph.node.append(helper.make_node("SequenceLength", ["seq"], ["count"]))
        with self.assertRaisesRegex(ValueError, "non-SequenceAt"):
            lower(m)


if __name__ == "__main__":
    unittest.main()
