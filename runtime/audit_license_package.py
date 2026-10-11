"""Audit attribution inventory coverage in a staged package; no legal/release approval."""
import argparse
import json
from pathlib import Path

from license_supplements import contained_file, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--previous-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not __debug__ or args.output.exists():
        raise ValueError("assertions enabled and new output required")
    root = args.package.resolve()
    index = json.loads((root / "package.json").read_text(encoding="utf-8"))
    licenses = json.loads((root / "licenses.json").read_text(encoding="utf-8"))
    audit = json.loads((root / "dependency-audit.json").read_text(encoding="utf-8"))
    notices = (root / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    inventory = {r["path"]: r for r in index["files"]}
    assert len(inventory) == len(index["files"])
    assert {(p["name"], p["version"]) for p in licenses["packages"]} == {
        (p["name"], p["version"]) for p in audit["packages"]}
    missing = []
    supplements = []
    for entry in licenses["packages"]:
        assert f"{entry['name']} {entry['version']} (" in notices
        for record in entry["files"]:
            assert inventory[record["path"]]["sha256"] == record["sha256"]
            assert sha(contained_file(root, record["path"])) == record["sha256"]
            assert record["path"] in notices
        if not entry["declared_license"] or not entry["files"]:
            missing.append({"package": entry["name"], "declared_license": entry["declared_license"],
                            "local_license_files": len(entry["files"])})
        if "supplement_evidence" in entry:
            supplements.append(entry["supplement_evidence"])
    assert missing == licenses["issues"] == index["license_issues"]
    reference_index = root / "licenses/reference-sources.json"
    references = json.loads(reference_index.read_text(encoding="utf-8"))["sources"]
    for entry in references:
        assert sha(contained_file(root / "licenses", entry["file"])) == entry["sha256"]
        assert entry["revision"] in notices and "licenses/" + entry["file"] in notices
    current_bundle = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    previous_bundle = json.loads((args.previous_package / "bundle.json").read_text(encoding="utf-8"))
    assert current_bundle["files"] == previous_bundle["files"]
    for asset in current_bundle["files"]:
        assert sha(root / "checkpoint" / asset["path"]) == asset["sha256"]
        assert sha(args.previous_package / "checkpoint" / asset["path"]) == asset["sha256"]
    assert sha(root / "jeff.exe") == sha(args.previous_package / "jeff.exe") == index["executable_sha256"]
    result = {"schema_version": "kaze_judge.license_package_review.v1", "checked_on": "2026-10-10",
              "auditor_sha256": sha(__file__), "package_index_sha256": sha(root / "package.json"),
              "licenses_index_sha256": sha(root / "licenses.json"),
              "notices_sha256": sha(root / "THIRD_PARTY_NOTICES.txt"),
              "supplement_index_sha256": sha(root / "licenses/supplements.json"),
              "reference_index_sha256": sha(reference_index),
              "dependency_packages": len(licenses["packages"]),
              "packages_with_license_files": sum(bool(p["files"]) for p in licenses["packages"]),
              "unresolved_license_collection_issues": missing, "supplements": supplements,
              "reference_sources": references, "all_recorded_license_files_hash_verified": True,
              "notices_inventory_covers_audited_packages": True,
              "checkpoint_assets_unchanged": len(current_bundle["files"]),
              "executable_unchanged": True, "previous_package_index_sha256": sha(args.previous_package / "package.json"),
              "scope": "Conservative locked graph includes build/dev dependencies; collection and attribution inventory only.",
              "distribution_legal_review_complete": False, "release_ready": False,
              "pending": ["project_license_selection", "base_model_and_third_party_distribution_review",
                          "clean_host_validation", "quality_evaluation", "performance_slo_acceptance"]}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"packages": result["dependency_packages"],
                      "license_files_present": result["packages_with_license_files"],
                      "unresolved": len(missing), "release_ready": False}))


if __name__ == "__main__":
    main()
