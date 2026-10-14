# pure-jeff 0.2.0

With one thread, a resident `Model` now matches or beats the official Python/PyTorch Jeff implementation at every tested length from 128 to 8192 tokens, and uses less memory. **Outputs are bitwise identical to 0.1.1**: same probabilities, same judgments, same token counts.

```toml
[dependencies]
pure-jeff = "0.2.0"
```

## What changed

- **One conversion buffer per forward** ([#14](https://github.com/siska-tech/pure-jeff/issues/14)): every BF16 weight is converted into a single F32 buffer, reused for the whole forward, instead of newly allocated memory. Half of the conversion time was the first write to new pages. The buffer is lent to one operation at a time and dropped with the forward.
- **Query-block attention** ([#17](https://github.com/siska-tech/pure-jeff/issues/17)): full attention runs in blocks of 512 query rows against all keys. At 8192 tokens the peak working set falls from 7.8 to 2.1 GiB. Up to 512 tokens nothing changes.
- **Optional FP32 weights** ([#4](https://github.com/siska-tech/pure-jeff/issues/4)): `LoadOptions::retain_f32` converts the backbone weights except the embedding to F32 once at load and keeps them (about 1.9 GiB more, 0.6 s longer load). It saves about 5% per short decision and pays off for a resident model after roughly 6 to 9 decisions. Off by default; not offered by the CLI, whose workers make one decision per process.

Every element is computed with the same operations in the same order as before; the result is the same bits.

## Breaking change

`LoadOptions` has a new public field, `retain_f32`. Code that builds it with a struct literal must add `retain_f32: false` or `..LoadOptions::default()`. `LoadOptions::default()` is unchanged.

`WeightSource` gains `convertible_shape` and `load_f32_into`, with default implementations, so existing implementations compile unchanged. MSRV is still Rust 1.88.

## Performance

One thread, Windows 11, AMD Ryzen AI MAX+ 395, 39 artificial inputs, a preregistered plan with a session-level one-sided 95% bound. These are descriptive measurements on one machine, not guarantees ([record](https://github.com/siska-tech/pure-jeff/blob/main/docs/release-0.2.0-verification-2026-10-14.md)):

| Tokens | Official Jeff | pure-jeff 0.2.0 | Ratio (upper 95% bound) |
| ---: | ---: | ---: | --- |
| 128 | 1.48 s | 1.42 s | 0.955 (0.986) |
| 512 | 6.43 s | 5.26 s | 0.821 (0.830) |
| 874 | 10.80 s | 9.18 s | 0.862 (0.898) |
| 3206 (255 candidates) | 43.00 s | 37.91 s | 0.882 (0.891) |
| 8192 | 144.00 s | 126.06 s | 0.884 (0.905) |

| | Official Jeff | 0.1.1 | 0.2.0 |
| --- | ---: | ---: | ---: |
| Peak working set, up to 513 tokens | 3.88 GiB | 1.07 GiB | 1.09 GiB |
| Peak working set, up to 8192 tokens | 5.17 GiB | 7.8 GiB | 2.09 GiB |
| One request per process, 128 tokens | 13.1 s | 4.0 s | 3.8 s |
| Model load | 10.4 s | 1.9 s | 1.9 s |

- These figures come from the repository build (pinned Candle revision). **Speed with the crates.io Candle 0.11.0 was not benchmarked**, nor on other CPUs, on Linux, or with more than one thread. The 0.1.1 column was measured on the same machine.
- The browser demo engine passes its end-to-end checks in Chrome and Edge with unchanged outputs; on this machine it takes 3.3 s at 128 tokens and 12.6 s at 512 tokens, with a wide tail.

## Verification

- **Same outputs as 0.1.1:** all 39 benchmark inputs give bitwise-identical probabilities, judgments and failures in the repository build and in a clean project built only from crates.io.
- **Official implementation:** every input passes the numeric gate (largest probability difference 4.74e-6, 3.96e-6 with crates.io Candle); the seven official reference cases pass through the CLI worker; budget, candidate-count and 8192-token limits hold; a timed-out `Model` can be reused.
- CI on Windows and Linux; MSRV checked with Rust 1.88.0.

## Upgrading

- Re-create bundle manifests used with `LoadOptions::require_runtime_build` or the `jeff` CLI (`jeff lock`), because `runtime_build_hash()` changed.
- The prompt contract, policy, schemas and outputs are unchanged.

## 日本語の要約

- `pure-jeff` 0.2.0では、1 threadでモデルを常駐させた判断が、128〜8192 tokensのすべての長さで公式Jeff（Python/PyTorch）と同等以上の速さになり、メモリも公式より少なくなりました。**出力（確率・判断・tokens数）は0.1.1とbit単位で同じです。**
- **変更点**
  - 重み変換の共有buffer（既定）
  - full attentionのquery-block化（8192 tokensのpeakが7.8→2.1 GiB）
  - FP32重みの保持（`LoadOptions::retain_f32`、opt-in）
- **非互換**：`LoadOptions`にfieldが増えました。struct literalで作っている場合は、`..LoadOptions::default()`を追加してください。
- **測定の条件**：Windows・AMD Ryzen AI MAX+ 395・1 threadでの、リポジトリ内のbuildの値です。crates.io版Candle、ほかのCPU、Linux、複数threadでの速度は測っていません。

## License

Apache-2.0 (LICENSE, NOTICE). The prompt and decision procedure reproduce the MIT-licensed Jeff reference implementation; see THIRD_PARTY_NOTICES.md.
