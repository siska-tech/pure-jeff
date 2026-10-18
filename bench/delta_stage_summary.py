"""Summary of a bench/delta_stage_profile.py run: stage medians by thread count, their share of
the forward, Amdahl bounds, paired variant ratios, the timers' cost, the scaling probe and the
E1 decision of docs/native-delta-threads-plan-2026-10-18.md. Writes summary.json next to
runs.json and prints Markdown tables.

    python -B bench/delta_stage_summary.py <run dir>"""
import json
from pathlib import Path
import statistics as st
import sys

STAGES = ["delta_extract", "delta_prep", "delta_core", "delta_sync", "delta_writeback", "delta_recurrence"]
LABEL = {128: "128", 512: "512", 874: "874", 8192: "8192"}


def median(values):
    return st.median(values) if values else None


def main():
    folder = Path(sys.argv[1])
    runs = json.loads((folder / "runs.json").read_text(encoding="utf-8"))
    stage_rows = [dict(r, session=run["session"]) for run in runs if run["kind"] == "stages" for r in run["rows"]]
    untimed_rows = [r for run in runs if run["kind"] == "no_stage_timers" for r in run["rows"]]
    probes = [r for run in runs if run["kind"] == "probe" for r in run["rows"] if "probe" in r]
    out = {"failed_runs": [{k: run[k] for k in ("kind", "session", "threads", "returncode", "stderr")}
                           for run in runs if run["returncode"] != 0 or not run["rows"]]}

    # Bit identity: one hidden hash per input over every thread count, variant and session.
    hashes = {}
    for r in stage_rows + untimed_rows + [r for run in runs if run["kind"] == "probe" for r in run["rows"]
                                          if "hidden_sha256" in r]:
        hashes.setdefault(r["input_tokens"], set()).add(r["hidden_sha256"])
    out["hidden_hashes"] = {n: sorted(h) for n, h in sorted(hashes.items())}
    out["bitwise_identical"] = all(len(h) == 1 for h in hashes.values()) and all(
        r["bitwise_equal"] for r in stage_rows + untimed_rows)

    threads = sorted({r["threads"] for r in stage_rows})
    lengths = sorted({r["input_tokens"] for r in stage_rows})
    variants = ["serial", "scoped", "pool", "fused"]

    def rows(n, length, variant, source=stage_rows):
        return [r for r in source if r["threads"] == n and r["input_tokens"] == length and r["delta"] == variant]

    # Stage medians and shares.
    stages = {}
    for n in threads:
        for length in lengths:
            for variant in variants:
                rs = rows(n, length, variant)
                if not rs:
                    continue
                forward = median([r["forward_s"] for r in rs])
                entry = {"forward_s": forward, "count": len(rs),
                         "stages": {s: median([r["seconds"][s] for r in rs]) for s in STAGES},
                         "notes": {k: median([r["delta_notes"].get(k, 0.0) for r in rs])
                                   for k in sorted({k for r in rs for k in r["delta_notes"]})},
                         "peak_working_set": max(run["memory"]["max_process_peak_working_set"] for run in runs
                                                 if run["kind"] == "stages" and run["threads"] == n
                                                 and any(r["input_tokens"] == length for r in run["rows"]))}
                entry["delta_total_s"] = sum(entry["stages"].values())
                entry["delta_share"] = entry["delta_total_s"] / forward
                stages[f"t{n}/{length}/{variant}"] = entry
    out["stages"] = stages

    # Amdahl bounds from the serial rows: forward reduction if a stage were 0, and if the whole
    # recurrence divided by the thread count (16 heads at most).
    amdahl = {}
    for n in threads:
        for length in lengths:
            e = stages.get(f"t{n}/{length}/serial")
            if not e:
                continue
            f, d = e["forward_s"], e["delta_total_s"]
            amdahl[f"t{n}/{length}"] = {
                "delta_zero": d / f, "delta_divided": (d - d / min(n, 16)) / f,
                **{f"{s}_zero": e["stages"][s] / f for s in STAGES}}
    out["amdahl"] = amdahl

    # Paired ratios: variant / serial, same process, same rep.
    ratios = {}
    for n in threads:
        for length in lengths:
            serial = {(r["session"], r["rep"]): r["forward_s"] for r in rows(n, length, "serial")}
            for variant in variants[1:]:
                pairs = [r["forward_s"] / serial[(r["session"], r["rep"])] for r in rows(n, length, variant)
                         if (r["session"], r["rep"]) in serial]
                if pairs:
                    ratios[f"t{n}/{length}/{variant}"] = {
                        "median": median(pairs), "min": min(pairs), "max": max(pairs), "count": len(pairs),
                        "by_session": {s: median([r["forward_s"] / serial[(s, r["rep"])]
                                                  for r in rows(n, length, variant)
                                                  if r["session"] == s and (s, r["rep"]) in serial])
                                       for s in sorted({r["session"] for r in rows(n, length, variant)})}}
    out["ratios"] = ratios

    # Timers' cost: delta_recurrence with every stage timed vs timed as one span (other process).
    cost = {}
    for n in threads:
        for length in sorted({r["input_tokens"] for r in untimed_rows}):
            for variant in ("serial", "fused"):
                timed = rows(n, length, variant)
                untimed = rows(n, length, variant, untimed_rows)
                if timed and untimed:
                    cost[f"t{n}/{length}/{variant}"] = {
                        "staged_delta_s": median([sum(r["seconds"][s] for s in STAGES) for r in timed]),
                        "unstaged_delta_s": median([r["seconds"]["delta_recurrence"] for r in untimed]),
                        "staged_forward_s": median([r["forward_s"] for r in timed]),
                        "unstaged_forward_s": median([r["forward_s"] for r in untimed])}
    out["timer_cost"] = cost
    out["probe"] = probes

    # E1 decision (plan section "E1").
    def ratio(n, length, variant):
        return ratios.get(f"t{n}/{length}/{variant}")

    e1 = {}
    for variant in variants[1:]:
        effect = all(ratio(n, length, variant)["median"] <= 0.95 for n in threads if n >= 4 for length in (512, 874))
        no_regression = all(ratio(2, length, variant)["median"] <= 1.01 for length in lengths if length != 8192
                            if ratio(2, length, variant)) and all(
            ratio(n, 128, variant)["median"] <= 1.01 for n in threads if n >= 2)
        # Measured for serial and fused only (plan); None where there are no 8192 rows.
        long = [ratio(n, 8192, variant) for n in threads if n >= 4]
        long_ok = None if any(r is None for r in long) else all(
            len(r["by_session"]) == 2 and max(r["by_session"].values()) <= 1.0 for r in long)
        e1[variant] = {"effect_4plus": effect, "no_regression": no_regression, "long_8192": long_ok}
    eligible = [v for v, c in e1.items() if c["effect_4plus"] and c["no_regression"] and c["long_8192"] is True]
    out["e1"] = {"criteria": e1, "eligible": eligible, "bitwise_identical": out["bitwise_identical"]}
    (folder / "summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")

    # Markdown.
    print("## Stages (median s): serial | fused\n")
    for length in lengths:
        print(f"### {length} tokens\n")
        print("| threads | forward | extract | prep | core | sync | writeback | rest | delta share |")
        print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for n in threads:
            for variant in variants:
                e = stages.get(f"t{n}/{length}/{variant}")
                if e:
                    s = e["stages"]
                    print(f"| {n} {variant} | {e['forward_s']:.3f} | {s['delta_extract']:.4f} | {s['delta_prep']:.4f} | "
                          f"{s['delta_core']:.4f} | {s['delta_sync']:.4f} | {s['delta_writeback']:.4f} | "
                          f"{s['delta_recurrence']:.4f} | {e['delta_share']:.1%} |")
        print()
    print("## Ratios to serial (median of pairs [min, max])\n")
    print("| threads | length | " + " | ".join(variants[1:]) + " |")
    print("| ---: | ---: |" + " ---: |" * 3)
    for n in threads:
        for length in lengths:
            cells = [ratio(n, length, v) for v in variants[1:]]
            print(f"| {n} | {length} | " + " | ".join(
                f"{c['median']:.3f} [{c['min']:.3f}, {c['max']:.3f}]" if c else "-" for c in cells) + " |")
    print("\n## Amdahl (serial rows): forward reduction if the recurrence were 0 / divided by threads\n")
    for k, a in amdahl.items():
        print(f"- {k}: zero {a['delta_zero']:.1%}, divided {a['delta_divided']:.1%}, "
              f"extract {a['delta_extract_zero']:.1%}, prep {a['delta_prep_zero']:.1%}")
    print("\n## Timer cost\n")
    for k, c in cost.items():
        print(f"- {k}: staged {c['staged_delta_s']:.4f} vs unstaged {c['unstaged_delta_s']:.4f} s")
    print(f"\nbitwise identical: {out['bitwise_identical']}; failed runs: {out['failed_runs']}")
    print(f"E1: {json.dumps(out['e1'], indent=1)}")


if __name__ == "__main__":
    main()
