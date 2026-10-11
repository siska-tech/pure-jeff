"""Verify the ONNX/Tract files migrated from KazeJudge against their recorded hashes.

  python tools/verify_tract_migration.py                       # migration commit vs the record
  python tools/verify_tract_migration.py --source ../KazeJudge # also re-derive from the source repo
  python tools/verify_tract_migration.py --source ../KazeJudge --write   # (re)create the record

The files are checked as they were in the migration merge commit, so later edits in pure-jeff do
not invalidate the record; the files changed since then are listed for information.

The migration replaced the user name in local absolute paths by <user> (see REDACTION; the name is
not stored here: --user-name, default the USERNAME/USER environment variable). With --source, every
recorded source blob is read from the source commit, its SHA-256 is checked, the same redaction is
applied and the result must equal the migrated bytes. Only the standard library and git are used;
the source repository is only read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/tract-migration-provenance.json"
SOURCE_COMMIT = "ad59b257d6c029dc1354f16925ecbfe3823fc979"
MIGRATION_COMMIT = "be56eccd2bb44c6f55f468a569cba54c973a5f71"  # "Merge the ONNX/Tract history from KazeJudge"
INCLUDE = ["runtime/onnx/", "runtime/tract/", "runtime/tract-driver-profile/", "runtime/bench-native/",
           "runtime/native-retained/", "docs/research/jeff-onnx-tract/", ".github/workflows/tract-probe.yml"]
INCLUDE_GLOB = re.compile(r"^docs/onnx-tract-[^/]*\.md$")
EXCLUDE = ["docs/onnx-tract-kzn-ocr-intake.md", "runtime/onnx/audit_kzn_ocr_intake.py",
           "runtime/onnx/prepare_kzn_ocr_intake.py", "runtime/onnx/test_kzn_ocr_intake.py",
           "docs/research/jeff-onnx-tract/kzn-ocr-intake-2026-10-11/"]
# The expression given to git filter-repo --replace-text (applied to every blob in the history),
# with {name} the user name.
REDACTION = r"(?i)(Users(?:\\|/)+|Users-){name}(?![A-Za-z])"


def redactor(name):
    pattern = re.compile(REDACTION.format(name=re.escape(name)).encode())
    return lambda data: pattern.sub(rb"\1<user>", data)


def selected(path):
    if any(path == e or (e.endswith("/") and path.startswith(e)) for e in EXCLUDE):
        return False
    return any(path == i or (i.endswith("/") and path.startswith(i)) for i in INCLUDE) or bool(
        INCLUDE_GLOB.match(path))


def blobs(repo, commit):
    """path -> bytes for the selected files of a commit."""
    entries = []
    tree = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", commit], check=True,
                          capture_output=True).stdout
    for line in tree.split(b"\0"):
        if line:
            meta, path = line.split(b"\t", 1)
            path = path.decode("utf-8")
            if selected(path):
                entries.append((path, meta.split()[2].decode()))
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], check=True, capture_output=True,
                         input="".join(f"{oid}\n" for _, oid in entries).encode()).stdout
    result, pos = {}, 0
    for path, _ in entries:
        header_end = out.index(b"\n", pos)
        size = int(out[pos:header_end].split()[2])
        result[path] = out[header_end + 1:header_end + 1 + size]
        pos = header_end + 1 + size + 1
    return result


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="a KazeJudge checkout containing the source commit")
    parser.add_argument("--write", action="store_true", help="write the record (requires --source)")
    parser.add_argument("--user-name", default=os.environ.get("USERNAME") or os.environ.get("USER"),
                        help="the redacted user name (needed with --source)")
    args = parser.parse_args()
    if args.write and not args.source:
        parser.error("--write requires --source")
    if args.source and not args.user_name:
        parser.error("--source requires --user-name")
    redact = redactor(args.user_name) if args.source else None
    source = blobs(args.source, SOURCE_COMMIT) if args.source else None
    migrated = blobs(ROOT, MIGRATION_COMMIT)
    failures = []
    if args.write:
        files = []
        for path, data in sorted(source.items()):
            after = migrated.get(path, b"")
            files.append({"path": path, "bytes": len(after), "sha256": sha256(after),
                          **({"source_bytes": len(data), "source_sha256": sha256(data)} if data != after else {})})
        record = {
            "schema_version": "pure_jeff.tract_migration.v1",
            "source_repository": "KazeJudge (local)",
            "source_commit": SOURCE_COMMIT,
            "migration_commit": MIGRATION_COMMIT,
            "method": "git filter-repo on a separate clone: --paths-from-file (include), --invert-paths (exclude), "
                      "--replace-text with the redaction; merged with --allow-unrelated-histories",
            "redaction": {"pattern": REDACTION, "replacement": r"\1<user>", "name": "not recorded"},
            "include": INCLUDE + ["docs/onnx-tract-*.md"],
            "exclude": EXCLUDE,
            "files": len(files),
            "redacted_files": sum("source_sha256" in f for f in files),
            "entries": files,
        }
        RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    paths = {e["path"] for e in record["entries"]}
    if set(migrated) != paths:
        failures.append("the migrated file set differs from the record")
    if source is not None and set(source) != paths:
        failures.append("the selected source file set differs from the record")
    changed = []
    for entry in record["entries"]:
        path = entry["path"]
        if path not in migrated or sha256(migrated[path]) != entry["sha256"]:
            failures.append(f"{path}: migration commit differs from the record")
        current = ROOT / path
        if not current.is_file() or sha256(current.read_bytes()) != entry["sha256"]:
            changed.append(path)
        if source is not None:
            data = source.get(path)
            if data is None or sha256(data) != entry.get("source_sha256", entry["sha256"]):
                failures.append(f"{path}: source blob differs from the record")
            elif sha256(redact(data)) != entry["sha256"]:
                failures.append(f"{path}: redacted source differs from the migrated file")
    print(f"{record['files']} files, {record['redacted_files']} redacted, source {record['source_commit'][:7]}"
          f"{' (re-derived)' if source is not None else ''}: {len(failures)} failure(s)")
    for failure in failures[:20]:
        print(f"  {failure}")
    print(f"{len(changed)} file(s) changed or removed in the working tree since the migration")
    for path in changed:
        print(f"  {path}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
