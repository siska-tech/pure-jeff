"""Resident benchmark of the experimental Tract path (patched Tract, run-no-change-axes, 1 thread).

  python bench/tract_resident.py --bench runtime/tract/target/release/bench.exe \
      --model <model.normalized.onnx> --gate <check_tract output dir> --output <new dir>

One bench.exe process loads, optimizes and plans the model once, then runs the four golden
cases (left-padded to 512 tokens) as warm-up and measured requests in a fixed round-robin order.
Every request's raw logits must equal, bit for bit, the logits that runtime/onnx/check_tract.py
recorded for the same model in --gate (whose numerical gate must have passed); otherwise the run
fails. Times are descriptive for this host only: no SLO, speed-up or comparison with other hosts
or with the archived KazeJudge numbers is derived from them.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bench", type=Path, required=True, help="bench.exe built from runtime/tract")
    parser.add_argument("--model", type=Path, required=True, help="the normalized ONNX graph")
    parser.add_argument("--gate", type=Path, required=True, help="output directory of check_tract.py")
    parser.add_argument("--output", type=Path, required=True, help="new directory")
    parser.add_argument("--warmup", type=int, default=1, help="warm-up rounds over all cases")
    parser.add_argument("--samples", type=int, default=3, help="measured rounds over all cases")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds for the whole child")
    args = parser.parse_args()
    parity = json.loads((args.gate / "parity.json").read_text(encoding="utf-8"))
    if not parity["passed"] or parity["stage"] != "run-no-change-axes" or parity["model_sha256"] != sha(args.model):
        raise SystemExit("a passed run-no-change-axes gate for this model is required")
    args.output.mkdir(parents=True, exist_ok=False)
    cases, expected = [], {}
    for item in parity["cases"]:
        name = item["case"]
        probe = args.gate / f"{name}.probe.json"
        if sha(probe) != item["probe_sha256"]:
            raise SystemExit(f"{probe} differs from the gate record")
        expected[name] = json.loads(json.loads(probe.read_text(encoding="utf-8"))["stdout"])["raw_logits"]
        golden = json.loads((ROOT / "tests/fixtures/jeff-golden" / f"{name}.json").read_text(encoding="utf-8"))
        cases.append({"id": name, "count": len(golden["request"]["candidates"]), "temperature": golden["temperature"],
                      "tokens": golden["official"]["input_tokens"],
                      "inputs": json.loads((args.gate / f"{name}.inputs.json").read_text(encoding="utf-8"))})
    schedule = [{"case": i, "warmup": True} for _ in range(args.warmup) for i in range(len(cases))]
    schedule += [{"case": i, "warmup": False} for _ in range(args.samples) for i in range(len(cases))]
    job = args.output / "job.json"
    job.write_text(json.dumps({"mode": "no-change-axes", "cases": cases, "schedule": schedule}), encoding="utf-8")
    record = {
        "schema_version": "pure_jeff.tract_resident_bench.v1",
        "started": datetime.now(timezone.utc).isoformat(),
        "host": {"machine": platform.machine(), "processor": platform.processor(), "system": platform.platform()},
        "bench_sha256": sha(args.bench), "model_sha256": sha(args.model), "gate_parity_sha256": sha(args.gate / "parity.json"),
        "harness_sha256": sha(__file__), "warmup_rounds": args.warmup, "sample_rounds": args.samples, "threads": 1,
        "interpretation": "descriptive, this host only; no SLO or cross-host comparison",
    }
    with (args.output / "stdout.jsonl").open("wb") as out, (args.output / "stderr.log").open("wb") as err:
        try:
            code = subprocess.run([str(args.bench), str(args.model), str(job)], stdout=out, stderr=err,
                                  timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    events = [json.loads(line) for line in (args.output / "stdout.jsonl").read_text(encoding="utf-8").splitlines()]
    requests = [e for e in events if e["event"] == "request"]
    mismatches = [e["iteration"] for e in requests if e["raw_logits"] != expected[e["case"]]]
    passed = (code == 0 and len(requests) == len(schedule) and not mismatches
              and any(e["event"] == "completed" for e in events))
    init = next((e for e in events if e["event"] == "initialized"), {})
    per_case = {}
    for case in cases:
        times = [e["forward_ns"] / 1e9 for e in requests if e["case"] == case["id"] and not e["warmup"]]
        if times:
            per_case[case["id"]] = {"tokens": case["tokens"], "n": len(times), "forward_median_s": statistics.median(times),
                                    "forward_min_s": min(times), "forward_max_s": max(times)}
    record.update({"exit": code, "requests": len(requests), "raw_logit_mismatches": mismatches, "passed": passed,
                   "startup_s": init.get("startup_ns", 0) / 1e9, "optimize_s": init.get("optimize_ns", 0) / 1e9,
                   "per_case": per_case})
    (args.output / "summary.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ["passed", "requests", "startup_s", "per_case"]}, indent=1))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
