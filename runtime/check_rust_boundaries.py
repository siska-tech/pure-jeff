"""Development-only real Rust tokenizer boundary checks, without model forward."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("run without -O")
    if args.output.exists():
        raise FileExistsError(args.output)
    executable, manifest = args.executable.resolve(), args.manifest.resolve()
    golden = json.loads(Path("tests/fixtures/jeff-golden/candidate-request.json").read_text(encoding="utf-8"))
    reference = json.loads(Path("tests/fixtures/jeff-golden/boundaries.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="p2-boundary-", dir="experiments/runs") as directory:
        work = Path(directory).resolve()
        assert work.is_relative_to(Path.cwd().resolve())
        request = work / "request.json"
        def prepare(value, tokens, accepted):
            request.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            process = subprocess.run([str(executable), "prepare", str(manifest), str(request), "120000", str(tokens)],
                                     capture_output=True, text=True, encoding="utf-8", timeout=180)
            assert (process.returncode == 0) == accepted, process.stderr
            if accepted:
                result = json.loads(process.stdout)
                assert result["forwards"] == 0
                return result
            return process.stderr
        base = golden["request"]
        exact = prepare(base, reference["exact_token_limit"], True)
        assert exact["token_ids"] == golden["official"]["inputs"]["input_ids"][0]
        assert "BudgetExceeded" in prepare(base, reference["undersized_token_limit"], False)
        largest = {**base, "candidates": [{"id": f"c{i}", "text": base["original_text"] if i == 0 else f"candidate {i}"}
                                          for i in range(255)]}
        maximum = prepare(largest, 8192, True)
        assert maximum["input_tokens"] == reference["maximum_candidates_input_tokens"]
        assert "BudgetExceeded" in prepare(largest, maximum["input_tokens"] - 1, False)
        over = {**largest, "candidates": largest["candidates"] + [{"id": "c255", "text": "extra"}]}
        assert "InvalidRequest" in prepare(over, 8192, False)
        # A larger caller limit cannot bypass this runtime's 8192-token ceiling.
        long = {**base, "original_text": "test " * 9000}
        assert "BudgetExceeded" in prepare(long, 20000, False)
    def sha(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    record = {"schema_version": "kaze_judge.rust_boundaries.v1", "checked_on": "2026-10-10",
              "executable_sha256": sha(executable), "manifest_sha256": sha(manifest),
              "checker_sha256": sha(Path(__file__)), "reference_sha256": sha(Path("tests/fixtures/jeff-golden/boundaries.json")),
              "exact_token_limit": 128, "undersized_token_limit_rejected": 127,
              "maximum_candidates": 255, "maximum_candidates_input_tokens": maximum["input_tokens"],
              "maximum_candidates_one_token_short_rejected": True, "over_maximum_candidates_rejected": 256,
              "runtime_8192_token_ceiling_enforced": True, "forwards": 0}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
