"""Supplement worker memory evidence when a Windows Python venv launcher starts an interpreter child."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from benchmark_rust_runtime import Memory, sha


class ProcessEntry(c.Structure):
    _fields_ = [("dwSize",w.DWORD),("cntUsage",w.DWORD),("th32ProcessID",w.DWORD),
        ("th32DefaultHeapID",c.c_size_t),("th32ModuleID",w.DWORD),("cntThreads",w.DWORD),
        ("th32ParentProcessID",w.DWORD),("pcPriClassBase",w.LONG),("dwFlags",w.DWORD),("szExeFile",w.WCHAR*260)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if not __debug__ or args.output.exists():
        raise ValueError("assertions enabled and new output required")
    kernel = c.WinDLL("kernel32",use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype=w.HANDLE
    kernel.Process32FirstW.argtypes=[w.HANDLE,c.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes=[w.HANDLE,c.POINTER(ProcessEntry)]
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]
    kernel.OpenProcess.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    memory = c.WinDLL("psapi",use_last_error=True).GetProcessMemoryInfo
    memory.argtypes=[w.HANDLE,c.POINTER(Memory),w.DWORD]
    memory.restype=w.BOOL
    def parents():
        handle = kernel.CreateToolhelp32Snapshot(2,0)
        if handle == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = ProcessEntry(dwSize=c.sizeof(ProcessEntry))
            result = {}
            more = kernel.Process32FirstW(handle,c.byref(entry))
            while more:
                result[entry.th32ProcessID]=(entry.th32ParentProcessID,entry.szExeFile)
                more = kernel.Process32NextW(handle,c.byref(entry))
            return result
        finally:
            kernel.CloseHandle(handle)
    cases = {}
    with tempfile.TemporaryDirectory(prefix="p4-memory-",dir="experiments/runs") as directory:
        work = Path(directory).resolve()
        assert work.is_relative_to(Path.cwd().resolve())
        for name in ("candidate-request","reversed","asr-unicode"):
            golden = json.loads((Path("tests/fixtures/jeff-golden")/(name+".json")).read_text(encoding="utf-8"))
            wire, output = work/"wire.json",work/(name+".json")
            wire.write_text(json.dumps({"schema_version":"kaze_judge.worker.v1","request":golden["request"],
                "max_input_tokens":512,"max_forwards":1,"timeout_ms":120000},ensure_ascii=False),encoding="utf-8")
            process = subprocess.Popen([str(args.python.resolve()),"-I","-B",str(Path("runtime/jeff_worker.py").resolve()),
                "--manifest",str(args.manifest.resolve()),"--request",str(wire),"--response",str(output)],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            handles, peaks, samples, names = {},{},0,{}
            aggregate_peak, started = 0,time.monotonic()
            try:
                while True:
                    tree = parents()
                    own = {process.pid,*handles}
                    while True:
                        descendants = {pid for pid,(parent,_) in tree.items() if parent in own}
                        extended = own|descendants
                        if extended == own:
                            break
                        own = extended
                    for pid in own:
                        if pid not in handles and pid in tree:
                            handle = kernel.OpenProcess(0x410,False,pid)
                            if not handle:
                                if c.get_last_error() == 87:
                                    # A launcher/helper can exit between snapshot and OpenProcess.
                                    continue
                                raise c.WinError(c.get_last_error())
                            handles[pid]=handle
                            names[pid]=tree[pid][1]
                    live_total = 0
                    for pid,handle in handles.items():
                        counters = Memory(cb=c.sizeof(Memory))
                        if memory(handle,c.byref(counters),c.sizeof(counters)):
                            peaks[pid]=max(peaks.get(pid,0),counters.PeakWorkingSetSize)
                            live_total += counters.WorkingSetSize
                    aggregate_peak = max(aggregate_peak,live_total)
                    samples += 1
                    if process.poll() is not None:
                        break
                    if time.monotonic()-started > 150:
                        raise TimeoutError("memory probe deadline exceeded")
                    time.sleep(.01)
                assert process.returncode == 0
                response = json.loads(output.read_text(encoding="utf-8"))
                assert response["result"]["status"] == "completed"
                observed = response["result"]["value"]
                assert observed["judgment"] == golden["official"]["judgment"]
                assert max(abs(a["option_probability"]-b) for a,b in zip(observed["scores"],golden["official"]["probabilities"])) <= 1e-4
                assert len(peaks) >= 2 and max(peaks.values()) > 100*1024**2, "interpreter child must be observed"
                cases[name]={"processes":[{"pid":pid,"executable_name":names[pid],"os_peak_working_set_bytes":peak} for pid,peak in sorted(peaks.items())],
                    "sampled_aggregate_working_set_peak_bytes":aggregate_peak,"samples":samples,
                    "elapsed_seconds":time.monotonic()-started}
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for handle in handles.values():
                    kernel.CloseHandle(handle)
            print(json.dumps({"case":name,"observed_processes":len(peaks)}),flush=True)
    record={"schema_version":"kaze_judge.p4_worker_tree_memory.v1","checked_on":"2026-10-10",
        "harness_sha256":sha(Path(__file__)),"memory_helper_sha256":sha(Path("runtime/benchmark_rust_runtime.py")),
        "python_manifest_sha256":sha(args.manifest),"cases":cases,"repeats_per_case":1,
        "method":"Toolhelp process-tree discovery; OS per-process PeakWorkingSetSize plus sampled aggregate WorkingSetSize; shared pages may be double counted; not private RSS",
        "poll_interval_lower_bound_seconds":.01,"scope_correction":"original p4-benchmark Python memory is launcher-only and cannot represent interpreter memory",
        "slo_accepted":False}
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(record,stream,ensure_ascii=False,indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
