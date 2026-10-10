"""Generate an isolated multithread/profile probe on the accepted duplicate-removal base."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from benchmark_pilot import ROOT, save, sha
from prepare_driver_profile import REV, replace_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, "-B", str(ROOT/"runtime/onnx/prepare_duplicate_experiment.py"),
        "--upstream", args.upstream, "--output", str(args.output), "--remove-duplicate-search"], check=True)
    output = args.output.resolve()
    shutil.copyfile(ROOT/"runtime/tract-driver-profile/forward.Cargo.lock", output/"Cargo.lock")
    generation = json.loads((output/"generation.json").read_text(encoding="utf-8"))
    cargo = output/"Cargo.toml"
    cargo.write_text(replace_once(cargo.read_text(encoding="utf-8"), '[dependencies]',
        '[dependencies]\ntract-linalg = { git = "https://github.com/sonos/tract", rev = "'+REV+'", features = ["multithread-mm"] }'), encoding="utf-8")
    shutil.copyfile(ROOT/"runtime/tract-driver-profile/forward_profile.rs", output/"src/forward_profile.rs")
    bench = output/"src/bin/bench.rs"
    text = bench.read_text(encoding="utf-8")
    text = replace_once(text, 'mod codegen_profile;', 'mod codegen_profile;\n#[path = "../forward_profile.rs"]\nmod forward_profile;')
    before = '''    tract_onnx::tract_core::tract_linalg::multithread::set_default_executor(
        tract_onnx::tract_core::tract_linalg::multithread::Executor::SingleThread,
    );'''
    after = '''    let threads = match job.get("threads") {
        None => 1,
        Some(value) => value.as_u64().ok_or_else(|| anyhow::anyhow!("invalid thread count"))? as usize,
    };
    ensure!([1, 2, 4, 8].contains(&threads), "unsupported thread count");
    use tract_onnx::tract_core::tract_linalg::multithread::{self, Executor};
    let executor = if threads == 1 { Executor::SingleThread } else { Executor::multithread(threads) };
    let executor_threads = match &executor {
        Executor::MultiThread(pool) => pool.current_num_threads(),
        _ => 1,
    };
    ensure!(executor_threads == threads, "executor size mismatch");
    multithread::set_default_executor(executor);
    let profile_forward = job["profile_forward"].as_bool().unwrap_or(false);'''
    text = replace_once(text, before, after)
    text = replace_once(text, '"threads":1,', '"threads":threads,"executor_threads":executor_threads,"multithread_mm":true,\n        "panel_threshold":multithread::current_threading_panel_threshold(),"element_threshold":multithread::current_threading_element_threshold(),')
    text = replace_once(text, '        let output = plan.run(tensors)?;', '''        let (output, forward_profile) = if profile_forward {
            let (output, profile) = forward_profile::run(&plan, tensors)?;
            (output, Some(profile))
        } else {
            (plan.run(tensors)?, None)
        };''')
    text = replace_once(text, '"raw_logits":raw,"probabilities":probabilities', '"raw_logits":raw,"probabilities":probabilities,"forward_profile":forward_profile')
    bench.write_text(text, encoding="utf-8")
    generation.update(generator_sha256=sha(__file__), parent_generator_sha256=sha(ROOT/"runtime/onnx/prepare_duplicate_experiment.py"),
        multithread_mm=True, forward_profile="public top-level callback; default disabled", internal_timers=False)
    generation["files"] = [{"path": p.relative_to(output).as_posix(), "sha256": sha(p)}
        for p in sorted(output.rglob("*")) if p.is_file() and p.name != "generation.json"]
    save(output/"generation.json", generation)


if __name__ == "__main__":
    main()
