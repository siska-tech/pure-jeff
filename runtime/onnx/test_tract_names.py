"""Check the actual Tract Graph/ModelPatch name rules in the generated variant."""
import os
import subprocess
import unittest


@unittest.skipUnless(os.environ.get("TRACT_NAME_SEMANTICS"), "set TRACT_NAME_SEMANTICS")
class NameTests(unittest.TestCase):
    def test_actual_graph_and_patch_names(self):
        result = subprocess.run([os.environ["TRACT_NAME_SEMANTICS"]], check=True,
                                capture_output=True, timeout=30)
        self.assertIn(b"6 Graph cases and 5 patch cases passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
