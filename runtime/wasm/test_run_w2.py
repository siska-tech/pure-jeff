"""W2 driver helpers without a browser or model forward."""
import json
import unittest

import run_w2
from run_w0 import GOLDEN


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.base = json.loads((GOLDEN / "candidate-request.json").read_text(encoding="utf-8"))["request"]

    def test_invalid_requests_are_each_invalid_in_one_way(self):
        items = {item["name"]: item for item in run_w2.invalid_requests(self.base)}
        self.assertEqual(len(items), 6)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(items["invalid_json"]["text"])
        self.assertEqual(len(json.loads(items["one_candidate"]["text"])["candidates"]), 1)
        ids = [c["id"] for c in json.loads(items["duplicate_candidate_ids"]["text"])["candidates"]]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 1)
        self.assertIsNone(json.loads(items["no_routing_reason"]["text"])["reason"])
        self.assertEqual(json.loads(items["token_budget_exceeded"]["text"]), self.base)
        self.assertEqual(items["token_budget_exceeded"]["max_input_tokens"], 64)

    def test_terminated_reply_is_not_completed(self):
        self.assertEqual(run_w2.as_run({"terminated": True})["outcome"], "terminated")
        self.assertEqual(run_w2.as_run({"code": 0, "output": {}})["outcome"], "completed")

    def test_bitwise_comparison_needs_both_results(self):
        result = {"probabilities": [0.5, 0.5], "last_hidden_state": [1.0]}
        self.assertTrue(run_w2.same(result, dict(result)))
        self.assertFalse(run_w2.same(result, None))
        self.assertFalse(run_w2.same(result, result | {"last_hidden_state": [1.0000001]}))

    def test_case_set_covers_lengths_and_candidate_counts(self):
        self.assertEqual(len(run_w2.GOLDEN_CASES) + len(run_w2.LENGTH_CASES), 12)
        self.assertEqual({n.rsplit("-", 2)[1] for n in run_w2.LENGTH_CASES}, {"2", "3", "8"})


if __name__ == "__main__":
    unittest.main()
