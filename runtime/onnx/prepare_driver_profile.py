"""Generate an isolated, hash-indexed Tract driver diagnostic build (no cache edits)."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

from benchmark_pilot import ROOT, save, sha

REV = "9e0cfaa9b3a9251f41f74101801dc2c937b1660a"


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("pinned source anchor changed: "+before[:100])
    return text.replace(before, after, 1)


def toml_value(value):
    if isinstance(value, dict):
        return "{ "+", ".join(json.dumps(k)+" = "+toml_value(v) for k,v in value.items())+" }"
    return json.dumps(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/".venv"):
        raise ValueError("generated build must stay in workspace .venv")
    upstream = args.upstream.resolve()
    if subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"]).decode().strip() != REV:
        raise ValueError("wrong Tract revision")
    subprocess.run(["git", "-C", str(upstream), "diff", "--exit-code", REV, "--", "core", "Cargo.toml"], check=True)
    output.mkdir(parents=True, exist_ok=False)
    probe = ROOT/"runtime/tract"
    shutil.copytree(probe/"src", output/"src")
    shutil.copytree(probe/"vendor", output/"vendor")
    shutil.copytree(upstream/"core", output/"vendor/core")
    shutil.copyfile(probe/"Cargo.lock", output/"Cargo.lock")
    manifest = (probe/"Cargo.toml").read_text(encoding="utf-8")
    manifest += '\ntract-core = { path = "vendor/core" }\n'
    (output/"Cargo.toml").write_text(manifest, encoding="utf-8")
    workspace = tomllib.loads((upstream/"Cargo.toml").read_text(encoding="utf-8"))["workspace"]
    deps = workspace["dependencies"]
    needed = set()
    for package in [output/"vendor/core/Cargo.toml", output/"vendor/data/Cargo.toml"]:
        for line in package.read_text(encoding="utf-8").splitlines():
            if ".workspace = true" in line:
                needed.add(line.split(".workspace")[0])
            elif "workspace = true" in line:
                needed.add(line.split("=")[0].strip())
    needed.discard("rust-version")
    selected = {key: deps[key] for key in sorted(needed)}
    selected["tract-data"] = {"path": "data", "version": "=0.23.8"}
    selected["tract-linalg"] = {"git": "https://github.com/sonos/tract", "rev": REV}
    text = '[workspace]\nmembers = ["data", "core"]\nresolver = "2"\n[workspace.package]\nrust-version = "1.91"\n[workspace.dependencies]\n'
    text += "\n".join(json.dumps(k)+" = "+toml_value(v) for k,v in selected.items())+"\n"
    (output/"vendor/Cargo.toml").write_text(text, encoding="utf-8")
    changes = {}
    def patch(path, before, after):
        target = output/"vendor/core"/path
        original = target.read_text(encoding="utf-8")
        changes.setdefault(path, {"upstream_sha256": sha(upstream/"core"/path)})
        target.write_text(replace_once(original, before, after), encoding="utf-8")
    patch("src/lib.rs", "pub mod optim;", "pub mod optim;\npub mod driver_timing;")
    patch("src/model/graph.rs", "    pub fn compact(&mut self) -> TractResult<()> {", "    pub fn compact(&mut self) -> TractResult<()> {\n        let _driver_span = crate::driver_timing::Span::new(\"compact\");")
    patch("src/model/patch.rs", "    pub fn apply(self, target: &mut Graph<F, O>) -> TractResult<()> {", "    pub fn apply(self, target: &mut Graph<F, O>) -> TractResult<()> {\n        let _driver_span = crate::driver_timing::Span::new(\"patch_apply\");")
    patch("src/model/patch.rs", "            for dup in 0..target.nodes.len() {", "            let driver_dup_span = crate::driver_timing::Span::new(\"duplicate_search\");\n            for dup in 0..target.nodes.len() {")
    patch("src/model/patch.rs", "            let facts = outputs.into_iter().map(|of| of.fact).collect();", "            drop(driver_dup_span);\n            let facts = outputs.into_iter().map(|of| of.fact).collect();")
    patch("src/model/patch.rs", "        let mut maybe_garbage: HashSet<usize>", "        let driver_garbage_span = crate::driver_timing::Span::new(\"garbage_removal\");\n        let mut maybe_garbage: HashSet<usize>")
    patch("src/model/patch.rs", "        for n in new_nodes.iter() {", "        drop(driver_garbage_span);\n        let _driver_rename_span = crate::driver_timing::Span::new(\"node_rename\");\n        for n in new_nodes.iter() {")
    shutil.copyfile(ROOT/"runtime/tract-driver-profile/driver_timing.rs", output/"vendor/core/src/driver_timing.rs")
    bench = output/"src/bin/bench.rs"
    text = bench.read_text(encoding="utf-8")
    text = replace_once(text, '    if mode == "no-change-axes" {', '    tract_onnx::tract_core::driver_timing::begin(job["profile_driver"].as_bool().unwrap_or(false));\n    if mode == "no-change-axes" {')
    text = replace_once(text, '    let optimize_ns = step.elapsed().as_nanos();', '    let optimize_ns = step.elapsed().as_nanos();\n    let driver_profile = tract_onnx::tract_core::driver_timing::finish();')
    text = replace_once(text, '        "codegen_profile":profile,', '        "codegen_profile":profile,"driver_profile":driver_profile,')
    bench.write_text(text, encoding="utf-8")
    for path, info in changes.items():
        info["instrumented_sha256"] = sha(output/"vendor/core"/path)
    files = [{"path":p.relative_to(output).as_posix(),"sha256":sha(p)} for p in sorted(output.rglob("*")) if p.is_file()]
    save(output/"generation.json", {"revision":REV,"generator_sha256":sha(__file__),"timer_sha256":sha(ROOT/"runtime/tract-driver-profile/driver_timing.rs"),"changes":changes,"files":files,"algorithm_changes":False})
    print(output)


if __name__ == "__main__":
    main()
