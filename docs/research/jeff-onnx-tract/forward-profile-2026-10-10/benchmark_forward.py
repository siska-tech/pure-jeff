"""Windows forward/thread pilot on fixed step1113 NNEF; no API E2E or SLO acceptance."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--generation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    control = ROOT/".venv/tract-duplicate-candidate-target/release/bench.exe"
    frozen = ROOT/"docs/research/jeff-onnx-tract/duplicate-search-2026-10-10/preregistration.json"
    if sha(control) != json.loads(frozen.read_text(encoding="utf-8"))["candidate_executable_sha256"]:
        raise ValueError("frozen control changed")
    asset_path = ROOT/"experiments/runs/nnef-pilot-20261010/artifact.json"
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    model = asset_path.parent/asset["file"]
    if sha(model) != asset["sha256"]:
        raise ValueError("model changed")
    generation = json.loads(args.generation.read_text(encoding="utf-8"))
    if not generation["multithread_mm"] or generation["internal_timers"]:
        raise ValueError("wrong experiment")
    for item in generation["files"]:
        if sha(args.generation.parent/item["path"]) != item["sha256"]:
            raise ValueError("generated source changed: "+item["path"])
    source = ROOT/"experiments/runs/performance-pilot-20261010/primary/resident-0-tract.job.json"
    cases = json.loads(source.read_text(encoding="utf-8"))["cases"]
    if len(cases) != 4:
        raise ValueError("four cases required")
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
        "candidate_lock_sha256": sha(args.generation.parent/"Cargo.lock"),
        "threads": [1, 2, 4, 8], "session_orders": [[1, 2, 4, 8], [8, 4, 2, 1]],
        "resident_sessions_per_thread": 2, "samples_per_session": 3, "warmups_per_session": 1,
        "profile_threads": 1, "profile_samples": 3, "profile_warmups": 1,
        "timeout_seconds": 600, "memory_limit_bytes": limit, "available_physical_bytes": memory.ullAvailPhys,
        "total_physical_bytes": memory.ullTotalPhys, "golden_probability_tolerance": 1e-4,
        "raw_logit_gate": "finite 255 logits; max abs difference <= 1e-3 from frozen control",
        "scope": "prepared 512 tensors; candidate-request warm pilot; process-cold startup incidental n=2; no tokenizer/API E2E",
        "limitations": ["filesystem cache, thermals, affinity and background load uncontrolled",
                        "executor pool size is not a claim that every operator uses all threads",
                        "top-level profile includes child-plan wall time; profiling perturbs timings",
                        "n=6 nearest-rank p95 is observed maximum; no confidence interval"],
        "formal_slo_acceptance": False})
    records, references = [], {}

    def run(run_id, threads, schedule, *, old=False, profile=False):
        job = args.output/(run_id+".job.json")
        save(job, {"mode": "nnef-decluttered", "profile_codegen": False, "threads": threads,
                   "profile_forward": profile, "cases": cases, "schedule": schedule})
        print("START", run_id, flush=True)
        exe = control if old else args.candidate
        record = invoke([exe.resolve(), model.resolve(), job.resolve()], args.output, run_id, limit)
        events = [json.loads(line) for line in (args.output/(run_id+".stdout.jsonl")).read_text(encoding="utf-8").splitlines()]
        validate_events(events, cases, policy, expected_threads=threads)
        if len(events) != len(schedule)+2:
            raise ValueError("schedule mismatch")
        if not old and (events[0]["executor_threads"] != threads or not events[0]["multithread_mm"]):
            raise ValueError("executor mismatch")
        for event, item in zip(events[1:-1], schedule):
            if event["case"] != cases[item["case"]]["id"] or event["warmup"] != item["warmup"]:
                raise ValueError("schedule mismatch")
            logits = event["raw_logits"]
            if len(logits) != 255 or not all(math.isfinite(v) for v in logits):
                raise ValueError("invalid logits")
            reference = references.setdefault(event["case"], logits)
            difference = max(abs(a-b) for a, b in zip(logits, reference))
            if difference > 1e-3:
                raise ValueError("raw logit regression")
            event.update(raw_max_abs_error=difference, raw_exact=logits == reference)
            if not old and bool(event["forward_profile"]) != profile:
                raise ValueError("profile mismatch")
        record.update(threads=threads, profiled=profile, old=old, events=events)
        save(args.output/(run_id+".validated.json"), record)
        records.append(record)
        print("DONE", run_id, f"startup={events[0]['startup_ns']/1e9:.3f}s",
              "forward="+str([round(e['forward_ns']/1e9, 3) for e in events[1:-1]]), flush=True)

    # All four goldens before timing; frozen feature-off binary establishes raw references.
    gate = [{"case": i, "warmup": False} for i in range(4)]
    run("gate-control", 1, gate, old=True)
    for threads in [1, 2, 4, 8]:
        run(f"gate-{threads}", threads, gate)
    schedule = [{"case": 0, "warmup": True}]+[{"case": 0, "warmup": False}]*3
    for block, order in enumerate([[1, 2, 4, 8], [8, 4, 2, 1]]):
        for threads in order:
            run(f"resident-{block}-{threads}", threads, schedule)
    run("profile-1", 1, schedule, profile=True)
    summary = {"formal_slo_acceptance": False, "threads": {}}
    for threads in [1, 2, 4, 8]:
        rows = [r for r in records if r["run_id"].startswith("resident-") and r["threads"] == threads]
        summary["threads"][str(threads)] = {
            "warm_forward_seconds": stats([e["forward_ns"]/1e9 for r in rows for e in r["events"][1:-1] if not e["warmup"]]),
            "session_medians_seconds": [stats([e["forward_ns"]/1e9 for e in r["events"][1:-1] if not e["warmup"]])["median"] for r in rows],
            "startup_seconds": stats([r["events"][0]["startup_ns"]/1e9 for r in rows]),
            "peak_working_set_bytes": stats([r["peak_working_set_bytes"] for r in rows])}
    profiles = [e for e in records[-1]["events"][1:-1] if not e["warmup"]]
    ops = sorted({g["op"] for e in profiles for g in e["forward_profile"]["groups"]})
    summary["profile"] = {"forward_seconds": stats([e["forward_ns"]/1e9 for e in profiles]),
        "groups": sorted([{"op": op, "seconds": stats([next((g["ns"] for g in e["forward_profile"]["groups"] if g["op"] == op), 0)/1e9 for e in profiles])} for op in ops], key=lambda g: -g["seconds"]["median"])}
    all_events = [e for r in records for e in r["events"][1:-1]]
    summary.update(processes=len(records), forwards=len(all_events), raw_logits_exact=all(e["raw_exact"] for e in all_events),
        raw_max_abs_error=max(e["raw_max_abs_error"] for e in all_events),
        max_probability_error=max(e["probability_max_abs_error"] for e in all_events))
    save(args.output/"summary.json", summary)
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
