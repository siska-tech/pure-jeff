"""Frozen Native CLI + NativeProcessProvider pilot; distinct from engine timing."""
import argparse
import ctypes as c
import json
from pathlib import Path
from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 2:
        raise ValueError("at least two repeats required")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    out = args.output_dir
    golden_path = ROOT/"tests/fixtures/jeff-golden/candidate-request.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    request = out/"request.json"
    save(request, golden["request"])
    status = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.windll.kernel32.GlobalMemoryStatusEx(c.byref(status)) or status.ullAvailPhys < 4*1024**3:
        raise RuntimeError("at least 4 GiB available RAM required")
    save(out/"preregistration.json", {"repeats": args.repeats, "executable_sha256": sha(args.executable),
        "manifest_sha256": sha(args.manifest), "golden_sha256": sha(golden_path),
        "harness_sha256": sha(Path(__file__)), "monitor_sha256": sha(Path(__file__).with_name("benchmark_pilot.py")),
        "scope": "frozen jeff decide-process CLI, child worker, Rust Attempt validation, CLI serialization and process exit",
        "peak_scope": "CLI parent only; excludes worker child; do not compare this peak to worker/engine peaks",
        "cache_mode": "new parent and worker per request; storage cache uncontrolled"})
    records = []
    for i in range(args.repeats):
        name = f"api-{i}"
        result = invoke([args.executable.resolve(), "decide-process", args.manifest.resolve(),
                         request.resolve(), "120000", "512"], out, name, min(8*1024**3,status.ullTotalPhys//2), timeout=180)
        attempt = json.loads((out/(name+".stdout.jsonl")).read_text(encoding="utf-8"))
        if attempt["outcome"]["status"] != "completed":
            raise ValueError("API outcome failed")
        observation = attempt["outcome"]["value"]
        actual = [score["option_probability"] for score in observation["scores"]]
        error = max(abs(a-b) for a,b in zip(actual,golden["official"]["probabilities"]))
        if (len(actual) != len(golden["request"]["candidates"]) or error > 1e-4
                or observation["judgment"] != golden["official"]["judgment"]
                or observation["input_tokens"] != golden["official"]["input_tokens"] or observation["forwards"] != 1):
            raise ValueError("API numerical gate failed")
        result.update(probability_max_abs_error=error, judgment_match=True)
        save(out/(name+".validated.json"), result)
        records.append(result)
        print(name, result["parent_process_ns"]/1e9, flush=True)
    save(out/"summary.json", {"pilot": True, "formal_slo_acceptance": False, "case": "candidate-request",
        "cli_e2e_ms": stats([r["parent_process_ns"]/1e6 for r in records]),
        "max_probability_error": max(r["probability_max_abs_error"] for r in records),
        "failures": 0, "peak_scope": "parent only, not reported as worker memory"})


if __name__ == "__main__":
    main()
