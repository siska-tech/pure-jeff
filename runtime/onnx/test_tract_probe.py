"""Real ONNX -> Tract forward smoke test. Set TRACT_PROBE to opt in."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto
from normalize_sequences import lower


@unittest.skipUnless(os.environ.get("TRACT_PROBE"), "set TRACT_PROBE to the built executable")
class TractProbeTests(unittest.TestCase):
    def test_lowered_sequence_forward(self):
        inputs = [helper.make_tensor_value_info(n, TensorProto.INT64, [1, 512])
                  for n in ["input_ids", "attention_mask", "mm_token_type_ids"]]
        output = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 255])
        nodes = [helper.make_node("SplitToSequence", ["input_ids", "sizes"], ["seq"], axis=1),
                 helper.make_node("SequenceAt", ["seq", "index"], ["part"]),
                 helper.make_node("Cast", ["part"], ["logits"], to=TensorProto.FLOAT)]
        initializers = [numpy_helper.from_array(np.array([255, 257], dtype=np.int64), "sizes"),
                        numpy_helper.from_array(np.array(0, dtype=np.int64), "index")]
        model = helper.make_model(helper.make_graph(nodes, "probe", inputs, [output], initializers),
                                  opset_imports=[helper.make_opsetid("", 18)])
        model.ir_version = 10
        with tempfile.TemporaryDirectory(prefix="tract-smoke-") as directory:
            root = Path(directory)
            original = root / "original.onnx"
            lowered = root / "lowered.onnx"
            onnx.save(model, original)
            rejected = subprocess.run([os.environ["TRACT_PROBE"], str(original), "type"],
                                      capture_output=True, timeout=30)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b"SplitToSequence", rejected.stderr)
            lower(model)
            onnx.checker.check_model(model, full_check=True)
            onnx.save(model, lowered)
            values = {"input_ids": list(range(512)), "attention_mask": [1]*512, "mm_token_type_ids": [2]*512}
            path = root / "inputs.json"
            path.write_text(json.dumps(values), encoding="utf-8")
            process = subprocess.run([os.environ["TRACT_PROBE"], str(lowered), "run", str(path)],
                                     capture_output=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
            result = json.loads(process.stdout)
            self.assertTrue(result["forward_executed"])
            self.assertEqual(result["raw_logits"], list(range(255)))
            values["input_ids"].pop()
            path.write_text(json.dumps(values), encoding="utf-8")
            rejected = subprocess.run([os.environ["TRACT_PROBE"], str(lowered), "run", str(path)],
                                      capture_output=True, timeout=30)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b"exactly 512", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
