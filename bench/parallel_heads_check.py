"""Experiment for issue #18: DeltaNet heads on the compute threads (forward_breakdown
--parallel-heads) against the serial recurrence, at several thread counts. Each run is a
separate process; serial and parallel alternate (the first one alternates with the thread
count). forward_breakdown checks every final hidden state against the library forward bit for
bit and fails otherwise. Records the per-stage seconds and each process's peak working set.
Descriptive only; the library is not changed.

    python -B bench/parallel_heads_check.py --output <new dir> [--threads 2 4 8 16] [--reps 3]"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import run_benchmark as rb
from procmem import TreeSampler

ROOT = rb.ROOT
EXE = ROOT / "runtime/rust/target/release/examples/forward_breakdown.exe"
GOLDEN = ROOT / "tests/fixtures/jeff-golden"
CASES = [GOLDEN / "candidate-request.json",
         ROOT / "docs/research/wasm-demo/w2-2026-10-11/official-references/synthetic-ocr-ascii-8-512.json",
         GOLDEN / "long-text.json"]
LONG = [GOLDEN / "token-limit-8192.json"]


def run(threads, parallel, cases, reps):
    command = [str(EXE), str(ROOT / f"models/pure-jeff-bundle-t{threads}-diag.json"), *map(str, cases),
               "--reps", str(reps), *(["--parallel-heads"] if parallel else [])]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with TreeSampler(process.pid) as sampler:
        out, err = process.communicate()
    rows = [json.loads(line) for line in out.decode().splitlines() if line.startswith("{")]
    return {"threads": threads, "parallel": parallel, "returncode": process.returncode,
            "stderr": err.decode(errors="replace")[-1000:], "memory": sampler.result(), "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, nargs="+", default=[2, 4, 8, 16])
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--long-threads", type=int, default=16)
    args = parser.parse_args()
    if rb.busy_processes():
        raise SystemExit("build/install/benchmark processes are running")
    args.output.mkdir(parents=True)
    plan = [(n, parallel) for i, n in enumerate(args.threads)
            for parallel in ((False, True) if i % 2 == 0 else (True, False))]
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.parallel_heads_check.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "plan": plan, "reps": args.reps, "cases": [c.name for c in CASES], "long": [c.name for c in LONG],
        "long_threads": args.long_threads, "source": {"commit": rb.git("rev-parse", "HEAD"),
                                                      "dirty": rb.git("status", "--porcelain")},
        "exe_sha256": rb.sha(EXE), "driver_sha256": rb.sha(__file__),
        "environment_start": rb.sample_environment(full=True)})
    results = [run(n, parallel, CASES, args.reps) for n, parallel in plan]
    results += [run(args.long_threads, parallel, LONG, 1) for parallel in (False, True)]
    for r in results:
        print(f"t{r['threads']} parallel={r['parallel']} rc={r['returncode']} rows={len(r['rows'])} "
              f"peak={r['memory']['max_process_peak_working_set'] / 2**30:.2f} GiB", flush=True)
    rb.save(args.output / "runs.json", results)
    raise SystemExit(0 if all(r["returncode"] == 0 and r["rows"] for r in results) else 1)


if __name__ == "__main__":
    main()
