"""Issue #18: numeric check of the final DeltaNet-heads commit on representative inputs.
Rules: docs/native-delta-heads-final-check-2026-10-18.md.

  reference  main at one thread (resident, `--mode api`), each input once;
  candidate  at 1/2/4/8/16 threads, two independent resident processes per thread count, each
             deciding every input twice (the second pass in reverse order);
  timeout    timeout_reuse of the candidate at 1, 4 and 16 threads (a deadline inside the
             8192-token forward, then the same Model again).
Every decision passes the common numeric gate, and every candidate probability must equal the
reference bit for bit.

    python -B bench/delta_heads_final_check.py --output <new dir> --baseline <dir> --candidate <dir>"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import catalog as cat
import run_benchmark as rb
import validate

ROOT = cat.ROOT
THREADS = [1, 2, 4, 8, 16]
INPUTS = ["synthetic-ocr-ja-2-127", "candidate-request", "synthetic-ocr-ja-2-129", "reversed",
          "synthetic-ocr-ja-2-511", "synthetic-ocr-ascii-8-512", "synthetic-ocr-ascii-3-513", "policy-near-tie",
          "policy-margin-near", "long-text", "maximum-candidates", "token-limit-8192", "token-limit-8193"]
TIMEOUT_THREADS = [1, 4, 16]


def bits(outcome):
    if outcome.get("status") == "completed":
        return [float(p).hex() for p in outcome["probabilities"]] + [json.dumps(outcome.get("judgment"), sort_keys=True)]
    return ["failed", outcome.get("failure")]


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
    args.output.mkdir(parents=True)
    job = lambda names, phase: [{"name": n, "phase": phase, "max_input_tokens": cat.MAX_TOKENS,
                                 "request": by_id[n]["request"]} for n in names]
    (args.output / "reference-job.json").write_text(json.dumps(job(INPUTS, "measure"), ensure_ascii=False),
                                                    encoding="utf-8")
    (args.output / "candidate-job.json").write_text(json.dumps(
        job(INPUTS, "pass1") + job(INPUTS[::-1], "pass2"), ensure_ascii=False), encoding="utf-8")
    base_exe = args.baseline / "examples/resident_bench.exe"
    cand_exe = args.candidate / "examples/resident_bench.exe"
    timeout_exe = args.candidate / "examples/timeout_reuse.exe"
    bundle = lambda arm, n: ROOT / f"models/pure-jeff-bundle-t{n}-{'diag' if arm == 'baseline' else 'delta-heads'}.json"
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.delta_heads_final_check.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": INPUTS, "threads": THREADS, "timeout_threads": TIMEOUT_THREADS,
        "timeout_seconds": args.timeout_seconds, "gates": validate.GATE,
        "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "hashes": {"driver": rb.sha(__file__), "catalog": rb.sha(cat.CATALOG), "baseline_exe": rb.sha(base_exe),
                   "candidate_exe": rb.sha(cand_exe), "timeout_exe": rb.sha(timeout_exe),
                   "bundles": {f"{arm}-t{n}": rb.sha(bundle(arm, n)) for arm in ("baseline", "candidate")
                               for n in THREADS}},
        "environment_start": rb.sample_environment(full=True)})
    env = os.environ | {"PYTHONUTF8": "1"}

    def decide(exe, manifest, job_file):
        run = rb.run_process([str(exe), "--mode", "api", str(manifest), str(job_file)], env, 4 * 3600)
        events = [json.loads(line) for line in run["stdout"].splitlines() if line.startswith("{")]
        decisions = [e for e in events if e.get("event") == "decision"]
        for d in decisions:
            d["gate"] = validate.check(by_id[d["name"]], "native", d["outcome"])
        return run, decisions

    run, reference = decide(base_exe, bundle("baseline", 1), args.output / "reference-job.json")
    expected = {d["name"]: bits(d["outcome"]) for d in reference}
    processes = [{"arm": "baseline", "threads": 1, "process": 0, "returncode": run["returncode"],
                  "memory": run["memory"], "decisions": reference}]
    print(f"reference rc={run['returncode']} decisions={len(reference)} "
          f"gate_failures={sum(bool(d['gate']) for d in reference)}", flush=True)
    for process in (0, 1):
        for n in (THREADS if process == 0 else THREADS[::-1]):
            run, decisions = decide(cand_exe, bundle("candidate", n), args.output / "candidate-job.json")
            mismatches = [f"{d['phase']}/{d['name']}" for d in decisions if bits(d["outcome"]) != expected.get(d["name"])]
            processes.append({"arm": "candidate", "threads": n, "process": process, "returncode": run["returncode"],
                              "memory": run["memory"], "decisions": decisions, "mismatches": mismatches})
            print(f"candidate t{n} p{process} rc={run['returncode']} decisions={len(decisions)} "
                  f"gate_failures={sum(bool(d['gate']) for d in decisions)} mismatches={len(mismatches)}", flush=True)
    golden = ROOT / "tests/fixtures/jeff-golden"
    timeouts = []
    for n in TIMEOUT_THREADS:
        run = rb.run_process([str(timeout_exe), str(bundle("candidate", n)), str(golden / "token-limit-8192.json"),
                              str(golden / "candidate-request.json"), str(args.timeout_seconds)], env, 3600)
        result = next((json.loads(l) for l in run["stdout"].splitlines() if l.startswith("{")), None)
        timeouts.append({"threads": n, "returncode": run["returncode"], "result": result, "stderr": run["stderr"][-1000:]})
        print(f"timeout t{n} rc={run['returncode']} {result}", flush=True)
    candidates = [p for p in processes if p["arm"] == "candidate"]
    failures = {
        "process_failures": [(p["arm"], p["threads"], p["process"]) for p in processes if p["returncode"] != 0],
        "missing_decisions": [(p["threads"], p["process"]) for p in candidates if len(p["decisions"]) != 2 * len(INPUTS)]
        + ([("reference",)] if len(reference) != len(INPUTS) else []),
        "gate_failures": [(p["arm"], p["threads"], d["name"]) for p in processes for d in p["decisions"] if d["gate"]],
        "bit_mismatches": [(p["threads"], p["process"], m) for p in candidates for m in p["mismatches"]],
        "timeout_reuse": [t["threads"] for t in timeouts if t["returncode"] != 0 or not t["result"]
                          or not (t["result"].get("timeout") and t["result"].get("reuse_bitwise_equal"))]}
    passed = not any(failures.values())
    rb.save(args.output / "results.json", {"processes": processes, "timeouts": timeouts, "failures": failures,
                                           "passed": passed, "environment_end": rb.sample_environment(full=True)})
    print("failures:", {k: v for k, v in failures.items() if v} or "none", "passed:", passed)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
