"""W1 gate logic without a browser or model forward."""
import json
import unittest

import run_w1
from run_w0 import GOLDEN


class GateTests(unittest.TestCase):
    def setUp(self):
        self.golden = json.loads((GOLDEN / "candidate-request.json").read_text(encoding="utf-8"))
        official = self.golden["official"]
        self.run = {"outcome": "completed", "code": 0, "result": {
            "rendered_prompt_sha256": self.golden["prompt_utf8_sha256"],
            "input_ids": official["inputs"]["input_ids"][0],
            "candidate_ids": [c["id"] for c in self.golden["request"]["candidates"]],
            "judgment": dict(official["judgment"]),
            "probabilities": [p + 5e-5 for p in official["probabilities"]]}}

    def test_matching_run_passes_within_bound(self):
        checks, error = run_w1.judge_run(self.run, self.golden, 1e-4)
        self.assertTrue(all(checks.values()), checks)
        self.assertAlmostEqual(error, 5e-5)

    def test_each_mismatch_fails(self):
        for key, value in [("probabilities", [0.5, 0.5]), ("input_ids", [1]),
                           ("judgment", {"kind": "abstained"}), ("candidate_ids", ["alternative", "original"]),
                           ("rendered_prompt_sha256", "0" * 64)]:
            run = json.loads(json.dumps(self.run))
            run["result"][key] = value
            self.assertFalse(all(run_w1.judge_run(run, self.golden, 1e-4)[0].values()), key)

    def test_error_or_panic_fails(self):
        for extra in ({"error": "trap"}, {"panic": "boom"}, {"outcome": "terminated"}):
            checks, _ = run_w1.judge_run(self.run | extra, self.golden, 1e-4)
            self.assertFalse(checks["completed"])


if __name__ == "__main__":
    unittest.main()
