"""Verify generated internal timers preserve graph execution and nested accounting."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import onnx
from test_tract_optimizer import cumsum_model


@unittest.skipUnless(os.environ.get("TRACT_DRIVER_BENCH") and os.environ.get("TRACT_PACK"), "set TRACT_DRIVER_BENCH and TRACT_PACK")
class DriverTests(unittest.TestCase):
    def test_control_and_instrumented_graph(self):
        with tempfile.TemporaryDirectory(prefix="tract-driver-") as directory:
            root = Path(directory)
            model = root/"model.onnx"
            onnx.save(cumsum_model(), model)
            archive = root/"model.nnef.tar"
            subprocess.run([os.environ["TRACT_PACK"], str(model), str(archive), "decluttered"],
                           check=True, capture_output=True, timeout=30)
            outputs = []
            for enabled in [False, True]:
                job = root/"job.json"
                job.write_text(json.dumps({"mode": "nnef-decluttered", "profile_driver": enabled,
                    "profile_codegen": enabled,
                    "cases": [{"id": "a", "count": 2, "temperature": 1., "tokens": 512,
                               "inputs": {"input_ids": list(range(512)), "attention_mask": [1]*512, "mm_token_type_ids": [2]*512}}],
                    "schedule": [{"case": 0, "warmup": False}, {"case": 0, "warmup": False}]}))
                result = subprocess.run([os.environ["TRACT_DRIVER_BENCH"], str(archive), str(job)],
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                events = [json.loads(line) for line in result.stdout.splitlines()]
                outputs.append([e["raw_logits"] for e in events[1:-1]])
                rows = events[0]["driver_profile"]
                if enabled:
                    self.assertTrue({"patch_apply", "duplicate_search", "compact"} <= rows.keys())
                    self.assertLessEqual(sum(row[2] for row in rows.values()), events[0]["optimize_ns"])
                    for calls, inclusive, exclusive in rows.values():
                        self.assertGreater(calls, 0)
                        self.assertGreaterEqual(inclusive, exclusive)
                else:
                    self.assertEqual(rows, {})
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0][0], outputs[0][1])


if __name__ == "__main__":
    unittest.main()
