# Benchmark harness

Performance-parity measurement of official Jeff (Python/PyTorch), Rust Native and the current browser engine, with a common numeric gate and preregistered statistics. Plan and acceptance rules: [docs/benchmark-parity-plan.md](../docs/benchmark-parity-plan.md). Earlier descriptive runs (unchanged): [docs/benchmark-plan.md](../docs/benchmark-plan.md), [2026-10-11](../docs/benchmark-results-2026-10-11.md), [2026-10-12](../docs/benchmark-results-2026-10-12.md); their driver and wrappers are in git at `a9538b9`.

| File | Role |
| --- | --- |
| `run_benchmark.py` | Driver: stages `short`, `long`, `wasm`, `oneshot`; `--path api` (default) or `internal`; `--threads` |
| `jeff_resident.py`, `../runtime/rust/examples/resident_bench.rs` | Resident sessions (`--mode api` / `internal`) emitting JSON lines |
| `wasm/engine-bench.html` | Drives the web demo's own `engine-worker.js` and stripped `engine.wasm` |
| `catalog.py`, `build_catalog.py`, `cases/` | Evaluation inputs: deduplicated, token IDs checked by both tokenizers, official references |
| `make_length_requests.py`, `search_policy_boundary.py` | Generated inputs (127/129 tokens; near the 0.7 threshold and ties) |
| `validate.py` | The common numeric gate for every decision of every arm |
| `stats.py` | Blocks, equivalence verdicts, regression threshold |
| `compare_runs.py` | Baseline vs candidate: one-shot median / peak > 5 %, bitwise identity |
| `test_bench.py` | Unit tests (no model): `python -B -m unittest bench/test_bench.py` |
| `wasm/bench.html`, `tract_resident.py`, `procmem.py` | The earlier probe page (kept for the old runs), the experimental Tract path, memory sampling |

## Setup

```powershell
python -B tools/fetch_model.py --output models/jeff-checkpoint
git clone https://github.com/firelex/jeff vendor/jeff; git -C vendor/jeff checkout 3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0
uv sync --frozen --no-default-groups --directory vendor/jeff     # uv >= 0.12.19 (Jeff's pyproject)
cargo build --release --locked --manifest-path runtime/rust/Cargo.toml --bin jeff --examples
python tools/build_wasm.py engine --target-dir .venv/demo-target-wasm
& runtime/rust/target/release/jeff.exe lock models/jeff-checkpoint models/pure-jeff-bundle-t1.json 51552f39a943d62e8387c4ea5e17026a1408729f 0.7 0.1 1
$py = (Resolve-Path vendor/jeff/.venv/Scripts/python.exe).Path
& $py -B runtime/jeff_worker.py --lock --manifest models/pure-jeff-reference-bundle-t1.json --checkpoint (Resolve-Path models/jeff-checkpoint).Path --source (Resolve-Path vendor/jeff).Path --source-revision 3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0 --min-probability 0.7 --min-margin 0.1 --cpu-threads 1
```

`bench/cases/catalog.json` is committed. To rebuild it (official interpreter; overwrites only with `--replace`):

```powershell
& $py -B bench/build_catalog.py --manifest models/pure-jeff-reference-bundle-t1.json --jeff-exe runtime/rust/target/release/jeff.exe --rust-manifest models/pure-jeff-bundle-t1.json --replace
```

## Running

Nothing else may build, install or benchmark during a run; the driver checks at the start and before every session, and refuses to start on battery. Each run writes `preregistration.json` before measuring, one file per session under `sessions/`, `environment-end.json` and `summary.json`, and exits non-zero if any gate fails.

```powershell
$common = @("--rust-manifest", "models/pure-jeff-bundle-t1.json", "--python", $py, "--py-manifest", "models/pure-jeff-reference-bundle-t1.json")
python -B bench/run_benchmark.py --stage short @common --output experiments/runs/parity-short
python -B bench/run_benchmark.py --stage long @common --output experiments/runs/parity-long
python -B bench/run_benchmark.py --stage oneshot @common --output experiments/runs/parity-oneshot
python -B bench/run_benchmark.py --stage wasm --rust-manifest models/pure-jeff-bundle-t1.json --engine-wasm .venv/demo-target-wasm/wasm32-unknown-unknown/release/pure_jeff_web_demo.wasm --browser "C:\Program Files\Google\Chrome\Application\chrome.exe" --output experiments/runs/parity-wasm
python -B bench/compare_runs.py experiments/runs/parity-oneshot experiments/runs/<candidate-oneshot>
```

`--threads N` needs both bundles locked with `cpu_threads=N`. `--path internal` measures the diagnostic boundary and is not used for verdicts. `summary.json` holds the gate failures, repeat violations, per-case descriptive statistics (load, first, warm), per-group block ratios with the one-sided 95% bounds and verdicts (`equivalent`, `slower`, `insufficient`), memory and the kernel information each arm reported.

## Experimental Tract path

`tract_resident.py` runs the patched Tract `bench.exe` (`runtime/tract`) resident at one thread on the four golden cases padded to 512 tokens. It needs the normalized ONNX graph and a passed `runtime/onnx/check_tract.py --stage run-no-change-axes` output directory, and fails unless every request's raw logits equal that gate's bit for bit. See [docs/tract-development.md](../docs/tract-development.md).

```powershell
python -B bench/tract_resident.py --bench runtime/tract/target/release/bench.exe `
  --model experiments/runs/tract/onnx/model.normalized.onnx --gate experiments/runs/tract/gate `
  --output experiments/runs/tract-bench --warmup 1 --samples 3
```

The `runtime/onnx/benchmark_*.py` harnesses are the archived KazeJudge experiments: they read fixed KazeJudge-era run directories and executable hashes and are kept unchanged as the record of those runs.
