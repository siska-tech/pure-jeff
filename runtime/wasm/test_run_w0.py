"""Driver checks without a browser or model forward."""
import importlib.util
import unittest

import run_w0


def ops(values, elapsed=1.0):
    return {"cases": [{"name": "gemm_odd_5x64_by_33x64T", "shape": [1], "values": values,
                       "elapsed_ms": elapsed}]}


class DriverTests(unittest.TestCase):
    def test_job_uses_all_golden_cases_with_one_vocabulary(self):
        # The committed checkpoint list has the same file records as a bundle manifest.
        job = run_w0.make_job(run_w0.ROOT / "tools/checkpoint.json")
        self.assertEqual([case["name"] for case in job["cases"]], run_w0.CASES)
        self.assertEqual(len(job["codes"]), 255)
        self.assertEqual(job["cases"][-1]["input_ids"].__len__(), 8192)

    def test_repeat_ignores_timings_only(self):
        self.assertEqual(run_w0.values_only(ops([1.0], 1.0)), run_w0.values_only(ops([1.0], 9.0)))
        self.assertNotEqual(run_w0.values_only(ops([1.0])), run_w0.values_only(ops([1.0000001])))

    def test_tensor_scale_threshold(self):
        native = {"cases": [{"name": "x", "shape": [2], "values": [100.0, 0.0], "elapsed_ms": 0}]}
        near = {"cases": [{"name": "x", "shape": [2], "values": [100.0, 9e-4], "elapsed_ms": 0}]}
        far = {"cases": [{"name": "x", "shape": [2], "values": [100.0, 2e-3], "elapsed_ms": 0}]}
        self.assertTrue(run_w0.compare_ops(native, near, {})[0])
        self.assertFalse(run_w0.compare_ops(native, far, {})[0])
        nan = {"cases": [{"name": "x", "shape": [2], "values": [100.0, float("nan")], "elapsed_ms": 0}]}
        self.assertFalse(run_w0.compare_ops(native, nan, {})[0])

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is not installed")
    def test_gemm_backward_bound_rejects_wrong_product(self):
        exact = run_w0.gemm_exact()
        product = exact["gemm_odd_5x64_by_33x64T"][0].ravel()
        good = [float(v) for v in product.astype("float32")]
        bad = list(good)
        bad[7] += 0.01
        native = {"cases": [{"name": "gemm_odd_5x64_by_33x64T", "shape": [5, 33], "values": good,
                             "elapsed_ms": 0}]}
        wrong = {"cases": [{"name": "gemm_odd_5x64_by_33x64T", "shape": [5, 33], "values": bad,
                            "elapsed_ms": 0}]}
        self.assertTrue(run_w0.compare_ops(native, native, {"gemm_odd_5x64_by_33x64T": exact["gemm_odd_5x64_by_33x64T"]})[0])
        self.assertFalse(run_w0.compare_ops(native, wrong, {"gemm_odd_5x64_by_33x64T": exact["gemm_odd_5x64_by_33x64T"]})[0])


if __name__ == "__main__":
    unittest.main()
