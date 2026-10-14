"""Apply the common numeric gate (validate.py) to outcomes written as JSON lines
{"id", "outcome"} by a decider of the Native arm (e.g. the crates.io consumer). Every catalog
input must appear exactly once. Exits non-zero on any violation.

    python -B bench/check_outcomes.py <outcomes.jsonl> [--arm native]"""
import argparse
import json
from pathlib import Path

import catalog as cat
import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outcomes", type=Path)
    parser.add_argument("--arm", default="native")
    args = parser.parse_args()
    by_id = cat.by_id(cat.load())
    rows = [json.loads(line) for line in args.outcomes.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen = [r["id"] for r in rows]
    failures = {}
    if sorted(seen) != sorted(by_id):
        failures["_inputs"] = [f"missing {sorted(set(by_id) - set(seen))}, extra or repeated "
                               f"{sorted({s for s in seen if seen.count(s) > 1 or s not in by_id})}"]
    worst = 0.0
    for row in rows:
        case = by_id.get(row["id"])
        if case is None:
            continue
        violations = validate.check(case, args.arm, row["outcome"])
        if violations:
            failures[row["id"]] = violations
        elif row["outcome"]["status"] == "completed":
            worst = max(worst, validate.max_abs(row["outcome"]["probabilities"], case["reference"]["probabilities"]))
    print(json.dumps({"cases": len(rows), "failures": failures, "max_abs_vs_official": worst}, ensure_ascii=False))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
