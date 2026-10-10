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

## Trilu single-change experiment

`prepare_trilu_experiment.py` accepts the same `--upstream` and a new `.venv`
`--output` as the forward generator. It verifies the pinned core/data/linalg
sources and generates the same multithread base, then adds only a contiguous
Trilu row-fill helper and guarded call. The original indexed path remains for
nonstandard layout and possible legacy i64 row+k overflow. Dependency lock,
benchmark driver, thread thresholds and optimizer settings stay identical.
Use a new `CARGO_TARGET_DIR`; build with `--locked --offline --release --bin bench`.
Run the standalone `rustc --edition=2024 --test` helper tests and
`test_tract_trilu.py` with `TRACT_FORWARD_BENCH` pointing to the frozen control
and `TRACT_TRILU_BENCH` to the candidate. The actual Tract test checks 168
shape/dtype/k/upper configurations against the control and scalar reference,
including existing release overflow behavior, twice per process.

`benchmark_trilu.py --candidate <exe> --generation <generation.json> --output
<new-run-dir>` requires the frozen multithread control/NNEF from the earlier
pilot. It rejects any generated source change outside Trilu/helper and verifies
all four goldens before timing. Four threads, three independent AB/BA/AB blocks,
one warmup plus three measured candidate-request forwards per binary/session,
n=9 per binary. Two separate profiled sessions follow and are excluded from the
latency comparison. All raw logits must equal the frozen control. Local pilot
acceptance requires all three session-median differences and pooled median/p95
to improve, without a guard failure. This does not establish a production SLO,
Native superiority, or API/recognition-quality acceptance.
## ScatterElements single-change experiment

`prepare_scatter_experiment.py --upstream <pinned-checkout> --output <new-dir>`
generates the accepted Trilu base, then adds a guarded contiguous row-copy path
only for ScatterElements reduction=None. It validates all row indices before
mutation; nonuniform, out-of-range, nonstandard-layout or unsupported-shape
cases retain the original loop. Duplicate targets preserve C-order overwrite
order. Use a new `CARGO_TARGET_DIR` and locked offline release build.

Run standalone `scatter_rows.rs` tests and direct `scatter_semantics.rs` tests
linked separately to control/candidate rlibs. `test_tract_scatter.py` requires
`TRACT_TRILU_BENCH` and `TRACT_SCATTER_BENCH`. It checks 192 successful ONNX
conditions against scalar reference, plus 64 I64 reduction conditions that both
imported paths reject with `TDim is not a number`. Each successful process runs
twice; those rejections are not successful forwards. I64 Cast imports as TDim
in pinned Tract. Reductions remain outside this optimization.

`audit_scatter_indices.py --model <frozen-normalized.onnx> --output <new.json>`
records stored shapes and scalar-Constant-to-Expand index provenance without
external weights. This does not establish runtime layout or call counts.
`benchmark_scatter.py --candidate <exe> --generation <generation.json>
--output <new-run-dir>` uses the frozen accepted Trilu binary as control.
Only ScatterElements/helper differences are allowed; all four raw-logit gates
precede four-thread AB/BA/AB resident pairs (warmup1 + samples3, n=9/binary).
Separate profile sessions follow. Acceptance requires all paired session
medians plus pooled median/p95 to improve, exact raw logits and no guard failure.
The pilot does not establish a production SLO, API E2E or Native superiority.
