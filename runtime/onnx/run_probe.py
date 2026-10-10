"""Run the isolated Rust feasibility probe with a hard child-process timeout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--stage", choices=["import", "analyze", "type", "optimize", "run"], required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.timeout <= 0:
        raise ValueError("new output and positive timeout required")
    command = [str(args.executable.resolve()), str(args.model.resolve()), args.stage]
    if (args.stage == "run") != (args.inputs is not None):
        raise ValueError("--inputs is required only for run")
    if args.inputs:
        command.append(str(args.inputs.resolve()))
    record = {"schema_version": "kaze_judge.tract_probe.v1", "model_sha256": sha(args.model),
              "executable_sha256": sha(args.executable), "harness_sha256": sha(Path(__file__)),
              "tract_revision": "9e0cfaa9b3a9251f41f74101801dc2c937b1660a", "command": command,
              "timeout_seconds": args.timeout, "performance_benchmark": False}
    if args.inputs:
        record["inputs_sha256"] = sha(args.inputs)
    start = time.monotonic()
    try:
        process = subprocess.run(command, capture_output=True, timeout=args.timeout)
        record.update(exit_code=process.returncode, timed_out=False,
                      stdout=process.stdout.decode("utf-8", errors="replace")[-100000:],
                      stderr=process.stderr.decode("utf-8", errors="replace")[-100000:])
    except subprocess.TimeoutExpired as error:
        record.update(exit_code=None, timed_out=True,
                      stdout=(error.stdout or b"").decode("utf-8", errors="replace")[-100000:],
                      stderr=(error.stderr or b"").decode("utf-8", errors="replace")[-100000:])
    record["elapsed_seconds"] = time.monotonic() - start
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(record, ensure_ascii=False))
    if record["timed_out"] or record["exit_code"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
