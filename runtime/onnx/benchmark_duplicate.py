"""Paired, timer-free NNEF startup experiment; numerical gates precede timing runs."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--generation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control", type=Path, help="frozen previous candidate executable")
    parser.add_argument("--control-reference", type=Path, help="its archived preregistration.json")
    args = parser.parse_args()
    control = ROOT/"runtime/tract/target/release/bench.exe"
    frozen = ROOT/"docs/research/jeff-onnx-tract/codegen-profile-2026-10-10/preregistration.json"
    if bool(args.control) != bool(args.control_reference):
        raise ValueError("control executable and archived reference required together")
    if args.control:
        control, frozen, key = args.control, args.control_reference, "candidate_executable_sha256"
    else:
        key = "executable_sha256"
    if sha(control) != json.loads(frozen.read_text(encoding="utf-8"))[key]:
        raise ValueError("frozen control executable changed")
    asset_path = ROOT/"experiments/runs/nnef-pilot-20261010/artifact.json"
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    model = asset_path.parent/asset["file"]
    if sha(model) != asset["sha256"]:
        raise ValueError("NNEF hash mismatch")
    generation = json.loads(args.generation.read_text(encoding="utf-8"))
    if generation["timers"] or not generation["algorithm_changes"]:
        raise ValueError("timer-free single-change candidate required")
    for item in generation["files"]:
        if item["path"] != "Cargo.lock" and sha(args.generation.parent/item["path"]) != item["sha256"]:
            raise ValueError("candidate source changed")
    source = ROOT/"experiments/runs/performance-pilot-20261010/primary/resident-0-tract.job.json"
    cases = json.loads(source.read_text(encoding="utf-8"))["cases"]
    if len(cases) != 4:
        raise ValueError("four golden cases required")
    for case in cases:
        path = ROOT/"tests/fixtures/jeff-golden"/(case["id"]+".json")
        golden = json.loads(path.read_text(encoding="utf-8"))
        if (sha(path) != case["golden_sha256"] or golden["request"] != case["request"]
            or golden["temperature"] != case["temperature"]
            or golden["official"]["probabilities"] != case["expected_probabilities"]
            or golden["official"]["judgment"] != case["expected_judgment"]
            or golden["official"]["input_tokens"] != case["tokens"]):
            raise ValueError("golden changed")
        for key, values in golden["official"]["inputs"].items():
            if case["inputs"][key] != [248044 if key == "input_ids" else 0]*(512-len(values[0]))+values[0]:
                raise ValueError("input mismatch")
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL("kernel32").GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError("need 4 GiB available RAM")
    limit = min(8*1024**3, memory.ullTotalPhys//2)
    policy = json.loads((ROOT/"models/jeff-rust-bundle-p3.json").read_text(encoding="utf-8"))["policy"]
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/"preregistration.json", {"date_utc": datetime.now(timezone.utc).isoformat(),
        "model_sha256": asset["sha256"], "source_job_sha256": sha(source),
        "control_executable_sha256": sha(control), "candidate_executable_sha256": sha(args.candidate),
        "generation_sha256": sha(args.generation), "script_sha256": sha(__file__),
        "control_reference_sha256": sha(frozen),
        "candidate_lock_sha256": sha(args.generation.parent/"Cargo.lock"),
        "threads": 1, "cold_blocks": 5, "resident_samples": 5, "resident_warmups": 1,
        "timeout_seconds": 600, "memory_limit_bytes": limit, "available_physical_bytes": memory.ullAvailPhys,
        "scope": "process-cold; filesystem cache, thermals and background load uncontrolled; no API E2E",
        "formal_slo_acceptance": False})
    records, references = [], {}

    def run(run_id, label, schedule):
        job = args.output/(run_id+".job.json")
        save(job, {"mode": "nnef-decluttered", "profile_codegen": False,
                   "cases": cases, "schedule": schedule})
        print("START", run_id, flush=True)
        exe = control if label == "control" else args.candidate
        record = invoke([exe.resolve(), model.resolve(), job.resolve()], args.output, run_id, limit)
        events = [json.loads(line) for line in (args.output/(run_id+".stdout.jsonl")).read_text(encoding="utf-8").splitlines()]
        validate_events(events, cases, policy)
        if len(events) != len(schedule)+2:
            raise ValueError("schedule length mismatch")
        for event, item in zip(events[1:-1], schedule):
            if event["case"] != cases[item["case"]]["id"] or event["warmup"] != item["warmup"]:
                raise ValueError("schedule mismatch")
            reference = references.setdefault(event["case"], event["raw_logits"])
            if event["raw_logits"] != reference:
                raise ValueError("control/candidate/repeat raw logits differ")
        record.update(label=label, events=events)
        save(args.output/(run_id+".validated.json"), record)
        print("DONE", run_id, f"startup={events[0]['startup_ns']/1e9:.3f}s", flush=True)
        return record

    # Four-case correctness gate on BOTH binaries, excluded from latency aggregates.
    for label in ["control", "candidate"]:
        run("gate-"+label, label, [{"case": i, "warmup": False} for i in range(4)])
    for block in range(5):
        for label in (["control", "candidate"] if block % 2 == 0 else ["candidate", "control"]):
            records.append(run(f"cold-{block}-{label}", label, [{"case": 0, "warmup": False}]))
    for label in ["candidate", "control"]:
        records.append(run("resident-"+label, label, [{"case": 0, "warmup": True}]+
                           [{"case": 0, "warmup": False} for _ in range(5)]))
    summary = {"units": "seconds", "formal_slo_acceptance": False, "raw_logits_exact": True,
               "warm_scope": "candidate-request only, one independent session per binary"}
    for label in ["control", "candidate"]:
        cold = [r for r in records if r["label"] == label and r["run_id"].startswith("cold-")]
        resident = next(r for r in records if r["run_id"] == "resident-"+label)
        summary[label] = {key: stats([r["events"][0][key]/1e9 for r in cold])
                          for key in ["load_ns", "optimize_ns", "plan_ns", "startup_ns"]}
        summary[label]["process_seconds"] = stats([r["parent_process_ns"]/1e9 for r in cold])
        summary[label]["cold_peak_bytes"] = stats([r["peak_working_set_bytes"] for r in cold])
        summary[label]["warm_forward_seconds"] = stats([e["forward_ns"]/1e9 for e in resident["events"][1:-1] if not e["warmup"]])
        summary[label]["resident_peak_bytes"] = resident["peak_working_set_bytes"]
    summary["paired_startup_candidate_minus_control_seconds"] = [
        next(r for r in records if r["run_id"] == f"cold-{i}-candidate")["events"][0]["startup_ns"]/1e9-
        next(r for r in records if r["run_id"] == f"cold-{i}-control")["events"][0]["startup_ns"]/1e9 for i in range(5)]
    summary["max_probability_error"] = max(e["probability_max_abs_error"] for r in records for e in r["events"][1:-1])
    save(args.output/"summary.json", summary)
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
