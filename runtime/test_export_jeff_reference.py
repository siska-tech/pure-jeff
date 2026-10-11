import unittest
from export_jeff_reference import compare_probabilities


class ReferenceComparison(unittest.TestCase):
    def observation(self, values):
        return {"scores": [{"option_probability": value} for value in values]}

    def test_accepts_equal_and_within_tolerance(self):
        self.assertEqual(compare_probabilities([0.8, 0.2], self.observation([0.8, 0.2]), 1e-6), 0)
        self.assertLess(compare_probabilities([0.8, 0.2], self.observation([0.8000001, 0.1999999]), 1e-6), 1e-6)

    def test_rejects_disagreement_and_invalid_numbers(self):
        for reference, actual, tolerance in [([0.8,0.2],[0.7,0.3],1e-6),
                ([0.8,0.2],[0.8],1e-6), ([float("nan"),0.2],[0.8,0.2],1e-6),
                ([0.8,0.3],[0.8,0.3],1e-6), ([0.8,0.2],[0.8,0.2],float("nan")),
                ([0.8,0.2],[0.8,float("nan")],1e-6),
                ([0.8,0.2],[0.8,0.2],-1)]:
            with self.subTest(reference=reference, tolerance=tolerance):
                with self.assertRaises(ValueError):
                    compare_probabilities(reference, self.observation(actual), tolerance)


if __name__ == "__main__":
    unittest.main()
