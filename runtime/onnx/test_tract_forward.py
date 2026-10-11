"""Numerical, executor and public eval-profile regression on a real GEMM toy."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from onnx import TensorProto as T, helper as h, numpy_helper as nh
from benchmark_pilot import validate_events


class ThreadGateTests(unittest.TestCase):
    def test_validator_requires_requested_executor(self):
        case = {"id": "a", "tokens": 128, "expected_probabilities": [.8, .2],
            "expected_judgment": {"kind": "selected", "candidate_id": "x"},
            "request": {"candidates": [{"id": "x"}, {"id": "y"}]}}
        events = [{"event": "initialized", "threads": 4},
            {"event": "request", "case": "a", "probabilities": [.8, .2], "effective_tokens": 128},
            {"event": "completed"}]
        policy = {"min_probability": .7, "min_margin": .1}
        with self.assertRaises(ValueError): validate_events(events, [case], policy)
        with self.assertRaises(ValueError): validate_events(events, [case], policy, expected_threads=2)
        validate_events(events, [case], policy, expected_threads=4)


def gemm_model():
    weights = np.arange(8*512, dtype=np.float32).reshape(8,512)/4096
    constants = [nh.from_array(weights,"weight")]
    for name, values in [("matrix_shape",[64,8]),("flat_shape",[1,32768]),
                         ("start",[0]),("end",[255]),("axis",[1])]:
        constants.append(nh.from_array(np.array(values,dtype=np.int64),name))
    nodes = [h.make_node("Add",["input_ids","attention_mask"],["a"]),
        h.make_node("Add",["a","mm_token_type_ids"],["b"]),
        h.make_node("Cast",["b"],["f"],to=T.FLOAT),
        h.make_node("Reshape",["f","matrix_shape"],["m"]),
        h.make_node("MatMul",["m","weight"],["product"]),
        h.make_node("Reshape",["product","flat_shape"],["flat"]),
        h.make_node("Slice",["flat","start","end","axis"],["logits"])]
    graph = h.make_graph(nodes,"gemm-profile",[h.make_tensor_value_info(n,T.INT64,[1,512])
        for n in ["input_ids","attention_mask","mm_token_type_ids"]],
        [h.make_tensor_value_info("logits",T.FLOAT,[1,255])],constants)
    return h.make_model(graph,opset_imports=[h.make_opsetid("",18)],ir_version=10), weights


@unittest.skipUnless(os.environ.get("TRACT_FORWARD_BENCH"),"set TRACT_FORWARD_BENCH")
class ForwardTests(unittest.TestCase):
    def test_threads_profile_and_repeated_outputs(self):
        with tempfile.TemporaryDirectory(prefix="tract-forward-") as directory:
            root = Path(directory)
            model, weights = gemm_model()
            onnx.checker.check_model(model)
            onnx.save(model,root/"model.onnx")
            expected = ((np.arange(512,dtype=np.float32)+3).reshape(64,8)@weights).reshape(-1)[:255]
            reference = None
            for threads, enabled in [(1,False),(1,True),(2,False),(4,False),(8,False)]:
                job = {"mode":"no-change-axes","threads":threads,"profile_forward":enabled,
                    "cases":[{"id":"a","count":2,"temperature":1.,"tokens":512,
                        "inputs":{"input_ids":list(range(512)),"attention_mask":[1]*512,"mm_token_type_ids":[2]*512}}],
                    "schedule":[{"case":0,"warmup":False}]*2}
                (root/"job.json").write_text(json.dumps(job),encoding="utf-8")
                result = subprocess.run([os.environ["TRACT_FORWARD_BENCH"],str(root/"model.onnx"),str(root/"job.json")],
                    capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr.decode("utf-8"))
                events = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(events[0]["threads"],threads)
                self.assertEqual(events[0]["executor_threads"],threads)
                for event in events[1:-1]:
                    np.testing.assert_allclose(event["raw_logits"],expected,rtol=1e-5,atol=1e-4)
                    if reference is None: reference = event["raw_logits"]
                    self.assertEqual(event["raw_logits"],reference)
                    profile = event["forward_profile"]
                    if enabled:
                        self.assertEqual(profile["total_ns"],profile["node_ns"]+profile["driver_and_instrumentation_ns"])
                        self.assertEqual(profile["node_ns"],sum(g["ns"] for g in profile["groups"]))
                        self.assertTrue(any("MatMul" in g["op"] for g in profile["groups"]))
                    else: self.assertIsNone(profile)

    def test_reject_invalid_thread_counts(self):
        with tempfile.TemporaryDirectory(prefix="tract-forward-invalid-") as directory:
            job = Path(directory)/"job.json"
            for threads in [0,3,16,-1,None,"4"]:
                job.write_text(json.dumps({"mode":"typed","threads":threads}),encoding="utf-8")
                result = subprocess.run([os.environ["TRACT_FORWARD_BENCH"],"missing.onnx",str(job)],
                    capture_output=True,timeout=30)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(b"thread count",result.stderr)


if __name__ == "__main__":
    unittest.main()
