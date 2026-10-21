"""Summary and decision of a bench/ab_acceptance.py run (rules:
docs/native-fixed-k-chunks-amd-acceptance-plan-2026-10-21.md). Writes summary.json and the two
bit references (bit-reference-baseline.json, bit-reference-candidate.json) next to the run,
refusing to overwrite any of them, and prints Markdown tables.

    python -B bench/ab_acceptance_summary.py <run dir>"""
import hashlib
import json
from pathlib import Path
import statistics as st
import sys

import catalog as cat

WARM_LIMIT = 1.03
ONESHOT_LIMIT = 1.05
MEMORY_LIMIT = 1.03


def outcome_key(outcome):
    """Everything a decision returns that must repeat bit for bit: probabilities (as hex), the
    judgment, the candidate order, or the failure."""
    if outcome.get("status") != "completed":
        return {"status": outcome.get("status"), "failure": outcome.get("failure")}
    return {"status": "completed", "probabilities": [float(p).hex() for p in outcome["probabilities"]],
            "judgment": outcome.get("judgment"), "candidate_ids": outcome.get("candidate_ids"),
            "input_tokens": outcome.get("input_tokens"), "forwards": outcome.get("forwards"),
            "rendered_prompt_sha256": outcome.get("rendered_prompt_sha256")}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def main():
    folder = Path(sys.argv[1])
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "work").glob("[0-9]*.json"))]
    prereg = json.loads((folder / "preregistration.json").read_text(encoding="utf-8"))
    by_id = cat.by_id(cat.load())
    timed = {c: by_id[c]["tokens"] for c in prereg["timed"]}
    violations = []
    if prereg.get("smoke"):
        violations.append("smoke run: never a decision")
    failed = [(r["index"], r["kind"], r["arm"], r["threads"]) for r in runs if r["returncode"] != 0]
    if failed:
        violations.append(f"failed processes: {failed}")
    gate = [(r["index"], r["arm"], d["name"], d["gate"]) for r in runs for d in r["decisions"] if d["gate"]]
    if gate:
        violations.append(f"numeric gate failures: {len(gate)}")
    expected = {"warm": 1 + prereg["reps"] * len(timed) + len(prereg["inputs"]) - len(timed),
                "affinity": len(prereg["inputs"]),
                "oneshot": 1}
    short = [(r["index"], r["kind"]) for r in runs if r["kind"] in expected and len(r["decisions"]) != expected[r["kind"]]]
    if short:
        violations.append(f"missing decisions: {short}")

    # Bits: within each arm one key per input over every process, thread count, repeat, start.
    keys = {arm: {} for arm in ("baseline", "candidate")}
    for r in runs:
        for d in r["decisions"]:
            keys[r["arm"]].setdefault(d["name"], {}).setdefault(digest(outcome_key(d["outcome"])),
                                                                  outcome_key(d["outcome"]))
    reproducible = {arm: sorted(n for n, ks in k.items() if len(ks) != 1) for arm, k in keys.items()}
    if reproducible["candidate"]:
        violations.append(f"candidate not reproducible: {reproducible['candidate']}")
    # The baseline's own repeatability is recorded (summary.json), not a rule for the candidate.
    inputs = sorted(set(keys["baseline"]) & set(keys["candidate"]))
    if inputs != sorted(prereg["inputs"]):
        violations.append("inputs missing from one arm")
    single = {arm: {n: next(iter(keys[arm][n].values())) for n in inputs} for arm in keys}
    changed, judgments_differ, max_diff = [], [], 0.0
    for n in inputs:
        a, b = single["baseline"][n], single["candidate"][n]
        if a != b:
            changed.append(n)
        if {k: v for k, v in a.items() if k != "probabilities"} != {k: v for k, v in b.items() if k != "probabilities"}:
            judgments_differ.append(n)
        if a.get("probabilities") and b.get("probabilities"):
            max_diff = max(max_diff, max(abs(float.fromhex(x) - float.fromhex(y))
                                         for x, y in zip(a["probabilities"], b["probabilities"])))
    if judgments_differ:
        violations.append(f"judgments differ from the baseline: {judgments_differ}")
    official = max((max(abs(float.fromhex(p) - q) for p, q in zip(single["candidate"][n]["probabilities"],
                                                                 by_id[n]["reference"]["probabilities"]))
                    for n in inputs if single["candidate"][n].get("probabilities")), default=None)

    # Speed and memory.
    rows = []
    sessions = sorted({r["session"] for r in runs if r["kind"] == "warm"})
    threads = sorted({r["threads"] for r in runs if r["kind"] == "warm"})
    for s in sessions:
        for n in threads:
            for case, tokens in timed.items():
                warm = {arm: st.median(d["wall_s"] for r in runs if (r["kind"], r["session"], r["threads"], r["arm"])
                                       == ("warm", s, n, arm) for d in r["decisions"]
                                       if d["phase"] == "measure" and d["name"] == case) for arm in keys}
                shots = {arm: [r for r in runs if (r["kind"], r["session"], r["threads"], r["arm"], r.get("case"))
                               == ("oneshot", s, n, arm, case)] for arm in keys}
                row = {"session": s, "threads": n, "tokens": tokens,
                       "warm_baseline_s": warm["baseline"], "warm_candidate_s": warm["candidate"],
                       "warm_ratio": warm["candidate"] / warm["baseline"]}
                for name, field in (("oneshot", "process_wall_s"), ("commit", "peak_private_commit"),
                                    ("working_set", "peak_working_set")):
                    pick = st.median if name == "oneshot" else max
                    base, cand = (pick(r[field] for r in shots[arm]) for arm in ("baseline", "candidate"))
                    row[f"{name}_baseline"], row[f"{name}_candidate"], row[f"{name}_ratio"] = base, cand, cand / base
                rows.append(row)
                where = f"s{s} t{n} {tokens}"
                if row["warm_ratio"] > WARM_LIMIT:
                    violations.append(f"{where}: warm ratio {row['warm_ratio']:.3f}")
                if row["oneshot_ratio"] > ONESHOT_LIMIT:
                    violations.append(f"{where}: one-shot ratio {row['oneshot_ratio']:.3f}")
                for name in ("commit", "working_set"):
                    if row[f"{name}_ratio"] > MEMORY_LIMIT:
                        violations.append(f"{where}: peak {name} ratio {row[f'{name}_ratio']:.4f}")
    timeouts = [r for r in runs if r["kind"] == "timeout"]
    bad = [r["threads"] for r in timeouts if r["returncode"] != 0 or not r.get("result")
           or not (r["result"].get("timeout") and r["result"].get("reuse_bitwise_equal"))]
    if bad or not timeouts:
        violations.append(f"timeout reuse: {bad or 'not run'}")

    summary = {"violations": violations, "accepted": not violations, "inputs": len(inputs),
               "changed_vs_baseline": changed, "judgments_differ": judgments_differ,
               "max_abs_diff_vs_baseline": max_diff, "max_abs_diff_candidate_vs_official": official,
               "not_reproducible": reproducible, "gate_failures": gate, "rows": rows,
               "timeouts": [{"threads": r["threads"], "result": r.get("result")} for r in timeouts],
               "source": prereg["source"]}
    save_new(folder / "summary.json", summary)
    for arm in keys:
        save_new(folder / f"bit-reference-{arm}.json", {
            "schema_version": "pure_jeff.bit_reference.v1", "arm": arm, "source": prereg["source"],
            "exe_sha256": prereg["hashes"]["exes"][arm], "bundles": prereg["hashes"]["bundles"][arm],
            "machine": prereg["environment_start"].get("processor"),
            "note": "One outcome per catalog input, identical over every process, thread count and start of this run.",
            "outcomes": {n: {"sha256": digest(single[arm][n]), **single[arm][n]} for n in inputs}})

    print("| session | threads | tokens | warm main | warm new | ratio | one-shot ratio | peak commit | peak WS |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        print(f"| {r['session']} | {r['threads']} | {r['tokens']} | {r['warm_baseline_s']:.3f} | {r['warm_candidate_s']:.3f} "
              f"| {r['warm_ratio']:.3f} | {r['oneshot_ratio']:.3f} | {r['commit_ratio']:.4f} | {r['working_set_ratio']:.4f} |")
    print(f"\ninputs {len(inputs)}, changed vs baseline {len(changed)}, judgments differ {len(judgments_differ)}, "
          f"max |diff| {max_diff:.3e}, candidate vs official {official:.3e}")
    print(f"not reproducible: {reproducible}; gate failures: {len(gate)}")
    print("timeouts:", summary["timeouts"])
    print("violations:", violations or "none")
    print("ACCEPTED" if not violations else "NOT ACCEPTED")


if __name__ == "__main__":
    main()
