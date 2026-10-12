#!/bin/bash
# Clean-environment check: clone the repository into WORKDIR, build and test with a fresh
# CARGO_HOME, download the pinned model from Hugging Face and compare the Native runtime with
# the six official golden references. Needs git, Rust 1.99.0 with the wasm32-unknown-unknown
# target, Python 3.12+ (standard library only) and about 4 GB of disk plus a 1.73 GB download.
#
#   bash tools/clean_check.sh <repository-or-url> <workdir> [python]
set -u
REPO=${1:?repository path or URL}
WORK=${2:?empty work directory}
PY=${3:-python}
if [ -e "$WORK" ]; then echo "work directory must not exist: $WORK" >&2; exit 2; fi
mkdir -p "$WORK"
export CARGO_HOME="$WORK/cargo-home"
git clone -q "$REPO" "$WORK/repo" && cd "$WORK/repo" || exit 1
echo "commit $(git rev-parse HEAD)"
failed=0
step() {
  local name=$1; shift
  local out code
  out=$("$@" 2>&1); code=$?
  echo "== $name exit=$code"
  echo "$out" | grep -E "^test result|FAILED|panicked|^error" | sed 's/^/   /'
  [ "$code" -eq 0 ] || failed=1
}
step "fetch model" "$PY" -B tools/fetch_model.py
export PURE_JEFF_PYTHON
PURE_JEFF_PYTHON=$(command -v "$PY")
export CARGO_TARGET_DIR="$WORK/target-native"
step "contract test" cargo test --locked --all-features
step "native test" cargo test --locked --release --manifest-path runtime/rust/Cargo.toml
step "native build" cargo build --locked --release --manifest-path runtime/rust/Cargo.toml
export CARGO_TARGET_DIR="$WORK/target-probe"
step "probe test" cargo test --locked --release --manifest-path runtime/wasm/Cargo.toml
export CARGO_TARGET_DIR="$WORK/target-engine"
step "engine test" cargo test --locked --release --manifest-path apps/web-demo/engine/Cargo.toml
export CARGO_TARGET_DIR="$WORK/target-wasm" RUSTFLAGS='--cfg getrandom_backend="custom" -C target-feature=+simd128'
step "probe wasm" cargo build --locked --release --lib --target wasm32-unknown-unknown --manifest-path runtime/wasm/Cargo.toml
step "engine wasm" cargo build --locked --release --lib --target wasm32-unknown-unknown --manifest-path apps/web-demo/engine/Cargo.toml
unset RUSTFLAGS
JEFF="$WORK/target-native/release/jeff"
[ -x "$JEFF.exe" ] && JEFF="$JEFF.exe"
step "lock bundle" "$JEFF" lock models/jeff-checkpoint models/jeff-rust-bundle.json 51552f39a943d62e8387c4ea5e17026a1408729f 0.7 0.1 1
mkdir -p experiments/runs
echo "== golden validation"
"$PY" -B runtime/validate_migration_cases.py --executable "$JEFF" --manifest models/jeff-rust-bundle.json \
  --output experiments/runs/golden.json || failed=1
step "python tests" "$PY" -B -m unittest discover -s runtime -p "test_*.py"
echo "failed=$failed"
exit $failed
