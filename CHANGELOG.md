# Changelog

Changes to the `pure-jeff` crate. Records of how each change was verified are linked from each entry.

## [Unreleased]

**Outputs change on some hosts** (see below); the official-reference gate and the judgments are unaffected. The numbers in this section come from a laptop and GitHub-hosted runners; the release gate on the reference machine is still to be run.

### Changed

- Matrix products whose summed dimension k exceeds 512 (every linear layer and the attention value product) are split by this crate into ceil(k / 512) equal chunks, added in order, instead of by gemm into blocks it sizes from the CPU's L1 cache. The bits then no longer depend on the cache sizes: the same on the P- and E-cores of a hybrid CPU, and on Linux and Windows on the same ARM64 CPU ([#18](https://github.com/siska-tech/pure-jeff/issues/18), [record](docs/native-fixed-k-chunks-2026-10-20.md)). Hosts on which gemm already used blocks of 512 (an 8-way L1 data cache) give the same outputs as before; hosts with larger blocks for some products (a 12-way L1, as on the reference machine, or a 64 KiB 4-way L1 under Linux on ARM64) change by up to a few 1e-6.
- Full attention never makes a one-row query block: a sequence of 512n + 1 tokens ends in blocks of 511 and 2 rows instead of 512 and 1 ([#39](https://github.com/siska-tech/pure-jeff/pull/39), [record](docs/native-query-blocks-2026-10-20.md)), so blocked attention stays bitwise equal to one block on every host.

## [0.2.0] - 2026-10-14

Native inference as fast as the official implementation at every tested length, with less memory. **Outputs are bitwise identical to 0.1.1.** The version is 0.2.0 because `LoadOptions` gained a public field (see Breaking).

### Changed

- Full attention runs in blocks of 512 query rows against all keys, so scores, mask and probabilities never exist for the whole sequence: at 8192 tokens the peak working set falls from 7.85 to 2.06 GiB, at the same speed. Sequences up to 512 tokens run exactly as before ([#17](https://github.com/siska-tech/pure-jeff/issues/17), [record](docs/native-attention-blocks-2026-10-14.md)).
- A Native forward converts every BF16 weight into one buffer, reused for the whole forward, instead of newly allocated memory for each weight. About half of the conversion time was the first write to new pages; the memory held for weights is still that of the largest one ([#14](https://github.com/siska-tech/pure-jeff/issues/14), [record](docs/native-weight-buffers-2026-10-13.md)). Browser sessions (`memory::Session`) keep the previous path.

### Added

- `LoadOptions::retain_f32`: convert the backbone weights except the embedding (319 tensors, 1,992,453,376 bytes) and the readout to F32 once at load and keep them, for resident models that make several decisions; `Model::retained_f32_bytes` ([#4](https://github.com/siska-tech/pure-jeff/issues/4)). Off by default.
- `WeightSource::convertible_shape` and `WeightSource::load_f32_into`, with default implementations (no conversion into a caller's buffer), so existing implementations compile unchanged.

### Breaking

- `LoadOptions` has a new public field. Code that builds it with a struct literal must add `retain_f32: false` or `..LoadOptions::default()`.

### Verification

Release gate ([procedure](docs/release-gate.md), [record](docs/release-0.2.0-verification-2026-10-14.md)), one thread, Windows, AMD Ryzen AI MAX+ 395:

- **Same outputs as 0.1.1:** on all 39 benchmark inputs (127 to 8193 tokens, 2 to 255 candidates, policy-boundary inputs), the probabilities, judgments and failures are bitwise identical to 0.1.1, both in the repository build and in a clean project built only from crates.io.
- **Official implementation:** every input passes the numeric gate (largest probability difference 4.74e-6 in the repository build, 3.96e-6 with crates.io Candle).
- **Speed:** with the model resident, this crate takes 0.82 to 0.96 of the official implementation's time in every length group from 128 to 8192 tokens (preregistered statistics, upper 95% bounds 0.83 to 0.99). One request per process takes 3.8 s at 128 tokens (official 13.1 s).
- **Memory:** peak working set 1.09 GiB up to 513 tokens (official 3.88 GiB) and 2.09 GiB up to 8192 tokens (official 5.17 GiB).
- **Browser demo engine:** end-to-end checks pass in Chrome and Edge; outputs are unchanged.
- **Not measured:** speed with crates.io Candle, other CPUs, Linux, more than one thread.
- MSRV is still Rust 1.88.

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
