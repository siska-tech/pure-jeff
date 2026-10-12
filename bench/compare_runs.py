"""Compare a candidate run of the default path with a baseline run of the same stage.

    python -B bench/compare_runs.py BASELINE_DIR CANDIDATE_DIR [--arm native] [--output report.json]

Reports, per measured case of the arm:
  - regression: candidate / baseline of the one-shot median wall time and of the peak working
    set (oneshot stage), or of the resident warm median (short/full stage); above 1.05 is a
    regression (stats.REGRESSION). Descriptive: no interval, so a flagged case is re-measured,
    not explained away.
  - bits: whether every completed probability vector of the case is bitwise identical in both
    runs. Required for an optimisation of the default path at the same build conditions; not
    expected across dependency versions.
Exits 1 if any case regresses or differs in bits."""
import argparse
import json
from pathlib import Path

import stats


def load(folder):
    folder = Path(folder)
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    sessions = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "sessions").glob("*.json"))]
    return summary, sessions


def bits(sessions, arm):
    out = {}
    for s in sessions:
        if s["arm"] != arm:
            continue
        for d in s["decisions"]:
            if d["outcome"].get("status") == "completed":
                out.setdefault(d["name"], set()).add(tuple(float(p).hex() for p in d["outcome"]["probabilities"]))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--arm", default="native")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    (base, base_sessions), (cand, cand_sessions) = load(args.baseline), load(args.candidate)
    if base["stage"] != cand["stage"] or base.get("threads") != cand.get("threads"):
        raise SystemExit("the runs differ in stage or threads")
    if not (base["valid"] and cand["valid"]):
        raise SystemExit("both runs must be valid (gate, repeat and environment)")
    report = {"stage": base["stage"], "arm": args.arm, "threshold": stats.REGRESSION, "cases": {}}
    base_bits, cand_bits = bits(base_sessions, args.arm), bits(cand_sessions, args.arm)
    for case, row in base["cases"].items():
        if args.arm not in row or args.arm not in cand["cases"].get(case, {}):
            continue
        before, after = row[args.arm], cand["cases"][case][args.arm]
        if base["stage"] == "oneshot":
            entry = {"wall_median": stats.regression(before["wall_s"]["median"], after["wall_s"]["median"]),
                     "peak_working_set": stats.regression(before["max_process_peak_working_set"]["max"],
                                                          after["max_process_peak_working_set"]["max"])}
        else:
            entry = {"warm_median": stats.regression(before["median"], after["median"])}
        entry["bits_identical"] = base_bits.get(case) == cand_bits.get(case) and len(base_bits.get(case, ())) == 1
        report["cases"][case] = entry
    report["regressed"] = sorted(c for c, e in report["cases"].items()
                                 if any(isinstance(v, dict) and v.get("regressed") for v in e.values()))
    report["bits_differ"] = sorted(c for c, e in report["cases"].items() if not e["bits_identical"])
    text = json.dumps(report, indent=1)
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text + "\n")
    print(text)
    raise SystemExit(1 if report["regressed"] or report["bits_differ"] else 0)


if __name__ == "__main__":
    main()
