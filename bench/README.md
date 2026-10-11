# Benchmark harness

Side-by-side measurement of official Jeff (Python/PyTorch), Rust Native and browser Wasm at one thread. Design: [docs/benchmark-plan.md](../docs/benchmark-plan.md). Results: [docs/benchmark-results-2026-10-11.md](../docs/benchmark-results-2026-10-11.md).

Prerequisites:
- `runtime/rust/target/release/jeff.exe` and `examples/resident_bench.exe` (`cargo build --release --example resident_bench`).
- The SIMD128 probe wasm (see `runtime/wasm/README.md`).
- A Native bundle locked for that build (`jeff lock ... 0.7 0.1 1`).
- An official Jeff bundle with `--cpu-threads 1` (`runtime/jeff_worker.py --lock`), plus its Python environment.

```powershell
Push-Location bench
& <official-jeff-python> -B run_benchmark.py `
  --python <official-jeff-python> --py-manifest ../models/jeff-bundle.json `
  --rust-manifest ../models/jeff-rust-bundle-pj.json `
  --wasm ../.venv/wasm-target-simd128/wasm32-unknown-unknown/release/kaze_judge_wasm_probe.wasm `
  --browser "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --output ../experiments/runs/bench-repeat
Pop-Location
```

The driver refuses to start when another build or benchmark process is running, or when on battery. It writes `preregistration.json` before measuring and exits non-zero if any validity gate fails.
