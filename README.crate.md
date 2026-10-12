# pure-jeff

Pure-Rust CPU inference for the [Jeff](https://github.com/firelex/jeff) candidate decision model (`Jeff-Qwen3.5-0.8B`), built on [Candle](https://github.com/huggingface/candle). No Python or PyTorch at run time. Unofficial; not affiliated with the authors of Jeff or Qwen.

Given an original recognized text (OCR or ASR) and 2–255 transcription candidates, the model returns a distribution over the supplied candidates and a decision: one candidate is **selected**, or the call **abstains**. The distribution compares the supplied choices only; it is not a probability that any candidate is a correct transcription.

## Model files

The weights (about 1.73 GB) are not part of this crate. Download the 11 files of [`jeff-legacy/Jeff-Qwen3.5-0.8B`](https://huggingface.co/jeff-legacy/Jeff-Qwen3.5-0.8B) at revision `51552f39a943d62e8387c4ea5e17026a1408729f` into one directory, for example `models/jeff-checkpoint`. The repository's `tools/fetch_model.py` does this and checks each file's SHA-256. The weights are licensed under Apache-2.0 and come with their own `LICENSE` and `NOTICE`.

Then write a *bundle manifest* once. It records the SHA-256 of every checkpoint file, the selection policy and the prompt contract:

```rust
use pure_jeff::Policy;
use std::time::{Duration, Instant};

let manifest_sha256 = pure_jeff::lock(
    "models/jeff-checkpoint",
    "models/jeff-bundle.json", // outside and above the checkpoint directory; must not exist
    "51552f39a943d62e8387c4ea5e17026a1408729f",
    Policy { min_probability: 0.7, min_margin: 0.1, cpu_threads: 1 },
    Instant::now() + Duration::from_secs(600),
)?;
```

`min_probability` and `min_margin` are example thresholds, not recommendations. A candidate is selected only when its probability is at least `min_probability` and leads the runner-up by at least `min_margin`; ties abstain.

## Deciding

```rust
use pure_jeff::{DecisionRequest, Limits, LoadOptions, Model};
use std::time::{Duration, Instant};

// Process-wide compute threads: equal to the policy's cpu_threads, before any inference.
pure_jeff::configure_threads(1)?;
let model = Model::load("models/jeff-bundle.json", &LoadOptions::default())?;

let request: DecisionRequest = serde_json::from_str(r#"{
  "request_id": "r1", "document_id": "d1", "segment_id": "s1",
  "original_text": "teh cat sat", "source": "ocr", "profile_id": "default", "domain": null,
  "question_id": "transcription-candidate.v1",
  "candidates": [{"id": "a", "text": "the cat sat"}, {"id": "b", "text": "teh cat sat"}],
  "reason": "candidate_competition"
}"#)?;
let limits = Limits {
    max_input_bytes: 1024 * 1024,
    max_input_tokens: 8192,
    max_forwards: 1,
    deadline: Instant::now() + Duration::from_secs(120),
};
let observation = model.decide(&request, limits)?;
for score in &observation.scores {
    println!("{} {:.4}", score.candidate_id, score.option_probability);
}
println!("{:?}", observation.judgment); // Selected { candidate_id } or Abstained
```

- `Model::load` verifies the manifest before anything is used: the set and SHA-256 of all checkpoint files, tensor names, shapes and dtypes, the decision config, the tokenizer's answer vocabulary, the prompt contract and the compute threads. Loading errors are `pure_jeff::Error` with an `ErrorKind`. The checkpoint files are memory-mapped and must not change while the `Model` exists.
- `Model::decide` checks the request, the byte, token and forward budgets and the deadline before the forward pass, and the deadline between steps. A deadline cannot interrupt a running matrix operation. Prompts longer than the token budget (at most 8192 tokens) are rejected, not truncated. Failures are `pure_jeff::Failure` (`InvalidRequest`, `InvalidOutput`, `BudgetExceeded`, `Timeout`, `Unavailable`).
- `pure_jeff::evaluate` wraps any `DecisionProvider` into an `Attempt` (schema `pure_jeff.attempt.v1`), in which a failure is never reported as a judgment.
- Each observation lists the checkpoint files, the manifest, the runtime build (`runtime_build_hash()`), the prompt contract, the rendered prompt and the policy as hashed artifacts.

`LoadOptions::require_runtime_build` additionally requires that the manifest was written by exactly this build of the library (same sources, compiler, target, profile and flags).

## Features

| Feature | Default | Adds |
| --- | --- | --- |
| `native` | yes | Files and memory-mapped weights: `Model`, `lock`, `ColdProvider` |
| `process` | no | One request per child process with a hard deadline: `NativeProcessProvider`, `worker::run` (and `LocalProcessProvider` for the repository's Python reference worker) |

`pure_jeff::memory::Session` makes the same verified decisions from bytes held in memory, without files or a clock.

## Scope and verification

- One fixed checkpoint (revision above), text only, batch one, FP32 compute on CPU, at most 8192 input tokens.
- Checked against the official Python implementation on seven reference cases (up to 8192 tokens and 255 candidates; artificial inputs): all judgments and token counts match. With this crate's crates.io dependencies the largest probability difference was 3.5e-6. Recognition quality on real OCR/ASR data has not been evaluated.
- Validated with the model on Windows x86_64. On Linux x86_64 the crate builds and passes the model-free tests in CI (GitHub Actions); other platforms are untested.
- Candle 0.11.0 from crates.io depends on `tokenizers` with the Oniguruma C library, so building needs a C compiler. The repository's browser (wasm32) build uses a later Candle revision. This crate does not support wasm32 on crates.io dependencies.

## License

Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). The prompt and decision procedure reproduce the MIT-licensed Jeff reference implementation; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Source, CLI, browser demo and validation records: <https://github.com/siska-tech/pure-jeff>.
