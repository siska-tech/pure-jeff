"""Development-only acceptance harness for the independent Rust CLI (no inference in Python)."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if not __debug__:
        raise RuntimeError("run this validation harness without -O")
    executable = args.executable.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    def invoke(command,request,manifest_path=args.manifest,tokens=512,timeout=120000,success=True):
        completed = subprocess.run([str(executable),command,str(manifest_path.resolve()),str(request),str(timeout),str(tokens)],
                                   capture_output=True,text=True,encoding="utf-8",timeout=180)
        if not success:
            assert completed.returncode != 0
            return {"exit_nonzero":True}
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        return json.loads(completed.stdout)
    runs = Path("experiments/runs")
    runs.mkdir(parents=True,exist_ok=True)
    cases,negative = [],{}
    with tempfile.TemporaryDirectory(prefix="p2-",dir=runs) as directory:
        work = Path(directory).resolve()
        assert work.is_relative_to(Path.cwd().resolve())
        for name in ("candidate-request","reversed","asr-unicode"):
            path = Path("tests/fixtures/jeff-golden")/(name+".json")
            golden = json.loads(path.read_text(encoding="utf-8"))
            original_assets = next(a["sha256"] for a in golden["worker_observation"]["artifacts"] if a["component"]=="checkpoint_bundle")
            # Python's WindowsPath inventory sorts case-insensitively; Rust uses
            # byte order. Preserve the reference's serialization order here.
            reference_order = sorted(manifest["files"],key=lambda r:r["path"].lower())
            assets = hashlib.sha256(json.dumps(reference_order,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            assert original_assets==assets
            request = work/(name+".json")
            request.write_text(json.dumps(golden["request"],ensure_ascii=False),encoding="utf-8")
            prepared = invoke("prepare",request)
            assert prepared["prompt"]==golden["prompt"]
            assert prepared["token_ids"]==golden["official"]["inputs"]["input_ids"][0]
            assert prepared["input_tokens"]==golden["official"]["input_tokens"]
            assert prepared["forwards"]==0
            attempt = invoke("decide",request)
            assert attempt["request"]==golden["request"] and attempt["outcome"]["status"]=="completed"
            observed = attempt["outcome"]["value"]
            assert observed["judgment"]==golden["official"]["judgment"]
            assert observed["input_tokens"]==golden["official"]["input_tokens"] and observed["forwards"]==1
            assert [s["candidate_id"] for s in observed["scores"]]==[c["id"] for c in golden["request"]["candidates"]]
            error = max(abs(s["option_probability"]-p) for s,p in zip(observed["scores"],golden["official"]["probabilities"]))
            assert error<=1e-4
            cases.append({"case":name,"reference_sha256":sha(path),"prompt_bytes_match":True,"token_ids_match":True,
                          "input_tokens":observed["input_tokens"],"forwards":1,"judgment":observed["judgment"],
                          "probability_max_absolute_error":error,"artifacts":observed["artifacts"]})
        request = work/"candidate-request.json"
        low = invoke("decide",request,tokens=127)
        assert low["outcome"]=={"status":"failed","value":"budget_exceeded"}
        negative["one_token_short"] = low["outcome"]
        expired = invoke("decide",request,timeout=1)
        assert expired["outcome"]=={"status":"failed","value":"timeout"}
        negative["one_ms_timeout"] = expired["outcome"]
        base = json.loads(request.read_text(encoding="utf-8"))
        skipped = work/"skipped.json"
        skipped.write_text(json.dumps({**base,"reason":None}),encoding="utf-8")
        skipped_attempt = invoke("decide",skipped,manifest_path=work/"missing.json")
        assert skipped_attempt["provider_calls_started"]==0 and skipped_attempt["outcome"]["status"]=="not_selected"
        negative["not_selected_missing_manifest"] = {"provider_calls_started":0,"status":"not_selected"}
        duplicate = work/"duplicate.json"
        duplicate.write_text('{"request_id":"a","request_id":"b"}',encoding="utf-8")
        negative["duplicate_request_key"] = invoke("decide",duplicate,success=False)
        # A manifest copy needs the same relative checkpoint location.
        # Write tampered copies next to the original using unique temporary names.
        mutations = {
            "runtime_build_changed":{**manifest,"runtime_build_sha256":"0"*64},
            "missing_required_component":{**manifest,"files":manifest["files"][1:]},
            "asset_hash_changed":{**manifest,"files":[{**r,"sha256":"0"*64} if i==0 else r for i,r in enumerate(manifest["files"])]},
            "path_traversal":{**manifest,"checkpoint_dir":"../escape"},
            "unknown_manifest_field":{**manifest,"extra":True},
        }
        for name,mutated in mutations.items():
            with tempfile.NamedTemporaryFile(prefix="p2-mutated-",suffix=".json",dir=args.manifest.resolve().parent,
                                             mode="w",encoding="utf-8",delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(mutated,stream)
            try:
                if name=="unknown_manifest_field":
                    negative[name]=invoke("decide",request,manifest_path=temporary,success=False)
                else:
                    result=invoke("decide",request,manifest_path=temporary)
                    assert result["outcome"]=={"status":"failed","value":"unavailable"}
                    negative[name]=result["outcome"]
            finally:
                assert temporary.resolve().is_relative_to(args.manifest.resolve().parent)
                temporary.unlink()
    result={"schema_version":"kaze_judge.p2_validation.v1","checked_on":"2026-10-10",
            "status":"independent_request_prompt_bundle_native_provider_verified_three_synthetic_cases",
            "runtime_executable_sha256":sha(executable),"manifest_sha256":sha(args.manifest),
            "runtime_build_sha256":manifest["runtime_build_sha256"],"harness_sha256":sha(Path(__file__)),
            "cargo_lock_sha256":sha(Path("runtime/rust/Cargo.lock")),"cases":cases,"negative_cases":negative,
            "hard_process_timeout":False,"recognition_quality_evaluated":False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({"cases":[{k:c[k] for k in ("case","input_tokens","probability_max_absolute_error","judgment")} for c in cases],
                      "negative_cases":len(negative)}))


if __name__ == "__main__":
    main()
