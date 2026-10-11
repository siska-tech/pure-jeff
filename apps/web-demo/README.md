# pure-jeff web demo

A static page that runs the Jeff candidate decision entirely in the browser (Rust → WebAssembly, in a Web Worker). Results: [W3](../../docs/web-demo-w3-results.md), [W4](../../docs/web-demo-w4-results.md). Hosting: [Cloudflare Pages + R2 study](../../docs/w4-hosting.md). Not deployed anywhere yet.

- Input text and candidates never leave the browser; there is no inference server.
- The model (about 1.73 GB) is downloaded only when the user presses the download button. It is stored in Cache Storage and can be deleted from the page.
- Each asset's SHA-256 is computed while it streams in and checked against the bundle manifest before use. The engine binary's hash is checked against the deployment config.
- Output is a `kaze_judge::Attempt` (`kaze_judge.attempt.v1`); a failure is never shown as a judgment.
- Validated range: up to 512 tokens and 2–8 candidates in the UI. Longer prompts return `budget_exceeded` without truncation.
- Requires WebAssembly SIMD and Cache Storage (HTTPS or localhost). Tested only on desktop Chrome/Edge 153 on Windows (headless).
- The build strips the Wasm probe's development exports (`kj_*`) from `engine.wasm` (`strip_exports.py`) and ships `licenses/`: the engine's dependency license texts, the checkpoint's LICENSE and NOTICE, Jeff's MIT license and the notices.

## Build

```powershell
# Engine (wasm32, SIMD128). build_wasm.py remaps host paths, so no user or home directory ships
# in engine.wasm, and the bytes do not depend on CARGO_HOME or the target directory.
python tools/build_wasm.py engine --target-dir .venv/demo-target-wasm
python tools/check_no_host_paths.py .venv/demo-target-wasm/wasm32-unknown-unknown/release/kaze_judge_web_demo.wasm

# Native checks
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/demo-target'
cargo test --locked --offline --release --manifest-path apps/web-demo/engine/Cargo.toml
cargo clippy --locked --offline --release --manifest-path apps/web-demo/engine/Cargo.toml --all-targets -- -D warnings

# Site (the output directory must not exist). Add --copy-model to include model/ for hosting,
# or --model-base-url https://models.example/model/ to fetch the model from another origin (CORS required).
Push-Location apps/web-demo
& python -B build_demo.py `
  --engine-wasm ../../.venv/demo-target-wasm/wasm32-unknown-unknown/release/kaze_judge_web_demo.wasm `
  --output ../../experiments/runs/web-demo-dist
Pop-Location
```

The output holds `index.html`, `app.js`, `engine-worker.js`, `style.css`, `engine.wasm`, `demo-config.json` (asset sizes and hashes, cache name, limits), `samples.json` (artificial inputs) and `build-info.json` (source commit and file hashes). Any static HTTPS host works if it also serves `model/manifest.json` and the four checkpoint files listed in the config. No COOP/COEP headers are needed (single-threaded).

## Run locally

```powershell
python -B apps/web-demo/serve_demo.py --dist experiments/runs/web-demo-dist
# open http://127.0.0.1:8765/
```

`serve_demo.py` binds to 127.0.0.1, maps `model/` to `models/jeff-checkpoint` when the build has no model copy, and can log every request (`--log`).

## End-to-end check

`run_w3.py` serves a build, starts a fresh headless browser profile with remote debugging, and runs `e2e_w3.mjs` (Node 24, Chrome DevTools Protocol). It clicks through the real UI: download, samples, JSON save, failure cases, cancel, page reload, cache load and delete. Then it evaluates the preregistered gates against the official references and the server's request log.

```powershell
Push-Location apps/web-demo
& python -B run_w3.py `
  --browser "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --dist ../../experiments/runs/web-demo-dist --output ../../experiments/runs/web-demo-w3-repeat
Pop-Location
```

`--w4` runs the hosting-like configuration instead: the site on `https://demo.test:9443` and the model on `https://models.test:9444` with CORS (build with `--model-base-url https://models.test:9444/model/`), a throwaway self-signed certificate trusted only by SPKI pin (needs `openssl`), and a download stopped mid-model before the normal flow.
