"""Generate the suffix-index variant on top of the frozen duplicate-search change."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from benchmark_pilot import ROOT, save, sha
from prepare_driver_profile import replace_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, "-B", str(ROOT/"runtime/onnx/prepare_duplicate_experiment.py"),
        "--upstream", args.upstream, "--output", str(args.output), "--remove-duplicate-search"], check=True)
    output = args.output.resolve()
    manifest = json.loads((output/"generation.json").read_text(encoding="utf-8"))
    graph = output/"vendor/core/src/model/graph.rs"
    text = graph.read_text(encoding="utf-8")
    start = text.index("        let prefix = prefix.into();", text.index("    pub fn unique_name<'n>"))
    end = text.index("        unreachable!();", start)+len("        unreachable!();")
    before = text[start:end]
    graph.write_text(replace_once(text, before,
        "        crate::name_index::unique_name(self.nodes.iter().map(|n| n.name.as_str()), prefix.into())"), encoding="utf-8")
    lib = output/"vendor/core/src/lib.rs"
    lib.write_text(replace_once(lib.read_text(encoding="utf-8"), "pub mod optim;", "pub mod optim;\nmod name_index;"), encoding="utf-8")
    shutil.copyfile(ROOT/"runtime/tract-driver-profile/name_index.rs", output/"vendor/core/src/name_index.rs")
    shutil.copyfile(ROOT/"runtime/tract-driver-profile/name_semantics.rs", output/"src/bin/name_semantics.rs")
    manifest.update(generator_sha256=sha(__file__), parent_generator_sha256=sha(ROOT/"runtime/onnx/prepare_duplicate_experiment.py"),
        name_index=True, removed_unique_name_body=before)
    manifest["files"] = [{"path": p.relative_to(output).as_posix(), "sha256": sha(p)}
        for p in sorted(output.rglob("*")) if p.is_file() and p.name != "generation.json"]
    save(output/"generation.json", manifest)


if __name__ == "__main__":
    main()
