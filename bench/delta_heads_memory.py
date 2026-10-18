"""Issue #18, E2b: peak memory of the DeltaNet-heads candidate against main, with the operating
system's lifetime peaks instead of samples. Plan: docs/native-delta-heads-e2e-plan-2026-10-18.md
(section E2b).

E2 sampled each process tree's Private bytes every 0.1 s (bench/procmem.py), which misses
peaks shorter than a sample. Here every one-shot process (`resident_bench --mode api`, one
decision) is opened when it starts and its counters are read after it exits: PeakPagefileUsage
(the peak private commit over the process's life) and PeakWorkingSetSize. Two sessions (thread
counts ascending, then descending); at each thread count and input the arms alternate.

    python -B bench/delta_heads_memory.py --output <new dir> --baseline <dir> --candidate <dir>"""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

import catalog as cat
import procmem as pm
import run_benchmark as rb
import validate

ROOT = cat.ROOT
THREADS = [1, 2, 4, 8, 16]
CASES = {"candidate-request": 3, "synthetic-ocr-ascii-8-512": 3, "long-text": 3, "token-limit-8192": 1}
ARMS = ("baseline", "candidate")
SYNCHRONIZE = 0x00100000


def plan(threads=THREADS, cases=CASES, sessions=(0, 1)):
    entries = []
    for session in sessions:
        for i, n in enumerate(threads if session == 0 else threads[::-1]):
            for j, (case, reps) in enumerate(cases.items()):
                for rep in range(reps):
                    arms = ARMS if (i + j + rep + session) % 2 == 0 else ARMS[::-1]
                    entries += [{"session": session, "threads": n, "case": case, "rep": rep, "arm": a} for a in arms]
    return entries


def run(command):
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    handle = pm._kernel.OpenProcess(pm.PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, process.pid)
    out, err = process.communicate(timeout=3600)
    wall = time.perf_counter() - started
    value = pm.Counters(cb=c.sizeof(pm.Counters))
    ok = handle and pm._psapi.GetProcessMemoryInfo(c.c_void_p(handle), c.byref(value), c.sizeof(value))
    if handle:
        pm._kernel.CloseHandle(c.c_void_p(handle))
    return {"returncode": process.returncode, "process_wall_s": wall, "stdout": out.decode("utf-8"),
            "stderr": err.decode("utf-8", errors="replace")[-2000:],
            "peak_private_commit": value.PeakPagefileUsage if ok else None,
            "peak_working_set": value.PeakWorkingSetSize if ok else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    # A smaller plan (e.g. the final-commit check); the defaults are the registered E2b plan.
    parser.add_argument("--threads", type=int, nargs="+", default=THREADS)
    parser.add_argument("--case", nargs=2, action="append", metavar=("ID", "REPS"),
                        help="input and its repetitions (repeatable); default: the E2b inputs")
    parser.add_argument("--sessions", type=int, default=2, choices=(1, 2))
    args = parser.parse_args()
    cases = {c: int(r) for c, r in args.case} if args.case else CASES
    threads, sessions = args.threads, tuple(range(args.sessions))
    if rb.busy_processes():
        raise SystemExit("build/install/benchmark processes are running")
    by_id = cat.by_id(cat.load())
    exes = {"baseline": args.baseline / "examples/resident_bench.exe",
            "candidate": args.candidate / "examples/resident_bench.exe"}
    bundles = {"baseline": {n: ROOT / f"models/pure-jeff-bundle-t{n}-diag.json" for n in threads},
               "candidate": {n: ROOT / f"models/pure-jeff-bundle-t{n}-delta-heads.json" for n in threads}}
    args.output.mkdir(parents=True)
    work = args.output / "work"
    work.mkdir()
    for case in cases:
        job = [{"name": case, "phase": "measure", "max_input_tokens": cat.MAX_TOKENS, "request": by_id[case]["request"]}]
        (work / f"{case}.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    entries = plan(threads, cases, sessions)
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.delta_heads_memory.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "plan": entries, "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "hashes": {"driver": rb.sha(__file__), "catalog": rb.sha(cat.CATALOG),
                   "exes": {arm: rb.sha(p) for arm, p in exes.items()},
                   "bundles": {arm: {n: rb.sha(p) for n, p in b.items()} for arm, b in bundles.items()}},
        "environment_start": rb.sample_environment(full=True)})
    results = []
    for index, entry in enumerate(entries):
        if rb.busy_processes():
            raise SystemExit("build/install/benchmark processes started during the run")
        arm, n = entry["arm"], entry["threads"]
        result = run([str(exes[arm]), "--mode", "api", str(bundles[arm][n]), str(work / f"{entry['case']}.json")])
        decisions = [json.loads(line) for line in result.pop("stdout").splitlines()
                     if line.startswith("{") and '"decision"' in line]
        decisions = [d for d in decisions if d.get("event") == "decision"]
        for d in decisions:
            d["gate"] = validate.check(by_id[d["name"]], "native", d["outcome"])
        results.append({**entry, "index": index, **result, "decisions": decisions})
        print(f"{index:03d} s{entry['session']} t{n} {entry['case']} {arm} rc={result['returncode']} "
              f"commit={(result['peak_private_commit'] or 0) / 2**30:.3f} GiB "
              f"ws={(result['peak_working_set'] or 0) / 2**30:.3f} GiB "
              f"gate_failures={sum(bool(d['gate']) for d in decisions)}", flush=True)
    rb.save(args.output / "runs.json", results)
    rb.save(args.output / "environment-end.json", rb.sample_environment(full=True))
    # E2b decision: max over reps of each peak, candidate / baseline, per (session, threads, case).
    rows, violations = [], []
    for s in sessions:
        for n in threads:
            for case in cases:
                peaks = {arm: [r for r in results if (r["session"], r["threads"], r["case"], r["arm"]) == (s, n, case, arm)]
                         for arm in ARMS}
                row = {"session": s, "threads": n, "case": case}
                for key in ("peak_private_commit", "peak_working_set"):
                    b, cnd = (max(r[key] for r in peaks[arm]) for arm in ARMS)
                    row[key] = {"baseline": b, "candidate": cnd, "ratio": cnd / b}
                    if cnd / b > 1.03:
                        violations.append(f"s{s} t{n} {case}: {key} {cnd / b:.3f}")
                rows.append(row)
    failures = [r["index"] for r in results if r["returncode"] != 0 or any(d["gate"] for d in r["decisions"])
                or r["peak_private_commit"] is None]
    rb.save(args.output / "summary.json", {"rows": rows, "violations": violations, "failed": failures,
                                           "e2b_met": not violations and not failures})
    print("violations:", violations or "none", "failed:", failures or "none")
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
