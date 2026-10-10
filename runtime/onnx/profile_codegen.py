"""Paired diagnostic of public optimizer callbacks; not a latency SLO run."""
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
    parser.add_argument("--source-job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blocks", type=int, default=3)
    parser.add_argument("--executable", type=Path, default=ROOT/"runtime/tract/target/release/bench.exe")
    args = parser.parse_args()
    if args.blocks < 1:
        raise ValueError("positive block count required")
    asset = json.loads(args.artifact.read_text(encoding="utf-8"))
    model = args.artifact.parent/asset["file"]
    if sha(model) != asset["sha256"]:
        raise ValueError("NNEF hash mismatch")
    source_job = json.loads(args.source_job.read_text(encoding="utf-8"))
    cases = source_job["cases"]
    if len(cases) != 4:
        raise ValueError("four reference cases required")
    for case in cases:
        path = ROOT/"tests/fixtures/jeff-golden"/(case["id"]+".json")
        golden = json.loads(path.read_text(encoding="utf-8"))
        if (sha(path) != case["golden_sha256"] or golden["official"]["probabilities"] != case["expected_probabilities"]
                or golden["official"]["judgment"] != case["expected_judgment"]
                or golden["request"] != case["request"] or golden["temperature"] != case["temperature"]
                or golden["official"]["input_tokens"] != case["tokens"]):
            raise ValueError("reference mismatch")
        for key, values in golden["official"]["inputs"].items():
            if case["inputs"][key] != [248044 if key == "input_ids" else 0]*(512-len(values[0]))+values[0]:
                raise ValueError("input mismatch")
    status = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL("kernel32").GlobalMemoryStatusEx(c.byref(status)) or status.ullAvailPhys < 4*1024**3:
        raise RuntimeError("need 4 GiB available RAM")
    limit = min(8*1024**3, status.ullTotalPhys//2)
    args.output.mkdir(parents=True, exist_ok=False)
    policy = json.loads((ROOT/"models/jeff-rust-bundle-p3.json").read_text(encoding="utf-8"))["policy"]
    order = [([False, True] if b % 2 == 0 else [True, False]) for b in range(args.blocks)]
    sources = [Path(__file__), ROOT/"runtime/tract/src/codegen_profile.rs", ROOT/"runtime/tract/src/bin/bench.rs",
               ROOT/"runtime/tract/Cargo.lock", ROOT/"runtime/tract/vendor/data/src/tensor.rs", ROOT/"runtime/onnx/benchmark_pilot.py"]
    save(args.output/"preregistration.json", {"date_utc": datetime.now(timezone.utc).isoformat(), "blocks": args.blocks,
        "order_profile_enabled": order, "model_sha256": asset["sha256"], "artifact_manifest_sha256": sha(args.artifact),
        "source_job_sha256": sha(args.source_job), "executable_sha256": sha(args.executable), "threads": 1,
        "sources": [{"path": str(p), "sha256": sha(p)} for p in sources], "policy": policy,
        "timeout_seconds": 600, "memory_limit_bytes": limit, "available_physical_bytes": status.ullAvailPhys,
        "scope": "codegen startup diagnostics; process-cold, storage cache uncontrolled; parent hash excluded",
        "forward_schedule": "first profiled process checks all four cases; others only case zero; no forward latency comparison",
        "residual": "driver plus instrumentation, not separately measured compaction or packing",
        "formal_slo_acceptance": False})
    records = []
    for block, enabled_order in enumerate(order):
        for enabled in enabled_order:
            run_id = f"block-{block}-{'profile' if enabled else 'control'}"
            schedule = [{"case": i, "warmup": False} for i in range(4 if enabled and block == 0 else 1)]
            job = args.output/(run_id+".job.json")
            save(job, {"mode": "nnef-decluttered", "profile_codegen": enabled, "cases": cases, "schedule": schedule})
            print("START", run_id, flush=True)
            record = invoke([args.executable.resolve(), model.resolve(), job.resolve()], args.output, run_id, limit)
            events = [json.loads(line) for line in (args.output/(run_id+".stdout.jsonl")).read_text(encoding="utf-8").splitlines()]
            validate_events(events, cases, policy)
            if len(events) != len(schedule)+2 or any(e["case"] != cases[s["case"]]["id"] for e,s in zip(events[1:-1],schedule)):
                raise ValueError("schedule mismatch")
            profile = events[0]["codegen_profile"]
            if enabled:
                if (profile["total_ns"] != profile["callback_ns"]+profile["driver_and_instrumentation_ns"]
                        or profile["callback_ns"] != sum(p["callback_ns"] for p in profile["passes"])):
                    raise ValueError("invalid profile accounting")
            elif profile is not None:
                raise ValueError("control must not be instrumented")
            record.update(block=block, profile_enabled=enabled, events=events)
            save(args.output/(run_id+".validated.json"), record)
            records.append(record)
            print("DONE", run_id, f"codegen={events[0]['optimize_ns']/1e9:.3f}s", flush=True)
    profiles = [r["events"][0]["codegen_profile"] for r in records if r["profile_enabled"]]
    names = [p["pass"] for p in profiles[0]["passes"]]
    if any([p["pass"] for p in profile["passes"]] != names for profile in profiles):
        raise ValueError("pass layout changed")
    summary = {"units": "seconds", "blocks": args.blocks, "formal_slo_acceptance": False,
        "preregistration_sha256": sha(args.output/"preregistration.json"),
        "control_codegen_seconds": stats([r["events"][0]["optimize_ns"]/1e9 for r in records if not r["profile_enabled"]]),
        "profile_codegen_seconds": stats([p["total_ns"]/1e9 for p in profiles]),
        "driver_and_instrumentation_seconds": stats([p["driver_and_instrumentation_ns"]/1e9 for p in profiles]),
        "passes": [{"pass": name, "callback_seconds": stats([p["passes"][i]["callback_ns"]/1e9 for p in profiles]),
                    "next_calls": [p["passes"][i]["next_calls"] for p in profiles],
                    "patches_returned": [p["passes"][i]["patches_returned"] for p in profiles]}
                   for i,name in enumerate(names)],
        "forwards": sum(len(r["events"])-2 for r in records),
        "max_probability_error": max(e["probability_max_abs_error"] for r in records for e in r["events"][1:-1]),
        "process_peak_working_set_bytes": stats([r["peak_working_set_bytes"] for r in records])}
    differences = []
    for block in range(args.blocks):
        pair = {r["profile_enabled"]: r["events"][0]["optimize_ns"]/1e9 for r in records if r["block"] == block}
        differences.append(pair[True]-pair[False])
    summary["paired_profile_minus_control_seconds"] = differences
    save(args.output/"summary.json", summary)
    print("Completed codegen diagnostic", flush=True)


if __name__ == "__main__":
    main()
