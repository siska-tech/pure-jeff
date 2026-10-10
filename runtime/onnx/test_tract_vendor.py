"""Keep the local Tract patch restricted to its documented file and bytes."""
import hashlib
import json
from pathlib import Path
import unittest


class VendorTests(unittest.TestCase):
    def test_only_documented_upstream_file_changed(self):
        root = Path(__file__).resolve().parents[1] / "tract/vendor"
        manifest = json.loads((root / "upstream.json").read_text(encoding="utf-8"))
        expected = {entry["path"]: entry["sha256"] for entry in manifest["original_files"]}
        actual = {str(path.relative_to(root)).replace("\\", "/"):
                  hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (root / "data").rglob("*") if path.is_file()}
        self.assertEqual(set(actual), set(expected))
        changed = [path for path in actual if actual[path] != expected[path]]
        self.assertEqual(changed, ["data/src/tensor.rs"])
        self.assertEqual(actual[changed[0]],
                         "a403a27489a8c235832d7bd5ed40209002d7bb0352a1c5b8f4bed1f77ef204c1")


if __name__ == "__main__":
    unittest.main()
