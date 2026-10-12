# Changelog

Changes to the `pure-jeff` crate. Records of how each change was verified are linked from each entry.

## [0.1.1] - 2026-10-12

Faster and smaller Native inference. **Outputs are bitwise identical to 0.1.0.**

### Changed

- The DeltaNet recurrence runs each head in blocks of 32 state columns over all tokens, so the block stays in L1 cache, and decay and the delta sum share one pass ([#6](https://github.com/siska-tech/pure-jeff/pull/6), [record](docs/native-delta-recurrence-2026-10-12.md)).
- The 4-tap causal convolution and its SiLU run as one loop, and the MLP and linear-attention gates no longer build intermediate tensors ([#7](https://github.com/siska-tech/pure-jeff/pull/7), [record](docs/native-elementwise-2026-10-12.md)).
- BF16 weights are converted to F32 straight from the safetensors bytes, without first copying the BF16 data, and the embedding reads only the rows of the input tokens instead of copying the whole 485 MiB table ([#9](https://github.com/siska-tech/pure-jeff/pull/9), [record](docs/native-weight-load-2026-10-12.md)).

Every element is computed with the same operations in the same order as before. Sums, softmax and matrix products are still Candle's.

### Added

- `WeightSource::load_f32` and `WeightSource::load_f32_rows`. Both have default implementations (load, then convert with Candle), so existing implementations of `WeightSource` compile unchanged. An implementation that overrides them must return bitwise the same values as the defaults.

### Dependencies

- `half` 2 is now a direct dependency, for the same `bf16::to_f32` that Candle's `to_dtype` uses. It was already in the dependency tree (2.7.1); no new crates are pulled in.

### Verification

- **Repository build** (pinned Candle revision): the final hidden state of all seven official reference cases (128 to 8192 tokens, up to 255 candidates) has the same SHA-256 as with 0.1.0.
- **crates.io dependencies:** two clean projects built only from crates.io, one depending on `pure-jeff` 0.1.0 and one on the 0.1.1 package, with identical versions of all other 156 locked packages. They give bitwise-identical candidate probabilities (all 268) and the same judgments on the seven reference cases. Against the official implementation the largest probability difference is 3.457e-6, as in 0.1.0.
- Unit tests compare each rewritten step with the previous code or the Candle operations it replaces, bit for bit, on x86-64 and on wasm32 with SIMD128.
- MSRV is still Rust 1.88.

### Performance

One thread, Windows 11, Core i7-1360P, artificial inputs. These are descriptive measurements on one machine, not guarantees ([benchmark](docs/benchmark-results-2026-10-12.md)):

| | 0.1.0 | 0.1.1 |
| --- | ---: | ---: |
| Resident decision, 128 tokens | 3.00 s | 2.06 s |
| Resident decision, 512 tokens | 9.60 s | 6.77 s |
| One request per process, 128 tokens | 5.45 s | 4.31 s |
| One request per process, 512 tokens | 12.10 s | 9.05 s |
| Resident process memory (working set, max) | 1.94 GiB | 1.07 GiB |

- With the model resident, the official Python/PyTorch implementation is still faster. It now takes 0.74–0.94 of this crate's time per decision (0.51–0.66 with 0.1.0).
- These figures come from the repository build, which uses a pinned Candle revision. Performance with the crates.io Candle 0.11.0 was not benchmarked.
- **Browser (wasm32) performance was not measured.** The repository's web demo engine uses the same library code, but the benchmark's browser arm is a research probe that runs frozen pre-0.1.1 code. The crates.io crate itself still does not support wasm32.

### Upgrade notes

- `runtime_build_hash()` changes with any library source change. A bundle manifest is accepted by 0.1.1 unless you load it with `LoadOptions::require_runtime_build` (default off). In that case, re-create it with `pure_jeff::lock`. The repository's `jeff` CLI always checks the build hash, so re-run `jeff lock` after updating.
- The prompt contract, policy, schemas and public types are unchanged.

## [0.1.0] - 2026-10-12

First release: verified bundle manifests, `Model` (resident) and `ColdProvider`, in-memory `memory::Session`, one-request worker processes (`process` feature), and the decision contract (`DecisionRequest`, `Observation`, `Attempt`). Checked against the official implementation on seven reference cases ([record](docs/crate-release-results-2026-10-12.md)).

[0.1.1]: https://github.com/siska-tech/pure-jeff/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/siska-tech/pure-jeff/releases/tag/v0.1.0
