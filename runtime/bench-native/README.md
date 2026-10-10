# Native resident diagnostic wrapper

Development-only performance instrumentation. The frozen `runtime/rust` source,
manifest, dependency lock and executable are unchanged. This independent package
calls the existing bundle verifier, tokenizer, backbone, readout and policy.

```powershell
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/bench-native-target'
cargo build --locked --release --manifest-path runtime/bench-native/Cargo.toml
cargo clippy --locked --release --manifest-path runtime/bench-native/Cargo.toml -- -D warnings
cargo fmt --manifest-path runtime/bench-native/Cargo.toml -- --check
```

The CLI takes the fixed Native manifest and a benchmark job JSON. It validates the
one-thread policy, retains tokenizer and BF16 mmap, and emits JSONL initialization,
request and completion events with monotonic nanosecond durations. Every request
recreates recurrent state by calling the unchanged native backbone.

`backbone_ns` includes BF16-to-FP32 conversion on every forward. `head_softmax_ns`
includes readout weights, matrix multiplication, mask, temperature and softmax;
these are not separately timed by the frozen readout API. `policy_ns` is separate.
This is not a resident FP32-weight Native backend, nor a public worker protocol.

Use [benchmark_pilot.py](../onnx/benchmark_pilot.py) to generate jobs, validate each
output and collect Windows process lifetime Peak Working Set with a parent guard.
The pilot distinguishes process-cold with uncontrolled storage cache from retained
model execution. It does not compare this wrapper's process time to a production
Tract DecisionProvider E2E latency. Python is only the development measurement host.
