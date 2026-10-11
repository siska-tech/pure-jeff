"""Verify fresh request state and event boundaries in the resident benchmark."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from test_tract_optimizer import cumsum_model


@unittest.skipUnless(os.environ.get("TRACT_BENCH"), "set TRACT_BENCH")
class BenchTests(unittest.TestCase):
    def test_reused_plan_resets_state(self):
        with tempfile.TemporaryDirectory(prefix="tract-bench-") as directory:
            root = Path(directory)
            model = root/"model.onnx"
            onnx.save(cumsum_model(), model)
            inputs = {"input_ids": list(range(512)), "attention_mask": [1]*512, "mm_token_type_ids": [2]*512}
            job = root/"job.json"
            job.write_text(json.dumps({"mode": "no-change-axes", "cases": [{"id": "a", "inputs": inputs,
                "count": 2, "temperature": 1.0, "tokens": 512}],
                "schedule": [{"case": 0, "warmup": True}, {"case": 0, "warmup": False}]}), encoding="utf-8")
            result = subprocess.run([os.environ["TRACT_BENCH"], str(model), str(job)], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([e["event"] for e in events], ["initialized", "request", "request", "completed"])
            expected = np.cumsum(np.arange(512, dtype=np.float32).reshape(8,64), axis=1).flatten()[:255]
            for event in events[1:3]:
                np.testing.assert_array_equal(event["raw_logits"], expected)
                self.assertAlmostEqual(sum(event["probabilities"]), 1, places=6)
                self.assertGreater(event["forward_ns"], 0)
            self.assertTrue(events[1]["warmup"])
            self.assertFalse(events[2]["warmup"])


if __name__ == "__main__":
    unittest.main()
