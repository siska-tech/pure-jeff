"""Reproduce CumSum Scan axis optimization independently of Jeff weights."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto


def cumsum_model():
    inputs = [helper.make_tensor_value_info(n, TensorProto.INT64, [1, 512])
              for n in ["input_ids", "attention_mask", "mm_token_type_ids"]]
    initializers = [numpy_helper.from_array(np.array(v, dtype=np.int64), n)
                    for n, v in [("shape", [1, 1, 8, 64]), ("flat", [1, 512]),
                                 ("axis", 3), ("starts", [0]), ("ends", [255]), ("axes", [1])]]
    nodes = [helper.make_node("Cast", ["input_ids"], ["float"], to=TensorProto.FLOAT),
             helper.make_node("Reshape", ["float", "shape"], ["chunks"]),
             helper.make_node("CumSum", ["chunks", "axis"], ["sum"]),
             helper.make_node("Reshape", ["sum", "flat"], ["flattened"]),
             helper.make_node("Slice", ["flattened", "starts", "ends", "axes"], ["logits"])]
    model = helper.make_model(helper.make_graph(nodes, "cumsum-reshape", inputs,
                              [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 255])],
                              initializers), opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    onnx.checker.check_model(model, full_check=True)
    return model


@unittest.skipUnless(os.environ.get("TRACT_PROBE"), "set TRACT_PROBE")
class OptimizerTests(unittest.TestCase):
    def test_cumsum_reshape(self):
        model = cumsum_model()
        with tempfile.TemporaryDirectory(prefix="tract-optimizer-") as directory:
            root = Path(directory)
            path = root / "repro.onnx"
            onnx.save(model, path)
            values = {"input_ids": list(range(512)), "attention_mask": [1]*512, "mm_token_type_ids": [2]*512}
            data = root / "inputs.json"
            data.write_text(json.dumps(values), encoding="utf-8")
            baseline = subprocess.run([os.environ["TRACT_PROBE"], str(path), "run", str(data)],
                                      capture_output=True, timeout=30)
            self.assertNotEqual(baseline.returncode, 0)
            self.assertIn(b"Incompatible reshape", baseline.stderr)
            self.assertIn(b"ChangeAxes", baseline.stderr)
            selected = subprocess.run([os.environ["TRACT_PROBE"], str(path), "run-no-change-axes", str(data)],
                                      capture_output=True, timeout=30)
            self.assertEqual(selected.returncode, 0, selected.stderr.decode("utf-8"))
            actual = json.loads(selected.stdout)["raw_logits"]
            expected = np.cumsum(np.arange(512, dtype=np.float32).reshape(8, 64), axis=1).flatten()[:255]
            np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
