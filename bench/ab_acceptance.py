"""A/B acceptance of a library change against a baseline build on one machine, through the
public API (`resident_bench --mode api`, no timers inside). Plan and rules of its first use:
docs/native-fixed-k-chunks-amd-acceptance-plan-2026-10-21.md; summary: bench/ab_acceptance_summary.py.

Two sessions (thread counts ascending, then descending); at every step the arms alternate which
runs first.
  warm      one resident process per (session, threads, arm): a warm-up, the timed inputs
            `REPS` times in a fixed shuffled order, then every other catalog input once;
  oneshot   one new process per timed input (load + first decision); the process's lifetime
            peaks (private commit, working set) are read from the OS after it exits;
  affinity  (candidate) one resident process per affinity mask, set right after the process
            starts and before it loads anything, deciding every catalog input once;
  timeout   (candidate, session 0) timeout_reuse: a deadline inside the 8192-token forward,
            then the same Model again.
Every decision passes the common numeric gate against the official reference.

    python -B bench/ab_acceptance.py --output <new dir> --baseline <release dir> \\
        --candidate <release dir> --baseline-bundle <template> --candidate-bundle <template>

A release dir holds examples/resident_bench.exe and examples/timeout_reuse.exe; a bundle
template has `{n}` for the thread count (each build needs bundles it locked itself)."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random

import catalog as cat
import delta_heads_affinity as aff
import delta_heads_memory as mem
import run_benchmark as rb
import validate

ROOT = cat.ROOT
THREADS = [1, 4, 16]
TIMED = ["candidate-request", "synthetic-ocr-ascii-8-512", "long-text", "token-limit-8192"]
REPS = 3
ONESHOT_REPS = {"candidate-request": 3, "synthetic-ocr-ascii-8-512": 3, "long-text": 3, "token-limit-8192": 1}
AFFINITY = {"cpus 0-15": 0x0000FFFF, "cpus 16-31": 0xFFFF0000}
AFFINITY_THREADS = 4
TIMEOUT_THREADS = [1, 4, 16]
SEED = 20261021
ARMS = ("baseline", "candidate")


def plan(threads, oneshot_reps, sessions, affinity, timeout_threads):
    entries = []
    for session in sessions:
        for i, n in enumerate(threads if session == 0 else threads[::-1]):
            arms = ARMS if (i + session) % 2 == 0 else ARMS[::-1]
            entries += [{"kind": "warm", "session": session, "threads": n, "arm": a} for a in arms]
            for j, (case, reps) in enumerate(oneshot_reps.items()):
                for rep in range(reps):
                    order = arms if (j + rep) % 2 == 0 else arms[::-1]
                    entries += [{"kind": "oneshot", "session": session, "threads": n, "arm": a, "case": case,
                                 "rep": rep} for a in order]
    entries += [{"kind": "affinity", "session": 0, "threads": AFFINITY_THREADS, "arm": "candidate", "mask": m}
                for m in affinity]
    entries += [{"kind": "timeout", "session": 0, "threads": n, "arm": "candidate"} for n in timeout_threads]
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-bundle", required=True)
    parser.add_argument("--candidate-bundle", required=True)
    parser.add_argument("--threads", type=int, nargs="+", default=THREADS)
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    parser.add_argument("--smoke", action="store_true",
                        help="a minimal run to check the driver and the summary (never for a decision)")
    args = parser.parse_args()
    timed_cases, reps, oneshot_reps, sessions = TIMED, REPS, ONESHOT_REPS, (0, 1)
    affinity, timeout_threads = AFFINITY, TIMEOUT_THREADS
    if args.smoke:
        timed_cases, reps, oneshot_reps, sessions = ["candidate-request"], 1, {"candidate-request": 1}, (0,)
        affinity, timeout_threads = {"cpus 0-15": AFFINITY["cpus 0-15"]}, [args.threads[0]]
    if rb.busy_processes():
        raise SystemExit("build/install/benchmark processes are running")
    by_id = cat.by_id(cat.load())
    every = sorted(by_id)
    if args.smoke:
        every = ["candidate-request", "reversed", "token-limit-8193"]
    exes = {"baseline": args.baseline, "candidate": args.candidate}
    bundles = {"baseline": {n: ROOT / args.baseline_bundle.format(n=n) for n in args.threads},
               "candidate": {n: ROOT / args.candidate_bundle.format(n=n) for n in args.threads}}
    for n in args.threads:
        a, b = (json.loads(bundles[arm][n].read_text(encoding="utf-8")) for arm in ARMS)
        if {k for k in a if a[k] != b.get(k)} - {"runtime_build_sha256"}:
            raise SystemExit(f"bundles for {n} threads differ beyond the runtime build")
    args.output.mkdir(parents=True)
    work = args.output / "work"
    work.mkdir()
    job = lambda names, phase: [{"name": c, "phase": phase, "max_input_tokens": cat.MAX_TOKENS,
                                 "request": by_id[c]["request"]} for c in names]
    timed = [c for c in timed_cases for _ in range(reps)]
    random.Random(SEED).shuffle(timed)
    files = {"warm": job(["synthetic-ocr-ja-2-256"], "warmup") + job(timed, "measure")
             + job([c for c in every if c not in timed_cases], "gate"),
             "affinity": job(every, "gate")}
    files.update({f"oneshot-{c}": job([c], "measure") for c in oneshot_reps})
    for name, content in files.items():
        (work / f"{name}.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    entries = plan(args.threads, oneshot_reps, sessions, affinity, timeout_threads)
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.ab_acceptance.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "smoke": args.smoke, "plan": entries, "seed": SEED, "timed": timed_cases, "reps": reps,
        "oneshot_reps": oneshot_reps, "affinity": affinity,
        "timeout_seconds": args.timeout_seconds, "gates": validate.GATE, "inputs": every,
        "jobs": {name: [f"{c['name']}/{c['phase']}" for c in content] for name, content in files.items()},
        "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "hashes": {"driver": rb.sha(__file__), "catalog": rb.sha(cat.CATALOG),
                   "exes": {arm: {e: rb.sha(d / f"examples/{e}.exe") for e in ("resident_bench", "timeout_reuse")}
                            for arm, d in exes.items()},
                   "bundles": {arm: {n: rb.sha(p) for n, p in b.items()} for arm, b in bundles.items()}},
        "environment_start": rb.sample_environment(full=True)})
    golden = ROOT / "tests/fixtures/jeff-golden"
    for index, entry in enumerate(entries):
        if rb.busy_processes():
            raise SystemExit("build/install/benchmark processes started during the run")
        arm, n, kind = entry["arm"], entry["threads"], entry["kind"]
        resident, bundle = exes[arm] / "examples/resident_bench.exe", bundles[arm][n]
        if kind == "timeout":
            run = rb.run_process([str(exes[arm] / "examples/timeout_reuse.exe"), str(bundle),
                                  str(golden / "token-limit-8192.json"), str(golden / "candidate-request.json"),
                                  str(args.timeout_seconds)], None, 3600)
            result = {"returncode": run["returncode"], "stderr": run["stderr"][-1000:],
                      "result": next((json.loads(l) for l in run["stdout"].splitlines() if l.startswith("{")), None),
                      "decisions": []}
        elif kind == "affinity":
            run = aff.run(resident, bundle, work / "affinity.json", affinity[entry["mask"]])
            result = {"returncode": run["returncode"], "affinity": run["affinity"], "stderr": run["stderr"],
                      "decisions": run["decisions"]}
        else:
            name = "warm" if kind == "warm" else f"oneshot-{entry['case']}"
            run = mem.run([str(resident), "--mode", "api", str(bundle), str(work / f"{name}.json")])
            events = [json.loads(l) for l in run.pop("stdout").splitlines() if l.startswith("{")]
            result = {**run, "init": next((e for e in events if e.get("event") == "init"), None),
                      "decisions": [e for e in events if e.get("event") == "decision"]}
        for d in result["decisions"]:
            d["gate"] = validate.check(by_id[d["name"]], "native", d["outcome"])
        rb.save(work / f"{index:03d}-{kind}-t{n}-{arm}.json", {**entry, "index": index, **result})
        print(f"{index:03d} {kind} s{entry['session']} t{n} {arm} {entry.get('case', entry.get('mask', ''))} "
              f"rc={result['returncode']} decisions={len(result['decisions'])} "
              f"gate_failures={sum(bool(d['gate']) for d in result['decisions'])}"
              + (f" commit={result['peak_private_commit'] / 2**30:.3f} GiB" if result.get("peak_private_commit") else "")
              + (f" {result['result']}" if kind == "timeout" else ""), flush=True)
    rb.save(args.output / "environment-end.json", rb.sample_environment(full=True))


if __name__ == "__main__":
    main()
