"""Build a local Windows runtime prototype with asset inventory and local dependency license evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from license_supplements import contained_file, load_supplements


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def write(path, value):
    with path.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--verifier",type=Path,required=True)
    parser.add_argument("--audit",type=Path,required=True)
    parser.add_argument("--destination",type=Path,required=True)
    args = parser.parse_args()
    if not __debug__:
        raise ValueError("run without -O")
    destination = args.destination.resolve()
    if destination.exists() or not destination.is_relative_to(Path.cwd().resolve()):
        raise ValueError("destination must be a new directory inside the workspace")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assert audit["executable_sha256"] == sha(args.executable)
    assert audit["cargo_lock_sha256"] == sha("runtime/rust/Cargo.lock")
    root = (args.manifest.resolve().parent/manifest["checkpoint_dir"]).resolve()
    metadata = json.loads(subprocess.check_output(["cargo","metadata","--locked","--offline",
        "--manifest-path","runtime/rust/Cargo.toml","--filter-platform","x86_64-pc-windows-msvc","--format-version","1"],text=True,encoding="utf-8"))
    supplement_index = Path(__file__).resolve().parent/"licenses/supplements.json"
    supplements = load_supplements(supplement_index,metadata["packages"])
    reference_index = supplement_index.parent/"reference-sources.json"
    references = json.loads(reference_index.read_text(encoding="utf-8"))
    if references["schema_version"] != "kaze_judge.reference_license_evidence.v1":
        raise ValueError("unsupported reference license evidence")
    for reference in references["sources"]:
        source = contained_file(reference_index.parent,reference["file"])
        if sha(source) != reference["sha256"]:
            raise ValueError("reference license hash mismatch")
    destination.mkdir()
    checkpoint = destination/"checkpoint"
    checkpoint.mkdir()
    for record in manifest["files"]:
        path = Path(record["path"])
        if path.is_absolute() or len(path.parts) != 1 or path.name in (".",".."):
            raise ValueError("only the fixed flat checkpoint is supported")
        source = root/path
        assert not source.is_symlink() and sha(source) == record["sha256"]
        shutil.copy2(source,checkpoint/path)
    shutil.copy2(args.executable,destination/"jeff.exe")
    shutil.copy2(args.verifier,destination/"verify.exe")
    policy = manifest["policy"]
    subprocess.run([str((destination/"jeff.exe").resolve()),"lock",str(checkpoint),str(destination/"bundle.json"),
        manifest["checkpoint_revision"],str(policy["min_probability"]),str(policy["min_margin"]),str(policy["cpu_threads"])],check=True)
    golden = json.loads(Path("tests/fixtures/jeff-golden/candidate-request.json").read_text(encoding="utf-8"))
    write(destination/"smoke-request.json",golden["request"])
    write(destination/"smoke-expected.json",{"input_tokens":golden["official"]["input_tokens"],
        "judgment":golden["official"]["judgment"],"scores":golden["worker_observation"]["scores"]})
    licenses = []
    issues = []
    audited = {(p["name"],p["version"]) for p in audit["packages"]}
    for package in sorted(metadata["packages"],key=lambda p:(p["name"],p["version"])):
        if (package["name"],package["version"]) not in audited:
            continue
        base = Path(package["manifest_path"]).parent
        def local_files(folder):
            return [p for p in folder.iterdir() if p.is_file() and p.name.upper().startswith(("LICENSE","COPYING","NOTICE"))]
        candidates = local_files(base)
        if package.get("license_file"):
            candidates += [base/package["license_file"]]
        if not candidates and package["source"] and package["source"].startswith("git+"):
            # Some workspace packages inherit the repository root's license files.
            for parent in list(base.parents)[:3]:
                candidates = local_files(parent)
                if candidates:
                    break
        copied = []
        supplement = supplements.get((package["name"],package["version"],package["source"]))
        if supplement:
            candidates += supplement["files"]
        for source in sorted(set(candidates)):
            target = destination/"licenses"/(package["name"]+"-"+package["version"])/source.name
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and sha(target) != sha(source):
                raise ValueError("conflicting license files for the same package")
            shutil.copy2(source,target)
            copied.append({"path":target.relative_to(destination).as_posix(),"sha256":sha(target)})
        entry = {"name":package["name"],"version":package["version"],"source":package["source"],
            "declared_license":package["license"],"files":copied}
        if supplement:
            entry["supplement_evidence"] = supplement["evidence"]
        licenses.append(entry)
        if not package["license"] or not copied:
            issues.append({"package":package["name"],"declared_license":package["license"],"local_license_files":len(copied)})
    write(destination/"licenses.json",{"schema_version":"kaze_judge.license_evidence.v1",
        "scope":"conservative locked build graph, includes build/dev dependencies; license text collection is not a completed distribution review",
        "packages":licenses,"issues":issues,"checkpoint_notice":"checkpoint/NOTICE","checkpoint_license":"checkpoint/LICENSE"})
    shutil.copy2(args.audit,destination/"dependency-audit.json")
    shutil.copy2(supplement_index,destination/"licenses/supplements.json")
    for reference in references["sources"]:
        target = destination/"licenses"/reference["file"]
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(reference_index.parent/reference["file"],target)
    shutil.copy2(reference_index,destination/"licenses/reference-sources.json")
    notice_lines = ["pure-jeff third-party attribution inventory (local prototype)",
        "", "This inventory preserves collected license/notice evidence; distribution review remains open.",
        "Dependency scope: conservative locked Windows build graph, including build/dev dependencies.",
        "Project license selection remains separate from third-party declarations.", "",
        f"Jeff checkpoint revision: {manifest['checkpoint_revision']}",
        "Model license: checkpoint/LICENSE; attribution/base-model notice: checkpoint/NOTICE.",
        "The fixed checkpoint files are copied without conversion or modification.", ""]
    for reference in references["sources"]:
        notice_lines += [f"{reference['name']} @ {reference['revision']} ({reference['declared_license']})",
            reference["source_license_url"],f"License: licenses/{reference['file']}",reference["scope"],""]
    for entry in licenses:
        notice_lines += [f"{entry['name']} {entry['version']} ({entry['declared_license'] or 'UNSPECIFIED'})",
            *[record["path"] for record in entry["files"]],""]
    (destination/"THIRD_PARTY_NOTICES.txt").write_text("\n".join(notice_lines)+"\n",encoding="utf-8")
    (destination/"README.txt").write_text(
        "pure-jeff fixed 0.8B Windows x86_64 CPU local prototype.\n"
        "Run verify.exe. Python, Cargo and PowerShell scripts are not needed.\n"
        "Requires Windows OS/CRT including VCRUNTIME140.dll. Model files must remain immutable during inference.\n"
        "Not release accepted: project license, third-party notices, quality, performance SLO and Python-free clean-host validation remain open.\n",
        encoding="utf-8")
    files = [{"path":p.relative_to(destination).as_posix(),"bytes":p.stat().st_size,"sha256":sha(p)}
             for p in sorted(destination.rglob("*")) if p.is_file()]
    write(destination/"package.json",{"schema_version":"kaze_judge.portable.v1","checked_on":"2026-10-10",
        "release_ready":False,"executable_sha256":sha(destination/"jeff.exe"),"source_manifest_sha256":sha(args.manifest),
        "builder_sha256":sha(Path(__file__)),"license_issues":issues,"files":files,
        "builder_helpers_sha256":{"license_supplements.py":sha(Path(__file__).resolve().parent/"license_supplements.py")},
        "license_supplements_sha256":sha(supplement_index),
        "reference_license_evidence_sha256":sha(reference_index),
        "payload_bytes":sum(f["bytes"] for f in files)})
    print(json.dumps({"destination":str(destination),"files":len(files),"payload_bytes":sum(f["bytes"] for f in files),
        "license_issues":issues,"release_ready":False}))


if __name__ == "__main__":
    main()
