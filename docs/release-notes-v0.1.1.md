# pure-jeff 0.1.1

Faster and smaller Native inference. **Outputs are bitwise identical to 0.1.0**: same probabilities, same judgments, same token counts.

```toml
[dependencies]
pure-jeff = "0.1.1"
```

## What changed

Three rewrites of the forward pass. Each computes every element with the same operations, in the same order, as before:

- **DeltaNet recurrence** ([#6](https://github.com/siska-tech/pure-jeff/pull/6)): each head runs in blocks of 32 state columns over all tokens, so the block stays in L1 cache.
- **Element-wise steps** ([#7](https://github.com/siska-tech/pure-jeff/pull/7)): the 4-tap causal convolution and its SiLU run as one loop, and the MLP and linear-attention gates no longer build intermediate tensors.
- **Weight loading** ([#9](https://github.com/siska-tech/pure-jeff/pull/9)): BF16 weights are converted to F32 straight from the safetensors bytes, and the embedding reads only the rows it needs instead of copying the whole 485 MiB table.

API: `WeightSource` gains `load_f32` and `load_f32_rows`, with default implementations, so existing implementations compile unchanged. `half` 2 becomes a direct dependency; it was already in the dependency tree. MSRV is still Rust 1.88.

## Performance

One thread, Windows 11, Core i7-1360P, artificial inputs, same benchmark plan and machine as for 0.1.0. These are descriptive measurements, not guarantees ([results](https://github.com/siska-tech/pure-jeff/blob/main/docs/benchmark-results-2026-10-12.md)):

| | 0.1.0 | 0.1.1 |
| --- | ---: | ---: |
| Resident decision, 128 tokens | 3.00 s | 2.06 s |
| Resident decision, 512 tokens | 9.60 s | 6.77 s |
| One request per process, 128 tokens | 5.45 s | 4.31 s |
| One request per process, 512 tokens | 12.10 s | 9.05 s |
| Resident process memory (working set, max) | 1.94 GiB | 1.07 GiB |

- Resident decisions are 31–32% shorter. The official Python/PyTorch implementation is still faster with the model resident: it now takes 0.74–0.94 of this crate's time (0.51–0.66 with 0.1.0).
- These figures come from the repository build, which uses a pinned Candle revision. **Performance with the crates.io Candle 0.11.0 was not benchmarked.**
- **Browser (WebAssembly) performance was not measured.** The repository's web demo engine uses the same library code, but the benchmark's browser arm is a research probe that runs frozen pre-0.1.1 code.

## Verification

- **Repository build:** the final hidden state of all seven official reference cases (128 to 8192 tokens, up to 255 candidates) has the same SHA-256 as with 0.1.0.
- **crates.io dependencies:** a clean project depending on `pure-jeff` 0.1.0 from crates.io and one depending on the 0.1.1 package give bitwise-identical probabilities (all 268) and the same judgments on the seven reference cases. All other 156 locked packages have the same versions in both. Against the official implementation the largest probability difference is 3.457e-6, as in 0.1.0.
- Unit tests compare each rewritten step with the previous code or the Candle operations it replaces, bit for bit, on x86-64 and on wasm32 with SIMD128.
- CI: Windows and Linux (library, CLI, Wasm probe, web demo engine, package and clean consumer build, license audit).

## Upgrading

- A bundle manifest from 0.1.0 still loads, unless you require a matching runtime build (`LoadOptions::require_runtime_build`, default off). In that case, re-create the manifest with `pure_jeff::lock`, because `runtime_build_hash()` changed. The repository's `jeff` CLI always checks the build hash; run `jeff lock` again.
- The prompt contract, policy, schemas and public types are unchanged.

## Browser demo

The public demo at https://pure-jeff.siska-tech.workers.dev has **not** been redeployed for this release. It still runs the engine built from commit `63324e0`, before these changes.

## 日本語の要約

- `pure-jeff` 0.1.1は、Native推論の高速化とメモリ削減のリリースです。**出力（確率・判断・tokens数）は0.1.0とbit単位で同じです。** リポジトリ内のbuildでは、公式参照7件で最終hidden stateのhashが一致しました。crates.ioの依存だけでbuildした場合も、0.1.0と0.1.1で全268個の確率が一致しました。
- 1 thread・Windows・Core i7-1360Pでの測定です。モデル常駐の判断は31〜32%短くなりました（128 tokensで3.00秒→2.06秒、512 tokensで9.60秒→6.77秒）。常駐時のメモリは1.94 GiBから1.07 GiBに減りました。常駐時は、公式Jeff（PyTorch）の方がまだ速いです（Nativeの0.74〜0.94倍の時間）。数値はリポジトリ内のbuild（固定revisionのCandle）で測ったもので、crates.io版Candleでの性能は測っていません。
- ブラウザ（WebAssembly）での性能は測っていません。公開中のWebデモは今回のリリースに合わせて再デプロイしておらず、改善前のcommit `63324e0`の版のままです。
- `WeightSource`に既定の実装を持つメソッドが2つ増えました。既存の実装はそのままbuildできます。build hashが変わるため、`require_runtime_build`を使う場合とCLIでは、bundle manifestを作り直してください。

## License

Apache-2.0 (LICENSE, NOTICE). The prompt and decision procedure reproduce the MIT-licensed Jeff reference implementation; see THIRD_PARTY_NOTICES.md.
