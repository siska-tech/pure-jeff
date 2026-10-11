"""Validate selected official fixtures through independent Rust preparation and native worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--cases",nargs="+",default=["candidate-request","reversed","asr-unicode","long-text","special-token-text","maximum-candidates"])
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if not __debug__ or args.output.exists():
        raise ValueError("assertions enabled and new output required")
    if any(Path(name).name != name or name in (".","..") for name in args.cases):
        raise ValueError("case names must be flat file stems")
    executable, manifest = args.executable.resolve(), args.manifest.resolve()
    bundle = json.loads(manifest.read_text(encoding="utf-8"))
    assets = hashlib.sha256(json.dumps(sorted(bundle["files"],key=lambda r:r["path"].lower()),ensure_ascii=False,
        sort_keys=True,separators=(",",":")).encode()).hexdigest()
    environment = dict(os.environ)
    environment["PATH"] = str(Path(os.environ["SystemRoot"])/"System32")
    assert all(shutil.which(name,path=environment["PATH"]) is None for name in ("python","python3","py"))
    def invoke(command,request,tokens,success=True):
        started = time.monotonic()
        process = subprocess.run([str(executable),command,str(manifest),str(request),"600000",str(tokens)],
            capture_output=True,text=True,encoding="utf-8",timeout=660,env=environment)
        assert (process.returncode == 0) == success, process.stderr
        return (json.loads(process.stdout) if success else {"exit_nonzero":True}),time.monotonic()-started
    cases = []
    with tempfile.TemporaryDirectory(prefix="migration-extended-",dir="experiments/runs") as directory:
        work = Path(directory).resolve()
        assert work.is_relative_to(Path.cwd().resolve())
        for name in args.cases:
            reference = Path("tests/fixtures/jeff-golden")/(name+".json")
            golden = json.loads(reference.read_text(encoding="utf-8"))
            assert next(a["sha256"] for a in golden["worker_observation"]["artifacts"] if a["component"] == "checkpoint_bundle") == assets
            tokens = golden["official"]["input_tokens"]
            request = work/(name+".json")
            request.write_text(json.dumps(golden["request"],ensure_ascii=False),encoding="utf-8")
            prepared,_ = invoke("prepare",request,tokens)
            assert prepared["prompt"] == golden["prompt"]
            assert prepared["token_ids"] == golden["official"]["inputs"]["input_ids"][0]
            assert prepared["input_tokens"] == tokens and prepared["forwards"] == 0
            attempt,elapsed = invoke("decide-process",request,tokens)
            assert attempt["request"] == golden["request"] and attempt["provider_calls_started"] == 1
            assert attempt["outcome"]["status"] == "completed"
            observed = attempt["outcome"]["value"]
            assert observed["judgment"] == golden["official"]["judgment"]
            assert observed["input_tokens"] == tokens and observed["forwards"] == 1
            assert len(observed["scores"]) == len(golden["official"]["probabilities"]) == len(golden["request"]["candidates"])
            assert [s["candidate_id"] for s in observed["scores"]] == [c["id"] for c in golden["request"]["candidates"]]
            error = max(abs(a["option_probability"]-b) for a,b in zip(observed["scores"],golden["official"]["probabilities"]))
            assert error <= 1e-4
            short,_ = invoke("decide-process",request,tokens-1)
            assert short["outcome"] == {"status":"failed","value":"budget_exceeded"}
            cases.append({"case":name,"reference_sha256":sha(reference),"prompt_utf8_sha256":golden["prompt_utf8_sha256"],
                "prompt_bytes_match":True,"token_ids_match":True,"candidate_order_match":True,
                "candidates":len(golden["request"]["candidates"]),"input_tokens":tokens,"forwards":1,
                "probability_max_absolute_error":error,"judgment":observed["judgment"],"exact_token_budget_accepted":True,
                "one_token_short_rejected":True,"elapsed_seconds":elapsed,"artifacts":observed["artifacts"]})
            print(json.dumps({"case":name,"input_tokens":tokens,"max_error":error,"judgment":observed["judgment"]}),flush=True)
    record={"schema_version":"kaze_judge.extended_migration_validation.v1","checked_on":"2026-10-10",
        "executable_sha256":sha(executable),"manifest_sha256":sha(manifest),"harness_sha256":sha(Path(__file__)),
        "runtime_build_sha256":bundle["runtime_build_sha256"],"probability_tolerance":1e-4,"cases":cases,
        "python_absent_from_child_path":True,"recognition_quality_evaluated":False,"slo_accepted":False}
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(record,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
