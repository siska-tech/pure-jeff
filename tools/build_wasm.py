"""Build the Wasm probe or the web demo engine reproducibly.

Panic messages embed source paths, so a plain build's bytes depend on where the repository,
CARGO_HOME (registry and git checkouts) and the target directory (build-script output that is
included) live. This remaps those prefixes to fixed names, so the same commit and toolchain
give the same .wasm on any machine path.

  python tools/build_wasm.py engine --target-dir .venv/demo-target-wasm
  python tools/build_wasm.py probe --target-dir .venv/wasm-target-simd128
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SEPARATOR = "\x1f"  # CARGO_ENCODED_RUSTFLAGS field separator
CRATES = {"probe": ("runtime/wasm/Cargo.toml", "kaze_judge_wasm_probe"),
          "engine": ("apps/web-demo/engine/Cargo.toml", "kaze_judge_web_demo")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("crate", choices=sorted(CRATES))
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    manifest, name = CRATES[args.crate]
    target = args.target_dir.resolve()
    cargo_home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo").resolve()
    remaps = [(ROOT, "/pure-jeff"), (cargo_home, "/cargo"), (target, "/target")]
    flags = ["--cfg", 'getrandom_backend="custom"', "-C", "target-feature=+simd128"]
    flags += [f"--remap-path-prefix={path}={mapped}" for path, mapped in remaps]
    # One flag per field, so paths with spaces survive; RUSTFLAGS would be split on spaces.
    env = {k: v for k, v in os.environ.items() if k != "RUSTFLAGS"}
    env |= {"CARGO_ENCODED_RUSTFLAGS": SEPARATOR.join(flags), "CARGO_TARGET_DIR": str(target)}
    command = ["cargo", "build", "--locked", "--release", "--lib", "--target", "wasm32-unknown-unknown",
               "--manifest-path", str(ROOT / manifest)] + (["--offline"] if args.offline else [])
    subprocess.run(command, check=True, env=env)
    output = target / "wasm32-unknown-unknown/release" / f"{name}.wasm"
    print(f"{output}\nsha256 {hashlib.sha256(output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
