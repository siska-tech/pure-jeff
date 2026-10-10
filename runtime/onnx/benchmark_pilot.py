"""Windows CPU pilot. Engine diagnostics are not a Tract DecisionProvider E2E benchmark."""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")


def stats(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": values[math.ceil(.5*len(values))-1],
            "p95": values[math.ceil(.95*len(values))-1], "min": values[0], "max": values[-1]}


class Memory(c.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [(name, c.c_size_t) for name in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


class MemoryStatus(c.Structure):
    _fields_ = [("dwLength", w.DWORD), ("dwMemoryLoad", w.DWORD)] + [(name, c.c_ulonglong) for name in (
        "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]


def invoke(command, outdir, run_id, memory_limit, timeout=600):
    query = c.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    query.argtypes = [w.HANDLE, c.POINTER(Memory), w.DWORD]
    query.restype = w.BOOL
    started = time.perf_counter_ns()
    record = {"run_id": run_id, "command": list(map(str, command)), "timeout_seconds": timeout,
              "memory_limit_bytes": memory_limit, "status": "running"}
    with (outdir / (run_id+".stdout.jsonl")).open("w+b") as stdout, (outdir / (run_id+".stderr.log")).open("w+b") as stderr:
        process = subprocess.Popen(record["command"], stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        peak, samples, final_query, last_progress = 0, 0, False, 0
        guard = None
        try:
            while True:
                counters = Memory(cb=c.sizeof(Memory))
                queried = bool(query(w.HANDLE(int(process._handle)), c.byref(counters), c.sizeof(counters)))
                if queried:
                    peak = max(peak, counters.PeakWorkingSetSize)
                    samples += 1
                elapsed = (time.perf_counter_ns()-started)/1e9
                if process.poll() is not None:
                    final_query = bool(query(w.HANDLE(int(process._handle)), c.byref(counters), c.sizeof(counters)))
                    if final_query:
                        peak = max(peak, counters.PeakWorkingSetSize)
                    break
                if elapsed > timeout or peak > memory_limit:
                    guard = "deadline" if elapsed > timeout else "working_set"
                    process.kill()
                    process.wait()
                    break
                if elapsed-last_progress >= 10:
                    save(outdir / "progress.json", {"run_id": run_id, "elapsed_seconds": elapsed,
                                                  "peak_working_set_bytes": peak})
                    last_progress = elapsed
                time.sleep(.01)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        record.update(parent_process_ns=time.perf_counter_ns()-started, exit_code=process.returncode,
                      guard_trigger=guard, peak_working_set_bytes=peak, memory_samples=samples,
                      post_exit_query_succeeded=final_query,
                      memory_scope="process lifetime peak, mapped/shared pages included; not private RSS",
                      status="completed" if not guard and process.returncode == 0 else "failed")
    save(outdir / (run_id+".process.json"), record)
    if record["status"] != "completed" or not samples or not peak:
        raise RuntimeError(f"{run_id} failed; retained process and stderr records")
    return record


def validate_events(events, cases, policy, expected_threads=1):
    by_id = {case["id"]: case for case in cases}
    if not events or events[0]["event"] != "initialized" or events[-1]["event"] != "completed":
        raise ValueError("incomplete engine events")
    if events[0].get("threads", 1) != expected_threads:
        raise ValueError("requested thread count mismatch")
    for event in events[1:-1]:
        case = by_id[event["case"]]
        actual = event["probabilities"]
        expected = case["expected_probabilities"]
        if len(actual) != len(expected) or any(not math.isfinite(v) or v < 0 or v > 1 for v in actual):
            raise ValueError("invalid probabilities")
        error = max(abs(a-b) for a, b in zip(actual, expected))
        ranked = sorted(range(len(actual)), key=lambda i: -actual[i])
        best, second = actual[ranked[0]], actual[ranked[1]]
        judgment = ({"kind": "selected", "candidate_id": case["request"]["candidates"][ranked[0]]["id"]}
                    if best-second > 0 and best >= policy["min_probability"] and best-second >= policy["min_margin"]
                    else {"kind": "abstained"})
        if error > 1e-4 or abs(sum(actual)-1) > 1e-6 or judgment != case["expected_judgment"]:
            raise ValueError("numerical gate failed")
        if "judgment" in event and event["judgment"] != judgment:
            raise ValueError("native policy mismatch")
        if event["effective_tokens"] != case["tokens"]:
            raise ValueError("token count mismatch")
        event.update(probability_max_abs_error=error, judgment_match=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--native-executable", type=Path, required=True)
    parser.add_argument("--tract-executable", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if os.name != "nt" or args.repeats < 2:
        raise ValueError("Windows and >=2 repeats required")
    args.output_dir.mkdir(exist_ok=False, parents=True)
    out = args.output_dir
    status = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.windll.kernel32.GlobalMemoryStatusEx(c.byref(status)) or status.ullAvailPhys < 4*1024**3:
        raise RuntimeError("at least 4 GiB available RAM required")
    memory_limit = min(8*1024**3, status.ullTotalPhys//2)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["policy"]["cpu_threads"] != 1:
        raise ValueError("one-thread fixed manifest required")
    oracle_path = ROOT / "experiments/runs/tract-continuation-20261010/normalized-oracle.json"
    gate_path = ROOT / "experiments/runs/tract-optimizer-20261010/parity/parity.json"
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    model_hash = sha(args.model)
    if not oracle["passed"] or not gate["passed"] or model_hash != oracle["model_sha256"] or model_hash != gate["model_sha256"]:
        raise ValueError("matching passed numerical gates required")
    # Parent preflight occurs outside timed launches; native child also verifies its bundle.
    assets = [{"path": str(args.model), "sha256": model_hash}]
    assets += [{"path": str(p), "sha256": sha(p)} for p in [args.model.parent/"model.onnx.data", args.manifest,
               args.native_executable, args.tract_executable, Path(__file__)]]
    export = json.loads((args.model.parent/"export.json").read_text(encoding="utf-8"))
    for asset in export["assets"]:
        if sha(args.model.parent/asset["path"]) != asset["sha256"]:
            raise ValueError("export asset hash mismatch")
    native_root = args.manifest.resolve().parent / manifest["checkpoint_dir"]
    source_manifest = json.loads((ROOT/"models/jeff-bundle.json").read_text(encoding="utf-8"))
    if (sha(ROOT/"models/jeff-bundle.json") != oracle["manifest_sha256"]
            or {a["path"]: a["sha256"] for a in manifest["files"]}
            != {a["path"]: a["sha256"] for a in source_manifest["checkpoint_files"]}
            or manifest["policy"] != source_manifest["policy"]):
        raise ValueError("Native and ONNX source checkpoints/policy must match")
    for asset in manifest["files"]:
        path = native_root/asset["path"]
        if sha(path) != asset["sha256"]:
            raise ValueError("native asset hash mismatch")
    cases = []
    padding_path = ROOT/"experiments/runs/onnx-phase1-padding.json"
    padding = json.loads(padding_path.read_text(encoding="utf-8"))
    if sha(padding_path) != oracle["padding_gate_sha256"]:
        raise ValueError("padding gate hash mismatch")
    for item in oracle["cases"]:
        name = item["case"]
        golden_path = ROOT/"tests/fixtures/jeff-golden"/(name+".json")
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        if sha(golden_path) != next(c for c in padding["cases"] if c["case"] == name)["golden_sha256"]:
            raise ValueError("golden hash mismatch")
        inputs = {key: [oracle["pad_token_id"] if key == "input_ids" else 0]*(512-len(value[0]))+value[0]
                  for key, value in golden["official"]["inputs"].items()}
        cases.append({"id": name, "request": golden["request"], "inputs": inputs,
                      "count": len(golden["request"]["candidates"]), "temperature": golden["temperature"],
                      "tokens": golden["official"]["input_tokens"], "golden_sha256": sha(golden_path),
                      "expected_probabilities": golden["official"]["probabilities"],
                      "expected_judgment": golden["official"]["judgment"]})
    rng = random.Random(1113)
    cold_order = [["native", "tract"] if block % 2 == 0 else ["tract", "native"] for block in range(args.repeats)]
    warm_schedule = [{"case": i % len(cases), "warmup": True} for i in range(5)]
    for _ in range(args.repeats):
        order = list(range(len(cases)))
        rng.shuffle(order)
        warm_schedule += [{"case": i, "warmup": False} for i in order]
    preregistration = {"schema_version": "kaze_judge.performance_pilot.v1", "seed": 1113,
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "repeats": args.repeats, "cold_order": cold_order, "warm_schedule": warm_schedule,
        "threads": 1, "assets": assets, "available_physical_bytes": status.ullAvailPhys,
        "total_physical_bytes": status.ullTotalPhys, "memory_limit_bytes": memory_limit,
        "cache_mode": "process-cold / storage cache uncontrolled; hashes preflighted before timing",
        "cold_input": cases[0]["id"], "warm_inputs": [case["id"] for case in cases],
        "quantile": "nearest rank; pilot p95 with n=5 is unstable",
        "comparison_scope": "engine diagnostics, not Tract DecisionProvider E2E",
        "limitations": ["native retains BF16 mmap and converts per forward; Tract retains FP32/packed plan",
                         "native startup includes child bundle verification/tokenizer; Tract excludes parent asset preflight",
                         "Tract uses prepared padded tensors; native request timing includes prompt/tokenize",
                         "native head+softmax combined; compare backbone+head+softmax with Tract forward+score",
                         "one resident session per backend; no independent-session confidence interval",
                         "temperature, throttling and P/E core affinity not controlled"],
        "native_manifest_sha256": sha(args.manifest), "oracle_sha256": sha(oracle_path), "gate_sha256": sha(gate_path)}
    save(out/"preregistration.json", preregistration)
    records = []
    for phase, sequence in [("cold", [(b, i) for i, order in enumerate(cold_order) for b in order]),
                            ("resident", [("tract", 0), ("native", 0)])]:
        for backend, block in sequence:
            run_id = f"{phase}-{block}-{backend}"
            job = out/(run_id+".job.json")
            save(job, {"mode": "no-change-axes", "cases": cases,
                       "schedule": [{"case": 0, "warmup": False}] if phase == "cold" else warm_schedule})
            executable = args.native_executable if backend == "native" else args.tract_executable
            asset = args.manifest if backend == "native" else args.model
            print(f"START {run_id}", flush=True)
            record = invoke([executable.resolve(), asset.resolve(), job.resolve()], out, run_id, memory_limit)
            events = [json.loads(line) for line in (out/(run_id+".stdout.jsonl")).read_text(encoding="utf-8").splitlines()]
            validate_events(events, cases, manifest["policy"])
            if len(events[1:-1]) != (1 if phase == "cold" else len(warm_schedule)):
                raise ValueError("missing requests")
            record.update(backend=backend, phase=phase, events=events)
            save(out/(run_id+".validated.json"), record)
            records.append(record)
            print(f"DONE {run_id} {record['parent_process_ns']/1e9:.3f}s peak={record['peak_working_set_bytes']/1024**3:.3f}GiB", flush=True)
    summary = {"schema_version": "kaze_judge.performance_pilot_summary.v1", "pilot": True,
               "formal_slo_acceptance": False, "preregistration_sha256": sha(out/"preregistration.json"), "cells": []}
    for backend in ["native", "tract"]:
        for phase in ["cold", "resident"]:
            group = [r for r in records if r["backend"] == backend and r["phase"] == phase]
            for case in cases:
                events = [event for r in group for event in r["events"][1:-1]
                          if event["case"] == case["id"] and not event["warmup"]]
                if not events:
                    continue
                keys = [k for k in events[0] if k.endswith("_ns")]
                measures = {key: stats([event[key]/1e6 for event in events]) for key in keys}
                combined = [(event["backbone_ns"]+event["head_softmax_ns"] if backend == "native"
                             else event["forward_ns"]+event["score_ns"])/1e6 for event in events]
                measures["compute_and_softmax_ms"] = stats(combined)
                summary["cells"].append({"backend": backend, "phase": phase, "case": case["id"],
                    "effective_tokens": case["tokens"], "physical_tokens": case["tokens"] if backend == "native" else 512,
                    "timings_ms": measures, "max_probability_error": max(e["probability_max_abs_error"] for e in events),
                    "process_peak_bytes": stats([r["peak_working_set_bytes"] for r in group]),
                    "process_startup_ms": stats([r["events"][0]["startup_ns"]/1e6 for r in group]),
                    "parent_process_ms": stats([r["parent_process_ns"]/1e6 for r in group])})
    save(out/"summary.json", summary)
    print("Completed pilot; summary.json", flush=True)


if __name__ == "__main__":
    main()
