# Isolated Tract feasibility probe

This package is an experimental CLI, not a DecisionProvider or production worker.
It does not depend on the Native package or modify its dependency lock.
Tract is pinned to the official 0.23.8 commit, with transformer extensions disabled.
The data crate has a local I64-to-TDim fix; see [patch attribution](vendor/NOTICE.md).
This is a patched Tract experiment, not a result for unmodified upstream Tract.

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
- `run-typed`: build and execute the typed graph without optimization. The input
  and output contract is the same as `run`. This isolates optimizer failures.
- `run-no-change-axes`: explicitly remove exactly one top-level `ChangeAxes` pass from the
  pinned declutter pipeline, then run the remaining declutter and codegen passes.
  It checks the pinned pass layout and fails if selection is ambiguous. This is
  an experimental alternative, never an automatic fallback from `run`.

Dynamic ONNX intermediate shape symbols must be specialized consistently before
`type`; simply replacing input facts does not bind every intermediate symbol.
The CLI itself has no deadline enforcement; always run it through a parent with a
hard timeout. The development Python harness kills and waits for a timed-out child.

See [current status](../../docs/onnx-tract-progress.md). Patched Jeff whole-model
typing and execution without optimization work; standard ChangeAxes optimization
still fails through a CumSum Scan body. The separate explicit pass selection
passes the four whole-model correctness cases. No latency SLO or speedup is established.

`src/bin/bench.rs` builds the separate `bench.exe` diagnostic. It retains a runnable
plan, explicitly selects a single-thread executor and emits JSONL stage durations
for initial load/type/optimization/plan and per-request input preparation,
head-inclusive forward and FP32 scoring. Each `plan.run` creates fresh execution
state. Jobs can select `typed` or `no-change-axes`; the Windows pilot uses the
numerically accepted latter mode. This diagnostic accepts already tokenized input
and is not a DecisionProvider E2E measurement. Its scores are checked against the
frozen goldens by the parent harness.
