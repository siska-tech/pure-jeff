"""Check official preparation and native rejection at the exact 8192-token ceiling."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import jeff_worker as worker


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--python-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not __debug__ or args.output.exists():
        raise ValueError("assertions enabled and new output required")
    manifest = worker.verify_bundle(args.python_manifest)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(Path(manifest["source"]) / "src"))
    from jeff.model import DecisionModel

    model = DecisionModel(checkpoint=Path(manifest["checkpoint"]), device="cpu",
                          cpu_threads=manifest["policy"]["cpu_threads"])
    forward_calls = []
    handle = model.register_forward_pre_hook(lambda *_: forward_calls.append(True))
    records = []
    for tokens, budget in [(8192, 8192), (8192, 8191), (8193, 8192), (8193, 8193)]:
        path = Path(f"tests/fixtures/jeff-requests/token-limit-{tokens}.json")
        request = worker.read_json(path)
        # Use the same clamp as the Python worker and default official predict.
        effective = min(budget, 8192)
        accepted = tokens <= effective
        try:
            batch = model.prepare([worker.make_row(request)], max_length=effective)
        except ValueError as error:
            assert not accepted and "token limit; no input was truncated" in str(error)
            actual = "budget_exceeded"
        else:
            assert accepted and batch.input_tokens == tokens
            actual = "prepared"
        records.append({"input_tokens": tokens, "requested_budget": budget,
                        "effective_ceiling": effective, "request_sha256": sha(path),
                        "official_prepare": actual})
    assert not forward_calls
    handle.remove()
    del model
    gc.collect()

    environment = dict(os.environ)
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    assert all(shutil.which(name, path=environment["PATH"]) is None
               for name in ("python", "python3", "py"))
    for record in records:
        path = Path(f"tests/fixtures/jeff-requests/token-limit-{record['input_tokens']}.json")
        prepared = subprocess.run([str(args.executable.resolve()), "prepare",
                                   str(args.manifest.resolve()), str(path.resolve()),
                                   "600000", str(record["requested_budget"])],
                                  capture_output=True, text=True, encoding="utf-8",
                                  env=environment, timeout=660)
        if record["official_prepare"] == "prepared":
            assert prepared.returncode == 0, prepared.stderr
            value = json.loads(prepared.stdout)
            assert value["input_tokens"] == record["input_tokens"] and value["forwards"] == 0
            record["rust_prepare"] = "prepared"
            # Actual accepted forward is verified separately against the golden.
        else:
            assert prepared.returncode != 0 and "BudgetExceeded" in prepared.stderr
            attempt = subprocess.run([str(args.executable.resolve()), "decide-process",
                                      str(args.manifest.resolve()), str(path.resolve()),
                                      "600000", str(record["requested_budget"])],
                                     capture_output=True, text=True, encoding="utf-8",
                                     env=environment, timeout=660)
            assert attempt.returncode == 0, attempt.stderr
            value = json.loads(attempt.stdout)
            assert value["outcome"] == {"status": "failed", "value": "budget_exceeded"}
            assert value["request"] == worker.read_json(path)
            record["rust_prepare"] = "budget_exceeded"
            record["rust_native_outcome"] = value["outcome"]
    result = {"schema_version": "kaze_judge.token_limit_boundaries.v1",
              "checked_on": "2026-10-10", "cases": records,
              "official_forward_calls": len(forward_calls),
              "python_prepare_clamp_matches_worker": True,
              "python_absent_from_native_child_path": True,
              "executable_sha256": sha(args.executable),
              "manifest_sha256": sha(args.manifest),
              "python_manifest_sha256": sha(args.python_manifest),
              "harness_sha256": sha(__file__),
              "request_generator_sha256": sha("runtime/create_token_limit_requests.py"),
              "recognition_quality_evaluated": False, "slo_accepted": False}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"boundary_cases": len(records), "official_forward_calls": len(forward_calls)}))


if __name__ == "__main__":
    main()
