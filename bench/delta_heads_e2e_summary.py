"""Summary and E2 decision of a bench/delta_heads_e2e.py run (rules in
docs/native-delta-heads-e2e-plan-2026-10-18.md). Writes summary.json next to the run and prints
Markdown tables.

    python -B bench/delta_heads_e2e_summary.py <run dir>"""
import json
from pathlib import Path
import statistics as st
import sys

TIMED = {"candidate-request": 128, "synthetic-ocr-ascii-8-512": 512, "long-text": 874, "token-limit-8192": 8192}


def bits(outcome):
    return tuple(float(p).hex() for p in outcome["probabilities"]) if outcome.get("status") == "completed" else (
        "failed", outcome.get("failure"))


def main():
    folder = Path(sys.argv[1])
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "work").glob("[0-9]*.json"))]
    out = {"processes": len(runs), "failed_processes": [
        {k: r.get(k) for k in ("index", "kind", "threads", "arm", "returncode", "stderr")}
        for r in runs if r["returncode"] != 0]}
    decisions = [(r, d) for r in runs for d in r["decisions"]]
    out["gate_failures"] = [{"index": r["index"], "arm": r["arm"], "threads": r["threads"], "case": d["name"],
                             "gate": d["gate"]} for r, d in decisions if d["gate"]]

    # Bit identity: every decision of an input equals baseline 1 thread, whatever arm, thread
    # count, process or repeat.
    reference = {}
    for r, d in decisions:
        if r["arm"] == "baseline" and r["threads"] == 1:
            reference.setdefault(d["name"], bits(d["outcome"]))
    mismatch = sorted({(r["arm"], r["threads"], d["name"]) for r, d in decisions
                       if bits(d["outcome"]) != reference.get(d["name"])})
    out["bit_mismatches_vs_baseline_1_thread"] = [list(m) for m in mismatch]
    out["inputs_checked"] = sorted(reference)

    timeouts = [r for r in runs if r["kind"] == "timeout"]
    out["timeout_reuse"] = [{"arm": r["arm"], "threads": r["threads"], "returncode": r["returncode"],
                             "result": next((e for e in r["events"] if "timeout" in e), None)} for r in timeouts]

    sessions = sorted({r["session"] for r in runs})
    threads = sorted({r["threads"] for r in runs})

    def warm(session, n, arm, case):
        return [d["wall_s"] for r in runs if r["kind"] == "warm" and (r["session"], r["threads"], r["arm"]) ==
                (session, n, arm) for d in r["decisions"] if d["phase"] == "measure" and d["name"] == case]

    def oneshot(session, n, arm, case):
        return [r for r in runs if r["kind"] == "oneshot" and (r["session"], r["threads"], r["arm"], r["case"]) ==
                (session, n, arm, case) and r["returncode"] == 0]

    rows, violations = [], []
    for s in sessions:
        for n in threads:
            for case, length in TIMED.items():
                b, c = st.median(warm(s, n, "baseline", case)), st.median(warm(s, n, "candidate", case))
                ob, oc = oneshot(s, n, "baseline", case), oneshot(s, n, "candidate", case)
                ob_s = st.median(r["process_wall_s"] for r in ob)
                oc_s = st.median(r["process_wall_s"] for r in oc)
                mem = {}
                for kind, pick in (("oneshot", lambda arm: oneshot(s, n, arm, case)),):
                    for key in ("max_process_peak_working_set", "max_tree_private"):
                        mb = max(r["memory"][key] for r in pick("baseline"))
                        mc = max(r["memory"][key] for r in pick("candidate"))
                        mem[f"{kind}_{key}"] = mc / mb
                row = {"session": s, "threads": n, "tokens": length, "warm_baseline_s": b, "warm_candidate_s": c,
                       "warm_ratio": c / b, "oneshot_baseline_s": ob_s, "oneshot_candidate_s": oc_s,
                       "oneshot_ratio": oc_s / ob_s, "memory_ratios": mem}
                rows.append(row)
                if n == 1 and not 0.97 <= row["warm_ratio"] <= 1.03:
                    violations.append(f"s{s} t1 {length}: warm ratio {row['warm_ratio']:.3f} outside 0.97-1.03")
                if n >= 2 and row["warm_ratio"] > 1.02:
                    violations.append(f"s{s} t{n} {length}: warm ratio {row['warm_ratio']:.3f} > 1.02")
                if n >= 4 and length >= 512 and row["warm_ratio"] > 0.95:
                    violations.append(f"s{s} t{n} {length}: warm ratio {row['warm_ratio']:.3f} > 0.95")
                if row["oneshot_ratio"] > 1.05:
                    violations.append(f"s{s} t{n} {length}: one-shot ratio {row['oneshot_ratio']:.3f} > 1.05")
                for key, ratio in mem.items():
                    if ratio > 1.03:
                        violations.append(f"s{s} t{n} {length}: {key} ratio {ratio:.3f} > 1.03")
            for key in ("max_process_peak_working_set", "max_tree_private"):
                mb = max(r["memory"][key] for r in runs if r["kind"] == "warm" and r["session"] == s
                         and r["threads"] == n and r["arm"] == "baseline")
                mc = max(r["memory"][key] for r in runs if r["kind"] == "warm" and r["session"] == s
                         and r["threads"] == n and r["arm"] == "candidate")
                rows.append({"session": s, "threads": n, "tokens": "warm-process", "memory_ratios": {f"warm_{key}": mc / mb},
                             "baseline_bytes": mb, "candidate_bytes": mc, "key": key})
                if mc / mb > 1.03:
                    violations.append(f"s{s} t{n} warm process: {key} ratio {mc / mb:.3f} > 1.03")
    out["rows"] = rows
    if out["failed_processes"]:
        violations.append("failed processes")
    if out["gate_failures"]:
        violations.append("numeric gate failures")
    if mismatch:
        violations.append("bit mismatches against baseline 1 thread")
    if len(timeouts) != 2 * len(threads) or not all(
            r["returncode"] == 0 and (t := next((e for e in r["events"] if "timeout" in e), None))
            and t["timeout"] and t["reuse_bitwise_equal"] for r in timeouts):
        violations.append("timeout reuse")
    out["violations"] = violations
    out["e2_met"] = not violations
    (folder / "summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")

    print("| session | threads | tokens | warm main | warm candidate | ratio | one-shot main | one-shot candidate | ratio | peak WS | private |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        if r["tokens"] == "warm-process":
            continue
        m = r["memory_ratios"]
        print(f"| {r['session']} | {r['threads']} | {r['tokens']} | {r['warm_baseline_s']:.3f} | {r['warm_candidate_s']:.3f} | "
              f"{r['warm_ratio']:.3f} | {r['oneshot_baseline_s']:.2f} | {r['oneshot_candidate_s']:.2f} | "
              f"{r['oneshot_ratio']:.3f} | {m['oneshot_max_process_peak_working_set']:.3f} | {m['oneshot_max_tree_private']:.3f} |")
    print("\nwarm-process memory ratios:")
    for r in rows:
        if r["tokens"] == "warm-process":
            print(f"  s{r['session']} t{r['threads']} {r['key']}: {r['baseline_bytes'] / 2**30:.3f} -> "
                  f"{r['candidate_bytes'] / 2**30:.3f} GiB ({r['candidate_bytes'] / r['baseline_bytes']:.3f})")
    print(f"\nprocesses {out['processes']}, failed {len(out['failed_processes'])}, gate failures {len(out['gate_failures'])}, "
          f"bit mismatches {len(mismatch)} over {len(reference)} inputs")
    print("timeout reuse:", [(t["arm"], t["threads"], t["result"] and t["result"]["stopped_after_s"]) for t in out["timeout_reuse"]])
    print("violations:", violations or "none")
    print("E2 met:", out["e2_met"])


if __name__ == "__main__":
    main()
