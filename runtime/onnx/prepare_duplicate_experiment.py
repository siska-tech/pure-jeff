"""Generate a timer-free, isolated duplicate-search experiment from pinned sources."""
import argparse
import shutil
import subprocess
import sys

from benchmark_pilot import ROOT, save, sha
from prepare_driver_profile import REV, replace_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--remove-duplicate-search", action="store_true")
    args = parser.parse_args()
    from pathlib import Path
    output, upstream = Path(args.output).resolve(), Path(args.upstream).resolve()
    subprocess.run([sys.executable, "-B", str(ROOT/"runtime/onnx/prepare_driver_profile.py"),
                    "--upstream", str(upstream), "--output", str(output)], check=True)
    # Restore all diagnostic changes before applying the single algorithm change.
    for path in ["src/lib.rs", "src/model/graph.rs", "src/model/patch.rs"]:
        shutil.copyfile(upstream/"core"/path, output/"vendor/core"/path)
    (output/"vendor/core/src/driver_timing.rs").unlink()
    shutil.copyfile(ROOT/"runtime/tract/src/bin/bench.rs", output/"src/bin/bench.rs")
    (output/"generation.json").unlink()
    target = output/"vendor/core/src/model/patch.rs"
    original = target.read_text(encoding="utf-8")
    start = original.index("            for dup in 0..target.nodes.len() {")
    end = original.index("            let facts = outputs.into_iter()", start)
    removed = original[start:end]
    if args.remove_duplicate_search:
        target.write_text(replace_once(original, removed, ""), encoding="utf-8")
    shutil.copyfile(ROOT/"runtime/tract-driver-profile/patch_semantics.rs", output/"src/bin/patch_semantics.rs")
    save(output/"generation.json", {"revision": REV, "generator_sha256": sha(__file__),
        "base_generator_sha256": sha(ROOT/"runtime/onnx/prepare_driver_profile.py"),
        "algorithm_changes": args.remove_duplicate_search, "timers": False,
        "removed_loop": removed if args.remove_duplicate_search else None,
        "original_patch_sha256": sha(upstream/"core/src/model/patch.rs"),
        "result_patch_sha256": sha(target),
        "files": [{"path": p.relative_to(output).as_posix(), "sha256": sha(p)}
                  for p in sorted(output.rglob("*")) if p.is_file()]})


if __name__ == "__main__":
    main()
