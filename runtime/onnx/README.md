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
## Accepted-binary thread follow-up and length inputs

`benchmark_accepted_threads.py --output <new-run-dir>` freezes the accepted
Scatter binary, generated sources and NNEF. Four/eight-thread golden gates
precede three unprofiled AB/BA/AB resident pairs, warmup1 + samples3, n=9/thread.
Prefer eight only if all paired session medians plus pooled median/p95 improve;
otherwise retain four for the next pilot. This changes no product configuration.

Build the development-only `prepare_lengths` bin in `runtime/bench-native` with
the existing locked dependencies, then run `prepare_lengths.exe
models/jeff-rust-bundle-p3.json <new-output.json>` from the repository root.
It uses unchanged Native prompt/tokenizer, verifies four golden prompts/IDs,
and generates 24 artificial full requests at 128/256/384/511/512 effective
tokens with physical512 padding. Exact/one-short token budgets and one 513
rejection are checked. Four variants per length plus eight-candidate extras
at lengths >=256; these have no recognition ground truth. Numeric acceptance
requires the oracle and whole-model Tract gate below. No runtime Python
dependency is introduced.

## Effective-length oracle and performance pilot

`prepare_length_oracle.py --output <new-run-dir>` checks frozen normalized ONNX,
external weights and the 24 Rust fixtures, then computes four golden references
plus 24 new CPU-only ORT references (one thread, optimization disabled). Python
is development-only. The supervised worker uses `sys._base_executable` directly:
on Windows the venv launcher otherwise hides the actual child memory from a
single-process guard. Worker interpreter identity and actual memory are checked.

`benchmark_lengths.py --oracle <oracle.json> --output <new-run-dir>` freezes the
accepted Scatter binary/NNEF and runs all 28 numeric gates before timing. Four
threads, three independent resident sessions, warmup5 then mixed samples20 each.
Each effective length 128/256/384/511/512 has n=12 across four inputs; physical
shape remains512. Extra eight-candidate cases are gate-only. Repeated raw logits
must exactly match Tract gate; probability/judgment/token gates use ORT. Records
include separate stages and per-input statistics. n=12 p95 is max; this is a
descriptive prepared-tensor pilot, not Native/API E2E or formal SLO acceptance.

## Common512 operating-configuration comparison

`benchmark_common512.py --output <new-run-dir>` uses the frozen Native wrapper
and accepted Scatter executable, without rebuilding either. Eight numeric gates
per engine (four goldens + four effective512 inputs) precede three resident
pairs in AB/BA/AB order. Both use one requested/reported compute thread; primary
inputs have physical512, no padding, batch1, text only. One warmup + four mixed
samples/session, n=12/engine and n=3/input. Native probabilities must exactly
repeat its gate; Tract raw logits must exactly match the previous length gate.
Compute aggregates Native backbone+head/softmax vs Tract forward+score.
Native BF16 mmap/per-forward FP32 conversion and Tract retained FP32 packed
plan remain different, as do algorithms and stage boundaries. This compares
operating configurations; it cannot isolate a runtime-only effect. Request and
startup scopes are unequal, not matched API E2E or cold adoption evidence.
No public runtime/API/policy or existing executable changes are required.

## Isolated Native FP32 retention experiment

`prepare_native_retained.py --output <new-dir>` checks the preserved Native
baseline, then generates a separate crate from its backbone/readout/wrapper.
The original equations remain unchanged; weight lookup selects either mmap or
owned CPU FP32 tensors. Retained mode preloads all model and readout tensors,
including embedding, releases the original mmap, and shares tensors on lookup.
The generator runs rustfmt, saves zero-context patches and source/file hashes.
It retains existing lock package versions; candle-nn becomes explicit at root.
Build/test/clippy with the generated locked manifest in a separate Cargo target;
never overwrite the frozen Native benchmark executable. These development
tools require the existing local baseline/assets and cached dependencies.

`benchmark_native_retained.py --output <new-run-dir>` uses the frozen generated
v2 crate and separate target, one executable with retained_f32 false/true. Eight
numeric gates per mode require exact probabilities to the previous frozen
Native gate plus ONNX probability/judgment/token tolerances. Three resident
AB/BA/AB pairs use common512, one thread, warmup1 + mixed samples4, n=12/mode.
Local warm acceptance requires all paired medians plus pooled median/p95 to
improve. Initialization/retention work and lifetime peak are recorded, not hidden
by warm compute timings. This is not Tract/API E2E, formal SLO or product change.
The measured retained mode includes all 473 model tensors; the later static
inventory identifies 153 unused visual tensors. A text-only 320-tensor filter
is future unmeasured work, not part of the accepted experiment.

## Text-only Native retention pilot

prepare_native_text.py --output <new-dir> derives a separate candidate from
the archived full473 crate. It requires the exact pinned 473-name inventory,
retains only the 320 text tensors, and preserves the separate head1. Equations,
wrapper, manifest and lock are byte-identical to the full candidate. Build in
a separate target; seven Rust tests, clippy/fmt and eleven reproduced files pass.

enchmark_native_text.py --output <new-run-dir> compares the frozen full473
exe and text320 exe, both retained FP32, common512/one thread. Eight gates per
mode precede three AB/BA/AB resident pairs, warmup1 + measured4, n=12/mode.
All 46 forwards match frozen Native probabilities exactly. Local acceptance
is MEMORY ONLY: every paired lifetime peak and pooled maximum must decrease.
Observed pooled maximum 5,190,696,960 to 4,591,202,304 bytes passes. Latency is
descriptive; no speed or noninferiority acceptance, API E2E or formal SLO.
The preceding full473 evidence stays unchanged and refers to its own run.

## FP32 common512 Native/Tract comparison

`audit_native_threads.py --output .venv/native-fp32-thread-audit.json` records
the pinned Candle commit, core/nn diff, Cargo features and source excerpts.
The fixed Native wrapper forces both RAYON_NUM_THREADS/CANDLE_NUM_THREADS to 1;
GEMM chooses Parallelism::None and the elementwise barrier pool has no auxiliary
workers. DeltaNet recurrence stays serial. This audits compute configuration,
not total OS thread count or active-worker telemetry. A Native thread matrix
requires a new isolated wrapper; external environment overrides are insufficient.

`benchmark_fp32_common512.py --output <new-run-dir>` uses the frozen text320
Native FP32 exe and accepted Tract packed FP32 exe, without rebuilding either.
Both use common effective/physical512, no padding and one compute thread.
Eight numerical gates per engine precede three AB/BA/AB resident pairs,
warmup1 + measured4/session, n=12/engine. Native probabilities must exactly
match frozen Native, Tract raw logits the earlier four-thread gate. Packed
layout, algorithms, stage boundaries and startup verification remain different.
This is a descriptive operating-configuration comparison; no runtime-only,
speedup, API E2E, formal SLO or backend-adoption claim is authorized by it.

## Native text320 thread matrix

`prepare_native_threads.py --output <new-dir>` generates a separate wrapper
from the archived text320 source. Backbone/readout/cache/inventory remain
byte-identical. Rayon =1.12.0, already locked transitively, becomes explicit.
Build/test/clippy/fmt in a new target; never overwrite frozen executables.
Job threads accepts only integer1/2/4/8, sets both environment variables before
initialization, explicitly builds the global Rayon pool and checks its actual
size plus Candle's GEMM setting. Manifest policy stays1; this is an experiment
compute override. Barrier auxiliary count is derived, not observed telemetry.

`benchmark_native_threads.py --output <new-run-dir>` gates eight cases per
setting, then runs four balanced Williams blocks with one warmup and four
mixed common512 requests/session: n=16/setting, n=4/input, 112 total forwards.
ONNX and frozen Native probability tolerance1e-4, judgment/tokens exact;
one-thread frozen probabilities exact, within-setting gate repeat <=1e-6.
Next-pilot eligibility requires all four block medians and pooled median/p95
below1 thread; choose the lowest eligible pooled median. This selects an
exploration candidate, not a formal SLO, product or Tract adoption. At n=16
nearest-rank p95=max. DeltaNet stays serial; no per-kernel speedup attribution.

## Independent Native2/4 confirmation and Tract4 comparison

`benchmark_native_confirm.py --output <new-run-dir>` reuses the frozen Native
thread exe and accepted Scatter Tract exe without rebuilds. After eight gates
per configuration, all six permutations of Native2/Native4/Tract4 balance the
order, with warmup1 + measured4/session: n=24/configuration, n=6/input,
114 total forwards. These are new independent sessions/seed on the SAME four
common512 artificial inputs, not held-out input data or recognition quality.
Native frozen probability tolerance1e-4, repeat1e-6; Tract raw exactly matches
the prior four-thread gate; ONNX probability/judgment/token gates apply to all.
Native4 local warm confirmation requires all six block medians and pooled
median/p95 below Native2. No post-hoc criterion changes or optional stopping.
Native4/Tract4 remains descriptive: dtype/shape/threads common, layout,
algorithm, stage/startup verification/request scopes unequal. No backend
adoption, runtime-only claim, API E2E or formal SLO. n=24 p95=second-largest;
startup/lifetime peaks n=6 incidental, not cold/private warm memory evidence.

`benchmark_length_compare.py` reuses the frozen Native thread wrapper and
accepted Tract binary at four threads with the existing 28-case length oracle.
Gate28/configuration precedes three AB/BA/AB resident pairs, each with five
mixed-length warmups and twenty measured requests. Four primary cases at each
of 128/256/384/511/512 effective tokens yield n=12/length/configuration and
n=3/input; p95 is the maximum. Native computes the effective length; Tract
computes left-padded physical512, so shorter cells have different shapes.
ONNX probability/judgment/token gates, Native per-case repeat<=1e-6 and existing
Native references where available, and exact previous Tract length-gate raw
logits are required for all 206 planned forwards. Eight-candidate extras are gate-only and
lack a128 cell. Same old artificial inputs, partially balanced order and
uncontrolled thermals/background/cache limit interpretation. No runtime-only
speedup, backend adoption, API E2E, cold campaign or formal SLO acceptance.
The first run stopped after 156 forwards: resident-1-native4 exceeded the
registered repeat tolerance for six observations/four cases, maximum
3.546476364135742e-6. All156 passed ONNX probability/judgment/token gates,
but the third pair was not run and performance comparison was not accepted.
Raw diagnostics, failure and independent audit are preserved in
`docs/research/jeff-onnx-tract/length-compare-2026-10-11`; no threshold relaxation
or replacement run. Timing drift in both backends remains unexplained.
