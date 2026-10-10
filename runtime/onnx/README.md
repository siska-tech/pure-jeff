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
