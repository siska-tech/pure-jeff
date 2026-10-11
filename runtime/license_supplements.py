"""Validate reviewed license supplements against the exact local dependency source."""
import hashlib
import json
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("license evidence path escapes its root")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("license evidence must be a contained file")
    return path


def load_supplements(index_path, packages):
    index_path = Path(index_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index["schema_version"] != "kaze_judge.license_supplements.v1":
        raise ValueError("unsupported license supplement schema")
    known = {(p["name"], p["version"], p["source"]): p for p in packages}
    result = {}
    for entry in index["packages"]:
        key = (entry["name"], entry["version"], entry["source"])
        if key not in known or key in result or entry["declared_license"] != known[key]["license"]:
            raise ValueError("supplement dependency identity does not match")
        base = Path(known[key]["manifest_path"]).parent
        for name, expected in entry["package_files"].items():
            if sha(contained_file(base, name)) != expected:
                raise ValueError("supplement dependency source hash does not match")
        vcs = json.loads((base / ".cargo_vcs_info.json").read_text(encoding="utf-8"))
        if vcs["git"]["sha1"] != entry["vcs_revision"]:
            raise ValueError("supplement dependency revision does not match")
        files = []
        for record in entry["files"]:
            path = contained_file(index_path.parent, record["path"])
            if sha(path) != record["sha256"]:
                raise ValueError("supplement license hash does not match")
            files.append(path)
        if not files:
            raise ValueError("supplement must contain license text")
        result[key] = {"files": files, "evidence": entry}
    return result
