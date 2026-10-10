"""Development-only, resource-guarded preparation of the step1113 NNEF cache."""
import argparse
import ctypes as c
from pathlib import Path

from benchmark_pilot import MemoryStatus, invoke, save, sha

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT/"experiments/runs/onnx-current-step1113-v2/model.normalized.onnx")
    parser.add_argument("--executable", type=Path, default=ROOT/"runtime/tract/target/release/pack.exe")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = args.model.resolve()
    model_hash = sha(model)
    data_hash = sha(model.parent/"model.onnx.data")
    if (model_hash != "4808e28131967e8ed33f8b50d46c4212e11c19b79e6dfb5209cf9b6931cd9b0c"
            or data_hash != "1b7c0e8a7b7902fe8631b9dec3a702858152f6693cdf5f501df1dfd710afb1a5"):
        raise ValueError("requires the validated step1113 normalized ONNX and external weights")
    status = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL("kernel32").GlobalMemoryStatusEx(c.byref(status)) or status.ullAvailPhys < 4*1024**3:
        raise RuntimeError("need 4 GiB available RAM")
    limit = min(8*1024**3, status.ullTotalPhys//2)
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/"pack-preregistration.json", {
        "model_sha256": model_hash, "external_data_sha256": data_hash,
        "pack_executable_sha256": sha(args.executable), "cargo_lock_sha256": sha(ROOT/"runtime/tract/Cargo.lock"),
        "harness_sha256": sha(__file__), "monitor_sha256": sha(ROOT/"runtime/onnx/benchmark_pilot.py"),
        "pack_source_sha256": sha(ROOT/"runtime/tract/src/bin/pack.rs"),
        "profile": "declutter excluding ChangeAxes; codegen deferred until reload",
        "timeout_seconds": 600, "peak_working_set_limit_bytes": limit,
        "available_physical_bytes": status.ullAvailPhys})
    output = args.output/"jeff.decluttered.nnef.tar"
    invoke([args.executable.resolve(), model, output.resolve(), "decluttered"],
           args.output, "pack-decluttered", limit)
    save(args.output/"artifact.json", {"file": output.name, "sha256": sha(output),
        "bytes": output.stat().st_size, "pack_preregistration_sha256": sha(args.output/"pack-preregistration.json")})
    print("Prepared NNEF asset; numerical acceptance requires benchmark_nnef.py", flush=True)


if __name__ == "__main__":
    main()
