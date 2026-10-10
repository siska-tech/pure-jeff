"""Provenance must not guess matches or silently invent missing shape metadata."""
import unittest

import onnx
from onnx import TensorProto as T, helper as h

from inspect_profile_graph import inspect, metadata


class ProfileGraphTests(unittest.TestCase):
    def test_exact_names_missing_metadata_and_attributes(self):
        nodes = [h.make_node("Transpose",["x"],["y"],name="move",perm=[1,0]),
            h.make_node("Identity",["y"],["z"],name="move_1")]
        graph = h.make_graph(nodes,"test",[h.make_tensor_value_info("x",T.FLOAT,[2,3])],
            [h.make_tensor_value_info("z",T.FLOAT,[3,2])])
        result = inspect(h.make_model(graph),{"move","move_2"})
        self.assertEqual(result["unmatched_profile_names"],["move_2"])
        matched = result["matched_profile_nodes"]
        self.assertEqual(len(matched),1)
        self.assertEqual(matched[0]["attributes"],{"perm":[1,0]})
        self.assertEqual(matched[0]["inputs"][0]["metadata"]["shape"],[2,3])
        self.assertIsNone(matched[0]["outputs"][0]["metadata"])

    def test_duplicate_names_are_rejected(self):
        graph = h.make_graph([h.make_node("Identity",["x"],["y"],name="dup"),
            h.make_node("Identity",["y"],["z"],name="dup")],"test",[],[])
        with self.assertRaises(ValueError): inspect(h.make_model(graph),{"dup"})

    def test_unknown_rank_is_not_scalar(self):
        self.assertIsNone(metadata(h.make_tensor_value_info("unknown",T.FLOAT,None))["shape"])
        self.assertEqual(metadata(h.make_tensor_value_info("scalar",T.FLOAT,[]))["shape"],[])
        self.assertIsNone(metadata(h.make_tensor_sequence_value_info("sequence",T.FLOAT,[2])))


if __name__ == "__main__":
    unittest.main()
