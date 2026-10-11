import json
from pathlib import Path
import tempfile
import unittest

from license_supplements import load_supplements, sha


class LicenseSupplementIntegrity(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package"
        self.package.mkdir()
        (self.package / "Cargo.toml").write_text("name = 'fixture'", encoding="utf-8")
        (self.package / ".cargo_vcs_info.json").write_text(
            json.dumps({"git": {"sha1": "a" * 40}}), encoding="utf-8")
        self.licenses = self.root / "licenses"
        self.licenses.mkdir()
        (self.licenses / "LICENSE").write_text("Fixture license evidence", encoding="utf-8")
        self.metadata = [{"name": "fixture", "version": "1.0.0", "source": "registry+fixture",
                          "license": "MIT", "manifest_path": str(self.package / "Cargo.toml")}]
        self.entry = {"name": "fixture", "version": "1.0.0", "source": "registry+fixture",
                      "declared_license": "MIT", "vcs_revision": "a" * 40,
                      "package_files": {"Cargo.toml": sha(self.package / "Cargo.toml")},
                      "files": [{"path": "LICENSE", "sha256": sha(self.licenses / "LICENSE")}]}
        self.index = self.licenses / "supplements.json"

    def load(self):
        self.index.write_text(json.dumps({"schema_version": "kaze_judge.license_supplements.v1",
                                          "packages": [self.entry]}), encoding="utf-8")
        return load_supplements(self.index, self.metadata)

    def test_matching_evidence_is_returned(self):
        result = self.load()
        self.assertEqual(result[("fixture", "1.0.0", "registry+fixture")]["files"],
                         [self.licenses / "LICENSE"])

    def test_changed_license_text_is_rejected(self):
        (self.licenses / "LICENSE").write_text("Changed evidence", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "license hash"):
            self.load()

    def test_wrong_dependency_and_changed_source_are_rejected(self):
        self.entry["version"] = "2.0.0"
        with self.assertRaisesRegex(ValueError, "identity"):
            self.load()
        self.entry["version"] = "1.0.0"
        (self.package / "Cargo.toml").write_text("Changed dependency", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source hash"):
            self.load()

    def test_evidence_path_escape_is_rejected(self):
        self.entry["files"][0]["path"] = "../package/Cargo.toml"
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.load()


if __name__ == "__main__":
    unittest.main()
