# Wasm feasibility probe

Development-only browser feasibility probe ([plan](../../docs/wasm-demo-feasibility-plan.md), [W0 results](../../docs/wasm-w0-results.md), [W1 results](../../docs/wasm-w1-results.md)). It is not a DecisionProvider and not a public worker protocol.

The drivers default to `models/jeff-rust-bundle.json`. The W0-W2 evidence was recorded with the KazeJudge-era versions of these drivers and pages (default manifest `jeff-rust-bundle-p3.json`, KazeJudge page titles); their hashes in the evidence correspond to those versions ([commit map](../../docs/commit-map.md)).

`build.rs` checks the SHA-256 of the frozen Native `backbone.rs`, `prompt.rs`, `readout.rs` and `policy.rs`; a changed frozen source fails the build. W0 includes the backbone byte-for-byte. W1 (`decide`) uses generated copies of the backbone and readout whose only change is reading weights from a byte slice (`SliceSafetensors`) instead of a memory map; every substitution must match exactly once. The wasm module uses a raw C ABI (no wasm-bindgen) and imports only `env.kj_random_fill`, `env.kj_now_ms` and `env.kj_panic`. `getrandom` 0.3 uses its custom backend, fed by `crypto.getRandomValues`.

```powershell
# Native reference and tests (1 thread is enforced by the driver at run time).
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/wasm-target'
cargo test --locked --offline --release --manifest-path runtime/wasm/Cargo.toml
cargo clippy --locked --offline --release --manifest-path runtime/wasm/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path runtime/wasm/Cargo.toml -- --check
cargo build --locked --offline --release --manifest-path runtime/wasm/Cargo.toml

# Browser modules: baseline and SIMD128, in separate target directories.
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/wasm-target-baseline'
$env:RUSTFLAGS = '--cfg getrandom_backend="custom"'
cargo build --locked --offline --release --lib --target wasm32-unknown-unknown --manifest-path runtime/wasm/Cargo.toml
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/wasm-target-simd128'
$env:RUSTFLAGS = '--cfg getrandom_backend="custom" -C target-feature=+simd128'
cargo build --locked --offline --release --lib --target wasm32-unknown-unknown --manifest-path runtime/wasm/Cargo.toml
Remove-Item Env:RUSTFLAGS

# Run in a fresh headless profile; the output directory must not exist.
python -B runtime/wasm/run_w0.py `
  --browser "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --reference .venv/wasm-target/release/w0_reference.exe `
  --variant "baseline=.venv/wasm-target-baseline/wasm32-unknown-unknown/release/kaze_judge_wasm_probe.wasm" `
  --variant "simd128=.venv/wasm-target-simd128/wasm32-unknown-unknown/release/kaze_judge_wasm_probe.wasm" `
  --output experiments/runs/wasm-w0-repeat

# W1: one real-model decision (run A), a Worker terminated mid-forward (B) and a fresh rerun (C).
# Run from runtime/wasm so run_w1.py can import run_w0.py.
Push-Location runtime/wasm
python -B run_w1.py `
  --browser "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --reference ../../.venv/wasm-target/release/w1_reference.exe `
  --wasm ../../.venv/wasm-target-simd128/wasm32-unknown-unknown/release/kaze_judge_wasm_probe.wasm `
  --heap-reserve-bytes 805306368 --output ../../experiments/runs/wasm-w1-repeat
python -B -m unittest test_run_w0 test_run_w1 test_run_w2 -v
Pop-Location

# W2: one resident session over 12 cases (128-512 tokens, 2-8 candidates), two passes,
# invalid requests, corrupted assets, a mid-forward cancel and a page reload.
# --official holds official Jeff references exported with runtime/export_jeff_reference.py
# (copies in docs/research/wasm-demo/w2-2026-10-11/official-references/).
Push-Location runtime/wasm
python -B run_w2.py `
  --browser "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --reference ../../.venv/wasm-target/release/w2_reference.exe `
  --wasm ../../.venv/wasm-target-simd128/wasm32-unknown-unknown/release/kaze_judge_wasm_probe.wasm `
  --official ../../docs/research/wasm-demo/w2-2026-10-11/official-references `
  --output ../../experiments/runs/wasm-w2-repeat
Pop-Location
```

W2 uses `kj_session_open` / `kj_session_decide`: assets are verified once and stay in page-owned linear memory, so each decision runs only prompt, forward, readout and policy.

W1 streams the 1.7 GB `model.safetensors` from disk into linear memory and needs several GB of free RAM; the browser's busiest process peaked near 3.7 GiB working set. `--heap-reserve-bytes` grows linear memory once after loading assets; without it, tokenizer setup took ~30 s because the allocator grew a large memory in small steps.

The driver serves only the page, Worker, wasm variants, tokenizer and job on 127.0.0.1, writes `preregistration.json` before running, and exits non-zero unless every variant passes. Thresholds are fixed in `run_w0.py`; the first run under v1 thresholds stays recorded as failed.
