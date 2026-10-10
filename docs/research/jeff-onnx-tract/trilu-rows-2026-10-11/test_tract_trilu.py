"""Real Tract Trilu: rectangular/batched, bool/int/float and legacy overflow fallback."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import onnx
from onnx import TensorProto as T, helper as h, numpy_helper as nh


def model(shape, upper, k, dtype, transpose):
    constants = [nh.from_array(np.array(shape,dtype=np.int64),"shape"),
        nh.from_array(np.array([1,512],dtype=np.int64),"flat"),
        nh.from_array(np.array(k,dtype=np.int64),"k"),
        nh.from_array(np.array([0],dtype=np.int64),"start"),
        nh.from_array(np.array([255],dtype=np.int64),"end"),
        nh.from_array(np.array([1],dtype=np.int64),"axis")]
    nodes = [h.make_node("Add",["input_ids","attention_mask"],["a"]),
        h.make_node("Add",["a","mm_token_type_ids"],["b"]),
        h.make_node("Cast",["b"],["c"],to=dtype),
        h.make_node("Reshape",["c","shape"],["matrix"])]
    source = "matrix"
    if transpose:
        perm = list(range(len(shape)))
        perm[-2:] = reversed(perm[-2:])
        nodes.append(h.make_node("Transpose",[source],["transposed"],perm=perm))
        source = "transposed"
    nodes += [h.make_node("Trilu",[source,"k"],["tri"],upper=int(upper)),
        h.make_node("Cast",["tri"],["float"],to=T.FLOAT),
        h.make_node("Reshape",["float","flat"],["flattened"]),
        h.make_node("Slice",["flattened","start","end","axis"],["logits"])]
    graph = h.make_graph(nodes,"trilu",[h.make_tensor_value_info(n,T.INT64,[1,512]) for n in
        ["input_ids","attention_mask","mm_token_type_ids"]],
        [h.make_tensor_value_info("logits",T.FLOAT,[1,255])],constants)
    return h.make_model(graph,opset_imports=[h.make_opsetid("",18)],ir_version=10)


@unittest.skipUnless(all(os.environ.get(k) for k in ["TRACT_FORWARD_BENCH","TRACT_TRILU_BENCH"]),
    "set frozen forward and isolated Trilu executables")
class TriluTests(unittest.TestCase):
    def test_actual_operator_matches_control_and_reference(self):
        with tempfile.TemporaryDirectory(prefix="trilu-regression-") as directory:
            root = Path(directory)
            inputs = {"input_ids":list(range(-203,309)),"attention_mask":[1]*512,"mm_token_type_ids":[2]*512}
            job = {"mode":"typed","threads":4,"profile_forward":False,
                "cases":[{"id":"a","count":2,"temperature":1.,"tokens":512,"inputs":inputs}],
                "schedule":[{"case":0,"warmup":False}]*2}
            (root/"job.json").write_text(json.dumps(job),encoding="utf-8")
            for shape, transpose in [([16,32],False),([2,8,32],True),([1,512],False),([512,1],False)]:
                for dtype, numpy_type in [(T.FLOAT,np.float32),(T.INT64,np.int64),(T.BOOL,np.bool_)]:
                    for upper in [False,True]:
                        for k in [-513,-1,0,1,513,-2**63,2**63-1]:
                            with self.subTest(shape=shape,dtype=dtype,upper=upper,k=k,transpose=transpose):
                                graph = model(shape,upper,k,dtype,transpose)
                                onnx.checker.check_model(graph)
                                onnx.save(graph,root/"model.onnx")
                                values = np.arange(-200,312).astype(numpy_type).reshape(shape)
                                if transpose: values = values.swapaxes(-1,-2)
                                expected = values.copy()
                                for coords in np.ndindex(expected.shape):
                                    row,col = coords[-2:]
                                    # Preserve the existing release operator's i64 wrap on overflow.
                                    diagonal = (row+k+2**63)%(2**64)-2**63
                                    if (upper and col < diagonal) or (not upper and col > diagonal):
                                        expected[coords] = 0
                                expected = expected.astype(np.float32).reshape(-1)[:255].tolist()
                                for name in ["TRACT_FORWARD_BENCH","TRACT_TRILU_BENCH"]:
                                    result = subprocess.run([os.environ[name],str(root/"model.onnx"),str(root/"job.json")],
                                        capture_output=True,timeout=30)
                                    self.assertEqual(result.returncode,0,result.stderr.decode("utf-8"))
                                    events = [json.loads(line) for line in result.stdout.splitlines()]
                                    for event in events[1:-1]: self.assertEqual(event["raw_logits"],expected)


if __name__ == "__main__":
    unittest.main()
