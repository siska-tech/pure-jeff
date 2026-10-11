"""Paired four-thread Trilu candidate: correctness gates, unprofiled latency, then diagnosis."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=Path,required=True)
    parser.add_argument("--generation",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    previous = ROOT/"docs/research/jeff-onnx-tract/forward-profile-2026-10-10"
    frozen = json.loads((previous/"preregistration.json").read_text(encoding="utf-8"))
    control = ROOT/".venv/tract-forward-target/release/bench.exe"
    base = ROOT/".venv/tract-forward-probe"
    model = ROOT/"experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar"
    if sha(control) != frozen["candidate_executable_sha256"] or sha(model) != frozen["model_sha256"]:
        raise ValueError("frozen control/model changed")
    generation = json.loads(args.generation.read_text(encoding="utf-8"))
    if generation["internal_timers"] or not generation["trilu_change"] or generation["new_dependencies"]:
        raise ValueError("wrong candidate")
    for item in generation["files"]:
        path = args.generation.parent/item["path"]
        if sha(path) != item["sha256"]:
            raise ValueError("source changed")
        if item["path"] not in ["vendor/core/src/ops/array/trilu.rs","vendor/core/src/ops/array/trilu/trilu_rows.rs"]:
            if sha(base/item["path"]) != item["sha256"]:
                raise ValueError("change outside Trilu")
    cases = json.loads((previous/"gate-4.job.json").read_text(encoding="utf-8"))["cases"]
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
    if len(cases) != 4:
        raise ValueError("four cases required")
    references = {e["case"]:e["raw_logits"] for e in [json.loads(line) for line in
        (previous/"gate-control.stdout.jsonl").read_text(encoding="utf-8").splitlines()][1:-1]}
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL("kernel32").GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError("need 4 GiB available RAM")
    limit = min(8*1024**3,memory.ullTotalPhys//2)
    policy = json.loads((ROOT/"models/jeff-rust-bundle-p3.json").read_text(encoding="utf-8"))["policy"]
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/"preregistration.json",{"date_utc":datetime.now(timezone.utc).isoformat(),
        "model_sha256":sha(model),"control_executable_sha256":sha(control),"candidate_executable_sha256":sha(args.candidate),
        "generation_sha256":sha(args.generation),"script_sha256":sha(__file__),"lock_sha256":sha(base/"Cargo.lock"),
        "threads":4,"orders":[["control","candidate"],["candidate","control"],["control","candidate"]],
        "warmups_per_session":1,"samples_per_session":3,"sessions_per_binary":3,
        "profile_sessions_per_binary":1,"profile_warmups":1,"profile_samples":3,
        "acceptance":"raw logits exact; all three paired session medians improve; pooled median and p95 improve; no guard failure",
        "scope":"candidate-request physical512; prepared tensors; process startup incidental n=3, not a cold campaign",
        "timeout_seconds":600,"memory_limit_bytes":limit,"available_physical_bytes":memory.ullAvailPhys,
        "formal_slo_acceptance":False,"limitations":["n=9 p95 is max; no confidence interval",
            "thermal, affinity, background load and storage cache uncontrolled","profile sessions excluded from latency comparison",
            "no Native or tokenizer/API E2E comparison"]})
    records = []
    def run(run_id,label,schedule,profile=False):
        job = args.output/(run_id+".job.json")
        save(job,{"mode":"nnef-decluttered","profile_codegen":False,"threads":4,"profile_forward":profile,
            "cases":cases,"schedule":schedule})
        print("START",run_id,flush=True)
        exe = control if label == "control" else args.candidate
        record = invoke([exe.resolve(),model.resolve(),job.resolve()],args.output,run_id,limit)
        events = [json.loads(line) for line in (args.output/(run_id+".stdout.jsonl")).read_text(encoding="utf-8").splitlines()]
        validate_events(events,cases,policy,expected_threads=4)
        if len(events) != len(schedule)+2 or events[0]["executor_threads"] != 4:
            raise ValueError("schedule/executor mismatch")
        for event,item in zip(events[1:-1],schedule):
            if event["case"] != cases[item["case"]]["id"] or event["warmup"] != item["warmup"]:
                raise ValueError("schedule mismatch")
            if event["raw_logits"] != references[event["case"]]:
                raise ValueError("raw logits differ")
            if bool(event["forward_profile"]) != profile:
                raise ValueError("profile mismatch")
        record.update(label=label,profiled=profile,events=events)
        save(args.output/(run_id+".validated.json"),record)
        records.append(record)
        print("DONE",run_id,[round(e["forward_ns"]/1e9,3) for e in events[1:-1]],flush=True)
    for label in ["control","candidate"]:
        run("gate-"+label,label,[{"case":i,"warmup":False} for i in range(4)])
    schedule = [{"case":0,"warmup":True}]+[{"case":0,"warmup":False}]*3
    for block,order in enumerate([["control","candidate"],["candidate","control"],["control","candidate"]]):
        for label in order:
            run(f"resident-{block}-{label}",label,schedule)
    for label in ["candidate","control"]:
        run("profile-"+label,label,schedule,profile=True)
    summary = {"formal_slo_acceptance":False,"raw_logits_exact":True,"processes":len(records),
        "forwards":sum(len(r["events"])-2 for r in records),"binaries":{}}
    for label in ["control","candidate"]:
        rows = [r for r in records if r["label"] == label and r["run_id"].startswith("resident-")]
        events = [e for r in rows for e in r["events"][1:-1] if not e["warmup"]]
        profile = next(r for r in records if r["run_id"] == "profile-"+label)
        summary["binaries"][label] = {"warm_forward_seconds":stats([e["forward_ns"]/1e9 for e in events]),
            "session_medians_seconds":[stats([e["forward_ns"]/1e9 for e in r["events"][1:-1] if not e["warmup"]])["median"] for r in rows],
            "startup_seconds":stats([r["events"][0]["startup_ns"]/1e9 for r in rows]),
            "peak_working_set_bytes":stats([r["peak_working_set_bytes"] for r in rows]),
            "profiled_trilu_seconds":stats([next(g["ns"] for g in e["forward_profile"]["groups"] if g["op"] == "Trilu")/1e9
                for e in profile["events"][1:-1] if not e["warmup"]])}
    control_s,candidate_s = [summary["binaries"][label] for label in ["control","candidate"]]
    deltas = [b-a for a,b in zip(control_s["session_medians_seconds"],candidate_s["session_medians_seconds"])]
    summary.update(paired_session_delta_seconds=deltas,local_pilot_accepted=all(d<0 for d in deltas) and
        all(candidate_s["warm_forward_seconds"][q] < control_s["warm_forward_seconds"][q] for q in ["median","p95"]),
        max_probability_error=max(e["probability_max_abs_error"] for r in records for e in r["events"][1:-1]))
    save(args.output/"summary.json",summary)
    print("COMPLETE",flush=True)


if __name__ == "__main__":
    main()
