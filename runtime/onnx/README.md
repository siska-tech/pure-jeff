# Development-only ONNX tooling

These tools do not form part of the Rust worker or its deployment dependencies.
Run from the repository root on Windows. Do not install into the frozen vendor venv.

```powershell
uv --cache-dir .venv/onnx-cache pip install --python vendor/jeff/.venv/Scripts/python.exe --target .venv/onnx-tools --require-hashes --only-binary :all: -r runtime/onnx/requirements.lock
$env:PYTHONPATH = (Resolve-Path .venv/onnx-tools).Path
$env:TRACT_PROBE = (Resolve-Path runtime/tract/target/release/kaze_judge_tract_probe.exe).Path
& vendor/jeff/.venv/Scripts/python.exe -B -m unittest discover -s runtime/onnx -p 'test_*.py' -v
```

`requirements.in` is the input to `uv pip compile --generate-hashes`; the lock is
the resolved environment, not a request to update versions during verification.
Clear `PYTHONPATH` after using these tools in an interactive shell.

All output paths below must be new. Historical assets/reports must be retained.

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/check_padding.py --manifest models/jeff-bundle.json --output experiments/runs/padding-new.json
& vendor/jeff/.venv/Scripts/python.exe -X utf8 -B runtime/onnx/export_current.py --manifest models/jeff-bundle.json --padding-gate experiments/runs/padding-new.json --output-dir experiments/runs/onnx-new --export
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/check_oracle.py --model experiments/runs/onnx-new/model.onnx --manifest models/jeff-bundle.json --padding-gate experiments/runs/padding-new.json --output experiments/runs/oracle-new.json
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/normalize_sequences.py experiments/runs/onnx-new/model.onnx experiments/runs/onnx-new/model.normalized.onnx --report experiments/runs/onnx-new/normalization.json
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/run_probe.py --executable runtime/tract/target/release/kaze_judge_tract_probe.exe --model experiments/runs/onnx-new/model.normalized.onnx --stage type --timeout 180 --output experiments/runs/onnx-new/tract-type.json
```

`check_oracle.py` validates the original export asset hashes. It does not silently
replace the model with a normalized graph. Use `--normalized-model` together with
`--baseline-oracle` for the separate normalized/original parity gate.
`check_tract.py` runs four golden cases through deadline-bounded `run-typed`
processes and compares probabilities and judgments with that passing oracle.
It requires `--model`, `--oracle`, `--manifest`, `--padding-gate`, `--executable`
and a new `--output-dir`. It is a correctness gate, not a performance benchmark.
Its optional `--stage` selects `run-typed` (default), standard `run`, or the
explicit experimental `run-no-change-axes` pipeline. Results record that choice.
`specialize_batch.py` is only needed for the public
dynamic-batch graph; it binds known `batch` expressions and retains other facts.

`normalize_sequences.py` supports top-level opset-18 SplitToSequence with known
axis extent, positive constant scalar/vector splits, keepdims=1 and exclusively
constant SequenceAt consumers. Unsupported cases are rejected. It changes only
graph structure, retaining the relative external weight references. Source and
output must be in the same directory. A failed checker is recorded and returns
nonzero; the graph file alone does not constitute a passing transformation.

`audit_probe.py` records dependencies, source license text hashes, build scripts
and PE imports. Use the same isolated Cargo home as the build. It does not approve
redistribution. Upstream exporter attribution is in [upstream/NOTICE.md](upstream/NOTICE.md).
The [progress report](../../docs/onnx-tract-progress.md) identifies passed and pending gates.

## Windows performance pilot

Build the isolated Tract `bench` binary and [Native diagnostic wrapper](../bench-native/README.md)
before measuring. Run all builds and tests outside the timing experiment:

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/benchmark_pilot.py --output-dir experiments/runs/pilot-new --native-executable .venv/bench-native-target/release/kaze_judge_native_bench.exe --tract-executable runtime/tract/target/release/bench.exe --manifest models/jeff-rust-bundle-p3.json --model experiments/runs/onnx-current-step1113-v2/model.normalized.onnx --repeats 5
```

The harness pre-registers the fixed input/seed/order, runs backends sequentially,
verifies checkpoint and golden hashes, measures process-cold startup five times
on candidate-request, and runs five warmups plus four input cases five times each
in one resident session per backend. Raw JSONL, OS process-lifetime peaks, guards,
per-case quantiles and numerical validation are retained. No build, export or other
benchmark should run concurrently. Storage cache is uncontrolled; this is a pilot,
not a production Tract worker E2E or statistical SLO acceptance.

## Forward operator / thread pilot

The optional experiment enables `tract-linalg/multithread-mm` on the accepted
duplicate-removal base, with a separate dependency lock and Cargo target. It
keeps the normal probe and Native runtime unchanged. The executor accepts only
1/2/4/8 threads and reports the actual pool size and parallelism thresholds.
`forward_profile.rs` uses the public top-level eval callback; Scan child work is
included in its parent wall time. Profiling defaults to disabled.

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/prepare_forward_experiment.py --upstream .venv/tract-cargo-home/git/checkouts/tract-3c391e7e500bc645/9e0cfaa --output .venv/forward-new
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/forward-new-target'
cargo build --locked --release --manifest-path .venv/forward-new/Cargo.toml --bin bench
$env:TRACT_FORWARD_BENCH = Join-Path $PWD '.venv/forward-new-target/release/bench.exe'
& vendor/jeff/.venv/Scripts/python.exe -B -m unittest discover -s runtime/onnx -p test_tract_forward.py -v
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/benchmark_forward.py --candidate $env:TRACT_FORWARD_BENCH --generation .venv/forward-new/generation.json --output experiments/runs/forward-new
```

Set the isolated `CARGO_HOME` as for previous generators. Each output/target must
be new; do not share a target between generated source trees. The real-model
harness also requires the frozen accepted duplicate-removal control executable,
the archived control hash, four golden jobs and the fixed NNEF artifact from
earlier pilots. It runs the old feature-off control and all four new executor
sizes through all goldens before timing. The matrix is a small pilot: two
independent sessions per thread in ascending/reversed order, each one warmup
and three measured candidate-request forwards (n=6). The separate profile
session has one warmup and three measurements. No builds/tests run concurrently
with the measured child. Raw outputs, guards and process-lifetime peaks are
retained. New dependency attribution is in
[NOTICE.md](../tract-driver-profile/NOTICE.md). This does not establish API E2E,
Native equivalence of physical shape, recognition quality or a formal SLO.

`profile_thread_followup.py --output experiments/runs/thread-profile-new` reuses
the frozen multithread binary and generation tree from the preceding pilot.
It rechecks asset/source/golden hashes and runs four golden gates at 4/8 threads
before two profile sessions per executor, orders [4,8] then [8,4], each warmup1
and samples3. This is operator diagnosis only: it has no unprofiled performance
comparison. Run it after all builds/tests, with the same isolated environment.
`inspect_profile_graph.py --model <normalized.onnx> --expected-model-sha256
<hash> --profiles <followup-output> --output <new.json>` loads ONNX without
external tensors, records stored shapes and exact node-name matches, and retains
unmatched optimizer names and missing metadata. It does not infer missing shape
or index uniqueness. Run this development analysis after timed processes finish.
