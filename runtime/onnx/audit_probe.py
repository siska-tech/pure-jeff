"""Record fixed Tract dependencies, source licenses, build scripts and PE imports."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_rust_dependencies import pe_imports, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("new output required")
    crate = Path(__file__).resolve().parents[1] / "tract"
    metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--locked", "--offline",
                          "--manifest-path", str(crate / "Cargo.toml"), "--format-version", "1",
                          "--filter-platform", "x86_64-pc-windows-msvc"], text=True, encoding="utf-8"))
    nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
    packages = []
    for p in sorted(metadata["packages"], key=lambda p: p["name"]):
        if p["id"] not in nodes:
            continue
        base = Path(p["manifest_path"]).parent
        texts = sorted({path for pattern in ["LICENSE*", "COPYING*", "NOTICE*"]
                        for path in base.glob(pattern) if path.is_file()})
        if p.get("license_file"):
            texts = sorted(set(texts) | {base / p["license_file"]})
        packages.append({"name": p["name"], "version": p["version"], "source": p["source"],
                         "features": nodes[p["id"]]["features"], "license": p["license"],
                         "license_texts": [{"path": str(path.relative_to(base)), "sha256": sha(path)} for path in texts],
                         "build_scripts": [{"path": str(Path(t["src_path"]).relative_to(base)),
                                            "sha256": sha(Path(t["src_path"]))}
                                           for t in p["targets"] if "custom-build" in t["kind"]]})
    executable = crate / "target/release/kaze_judge_tract_probe.exe"
    result = {"schema_version": "kaze_judge.tract_dependencies.v1", "packages": packages,
              "cargo_lock_sha256": sha(crate / "Cargo.lock"), "executable_sha256": sha(executable),
              "direct_pe_imports": pe_imports(executable), "distribution_approved": False,
              "scope": "development probe inventory; Tract uses build-time cc/Windows assembler for SIMD; source/redistribution review remains"}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"packages": len(packages), "imports": result["direct_pe_imports"]}))


if __name__ == "__main__":
    main()
