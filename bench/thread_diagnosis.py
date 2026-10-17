"""Diagnosis for issue #18: are Native decisions with more compute threads repeatable bit for bit,
how far do they move from one thread, and how does the speed scale (with official Jeff at the
same thread count for reference)? Descriptive only: no acceptance, no change to the default
path.

    python -B bench/thread_diagnosis.py --output <new dir> --threads 1 2 4 8 16 \
        --python <official Jeff python> [--processes 2] [--repeats 3]

Bundles models/pure-jeff-bundle-tN-diag.json (Native, locked by runtime/rust's jeff.exe) and
models/pure-jeff-reference-bundle-tN.json (official) are created when missing. For each thread
count, `processes` independent Native resident sessions (API path) run the same job: the short
inputs and policy-boundary inputs `repeats` times in a fixed shuffled order, then the long
inputs once; the order of thread counts alternates between process rounds. One official Jeff
session per thread count runs 128, 512 and 874 tokens `repeats` times. Every decision passes
the common numeric gate against the official 1-thread reference."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import catalog as cat
import run_benchmark as rb
import stats
import validate

ROOT = cat.ROOT
SHORT = ["synthetic-ocr-ja-2-127", "candidate-request", "synthetic-ocr-ja-2-129", "special-token-text", "asr-unicode",
         "synthetic-ocr-ja-2-256", "synthetic-ocr-ascii-8-384", "synthetic-ocr-ja-2-511", "synthetic-ocr-ja-2-512",
         "synthetic-ocr-ascii-3-513", "policy-top1-above", "policy-top1-below", "policy-near-tie", "policy-margin-near"]
LONG = ["long-text", "maximum-candidates", "token-limit-8192"]
OFFICIAL = ["candidate-request", "synthetic-ocr-ja-2-512", "long-text"]
REVISION = "51552f39a943d62e8387c4ea5e17026a1408729f"


def bundles(n, python):
    native = ROOT / f"models/pure-jeff-bundle-t{n}-diag.json"
    if not native.exists():
        subprocess.run([str(ROOT / "runtime/rust/target/release/jeff.exe"), "lock", str(ROOT / "models/jeff-checkpoint"),
                        str(native), REVISION, "0.7", "0.1", str(n)], check=True, capture_output=True)
    official = ROOT / f"models/pure-jeff-reference-bundle-t{n}.json"
    if not official.exists():
        subprocess.run([str(python), "-B", str(ROOT / "runtime/jeff_worker.py"), "--lock", "--manifest", str(official),
                        "--checkpoint", str((ROOT / "models/jeff-checkpoint").resolve()),
                        "--source", str((ROOT / "vendor/jeff").resolve()),
                        "--source-revision", "3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0",
                        "--min-probability", "0.7", "--min-margin", "0.1", "--cpu-threads", str(n)], check=True)
    return native, official


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4, 8, 16])
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--processes", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261017)
    args = parser.parse_args()
    if rb.busy_processes():
        raise SystemExit("build/install/benchmark processes are running")
    by_id = cat.by_id(cat.load())
    exe = ROOT / "runtime/rust/target/release/examples/resident_bench.exe"
    short = [c for c in SHORT for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(short)
    native_job = [{"name": c, "phase": "measure", "max_input_tokens": cat.MAX_TOKENS, "request": by_id[c]["request"]}
                  for c in short + LONG]
    official_job = [{"name": c, "phase": "measure", "max_input_tokens": cat.MAX_TOKENS, "request": by_id[c]["request"]}
                    for c in OFFICIAL for _ in range(args.repeats)]
    args.output.mkdir(parents=True)
    work = args.output / "work"
    work.mkdir()
    (work / "native-job.json").write_text(json.dumps(native_job, ensure_ascii=False), encoding="utf-8")
    (work / "official-job.json").write_text(json.dumps(official_job, ensure_ascii=False), encoding="utf-8")
    paths = {n: bundles(n, args.python) for n in args.threads}
    plan = [("native", n, p) for p in range(args.processes)
            for n in (args.threads if p % 2 == 0 else args.threads[::-1])]
    plan += [("official", n, 0) for n in args.threads]
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.thread_diagnosis.preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "threads": args.threads, "plan": plan,
        "native_job": short + LONG, "official_job": [c for c in OFFICIAL for _ in range(args.repeats)],
        "gates": validate.GATE, "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "hashes": {"resident_exe": rb.sha(exe), "driver": rb.sha(__file__), "catalog": rb.sha(cat.CATALOG),
                   "bundles": {n: [rb.sha(a), rb.sha(b)] for n, (a, b) in paths.items()}},
        "environment_start": rb.sample_environment(full=True)})
    sessions = []
    for arm, n, process in plan:
        native, official = paths[n]
        threads = str(n)
        env = os.environ | {"PYTHONUTF8": "1", "OMP_NUM_THREADS": threads, "MKL_NUM_THREADS": threads}
        if arm == "native":
            command = [str(exe), "--mode", "api", str(native), str(work / "native-job.json")]
        else:
            command = [str(args.python), "-B", str(ROOT / "bench/jeff_resident.py"), "--mode", "api", str(official),
                       str(work / "official-job.json")]
        run = rb.run_process(command, env, 4 * 3600)
        events = [json.loads(line) for line in run["stdout"].splitlines() if line.startswith("{")]
        init = next((e for e in events if e["event"] == "init"), {})
        decisions = [e for e in events if e["event"] == "decision"]
        for d in decisions:
            d["gate"] = validate.check(by_id[d["name"]], arm if arm == "native" else "jeff", d["outcome"])
        session = {"arm": arm, "threads": n, "process": process, "returncode": run["returncode"],
                   "init": init, "memory": run["memory"], "decisions": decisions, "stderr": run["stderr"][-2000:]}
        sessions.append(session)
        rb.save(work / f"{arm}-t{n}-p{process}.json", session)
        print(f"{arm} t{n} p{process}: {len(decisions)} decisions, gate failures "
              f"{sum(bool(d['gate']) for d in decisions)}, threads reported "
              f"{init.get('compute_threads', init.get('torch_threads'))}", flush=True)
    # Analysis.
    bits = lambda o: tuple(float(p).hex() for p in o["probabilities"]) if o.get("status") == "completed" else None
    native = [s for s in sessions if s["arm"] == "native"]
    one = {}
    for s in native:
        if s["threads"] == min(args.threads):
            for d in s["decisions"]:
                one.setdefault(d["name"], bits(d["outcome"]))
    summary = {"schema_version": "pure_jeff.thread_diagnosis.summary.v1", "threads": {}}
    for n in args.threads:
        own = [s for s in native if s["threads"] == n]
        per_case = {}
        for s in own:
            for d in s["decisions"]:
                per_case.setdefault(d["name"], []).append((s["process"], bits(d["outcome"]), d["outcome"], d["wall_s"]))
        within = sorted(c for c, rows in per_case.items()
                        if any(len({b for p, b, _, _ in rows if p == q}) > 1 for q in range(args.processes)))
        across = sorted(c for c, rows in per_case.items() if len({b for _, b, _, _ in rows}) > 1)
        vs_one = {}
        for c, rows in per_case.items():
            ref = by_id[c]["reference"]["probabilities"]
            base = [float.fromhex(h) for h in one[c]] if one.get(c) else None
            diffs = [validate.max_abs(o["probabilities"], base) for _, _, o, _ in rows if base and o.get("status") == "completed"]
            vs_one[c] = {"bit_equal_to_min_threads": all(b == one.get(c) for _, b, _, _ in rows),
                         "max_abs_vs_min_threads": max(diffs) if diffs else None,
                         "max_abs_vs_official": max(validate.max_abs(o["probabilities"], ref) for _, _, o, _ in rows)}
        official_s = [s for s in sessions if s["arm"] == "official" and s["threads"] == n]
        speed = {c: {"native": stats.describe([w for _, _, _, w in per_case[c]]).get("median")} for c in OFFICIAL + LONG}
        for c in OFFICIAL:
            speed[c]["official"] = stats.describe([d["wall_s"] for s in official_s for d in s["decisions"]
                                                   if d["name"] == c]).get("median")
        summary["threads"][n] = {
            "gate_failures": sum(bool(d["gate"]) for s in own + official_s for d in s["decisions"]),
            "sessions_ok": all(s["returncode"] == 0 for s in own + official_s),
            "reported_threads": sorted({s["init"].get("compute_threads") for s in own}),
            "official_threads": sorted({s["init"].get("torch_threads") for s in official_s}),
            "within_process_bit_mismatch": within, "across_process_bit_mismatch": across,
            "cases_not_bit_equal_to_min_threads": sorted(c for c, v in vs_one.items() if not v["bit_equal_to_min_threads"]),
            "max_abs_vs_min_threads": max((v["max_abs_vs_min_threads"] or 0) for v in vs_one.values()),
            "max_abs_vs_official": max(v["max_abs_vs_official"] for v in vs_one.values()),
            "judgments_vs_official_ok": all(not d["gate"] for s in own for d in s["decisions"]),
            "median_wall_s": speed,
            "peak_working_set_gib": max(s["memory"]["max_process_peak_working_set"] for s in own) / 2**30,
        }
    summary["environment_end"] = rb.sample_environment(full=True)
    rb.save(args.output / "summary.json", summary)
    print(json.dumps({n: {k: v for k, v in row.items() if k != "median_wall_s"} for n, row in summary["threads"].items()},
                     indent=1))


if __name__ == "__main__":
    main()
