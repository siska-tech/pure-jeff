"""NNEF serialization boundary and fresh-process numerical round trip."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from test_tract_optimizer import cumsum_model


@unittest.skipUnless(os.environ.get("TRACT_PACK") and os.environ.get("TRACT_BENCH"), "set TRACT_PACK and TRACT_BENCH")
class NnefTests(unittest.TestCase):
    def test_codegen_boundary_and_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="tract-nnef-") as directory:
            root = Path(directory)
            model = root/"model.onnx"
            onnx.save(cumsum_model(), model)
            optimized = subprocess.run([os.environ["TRACT_PACK"], str(model), str(root/"optimized.tar"),
                                        "optimized"], capture_output=True, timeout=30)
            self.assertNotEqual(optimized.returncode, 0)
            self.assertIn(b"No serializer found", optimized.stderr)
            self.assertIn(b"IntoShape", optimized.stderr)
            archive = root/"decluttered.nnef.tar"
            packed = subprocess.run([os.environ["TRACT_PACK"], str(model), str(archive), "decluttered"],
                                     capture_output=True, timeout=30)
            self.assertEqual(packed.returncode, 0, packed.stderr.decode())
            before = archive.read_bytes()
            repeated = subprocess.run([os.environ["TRACT_PACK"], str(model), str(archive), "decluttered"],
                                       capture_output=True, timeout=30)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(archive.read_bytes(), before)
            inputs = {"input_ids": list(range(512)), "attention_mask": [1]*512, "mm_token_type_ids": [2]*512}
            job = root/"job.json"
            job.write_text(json.dumps({"mode": "nnef-decluttered", "cases": [{"id": "a", "inputs": inputs,
                "count": 2, "temperature": 1., "tokens": 512}],
                "schedule": [{"case": 0, "warmup": True}, {"case": 0, "warmup": False}]}))
            result = subprocess.run([os.environ["TRACT_BENCH"], str(archive), str(job)],
                                     capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([e["event"] for e in events], ["initialized", "request", "request", "completed"])
            self.assertEqual(events[0]["type_ns"], 0)
            expected = np.cumsum(np.arange(512, dtype=np.float32).reshape(8,64), axis=1).flatten()[:255]
            for event in events[1:3]:
                np.testing.assert_array_equal(event["raw_logits"], expected)


if __name__ == "__main__":
    unittest.main()
