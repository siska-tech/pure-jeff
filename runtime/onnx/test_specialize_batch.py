import unittest
from onnx import helper, TensorProto
from specialize_batch import specialize


class BatchTests(unittest.TestCase):
    def test_preserve_known_shapes_and_bind_expressions(self):
        x = helper.make_tensor_value_info("x", TensorProto.FLOAT, ["batch", 512, "8192*batch"])
        m = helper.make_model(helper.make_graph([], "shape", [x], []))
        self.assertEqual(specialize(m), 2)
        self.assertEqual([d.dim_value for d in m.graph.input[0].type.tensor_type.shape.dim], [1, 512, 8192])

    def test_reject_unknown_expression(self):
        x = helper.make_tensor_value_info("x", TensorProto.FLOAT, ["other"])
        m = helper.make_model(helper.make_graph([], "shape", [x], []))
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            specialize(m)
