"""Check the crates.io package of pure-jeff from the outside.

  python tools/check_package.py --work <new dir>                         # model-free
  python tools/check_package.py --work <new dir> --manifest models/x.json   # also the official goldens

1. `cargo package` (which also builds the packaged sources) and `cargo publish --dry-run`.
2. The packaged file list must be exactly the expected set: sources, the tensor spec, build
   script, README, license and notice files. No model, fixture or research file, and the
   .crate must stay small.
3. The .crate is unpacked and tools/consumer is built against it as a separate project with
   no [patch], so Candle and every other dependency come from crates.io exactly as for a user.
   The consumer runs model-free checks of the public API and, with --manifest, decides every
   official golden request and compares it with the official probabilities (<= 1e-4), judgment
   and token count. With --cases it also decides every benchmark catalog input and applies
   the common numeric gate of bench/validate.py (bench/check_outcomes.py).
4. With --msrv TOOLCHAIN (e.g. 1.88.0), the consumer is also checked with that toolchain.

Nothing is published. The work directory must not exist.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
NAME, VERSION = "pure-jeff", "0.2.0"
EXPECTED = {
    ".cargo_vcs_info.json", "Cargo.lock", "Cargo.toml", "Cargo.toml.orig", "LICENSE", "NOTICE",
    "README.crate.md", "THIRD_PARTY_NOTICES.md", "build.rs", "runtime/licenses/jeff-source/LICENSE",
    "spec/jeff-0.8b-tensors.json",
}
MAX_CRATE_BYTES = 512 * 1024


def run(command, **kwargs):
    print("$", " ".join(str(c) for c in command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="bundle manifest for the golden check")
    parser.add_argument("--cases", action="store_true", help="with --manifest: also gate every catalog input")
    parser.add_argument("--msrv", help="rustup toolchain to `cargo check` the consumer with, e.g. 1.88.0")
    parser.add_argument("--allow-dirty", action="store_true", help="package uncommitted changes (local trials)")
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    dirty = ["--allow-dirty"] if args.allow_dirty else []
    target = work / "package-target"
    listed = run(["cargo", "package", "--locked", "--list"] + dirty, cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout
    files = {line.strip().replace("\\", "/") for line in listed.splitlines() if line.strip()}
    sources = {f for f in files if f.startswith("src/") and f.endswith(".rs")}
    unexpected = files - EXPECTED - sources
    missing = EXPECTED - files
    print(f"{len(files)} packaged files ({len(sources)} sources)")
    if unexpected or missing or not {"src/lib.rs", "src/backbone.rs"} <= sources:
        raise SystemExit(f"unexpected package contents: extra {sorted(unexpected)}, missing {sorted(missing)}")
    run(["cargo", "package", "--locked", "--target-dir", str(target)] + dirty, cwd=ROOT)
    crate = target / "package" / f"{NAME}-{VERSION}.crate"
    size = crate.stat().st_size
    print(f"{crate.name}: {size} bytes")
    if size > MAX_CRATE_BYTES:
        raise SystemExit(f"{crate.name} is larger than {MAX_CRATE_BYTES} bytes")
    run(["cargo", "publish", "--dry-run", "--locked", "--target-dir", str(target)] + dirty, cwd=ROOT)
    with tarfile.open(crate) as archive:
        archive.extractall(work / "unpacked", filter="data")
    unpacked = work / "unpacked" / f"{NAME}-{VERSION}"
    consumer = work / "consumer"
    shutil.copytree(ROOT / "tools/consumer/src", consumer / "src")
    dependency = unpacked.as_posix()
    (consumer / "Cargo.toml").write_text(f"""[package]
name = "pure-jeff-consumer"
version = "0.0.0"
edition = "2021"
publish = false

[dependencies]
pure-jeff = {{ path = "{dependency}" }}
serde_json = "1"
""", encoding="utf-8")
    run(["cargo", "build", "--release"], cwd=consumer)
    tree = run(["cargo", "tree", "-e", "normal", "-i", "candle-core"], cwd=consumer, capture_output=True, text=True, encoding="utf-8").stdout
    if "git+" in tree or "candle-core v0.11.0" not in tree:
        raise SystemExit("the consumer must use candle-core 0.11.0 from crates.io")
    exe = consumer / "target/release" / ("pure-jeff-consumer" + (".exe" if sys.platform == "win32" else ""))
    command = [str(exe)]
    if args.manifest:
        command += [str(args.manifest.resolve()), str(ROOT / "tests/fixtures/jeff-golden")]
        if args.cases:
            cases, outcomes = work / "cases.json", work / "outcomes.jsonl"
            run([sys.executable, "-B", str(ROOT / "bench/export_cases.py"), str(cases)])
            command += [str(cases), str(outcomes)]
    run(command)
    if args.manifest and args.cases:
        run([sys.executable, "-B", str(ROOT / "bench/check_outcomes.py"), str(outcomes)])
    if args.msrv:
        run(["cargo", f"+{args.msrv}", "check", "--release"], cwd=consumer)
    print("package check passed")


if __name__ == "__main__":
    main()
