"""Build the resident benchmark wrapper against pure-jeff and Candle from crates.io, as a crate
user would, and lock a bundle for that build.

    python -B bench/build_cratesio_resident.py --work <new dir> [--version 0.2.0]

The new project takes `pure-jeff = "=VERSION"` and `candle-core = "=0.11.0"` from crates.io
(no [patch], no path dependency) and builds two binaries:
  resident_bench  runtime/rust/examples/resident_bench.rs, unchanged
  lock            pure_jeff::lock for this build (the API path requires a bundle locked by the
                  same build)
The bundle is written next to models/jeff-checkpoint as
models/pure-jeff-bundle-t1-cratesio-VERSION.json (an existing file is an error). The result
(paths, hashes, the resolved Candle version) is printed as JSON and saved in the work dir with
the generated Cargo.toml and Cargo.lock."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CANDLE = "0.11.0"
REVISION = "51552f39a943d62e8387c4ea5e17026a1408729f"
LOCK = """use std::{path::Path, time::{Duration, Instant}};
fn main() {
    let a: Vec<String> = std::env::args().collect();
    assert_eq!(a.len(), 7, "usage: lock checkpoint manifest revision min-probability min-margin threads");
    let policy = pure_jeff::Policy {
        min_probability: a[4].parse().unwrap(),
        min_margin: a[5].parse().unwrap(),
        cpu_threads: a[6].parse().unwrap(),
    };
    let sha = pure_jeff::lock(Path::new(&a[1]), Path::new(&a[2]), &a[3], policy,
                              Instant::now() + Duration::from_secs(600)).unwrap();
    println!("{sha}");
}
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, **kwargs):
    print("$", " ".join(str(c) for c in command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--version", default="0.2.0", help="pure-jeff version on crates.io")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "models/jeff-checkpoint")
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    (work / "src/bin").mkdir(parents=True)
    shutil.copyfile(ROOT / "runtime/rust/examples/resident_bench.rs", work / "src/bin/resident_bench.rs")
    (work / "src/bin/lock.rs").write_text(LOCK, encoding="utf-8")
    (work / "Cargo.toml").write_text(f"""[package]
name = "pure-jeff-cratesio-bench"
version = "0.0.0"
edition = "2021"
publish = false

[dependencies]
pure-jeff = "={args.version}"
candle-core = {{ version = "={CANDLE}", default-features = false }}
anyhow = "1"
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
""", encoding="utf-8")
    run(["cargo", "build", "--release"], cwd=work)
    tree = run(["cargo", "tree", "-e", "normal", "-i", "candle-core"], cwd=work, capture_output=True, text=True,
               encoding="utf-8").stdout
    if "git+" in tree or f"candle-core v{CANDLE}" not in tree:
        raise SystemExit(f"candle-core must be {CANDLE} from crates.io:\n{tree}")
    lock = (work / "Cargo.lock").read_text(encoding="utf-8")
    if f'name = "pure-jeff"\nversion = "{args.version}"\nsource = "registry+' not in lock.replace("\r", ""):
        raise SystemExit("pure-jeff must come from crates.io")
    exe = work / "target/release" / f"resident_bench{'.exe' if sys.platform == 'win32' else ''}"
    locker = work / "target/release" / f"lock{'.exe' if sys.platform == 'win32' else ''}"
    bundle = args.checkpoint.resolve().parent / f"pure-jeff-bundle-t1-cratesio-{args.version}.json"
    if bundle.exists():
        raise SystemExit(f"{bundle} exists")
    manifest_sha = run([str(locker), str(args.checkpoint.resolve()), str(bundle), REVISION, "0.7", "0.1", "1"],
                       capture_output=True, text=True).stdout.strip()
    result = {"pure_jeff": args.version, "candle_core": CANDLE, "source": "crates.io",
              "resident_exe": str(exe), "resident_exe_sha256": sha(exe),
              "resident_source_sha256": sha(work / "src/bin/resident_bench.rs"),
              "bundle": str(bundle), "bundle_sha256": manifest_sha,
              "cargo_toml_sha256": sha(work / "Cargo.toml"), "cargo_lock_sha256": sha(work / "Cargo.lock"),
              "candle_tree": tree.strip().splitlines()[0]}
    (work / "build.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
