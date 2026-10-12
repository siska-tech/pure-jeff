"""Total time of 1/10/100 requests and memory for Native weight variants (issues #4, #14).

Each session is one fresh `resident_bench --mode api` process that loads the bundle and then
decides the same request N times. Variants are given as name=exe[,--retain-f32]@manifest. The
order of variants alternates per repetition (ABC, CBA, ...). Every decision passes the common
numeric gate (validate.py). Reported per session: startup (process start to loaded), each
decision, the cumulative time after 1/10/100 decisions (startup + decisions), and the tree's
Working Set, Private bytes, the process's lifetime peak Working Set and page faults.

    python -B bench/request_curve.py --output experiments/runs/curve \
        --variant main=experiments/runs/exe-main/resident_bench.exe@models/pure-jeff-bundle-t1.json \
        --variant reuse=runtime/rust/target/release/examples/resident_bench.exe@models/b.json \
        --variant retain=runtime/rust/target/release/examples/resident_bench.exe,--retain-f32@models/b.json \
        --case candidate-request:100:2 --case synthetic-ocr-ja-2-512:100:1 --case token-limit-8192:2:1"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import catalog as cat
import run_benchmark as rb
import stats
import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", action="append", required=True, help="name=exe[,--retain-f32]@manifest")
    parser.add_argument("--case", action="append", required=True, help="catalog id:requests:repetitions")
    parser.add_argument("--timeout", type=float, default=4 * 3600)
    args = parser.parse_args()
    busy = rb.busy_processes()
    if busy:
        raise SystemExit(f"build/install/benchmark processes are running: {busy}")
    by_id = cat.by_id(cat.load())
    variants = []
    for spec in args.variant:
        name, rest = spec.split("=", 1)
        program, manifest = rest.rsplit("@", 1)
        exe, *flags = program.split(",")
        exe, manifest = str(Path(exe).resolve()), str(Path(manifest).resolve())
        variants.append({"name": name, "exe": exe, "flags": flags, "manifest": manifest,
                         "exe_sha256": rb.sha(exe), "manifest_sha256": rb.sha(manifest)})
    cases = []
    for spec in args.case:
        case, count, reps = spec.split(":")
        cases.append((case, int(count), int(reps)))
    plan = []
    for case, count, reps in cases:
        for rep in range(reps):
            order = variants if rep % 2 == 0 else variants[::-1]
            plan.extend({"case": case, "count": count, "rep": rep, "variant": v["name"]} for v in order)
    args.output.mkdir(parents=True)
    env_start = rb.sample_environment(full=True)
    rb.save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.request_curve.preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "variants": variants, "plan": plan,
        "gates": validate.GATE, "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "hashes": {"driver": rb.sha(__file__), "catalog": rb.sha(cat.CATALOG)}, "environment_start": env_start})
    if env_start["ac_line_status"] != 1:
        raise SystemExit("AC power is required")
    env = os.environ | {"PYTHONUTF8": "1"}
    work = args.output / "work"
    work.mkdir()
    sessions, failures = [], []
    for i, item in enumerate(plan):
        variant = next(v for v in variants if v["name"] == item["variant"])
        job = work / f"job-{i}.json"
        job.write_text(json.dumps([{"name": item["case"], "phase": "measure", "max_input_tokens": cat.MAX_TOKENS,
                                    "request": by_id[item["case"]]["request"]}] * item["count"], ensure_ascii=False),
                       encoding="utf-8")
        if rb.busy_processes():
            raise SystemExit("build/install/benchmark processes started during the run")
        before = rb.sample_environment()
        run = rb.run_process([variant["exe"], *variant["flags"], "--mode", "api", variant["manifest"], str(job)],
                             env, args.timeout)
        events = [json.loads(line) for line in run["stdout"].splitlines() if line.startswith("{")]
        init = next((e for e in events if e["event"] == "init"), {})
        decisions = [e for e in events if e["event"] == "decision"]
        violations = [v for d in decisions for v in validate.check(by_id[item["case"]], "native", d["outcome"])]
        if run["returncode"] != 0 or len(decisions) != item["count"] or violations:
            failures.append({"session": i, "returncode": run["returncode"], "decisions": len(decisions),
                             "violations": violations[:5], "stderr": run["stderr"][-500:]})
        walls = [d["wall_s"] for d in decisions]
        cumulative = {str(n): init.get("startup_s", 0) + sum(walls[:n]) for n in (1, 10, 100) if n <= len(walls)}
        session = {**item, "returncode": run["returncode"], "process_wall_s": run["wall_s"], "init": init,
                   "walls": walls, "cumulative_s": cumulative, "memory": run["memory"], "affinity": run["affinity"],
                   "environment": {"before": before, "after": rb.sample_environment()},
                   "probabilities": sorted({tuple(d["outcome"].get("probabilities") or []) for d in decisions})}
        sessions.append(session)
        rb.save(work / f"session-{i}.json", session)
        print(f"{i + 1}/{len(plan)} {item['case']} x{item['count']} {item['variant']}: startup "
              f"{init.get('startup_s', 0):.2f}s warm median {stats.describe(walls[1:]).get('median', 0):.3f}s "
              f"peak {run['memory']['max_process_peak_working_set'] / 2**30:.2f} GiB", flush=True)
    summary = {"schema_version": "pure_jeff.request_curve.summary.v1", "failures": failures, "cases": {}}
    for case, count, _ in cases:
        rows = {}
        for v in variants:
            own = [s for s in sessions if s["case"] == case and s["variant"] == v["name"]]
            rows[v["name"]] = {
                "startup_s": stats.describe([s["init"].get("startup_s") for s in own]),
                "load_s": stats.describe([s["init"].get("load_s") for s in own]),
                "first_s": stats.describe([s["walls"][0] for s in own if s["walls"]]),
                "warm_s": stats.describe([w for s in own for w in s["walls"][1:]]),
                "cumulative_s": {n: stats.describe([s["cumulative_s"].get(n) for s in own]) for n in ("1", "10", "100")},
                "max_tree_working_set": max((s["memory"]["max_tree_working_set"] for s in own), default=None),
                "max_tree_private": max((s["memory"]["max_tree_private"] for s in own), default=None),
                "max_process_peak_working_set": max((s["memory"]["max_process_peak_working_set"] for s in own),
                                                    default=None),
                "max_process_page_faults": max((s["memory"]["max_process_page_faults"] for s in own), default=None),
                "retained_f32_bytes": next((s["init"].get("retained_f32_bytes") for s in own), None),
                "probability_vectors": len({p for s in own for p in s["probabilities"]})}
        names = [v["name"] for v in variants]
        for a in names:
            for b in names:
                if a == b:
                    continue
                extra = (rows[b]["startup_s"].get("median") or 0) - (rows[a]["startup_s"].get("median") or 0)
                saved = (rows[a]["warm_s"].get("median") or 0) - (rows[b]["warm_s"].get("median") or 0)
                if extra > 0 and saved > 0:
                    rows[b].setdefault("break_even_requests_vs", {})[a] = extra / saved
        summary["cases"][case] = rows
    bits = {}
    for case, _, _ in cases:
        vectors = {p for s in sessions if s["case"] == case for p in s["probabilities"]}
        bits[case] = len(vectors) == 1
    summary["bitwise_identical_across_variants"] = bits
    summary["valid"] = not failures and all(bits.values())
    rb.save(args.output / "summary.json", summary)
    print(json.dumps({"valid": summary["valid"], "failures": len(failures), "bits": bits}, indent=1))
    raise SystemExit(0 if summary["valid"] else 1)


if __name__ == "__main__":
    main()
