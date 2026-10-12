"""Unit tests of the gate, statistics and plans (no model): python -B -m unittest bench/test_bench.py"""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog as cat  # noqa: E402
import run_benchmark as rb  # noqa: E402
import stats  # noqa: E402
import validate  # noqa: E402

CASE = {"id": "x", "tokens": 128, "candidate_ids": ["a", "b"], "input_ids_sha256": "f" * 64,
        "expect": {"jeff": "completed", "native": "completed", "wasm": "completed"},
        "reference": {"probabilities": [0.75, 0.25], "judgment": {"kind": "selected", "candidate_id": "a"}}}
LONG = {**CASE, "tokens": 600, "expect": {"jeff": "completed", "native": "completed", "wasm": "budget_exceeded"}}


def outcome(**changes):
    value = {"status": "completed", "candidate_ids": ["a", "b"], "probabilities": [0.75004, 0.24996],
             "judgment": {"kind": "selected", "candidate_id": "a"}, "input_tokens": 128, "forwards": 1}
    value.update(changes)
    return value


class Gate(unittest.TestCase):
    def test_passes_within_bounds(self):
        self.assertEqual(validate.check(CASE, "native", outcome()), [])

    def test_rejects_each_mismatch(self):
        bad = {
            "order": outcome(candidate_ids=["b", "a"]),
            "tokens": outcome(input_tokens=127),
            "ids": outcome(input_ids_sha256="0" * 64),
            "error": outcome(probabilities=[0.7502, 0.2498]),
            "sum": outcome(probabilities=[0.75, 0.25001]),
            "nan": outcome(probabilities=[math.nan, 0.25]),
            "inf": outcome(probabilities=[math.inf, 0.25]),
            "negative": outcome(probabilities=[1.25, -0.25]),
            "bool": outcome(probabilities=[True, False]),
            "string": outcome(probabilities=["0.75", "0.25"]),
            "count": outcome(probabilities=[0.75, 0.25, 0.0]),
            "missing": outcome(probabilities=None),
            "judgment": outcome(judgment={"kind": "abstained"}),
            "other candidate": outcome(judgment={"kind": "selected", "candidate_id": "b"}),
            "malformed judgment": outcome(judgment="selected"),
            "forwards": outcome(forwards=2),
        }
        for name, value in bad.items():
            with self.subTest(name):
                self.assertTrue(validate.check(CASE, "native", value))

    def test_status_must_match_the_arm(self):
        self.assertTrue(validate.check(CASE, "native", {"status": "failed", "failure": "unavailable"}))
        self.assertEqual(validate.check(LONG, "wasm", {"status": "failed", "failure": "budget_exceeded"}), [])
        self.assertTrue(validate.check(LONG, "wasm", {"status": "failed", "failure": "timeout"}))
        self.assertTrue(validate.check(LONG, "wasm", outcome(input_tokens=600)))
        self.assertTrue(validate.check(CASE, "native", None))
        self.assertTrue(validate.check(CASE, "native", {"status": "ok"}))

    def test_repeat_requires_identical_bits(self):
        same = [("native", "api", "x", outcome()), ("native", "api", "x", outcome())]
        self.assertEqual(validate.repeat_violations(same), [])
        drift = same + [("native", "api", "x", outcome(probabilities=[0.75004000000000001, 0.24995999999]))]
        self.assertEqual(validate.repeat_violations(drift), ["native/api/x"])


class Statistics(unittest.TestCase):
    def test_equivalent(self):
        result = stats.equivalence([0.97, 0.98, 0.96, 0.99, 0.97, 0.98])
        self.assertEqual(result["verdict"], "equivalent")
        self.assertLessEqual(result["upper95"], 1.05)

    def test_point_above_one_is_never_equivalent(self):
        self.assertNotEqual(stats.equivalence([1.005, 1.006, 1.004, 1.005, 1.006])["verdict"], "equivalent")

    def test_wide_interval_is_insufficient(self):
        self.assertEqual(stats.equivalence([0.8, 1.15, 0.85, 1.1, 0.9])["verdict"], "insufficient")

    def test_clearly_slower(self):
        self.assertEqual(stats.equivalence([1.2, 1.21, 1.19, 1.2, 1.22])["verdict"], "slower")

    def test_too_few_blocks(self):
        self.assertEqual(stats.equivalence([0.9, 0.9, 0.91, 0.9])["verdict"], "insufficient")
        self.assertEqual(stats.equivalence([0.9])["verdict"], "insufficient")

    def test_t_quantile_matches_known_values(self):
        self.assertAlmostEqual(stats.t95(4), 2.132)
        self.assertAlmostEqual(stats.t95(100), 1.697)

    def test_regression_threshold(self):
        self.assertFalse(stats.regression(10.0, 10.5)["regressed"])
        self.assertTrue(stats.regression(10.0, 10.51)["regressed"])


class Plans(unittest.TestCase):
    CASES = [{"id": i, "tokens": t, "expect": {"wasm": "completed" if t <= 512 else "budget_exceeded"}}
             for i, t in [("synthetic-ocr-ja-2-127", 127), ("candidate-request", 128), ("synthetic-ocr-ja-2-128", 128),
                          ("synthetic-ocr-ja-2-129", 129), ("synthetic-ocr-ja-2-256", 256),
                          ("synthetic-ocr-ascii-8-256", 256), ("synthetic-asr-unicode-2-384", 384),
                          ("synthetic-ocr-ascii-8-384", 384), ("synthetic-ocr-ja-2-511", 511),
                          ("synthetic-ocr-ja-2-512", 512), ("synthetic-ocr-ascii-3-513", 513),
                          ("synthetic-ocr-ascii-8-512", 512), ("special", 182), ("long-text", 874)]]

    def test_resident_plan_balances_order_and_fixes_inputs(self):
        plan = rb.resident_plan("short", ["jeff", "native"], 6, 6, 4, 1, self.CASES)
        self.assertEqual(len(plan), 12)
        firsts = [p["arm_order"][0] for p in plan[:6]]
        self.assertEqual(firsts.count("jeff"), firsts.count("native"))
        for p in plan:
            self.assertEqual(sorted(p["measure"]), sorted(rb.TIMED["short"] * 4))
            self.assertEqual(p["warmup"][0], "synthetic-ocr-ascii-3-513")
        self.assertEqual(plan[0]["gate"], [c["id"] for c in self.CASES if c["tokens"] <= 513])
        self.assertTrue(all(not p["gate"] for p in plan[1:]))
        self.assertEqual(plan, rb.resident_plan("short", ["jeff", "native"], 6, 6, 4, 1, self.CASES))
        self.assertTrue(all(p["extension"] for p in plan[6:]))

    def test_wasm_plan_excludes_inputs_over_its_limit_from_timing(self):
        plan = rb.resident_plan("wasm", ["wasm"], 6, 0, 4, 1, self.CASES)
        self.assertNotIn("synthetic-ocr-ascii-3-513", plan[0]["measure"])
        self.assertIn("synthetic-ocr-ascii-3-513", plan[0]["gate"])
        self.assertIn("long-text", plan[0]["gate"])

    def test_oneshot_plan_alternates_arm_order(self):
        plan = rb.oneshot_plan(10, 1)
        for case in rb.TIMED["oneshot"]:
            firsts = [next(arm for arm, c in p["runs"] if c == case) for p in plan]
            self.assertEqual(firsts.count("jeff"), 5)


class Catalog(unittest.TestCase):
    def test_groups(self):
        self.assertEqual([cat.group_of(t) for t in (126, 127, 129, 130, 511, 513, 8192, 8193)],
                         [None, "128", "128", None, "512", "512", "8192", None])

    def test_request_hash_ignores_key_order(self):
        self.assertEqual(cat.request_sha256({"a": 1, "b": "猫"}), cat.request_sha256({"b": "猫", "a": 1}))


if __name__ == "__main__":
    unittest.main()
