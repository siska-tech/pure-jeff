"""Audit the licenses of every Cargo dependency per crate and target, and optionally write the
third-party notice text for a shipped binary.

  python tools/audit_licenses.py --output docs/license-audit.json
  python tools/audit_licenses.py --notices out/THIRD_PARTY_LICENSES.txt --crate engine --target wasm32-unknown-unknown

Only normal (non-dev, non-build) dependencies reachable from a crate are shipped in its binary;
build dependencies are listed separately. Nothing is downloaded: run `cargo fetch` first.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CRATES = {  # name -> (manifest, targets that are shipped)
    "core": ("Cargo.toml", ["x86_64-pc-windows-msvc"]),
    "native": ("runtime/rust/Cargo.toml", ["x86_64-pc-windows-msvc"]),
    "probe": ("runtime/wasm/Cargo.toml", ["wasm32-unknown-unknown", "x86_64-pc-windows-msvc"]),
    "engine": ("apps/web-demo/engine/Cargo.toml", ["wasm32-unknown-unknown", "x86_64-pc-windows-msvc"]),
}
OWN = {"kaze_judge", "kaze_judge_jeff", "kaze_judge_wasm_probe", "kaze_judge_web_demo"}
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "Unicode-3.0",
              "Unicode-DFS-2016", "BSL-1.0", "CC0-1.0", "Unlicense", "Apache-2.0 WITH LLVM-exception", "0BSD"}
TEXT_NAMES = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|UNLICENSE)([-_.].*)?$", re.IGNORECASE)
SUPPLEMENTS = ROOT / "runtime/licenses/supplements.json"


def metadata(manifest, target):
    out = subprocess.run(["cargo", "metadata", "--format-version", "1", "--locked", "--offline",
                          "--manifest-path", str(ROOT / manifest), "--filter-platform", target],
                         check=True, capture_output=True, text=True, encoding="utf-8").stdout
    return json.loads(out)


def reachable(meta, kinds):
    """Package ids reachable from the root through dependency edges of the given kinds."""
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    root = meta["resolve"]["root"]
    seen, pending = set(), [root]
    while pending:
        node = nodes[pending.pop()]
        for dep in node["deps"]:
            if any(k["kind"] in kinds for k in dep["dep_kinds"]) and dep["pkg"] not in seen:
                seen.add(dep["pkg"])
                pending.append(dep["pkg"])
    return seen


def alternatives(expression):
    """Satisfiable license sets of an SPDX expression (only AND / OR / parentheses / WITH)."""
    expression = (expression or "").replace("/", " OR ")
    groups = [part.strip(" ()") for part in re.split(r"\s+OR\s+", expression) if part.strip()]
    return [[t.strip(" ()") for t in re.split(r"\s+AND\s+", g)] for g in groups]


def classify(expression):
    if not expression:
        return "undeclared"
    for option in alternatives(expression):
        if all(term in PERMISSIVE for term in option):
            return "permissive"
    return "review"


def texts(package):
    folder = Path(package["manifest_path"]).parent
    found = sorted(p for p in folder.iterdir() if p.is_file() and TEXT_NAMES.match(p.name))
    if package.get("license_file"):
        named = folder / package["license_file"]
        if named.is_file() and named not in found:
            found.append(named)
    # A crate from a git workspace (e.g. Candle) may keep its texts at the repository root.
    if not found and (package.get("source") or "").startswith("git+"):
        for parent in folder.parents:
            found = sorted(p for p in parent.iterdir() if p.is_file() and TEXT_NAMES.match(p.name))
            workspace = parent / "Cargo.toml"
            is_root = (parent / ".git").exists() or (
                workspace.is_file() and "[workspace]" in workspace.read_text(encoding="utf-8"))
            if found or is_root:
                break
    return found


def supplements():
    if not SUPPLEMENTS.exists():
        return {}
    index = json.loads(SUPPLEMENTS.read_text(encoding="utf-8"))
    return {(p["name"], p["version"]): [ROOT / "runtime/licenses" / f["path"] for f in p["files"]]
            for p in index["packages"]}


def audit():
    extra = supplements()
    report = {"schema_version": "pure_jeff.license_audit.v1", "crates": {}, "packages": {}}
    for crate, (manifest, targets) in CRATES.items():
        report["crates"][crate] = {"manifest": manifest, "targets": {}}
        for target in targets:
            meta = metadata(manifest, target)
            packages = {p["id"]: p for p in meta["packages"]}
            shipped = reachable(meta, {None})
            build = reachable(meta, {None, "build"}) - shipped
            report["crates"][crate]["targets"][target] = {
                "shipped": sorted(f"{packages[i]['name']} {packages[i]['version']}" for i in shipped),
                "build_only": sorted(f"{packages[i]['name']} {packages[i]['version']}" for i in build)}
            for pid in shipped | build:
                p = packages[pid]
                key = f"{p['name']} {p['version']}"
                if key in report["packages"]:
                    continue
                files = texts(p) or extra.get((p["name"], p["version"]), [])
                report["packages"][key] = {
                    "license": p.get("license"), "class": "own" if p["name"] in OWN else classify(p.get("license")),
                    "repository": p.get("repository"), "source": (p.get("source") or "path").split("#")[0],
                    "license_texts": [str(f.relative_to(f.parents[1])).replace("\\", "/") for f in files],
                    "text_from_supplement": not texts(p) and bool(files)}
    findings = {
        "own_crates_without_license": sorted(k for k, v in report["packages"].items() if v["class"] == "own"),
        "undeclared": sorted(k for k, v in report["packages"].items() if v["class"] == "undeclared"),
        "needs_review": sorted(f"{k}: {v['license']}" for k, v in report["packages"].items() if v["class"] == "review"),
        "missing_license_text": sorted(k for k, v in report["packages"].items()
                                       if v["class"] != "own" and not v["license_texts"]),
    }
    report["findings"] = findings
    report["license_counts"] = {}
    for v in report["packages"].values():
        report["license_counts"][v["license"] or "(none)"] = report["license_counts"].get(v["license"] or "(none)", 0) + 1
    return report


def notices(crate, target, path):
    manifest, _ = CRATES[crate]
    meta = metadata(manifest, target)
    packages = {p["id"]: p for p in meta["packages"]}
    extra = supplements()
    chunks = [f"Third-party licenses for the {crate} crate ({target}).\n"
              "Generated by tools/audit_licenses.py from Cargo.lock; one entry per shipped dependency.\n"]
    missing = []
    for pid in sorted(reachable(meta, {None}), key=lambda i: (packages[i]["name"], packages[i]["version"])):
        p = packages[pid]
        if p["name"] in OWN:
            continue
        files = texts(p) or extra.get((p["name"], p["version"]), [])
        chunks.append("=" * 78 + f"\n{p['name']} {p['version']}\nLicense: {p.get('license')}\n"
                      f"Repository: {p.get('repository') or '-'}\n")
        if not files:
            missing.append(f"{p['name']} {p['version']}")
        for f in files:
            chunks.append(f"--- {f.name} ---\n" + f.read_text(encoding="utf-8", errors="replace").rstrip() + "\n")
    if missing:
        raise SystemExit(f"no license text for: {missing}")
    Path(path).write_text("\n".join(chunks), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--notices", type=Path)
    parser.add_argument("--crate", choices=sorted(CRATES))
    parser.add_argument("--target")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on undeclared, unreviewed or text-less dependency licenses")
    args = parser.parse_args()
    if args.notices:
        notices(args.crate, args.target, args.notices)
        return
    report = audit()
    text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"packages": len(report["packages"]), "findings": report["findings"],
                      "license_counts": report["license_counts"]}, ensure_ascii=False, indent=1))
    # Our own crates have no license until the owner decides one; that is reported, not failed here.
    problems = {k: v for k, v in report["findings"].items() if k != "own_crates_without_license" and v}
    if args.strict and problems:
        raise SystemExit(f"license audit failed: {problems}")


if __name__ == "__main__":
    main()
