"""Check benchmark quantiles and reject numerically invalid measurements."""
import unittest
from benchmark_pilot import stats, validate_events


class PilotTests(unittest.TestCase):
    def test_nearest_rank(self):
        actual = stats([5, 1, 4, 2, 3])
        self.assertEqual(actual["median"], 3)
        self.assertEqual(actual["p95"], 5)
        self.assertEqual(stats([]), {"n": 0})

    def test_numerical_validation(self):
        cases = [{"id": "a", "tokens": 100, "request": {"candidates": [{"id": "first"}, {"id": "second"}]},
                  "expected_probabilities": [.9, .1], "expected_judgment": {"kind": "selected", "candidate_id": "first"}}]
        events = [{"event": "initialized"}, {"event": "request", "case": "a", "effective_tokens": 100,
                  "probabilities": [.9, .1]}, {"event": "completed"}]
        validate_events(events, cases, {"min_probability": .7, "min_margin": .1})
        events[1]["probabilities"] = [.89, .11]
        with self.assertRaises(ValueError):
            validate_events(events, cases, {"min_probability": .7, "min_margin": .1})


if __name__ == "__main__":
    unittest.main()
