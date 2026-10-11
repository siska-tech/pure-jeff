"""Development checks for the staged Rust-only local prototype, including reversible corruption cases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if not __debug__ or args.output.exists():
        raise ValueError("assertions must be enabled and output must be new")
    package = args.package.resolve()
    assert package.is_relative_to(Path.cwd().resolve()/"experiments/runs")
    index = json.loads((package/"package.json").read_text(encoding="utf-8"))
    assert not any(Path(r["path"]).suffix.lower() in (".py",".pyc",".pyd") for r in index["files"])
    environment = dict(os.environ)
    environment["PATH"] = str(Path(os.environ["SystemRoot"])/"System32")
    assert all(shutil.which(name,path=environment["PATH"]) is None for name in ("python","python3","py","cargo"))
    def invoke(expected):
        # Start outside both the checkout and package directory; all runtime paths
        # must derive from the relocated executable, not the caller's working dir.
        with tempfile.TemporaryDirectory(prefix="kaze-portable-cwd-") as cwd:
            process = subprocess.run([str(package/"verify.exe")],cwd=cwd,env=environment,
                capture_output=True,text=True,encoding="utf-8",timeout=150)
        assert (process.returncode == 0) == expected, process.stderr
        return json.loads(process.stdout) if expected else {"exit_nonzero":True}
    success = invoke(True)
    assert success["status"] == "verified_local_prototype" and success["release_ready"] is False
    negative = {}
    extra = package/"unexpected-validation-file.txt"
    assert not extra.exists()
    try:
        extra.write_text("unexpected",encoding="utf-8")
        negative["added_file"] = invoke(False)
    finally:
        extra.unlink()
    target = package/"smoke-request.json"
    original = target.read_bytes()
    try:
        target.write_bytes(original+b" ")
        negative["changed_file"] = invoke(False)
        target.unlink()
        negative["missing_file"] = invoke(False)
    finally:
        target.write_bytes(original)
    index_path = package/"package.json"
    index_bytes = index_path.read_bytes()
    try:
        corrupted = {**index,"files":[*index["files"],{"path":"../escape","bytes":0,"sha256":"0"*64}]}
        index_path.write_text(json.dumps(corrupted),encoding="utf-8")
        negative["path_traversal"] = invoke(False)
    finally:
        index_path.write_bytes(index_bytes)
    # Verify byte-for-byte restoration, including the large checkpoint assets.
    assert all(sha(package/r["path"]) == r["sha256"] for r in index["files"])
    record = {"schema_version":"kaze_judge.p4_portable_validation.v1","checked_on":"2026-10-10",
        "status":"relocated_local_prototype_verified","package_index_sha256":sha(index_path),
        "builder_sha256":index["builder_sha256"],"harness_sha256":sha(Path(__file__)),
        "executable_sha256":sha(package/"jeff.exe"),"verifier_sha256":sha(package/"verify.exe"),
        "payload_bytes":index["payload_bytes"],"payload_files":len(index["files"]),
        "python_and_cargo_absent_from_child_path":True,"python_uninstalled_host_test":False,
        "working_directory_outside_checkout":True,"native_smoke":success,"negative_cases":negative,
        "license_issues":index["license_issues"],"release_ready":False}
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(record,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(json.dumps({"status":record["status"],"payload_bytes":index["payload_bytes"],"negative_cases":len(negative)}))


if __name__ == "__main__":
    main()
