"""Issue #18: the DeltaNet recurrence by stage and the experimental head-parallel variants, at
1/2/4/8/16 compute threads (forward_breakdown --delta). Diagnostic only; the library is not
changed. Plan and decision rules: docs/native-delta-threads-plan-2026-10-18.md.

Every process runs each rep with every listed variant (rotating which goes first) and checks
each final hidden state against the library forward bit for bit, or fails. Two sessions: the
first runs the thread counts in ascending order, the second in descending order. Also: one
process per thread count without the stage timers (their cost), and one scaling probe.

    python -B bench/delta_stage_profile.py --output <new dir>"""
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
SHORT = [GOLDEN / "candidate-request.json",
         ROOT / "docs/research/wasm-demo/w2-2026-10-11/official-references/synthetic-ocr-ascii-8-512.json",
         GOLDEN / "long-text.json"]
LONG = [GOLDEN / "token-limit-8192.json"]
THREADS = [1, 2, 4, 8, 16]
VARIANTS = "serial,scoped,pool,fused"


def plan():
    runs = []
    for session in (0, 1):
        for n in (THREADS if session == 0 else THREADS[::-1]):
            runs.append({"kind": "stages", "session": session, "threads": n, "cases": SHORT, "reps": 3,
                         "args": ["--delta", VARIANTS]})
            runs.append({"kind": "stages", "session": session, "threads": n, "cases": LONG, "reps": 1,
                         "args": ["--delta", "serial,fused"]})
    for n in THREADS:
        runs.append({"kind": "no_stage_timers", "session": 0, "threads": n, "cases": SHORT[::2], "reps": 3,
                     "args": ["--delta", "serial,fused", "--no-stage-timers"]})
    runs.append({"kind": "probe", "session": 0, "threads": 16, "cases": [SHORT[2], LONG[0]], "reps": 1,
                 "args": ["--delta", "fused", "--probe-scaling"]})
    return runs


def run(entry):
    command = [str(EXE), str(ROOT / f"models/pure-jeff-bundle-t{entry['threads']}-diag.json"),
               *map(str, entry["cases"]), "--reps", str(entry["reps"]), *entry["args"]]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with TreeSampler(process.pid) as sampler:
        out, err = process.communicate()
    rows = [json.loads(line) for line in out.decode().splitlines() if line.startswith("{")]
    result = {**entry, "cases": [c.name for c in entry["cases"]], "command": command[1:],
              "returncode": process.returncode, "stderr": err.decode(errors="replace")[-1000:],
              "memory": sampler.result(), "rows": rows}
    print(f"{entry['kind']} s{entry['session']} t{entry['threads']} {result['cases']} rc={process.returncode} "
          f"rows={len(rows)} peak={result['memory']['max_process_peak_working_set'] / 2**30:.2f} GiB", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if rb.busy_processes():
        raise SystemExit("build/install/benchmark processes are running")
    args.output.mkdir(parents=True)
    runs = plan()
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.delta_stage_profile.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "plan": [{**r, "cases": [c.name for c in r["cases"]]} for r in runs],
        "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "exe_sha256": rb.sha(EXE), "driver_sha256": rb.sha(__file__),
        "environment_start": rb.sample_environment(full=True)})
    results = [run(r) for r in runs]
    rb.save(args.output / "runs.json", results)
    rb.save(args.output / "environment-end.json", rb.sample_environment(full=True))
    raise SystemExit(0 if all(r["returncode"] == 0 and r["rows"] for r in results) else 1)


if __name__ == "__main__":
    main()
