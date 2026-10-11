"""Measure cached NNEF startup separately from one-time ONNX preparation."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path

from benchmark_pilot import MemoryStatus, invoke, save, sha, stats, validate_events

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source-pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", type=Path, default=ROOT/"runtime/tract/target/release/bench.exe")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        raise ValueError("positive sample count required")
    args.output.mkdir(parents=True, exist_ok=False)
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    model = args.artifact.parent/artifact["file"]
    if sha(model) != artifact["sha256"] or model.stat().st_size != artifact["bytes"]:
        raise ValueError("NNEF hash mismatch")
    pack_prereg = args.artifact.parent/"pack-preregistration.json"
    if sha(pack_prereg) != artifact["pack_preregistration_sha256"]:
        raise ValueError("pack provenance mismatch")
    pack = json.loads(pack_prereg.read_text(encoding="utf-8"))
    if pack["model_sha256"] != "4808e28131967e8ed33f8b50d46c4212e11c19b79e6dfb5209cf9b6931cd9b0c":
        raise ValueError("expected same-checkpoint normalized ONNX")
    if sha(ROOT/"runtime/tract/Cargo.lock") != pack["cargo_lock_sha256"]:
        raise ValueError("pack/load dependency mismatch")
    source_job = args.source_pilot/"resident-0-tract.job.json"
    job = json.loads(source_job.read_text(encoding="utf-8"))
    cases = job["cases"]
    for case in cases:
        path = ROOT/"tests/fixtures/jeff-golden"/(case["id"]+".json")
        golden = json.loads(path.read_text(encoding="utf-8"))
        if (sha(path) != case["golden_sha256"] or golden["official"]["probabilities"] != case["expected_probabilities"]
                or golden["official"]["judgment"] != case["expected_judgment"]
                or golden["temperature"] != case["temperature"]):
            raise ValueError("golden mismatch")
        for key, values in golden["official"]["inputs"].items():
            expected = [248044 if key == "input_ids" else 0]*(512-len(values[0]))+values[0]
            if case["inputs"][key] != expected:
                raise ValueError("padded inputs mismatch")
    policy = json.loads((ROOT/"models/jeff-rust-bundle-p3.json").read_text(encoding="utf-8"))["policy"]
    status = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL("kernel32").GlobalMemoryStatusEx(c.byref(status)) or status.ullAvailPhys < 4*1024**3:
        raise RuntimeError("need 4 GiB available RAM")
    limit = min(8*1024**3, status.ullTotalPhys//2)
    warm_schedule = [{"case": i % len(cases), "warmup": True} for i in range(5)]
    # Preserve the previous pilot's order for n=5. This is a later, unpaired experiment.
    measured = [item for item in job["schedule"] if not item["warmup"]]
    if len(measured) != args.repeats*len(cases):
        raise ValueError("sample count must match source schedule")
    prereg = {"schema_version": "kaze_judge.nnef_pilot.v1", "date_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_sha256": artifact["sha256"], "artifact_manifest_sha256": sha(args.artifact),
        "pack_preregistration_sha256": sha(pack_prereg), "executable_sha256": sha(args.executable),
        "source_job_sha256": sha(source_job), "source_preregistration_sha256": sha(args.source_pilot/"preregistration.json"),
        "policy": policy, "cold_samples": args.repeats, "warm_samples_per_case": args.repeats,
        "resident_sessions": 1, "warm_schedule": warm_schedule+measured, "threads": 1,
        "timeout_seconds": 600, "memory_limit_bytes": limit, "available_physical_bytes": status.ullAvailPhys,
        "cache_mode": "process-cold; storage cache uncontrolled, parent hash preflight excluded",
        "scope": "prepared tensors, engine only; no tokenizer or DecisionProvider",
        "comparison": "later unpaired measurement against archived ONNX pilot; executable changed",
        "formal_slo_acceptance": False}
    save(args.output/"preregistration.json", prereg)
    records = []
    for phase, block in [("cold", i) for i in range(args.repeats)]+[("resident", 0)]:
        run_id = f"{phase}-{block}-nnef"
        task_job = args.output/(run_id+".job.json")
        schedule = [{"case": 0, "warmup": False}] if phase == "cold" else warm_schedule+measured
        save(task_job, {"mode": "nnef-decluttered", "cases": cases, "schedule": schedule})
        print(f"START {run_id}", flush=True)
        record = invoke([args.executable.resolve(), model.resolve(), task_job.resolve()], args.output, run_id, limit)
        events = [json.loads(line) for line in (args.output/(run_id+".stdout.jsonl")).read_text(encoding="utf-8").splitlines()]
        validate_events(events, cases, policy)
        if len(events) != len(schedule)+2:
            raise ValueError("missing events")
        for event, item in zip(events[1:-1], schedule):
            if event["case"] != cases[item["case"]]["id"] or event["warmup"] != item["warmup"]:
                raise ValueError("schedule mismatch")
        record.update(phase=phase, events=events)
        save(args.output/(run_id+".validated.json"), record)
        records.append(record)
        print(f"DONE {run_id} {record['parent_process_ns']/1e9:.3f}s", flush=True)
    cold = [r for r in records if r["phase"] == "cold"]
    resident = records[-1]
    summary = {"preregistration_sha256": sha(args.output/"preregistration.json"), "units": "seconds",
        "cold": {key: stats([r["events"][0][key]/1e9 for r in cold])
                 for key in ["load_ns", "type_ns", "optimize_ns", "plan_ns", "startup_ns"]},
        "cold_process_seconds": stats([r["parent_process_ns"]/1e9 for r in cold]),
        "cold_peak_working_set_bytes": stats([r["peak_working_set_bytes"] for r in cold]),
        "resident_peak_working_set_bytes": resident["peak_working_set_bytes"], "warm": [],
        "max_probability_error": max(e["probability_max_abs_error"] for r in records for e in r["events"][1:-1])}
    for case in cases:
        events = [e for e in resident["events"][1:-1] if e["case"] == case["id"] and not e["warmup"]]
        summary["warm"].append({"case": case["id"], "compute_and_softmax_seconds":
                                stats([(e["forward_ns"]+e["score_ns"])/1e9 for e in events])})
    save(args.output/"summary.json", summary)
    print("Completed NNEF pilot", flush=True)


if __name__ == "__main__":
    main()
