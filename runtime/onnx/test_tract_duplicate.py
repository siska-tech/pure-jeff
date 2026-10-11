"""Compare valid graph structure and execution across the isolated single change."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import onnx
from test_tract_optimizer import cumsum_model


@unittest.skipUnless(all(os.environ.get(k) for k in ["TRACT_PATCH_CONTROL", "TRACT_PATCH_CANDIDATE",
    "TRACT_DUPLICATE_BENCH", "TRACT_BENCH", "TRACT_PACK"]), "set isolated patch experiment executables")
class DuplicateTests(unittest.TestCase):
    def test_patch_structure_and_values(self):
        results = []
        for key in ["TRACT_PATCH_CONTROL", "TRACT_PATCH_CANDIDATE"]:
            result = subprocess.run([os.environ[key]], check=True, capture_output=True, timeout=30)
            results.append([json.loads(line) for line in result.stdout.splitlines()])
        self.assertEqual(len(results[0]), 3)
        self.assertEqual(results[0], results[1])

    def test_small_nnef_repeated_outputs(self):
        with tempfile.TemporaryDirectory(prefix="tract-duplicate-") as directory:
            root = Path(directory)
            model, archive, job = root/"model.onnx", root/"model.nnef.tar", root/"job.json"
            onnx.save(cumsum_model(), model)
            subprocess.run([os.environ["TRACT_PACK"], str(model), str(archive), "decluttered"],
                           check=True, capture_output=True, timeout=30)
            job.write_text(json.dumps({"mode": "nnef-decluttered", "profile_codegen": False,
                "cases": [{"id": "a", "count": 2, "temperature": 1., "tokens": 512,
                           "inputs": {"input_ids": list(range(512)), "attention_mask": [1]*512,
                                      "mm_token_type_ids": [2]*512}}],
                "schedule": [{"case": 0, "warmup": False}]*2}))
            results = []
            for key in ["TRACT_BENCH", "TRACT_DUPLICATE_BENCH"]:
                result = subprocess.run([os.environ[key], str(archive), str(job)],
                                        check=True, capture_output=True, timeout=30)
                events = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertIsNone(events[0]["codegen_profile"])
                results.append([e["raw_logits"] for e in events[1:-1]])
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0][0], results[0][1])


if __name__ == "__main__":
    unittest.main()
