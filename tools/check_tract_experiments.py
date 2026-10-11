"""Regenerate the Tract optimization experiments and compare them with the recorded evidence.

  python tools/check_tract_experiments.py --upstream <tract checkout at 9e0cfaa> --work .venv/tract-gen

Each runtime/onnx/prepare_*.py generator writes a crate (patched Tract core/data plus a benchmark
driver) and a generation.json with the hashes of every generated file. The generation.json written
here must equal the one archived in docs/research/jeff-onnx-tract when the experiment was run, so
the patched Tract that produced the archived numbers is reproduced byte for byte. With --patches,
the normalized differences to upstream are also compared with runtime/tract/patches/*.patch.
Development tool; the upstream checkout comes from Cargo (see runtime/tract/README.md).
"""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/research/jeff-onnx-tract"
# name -> (generator, extra arguments, archived generation.json, patch file or None)
EXPERIMENTS = {
    "driver": ("prepare_driver_profile.py", [], "driver-profile-2026-10-10/generation.json", "driver-timers"),
    "duplicate-control": ("prepare_duplicate_experiment.py", [],
                          "duplicate-search-2026-10-10/control-generation.json", None),
    "duplicate-candidate": ("prepare_duplicate_experiment.py", ["--remove-duplicate-search"],
                            "duplicate-search-2026-10-10/candidate-generation.json", "duplicate-search-removal"),
    "name": ("prepare_name_experiment.py", [], "name-index-2026-10-10/candidate-generation.json", "name-index"),
    "forward": ("prepare_forward_experiment.py", [], "forward-profile-2026-10-10/candidate-generation.json", None),
    "trilu": ("prepare_trilu_experiment.py", [], "trilu-rows-2026-10-11/candidate-generation.json", "trilu-rows"),
    "scatter": ("prepare_scatter_experiment.py", [], "scatter-rows-2026-10-11/candidate-generation.json",
                "scatter-rows"),
}


def normalized_diff(upstream, generated, crate):
    """Unified diff of a generated crate against upstream, with CRLF read as LF."""
    base, new = upstream / crate, generated / crate
    files = sorted({p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()} |
                   {p.relative_to(new).as_posix() for p in new.rglob("*") if p.is_file()})
    chunks = []
    for name in files:
        a = (base / name).read_bytes().replace(b"\r\n", b"\n").decode() if (base / name).exists() else ""
        b = (new / name).read_bytes().replace(b"\r\n", b"\n").decode() if (new / name).exists() else ""
        if a != b:
            chunks.append("".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                                       f"a/{crate}/{name}" if a else "/dev/null",
                                                       f"b/{crate}/{name}", n=3)))
    return "".join(chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True, help="directory for the generated crates (recreated)")
    parser.add_argument("--patches", action="store_true", help="also compare runtime/tract/patches/*.patch")
    args = parser.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    failures = []
    for name, (generator, extra, archived, patch) in EXPERIMENTS.items():
        output = args.work / name
        subprocess.run([sys.executable, "-B", str(ROOT / "runtime/onnx" / generator), "--upstream",
                        str(args.upstream), "--output", str(output), *extra], check=True, capture_output=True)
        same = (json.loads((output / "generation.json").read_text(encoding="utf-8")) ==
                json.loads((EVIDENCE / archived).read_text(encoding="utf-8")))
        print(f"{name}: generation {'matches' if same else 'DIFFERS from'} {archived}")
        if not same:
            failures.append(name)
        if args.patches and patch:
            text = normalized_diff(args.upstream, output / "vendor", "core")
            if text != (ROOT / f"runtime/tract/patches/{patch}.patch").read_text(encoding="utf-8"):
                print(f"{name}: core diff differs from runtime/tract/patches/{patch}.patch")
                failures.append(f"{name} patch")
    if args.patches:
        text = normalized_diff(args.upstream, ROOT / "runtime/tract/vendor", "data")
        if text != (ROOT / "runtime/tract/patches/data-i64-tdim.patch").read_text(encoding="utf-8"):
            print("vendor data diff differs from runtime/tract/patches/data-i64-tdim.patch")
            failures.append("data patch")
    print(f"{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
