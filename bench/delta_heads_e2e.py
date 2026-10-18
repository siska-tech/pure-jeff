"""Issue #18, E2: the library with the DeltaNet heads on the compute threads (candidate) against
main (baseline), through the public API (`resident_bench --mode api`, no timers inside), at
1/2/4/8/16 threads. Plan and decision rules: docs/native-delta-heads-e2e-plan-2026-10-18.md.

The baseline uses `models/pure-jeff-bundle-tN-diag.json` (locked by main), the candidate
`models/pure-jeff-bundle-tN-delta-heads.json` (locked by the candidate's jeff.exe); they differ
only in `runtime_build_sha256`, which covers the library sources. Two sessions: thread counts ascending, then
descending; at each thread count the two arms alternate which runs first. Per arm and thread
count a session runs:
  warm     one resident process: a warm-up, then the timed inputs `REPS` times in a fixed
           shuffled order, then every gate input once;
  oneshot  one new process per timed input (load + first decision), `ONESHOT_REPS` times
           (8192 tokens once), arms alternating per input;
  timeout  timeout_reuse (a deadline inside the 8192-token forward, then the same Model again).
Every decision passes the common numeric gate (validate.py) against the official reference.

    python -B bench/delta_heads_e2e.py --output <new dir> --baseline <dir> --candidate <dir>

`--baseline` / `--candidate` are runtime/rust release directories holding
examples/resident_bench.exe and examples/timeout_reuse.exe."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random

import catalog as cat
import run_benchmark as rb
import validate

ROOT = cat.ROOT
THREADS = [1, 2, 4, 8, 16]
TIMED = ["candidate-request", "synthetic-ocr-ascii-8-512", "long-text", "token-limit-8192"]
GATE = ["synthetic-ocr-ja-2-127", "synthetic-ocr-ja-2-128", "synthetic-ocr-ja-2-129", "reversed",
        "synthetic-ocr-ja-2-511", "synthetic-ocr-ja-2-512", "synthetic-ocr-ascii-3-513", "special-token-text",
        "asr-unicode", "policy-top1-above", "policy-top1-below", "policy-near-tie", "policy-margin-near",
        "maximum-candidates", "token-limit-8193"]
REPS = 3
ONESHOT_REPS = 3
SEED = 20261018
ARMS = ("baseline", "candidate")


def job(by_id, names, phase):
    return [{"name": c, "phase": phase, "max_input_tokens": cat.MAX_TOKENS, "request": by_id[c]["request"]}
            for c in names]


def plan():
    entries = []
    for session in (0, 1):
        for i, n in enumerate(THREADS if session == 0 else THREADS[::-1]):
            arms = ARMS if (i + session) % 2 == 0 else ARMS[::-1]
            entries += [{"kind": "warm", "session": session, "threads": n, "arm": a} for a in arms]
            for j, case in enumerate(TIMED):
                for rep in range(1 if case == "token-limit-8192" else ONESHOT_REPS):
                    order = arms if (j + rep) % 2 == 0 else arms[::-1]
                    entries += [{"kind": "oneshot", "session": session, "threads": n, "arm": a, "case": case,
                                 "rep": rep} for a in order]
            if session == 0:
                entries += [{"kind": "timeout", "session": session, "threads": n, "arm": a} for a in arms]
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    args = parser.parse_args()
    if rb.busy_processes():
        raise SystemExit("build/install/benchmark processes are running")
    by_id = cat.by_id(cat.load())
    exes = {arm: {"resident": d / "examples/resident_bench.exe", "timeout": d / "examples/timeout_reuse.exe"}
            for arm, d in (("baseline", args.baseline), ("candidate", args.candidate))}
    timed = [c for c in TIMED for _ in range(REPS)]
    random.Random(SEED).shuffle(timed)
    args.output.mkdir(parents=True)
    work = args.output / "work"
    work.mkdir()
    warm_job = job(by_id, ["synthetic-ocr-ja-2-256"], "warmup") + job(by_id, timed, "measure") + job(by_id, GATE, "gate")
    (work / "warm-job.json").write_text(json.dumps(warm_job, ensure_ascii=False), encoding="utf-8")
    for case in TIMED:
        (work / f"oneshot-{case}.json").write_text(json.dumps(job(by_id, [case], "measure"), ensure_ascii=False),
                                                   encoding="utf-8")
    golden = ROOT / "tests/fixtures/jeff-golden"
    entries = plan()
    bundles = {"baseline": {n: ROOT / f"models/pure-jeff-bundle-t{n}-diag.json" for n in THREADS},
               "candidate": {n: ROOT / f"models/pure-jeff-bundle-t{n}-delta-heads.json" for n in THREADS}}
    for n in THREADS:
        a, b = (json.loads(bundles[arm][n].read_text(encoding="utf-8")) for arm in ARMS)
        if {k for k in a if a[k] != b.get(k)} != {"runtime_build_sha256"}:
            raise SystemExit(f"bundles for {n} threads differ beyond the runtime build")
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.delta_heads_e2e.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "plan": entries, "warm_job": [c["name"] + "/" + c["phase"] for c in warm_job], "seed": SEED,
        "reps": REPS, "oneshot_reps": ONESHOT_REPS, "timeout_seconds": args.timeout_seconds, "gates": validate.GATE,
        "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "hashes": {"driver": rb.sha(__file__), "catalog": rb.sha(cat.CATALOG),
                   "exes": {arm: {k: rb.sha(p) for k, p in e.items()} for arm, e in exes.items()},
                   "bundles": {arm: {n: rb.sha(p) for n, p in b.items()} for arm, b in bundles.items()}},
        "environment_start": rb.sample_environment(full=True)})
    results = []
    for index, entry in enumerate(entries):
        if rb.busy_processes():
            raise SystemExit("build/install/benchmark processes started during the run")
        n, arm = entry["threads"], entry["arm"]
        env = os.environ | {"PYTHONUTF8": "1"}
        if entry["kind"] == "timeout":
            command = [str(exes[arm]["timeout"]), str(bundles[arm][n]), str(golden / "token-limit-8192.json"),
                       str(golden / "candidate-request.json"), str(args.timeout_seconds)]
        else:
            job_file = work / ("warm-job.json" if entry["kind"] == "warm" else f"oneshot-{entry['case']}.json")
            command = [str(exes[arm]["resident"]), "--mode", "api", str(bundles[arm][n]), str(job_file)]
        run = rb.run_process(command, env, 4 * 3600)
        events = [json.loads(line) for line in run["stdout"].splitlines() if line.startswith("{")]
        decisions = [e for e in events if e.get("event") == "decision"]
        for d in decisions:
            d["gate"] = validate.check(by_id[d["name"]], "native", d["outcome"])
        result = {**entry, "index": index, "returncode": run["returncode"], "process_wall_s": run["wall_s"],
                  "memory": run["memory"], "affinity": run["affinity"], "events": events if entry["kind"] == "timeout"
                  else [e for e in events if e.get("event") != "decision"], "decisions": decisions,
                  "stderr": run["stderr"][-2000:]}
        results.append(result)
        rb.save(work / f"{index:03d}-{entry['kind']}-t{n}-{arm}.json", result)
        print(f"{index:03d} {entry['kind']} s{entry['session']} t{n} {arm} {entry.get('case', '')} "
              f"rc={run['returncode']} decisions={len(decisions)} gate_failures={sum(bool(d['gate']) for d in decisions)} "
              f"peak={run['memory']['max_process_peak_working_set'] / 2**30:.2f} GiB", flush=True)
    rb.save(args.output / "environment-end.json", rb.sample_environment(full=True))
    ok = all(r["returncode"] == 0 and not any(d["gate"] for d in r["decisions"]) for r in results)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
