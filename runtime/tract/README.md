# Isolated Tract feasibility probe

This package is an experimental CLI, not a DecisionProvider or production worker.
It does not depend on the Native package or modify its dependency lock.
Tract is pinned to the official 0.23.8 commit, with transformer extensions disabled.

From the repository root, use a fresh Cargo home to avoid locally modified sources:

```powershell
$env:CARGO_HOME = Join-Path $PWD '.venv/tract-cargo-home'
cargo build --locked --release --manifest-path runtime/tract/Cargo.toml
cargo clippy --locked --manifest-path runtime/tract/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path runtime/tract/Cargo.toml -- --check
```

Use `runtime/onnx/run_probe.py` for recorded, deadline-bounded runs. Stages:

- `import`: load graph and external weights.
- `analyze`: infer the graph as declared; useful for small generic reproductions.
- `type`: require three named Jeff inputs and specialize their facts to i64 `[1,512]`.
- `optimize`: type and optimize.
- `run`: optimize, build a plan and execute once. Requires `--inputs` containing a
  JSON object with flat 512-element i64 arrays for `input_ids`, `attention_mask`,
  `mm_token_type_ids`. Returns finite raw f32 `[1,255]` logits, without policy or temperature.

Dynamic ONNX intermediate shape symbols must be specialized consistently before
`type`; simply replacing input facts does not bind every intermediate symbol.
The CLI itself has no deadline enforcement; always run it through a parent with a
hard timeout. The development Python harness kills and waits for a timed-out child.

See [current status](../../docs/onnx-tract-progress.md). Jeff whole-model typing
currently fails at Slice. No latency SLO or speedup is established.
