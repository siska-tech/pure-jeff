"""Frozen-binary 4/8-thread top-level wall-time diagnosis, not a speedup experiment."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = ROOT/"docs/research/jeff-onnx-tract/forward-profile-2026-10-10"
    frozen = json.loads((previous/"preregistration.json").read_text(encoding="utf-8"))
    exe = ROOT/".venv/tract-forward-target/release/bench.exe"
    generation = ROOT/".venv/tract-forward-probe/generation.json"
    model = ROOT/"experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar"
    for path, expected in [(exe, frozen["candidate_executable_sha256"]),
        (generation, frozen["generation_sha256"]), (model, frozen["model_sha256"])]:
        if sha(path) != expected:
            raise ValueError("frozen asset changed: "+str(path))
    generated = json.loads(generation.read_text(encoding="utf-8"))
    for row in generated["files"]:
        if sha(generation.parent/row["path"]) != row["sha256"]:
            raise ValueError("generated source changed")
    cases = json.loads((previous/"gate-4.job.json").read_text(encoding="utf-8"))["cases"]
    if len(cases) != 4:
        raise ValueError("four cases required")
    for case in cases:
        path = ROOT/"tests/fixtures/jeff-golden"/(case["id"]+".json")
        golden = json.loads(path.read_text(encoding="utf-8"))
        if sha(path) != case["golden_sha256"] or golden["request"] != case["request"]:
            raise ValueError("golden changed")
        for key, values in golden["official"]["inputs"].items():
            if case["inputs"][key] != [248044 if key == "input_ids" else 0]*(512-len(values[0]))+values[0]:
                raise ValueError("inputs changed")
    references = {e["case"]: e["raw_logits"] for e in
        [json.loads(line) for line in (previous/"gate-control.stdout.jsonl").read_text(encoding="utf-8").splitlines()][1:-1]}
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL("kernel32").GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError("need 4 GiB available RAM")
    limit = min(8*1024**3, memory.ullTotalPhys//2)
    policy = json.loads((ROOT/"models/jeff-rust-bundle-p3.json").read_text(encoding="utf-8"))["policy"]
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/"preregistration.json", {"date_utc": datetime.now(timezone.utc).isoformat(),
        "model_sha256": sha(model), "executable_sha256": sha(exe), "generation_sha256": sha(generation),
        "script_sha256": sha(__file__), "previous_preregistration_sha256": sha(previous/"preregistration.json"),
        "source_job_sha256": sha(previous/"gate-4.job.json"), "reference_raw_sha256": sha(previous/"gate-control.stdout.jsonl"),
        "orders": [[4,8],[8,4]], "warmups_per_session": 1, "samples_per_session": 3,
        "sessions_per_thread": 2, "profile_scope": "top-level wall time; child plans included; no CPU attribution",
        "formal_slo_acceptance": False, "performance_improvement_claim": False,
        "timeout_seconds": 600, "memory_limit_bytes": limit, "available_physical_bytes": memory.ullAvailPhys,
        "limitations": ["profile enabled timings only, no unprofiled latency comparison",
            "prepared candidate-request physical512 tensors; no tokenizer or API E2E",
            "thermals, affinity, background load and storage cache uncontrolled", "n=6 p95 is max"]})
    records = []
    def run(run_id, threads, schedule, profile):
        job = args.output/(run_id+".job.json")
        save(job, {"mode":"nnef-decluttered", "profile_codegen":False, "threads":threads,
            "profile_forward":profile, "cases":cases, "schedule":schedule})
        print("START", run_id, flush=True)
        record = invoke([exe.resolve(),model.resolve(),job.resolve()],args.output,run_id,limit)
        events = [json.loads(line) for line in (args.output/(run_id+".stdout.jsonl")).read_text(encoding="utf-8").splitlines()]
        validate_events(events,cases,policy,expected_threads=threads)
        if len(events) != len(schedule)+2 or events[0]["executor_threads"] != threads:
            raise ValueError("executor/schedule mismatch")
        for event, item in zip(events[1:-1],schedule):
            if event["case"] != cases[item["case"]]["id"] or event["warmup"] != item["warmup"]:
                raise ValueError("schedule mismatch")
            raw = event["raw_logits"]
            if len(raw) != 255 or not all(math.isfinite(v) for v in raw) or raw != references[event["case"]]:
                raise ValueError("raw logits differ from frozen reference")
            if bool(event["forward_profile"]) != profile:
                raise ValueError("profile mismatch")
            if profile:
                p = event["forward_profile"]
                if p["total_ns"] != p["node_ns"]+p["driver_and_instrumentation_ns"] or p["node_ns"] != sum(g["ns"] for g in p["groups"]):
                    raise ValueError("profile accounting mismatch")
        record.update(threads=threads,profiled=profile,events=events)
        save(args.output/(run_id+".validated.json"),record)
        records.append(record)
        print("DONE",run_id,[round(e["forward_ns"]/1e9,3) for e in events[1:-1]],flush=True)
    for threads in [4,8]:
        run(f"gate-{threads}",threads,[{"case":i,"warmup":False} for i in range(4)],False)
    schedule = [{"case":0,"warmup":True}]+[{"case":0,"warmup":False}]*3
    for block, order in enumerate([[4,8],[8,4]]):
        for threads in order:
            run(f"profile-{block}-{threads}",threads,schedule,True)
    summary = {"formal_slo_acceptance":False,"performance_improvement_claim":False,"threads":{},
        "processes":len(records),"forwards":sum(len(r["events"])-2 for r in records),"raw_logits_exact":True,
        "max_probability_error":max(e["probability_max_abs_error"] for r in records for e in r["events"][1:-1])}
    for threads in [4,8]:
        rows = [r for r in records if r["profiled"] and r["threads"] == threads]
        events = [e for r in rows for e in r["events"][1:-1] if not e["warmup"]]
        profiles = [e["forward_profile"] for e in events]
        ops = sorted({g["op"] for p in profiles for g in p["groups"]})
        groups = []
        for op in ops:
            matches = [next(g for g in p["groups"] if g["op"] == op) for p in profiles]
            groups.append({"op":op,"calls":sorted({g["calls"] for g in matches}),
                "seconds":stats([g["ns"]/1e9 for g in matches]),
                "wall_share_percent":stats([100*g["ns"]/p["total_ns"] for g,p in zip(matches,profiles)])})
        summary["threads"][str(threads)] = {"profiled_forward_seconds":stats([e["forward_ns"]/1e9 for e in events]),
            "driver_and_instrumentation_seconds":stats([p["driver_and_instrumentation_ns"]/1e9 for p in profiles]),
            "peak_working_set_bytes":stats([r["peak_working_set_bytes"] for r in rows]),
            "groups":sorted(groups,key=lambda g:-g["seconds"]["median"])}
    save(args.output/"summary.json",summary)
    print("COMPLETE",flush=True)


if __name__ == "__main__":
    main()
