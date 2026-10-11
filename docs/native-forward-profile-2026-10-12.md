# Native forwardの内訳（2026-10-12）

[改善計画](native-fp32-retention-plan.md)の第1段階。Nativeのforward（1 thread、mmapしたBF16重み）がどこで時間を使っているかを測った。**診断のみで、推論の実装は変えていない。**

## 方法

- `runtime/wasm/build.rs`が、凍結した`backbone.rs`から計時用のcopy（`backbone_profiled.rs`）を生成する。追加するのは計時だけで、演算は変えない。置換はすべて、正確に1回一致することをbuild時に検査する。
- `runtime/wasm/examples/forward_profile.rs`が、各入力について凍結版のforwardを1回、計時版を3回実行する。**計時版の最終hidden stateは、凍結版とbit単位で一致する**ことを毎回確かめる（全18回一致）。
- token IDsは公式参照と一致することを確認した。1 thread、Core i7-1360P、Windows 11。単発の観測値。
- 分類は排他的なもの（重みの読込、BF16→FP32変換、行列積、DeltaNetの逐次更新、embeddingの読込、その他）と、block単位の包含的なものがある。

## 結果（3回の中央値）

| tokens | forward | 重み読込 | BF16→FP32 | 行列積 | DeltaNet再帰 | embedding読込 | その他 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 | 2.87秒 | 6% | 11% | 42% | 21% | 3% | 17% |
| 206 | 4.14秒 | 4% | 8% | 45% | 23% | 2% | 18% |
| 256 | 4.92秒 | 3% | 7% | 45% | 24% | 2% | 19% |
| 384 | 7.34秒 | 2% | 5% | 48% | 25% | 1% | 20% |
| 512 | 9.68秒 | 2% | 4% | 48% | 25% | 1% | 20% |
| 874 | 15.99秒 | 1% | 2% | 49% | 26% | 0% | 22% |

「その他」は、正規化、活性化、RoPE、softmax、tensorの生成・連結などの要素ごとの演算。block単位では、linear attention（18層）が全体の約58%、MLPが約31%、full attention（6層）が約9%を占める（512 tokens）。

## 読み取れること

- **FP32保持で減らせるのは最大で「重み読込＋変換＋embedding読込」**、512 tokensで約7%、128 tokensで約20%に限られる。KazeJudgeでFP32保持が512 tokensで7.3%の短縮だったことと合う。公式Jeffとの差（512 tokensで約34%）は埋められない。
- **大きいのは行列積（約半分）とDeltaNetの逐次更新（約4分の1）**。逐次更新は`delta_recurrence`のtokenごと・headごとのscalar loopで、既定のx86-64 target（SSE2）でbuildされている。
- 長い入力ほど、行列積・逐次更新・その他の比率が上がる。

生データ：[research/native-profile-2026-10-12/forward-profile.jsonl](research/native-profile-2026-10-12/forward-profile.jsonl)。
