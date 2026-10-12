"""Exploratory Windows one-shot benchmark; no SLO or quality acceptance is inferred."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time


class Memory(c.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [(name, c.c_size_t) for name in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stats(values):
    values = sorted(values)
    return {"count":len(values), "min":values[0], "p50":values[math.ceil(len(values)*.5)-1],
            "p95":values[math.ceil(len(values)*.95)-1], "max":values[-1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable",type=Path,required=True)
    parser.add_argument("--profiler",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--python",type=Path,required=True)
    parser.add_argument("--python-manifest",type=Path,required=True)
    parser.add_argument("--repeats",type=int,default=5)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if not __debug__ or os.name != "nt" or args.repeats < 2:
        raise ValueError("Windows, assertions enabled and at least two repeats required")
    if args.output.exists():
        raise FileExistsError(args.output)
    memory = c.WinDLL("psapi",use_last_error=True).GetProcessMemoryInfo
    memory.argtypes = [w.HANDLE,c.POINTER(Memory),w.DWORD]
    memory.restype = w.BOOL
    def invoke(command, environment=None):
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            start = time.perf_counter()
            process = subprocess.Popen(list(map(str,command)), stdout=out, stderr=err, env=environment,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            peak, samples, final_query = 0, 0, False
            try:
                while True:
                    counters = Memory(cb=c.sizeof(Memory))
                    if memory(w.HANDLE(int(process._handle)), c.byref(counters), c.sizeof(counters)):
                        peak = max(peak,counters.PeakWorkingSetSize)
                        samples += 1
                    if process.poll() is not None:
                        counters = Memory(cb=c.sizeof(Memory))
                        final_query = bool(memory(w.HANDLE(int(process._handle)),c.byref(counters),c.sizeof(counters)))
                        if final_query:
                            peak = max(peak,counters.PeakWorkingSetSize)
                        break
                    if time.perf_counter()-start > 180:
                        raise TimeoutError("benchmark exceeded safety timeout")
                    time.sleep(.01)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            elapsed = time.perf_counter()-start
            out.seek(0)
            err.seek(0)
            if process.returncode:
                raise RuntimeError(err.read().decode("utf-8",errors="replace"))
            assert samples > 0 and peak > 0
            return out.read().decode("utf-8"), {"seconds":elapsed,"os_peak_working_set_bytes":peak,
                "memory_samples":samples,"post_exit_memory_query_succeeded":final_query}
    executable, profiler, manifest = args.executable.resolve(), args.profiler.resolve(), args.manifest.resolve()
    python, python_manifest = args.python.resolve(), args.python_manifest.resolve()
    rust_bundle = json.loads(manifest.read_text(encoding="utf-8"))
    original_bundle = json.loads(python_manifest.read_text(encoding="utf-8"))
    assert rust_bundle["policy"] == original_bundle["policy"]
    assert {r["path"]:r["sha256"] for r in rust_bundle["files"]} == {r["path"]:r["sha256"] for r in original_bundle["checkpoint_files"]}
    restricted = dict(os.environ)
    restricted["PATH"] = str(Path(os.environ["SystemRoot"])/"System32")
    cases = {}
    with tempfile.TemporaryDirectory(prefix="p4-bench-",dir="experiments/runs") as directory:
        work = Path(directory).resolve()
        assert work.is_relative_to(Path.cwd().resolve())
        for name in ("candidate-request","reversed","asr-unicode"):
            golden_path = Path("tests/fixtures/jeff-golden")/(name+".json")
            golden = json.loads(golden_path.read_text(encoding="utf-8"))
            request = work/(name+".json")
            request.write_text(json.dumps(golden["request"],ensure_ascii=False),encoding="utf-8")
            wire = work/(name+"-wire.json")
            wire.write_text(json.dumps({"schema_version":"pure_jeff.worker.v1","request":golden["request"],
                "max_input_tokens":512,"max_forwards":1,"timeout_ms":120000},ensure_ascii=False),encoding="utf-8")
            def check(observed):
                assert observed["judgment"] == golden["official"]["judgment"]
                assert observed["input_tokens"] == golden["official"]["input_tokens"] and observed["forwards"] == 1
                probabilities = observed.get("probabilities") or [s["option_probability"] for s in observed["scores"]]
                error = max(abs(a-b) for a,b in zip(probabilities,golden["official"]["probabilities"]))
                assert error <= 1e-4
                return error
            runs = {"rust_worker":[],"python_worker":[]}
            for repeat in range(args.repeats):
                # Alternate the backend order to reduce systematic ordering effects.
                for backend in (["rust_worker","python_worker"] if repeat%2==0 else ["python_worker","rust_worker"]):
                    output = work/f"{name}-{repeat}-{backend}.json"
                    command = [executable,"worker"] if backend == "rust_worker" else [python,"-I","-B",Path("runtime/jeff_worker.py").resolve()]
                    command += ["--manifest",manifest if backend == "rust_worker" else python_manifest,"--request",wire,"--response",output]
                    _, measurement = invoke(command,restricted if backend == "rust_worker" else None)
                    response = json.loads(output.read_text(encoding="utf-8"))
                    assert response["schema_version"] == "pure_jeff.worker.v1" and response["request_id"] == golden["request"]["request_id"]
                    assert response["result"]["status"] == "completed"
                    measurement["probability_max_absolute_error"] = check(response["result"]["value"])
                    runs[backend].append(measurement)
                print(json.dumps({"case":name,"repeat":repeat+1,"repeats":args.repeats}),flush=True)
            raw, outer = invoke([executable,"decide-process",manifest,request,120000,512],restricted)
            attempt = json.loads(raw)
            assert attempt["outcome"]["status"] == "completed"
            check(attempt["outcome"]["value"])
            raw, diagnostic_memory = invoke([profiler,manifest,request],restricted)
            diagnostic = json.loads(raw)
            check(diagnostic)
            cases[name] = {"reference_sha256":sha(golden_path),"input_tokens":golden["official"]["input_tokens"],
                "runs":runs,"summary":{backend:{"seconds":stats([r["seconds"] for r in rows]),
                    "os_peak_working_set_bytes":stats([r["os_peak_working_set_bytes"] for r in rows])} for backend,rows in runs.items()},
                "native_process_cli_single_run":outer,"diagnostic_profile":diagnostic,"diagnostic_process":diagnostic_memory}
    record = {"schema_version":"kaze_judge.p4_benchmark.v1","status":"exploratory_no_slo_acceptance",
        "checked_on":"2026-10-10","host":{"platform":platform.platform(),"processor":os.environ.get("PROCESSOR_IDENTIFIER"),"logical_cpus":os.cpu_count()},
        "method":{"process":"fresh process and model load for every run","os_file_cache":"not flushed; potentially cached",
            "warm_model":False,"worker_memory":"Windows PeakWorkingSetSize of directly launched process only; includes mapped/shared pages, not private RSS; Python venv interpreter descendants are excluded",
            "memory_sampling_seconds":.01,"native_cli_memory":"parent only; worker memory measured separately",
            "quantile":"nearest rank; with 5 samples p95 is max; exploratory small sample",
            "stage_profile":"single diagnostic process; forward includes BF16 weight loading/conversion; bundle stage includes hash and tensor metadata",
            "python_worker_includes":"Python/PyTorch/transformers startup, source/dependency/hash validation and model loading"},
        "executable_sha256":sha(executable),"profiler_executable_sha256":sha(profiler),"harness_sha256":sha(Path(__file__)),
        "manifest_sha256":sha(manifest),"python_manifest_sha256":sha(python_manifest),"policy":rust_bundle["policy"],
        "cases":cases,"slo":None,"quality_accepted":False,
        "memory_scope":{"rust_worker":"direct Rust worker process",
            "python_worker":"directly launched executable only; invalid for interpreter memory when the venv executable redirects to a child"},
        "supplemental_tree_memory_tool":"runtime/measure_worker_tree.py"}
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(record,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output":str(args.output),"status":record["status"]}),flush=True)


if __name__ == "__main__":
    main()
