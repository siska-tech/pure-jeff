# Native推論の改善計画：FP32重み保持のoption化

2026-10-11。**計画のみ。実装しておらず、公開準備より優先しない。** 既存の証跡（KazeJudgeでの実験、今回のbenchmark）から、BF16 mmapを既定のまま、FP32重みの保持をoptionにする案の妥当性と、性能・メモリのtradeoffを整理する。

## 現状

Native（`runtime/rust`）は、`model.safetensors`をmmapし、forwardのたびにBF16の重みを読み出してFP32へ変換する。この方式は起動が速く、メモリが小さい。代わりに、変換の費用が毎回かかる。

[今回のbenchmark](benchmark-results-2026-10-11.md)（1 thread、モデル常駐）では、公式Jeff（PyTorch、load時に全重みをFP32化）がNativeより速かった。

| tokens | 公式Jeff | Native（BF16 mmap） | Jeff／Native |
| ---: | ---: | ---: | ---: |
| 128 | 1.52秒 | 3.00秒 | 0.51 |
| 512 | 6.33秒 | 9.60秒 | 0.66 |

メモリは逆で、Native residentは1.93 GiB、公式Jeffは3.78 GiBだった。

## 既存の証跡：FP32保持の効果（KazeJudge、凍結Nativeから生成した別crate）

いずれも1 thread、有効・物理512 tokens、独立3組、各n＝12。数値は凍結Nativeの候補確率と**全件bit単位で一致**した。

| 実験 | compute中央値 | 初期化中央値 | process peak最大 |
| --- | --- | --- | --- |
| mmap → 全473 tensorをFP32保持 | 9.79 → 9.07秒（−7.3%） | 2.05 → 3.81秒 | 1.95 → 4.84 GiB |
| 全473 → text用320 tensorのみ保持 | 9.21 → 8.93秒（記述的） | 3.82 → 3.54秒 | 5.19 → 4.59 GB |
| FP32 text320で1／2／4／8 threads | 9.10／7.12／6.74／7.16秒 | — | — |

出典：KazeJudge commit `43f315b`の`docs/onnx-tract-native-retained.md`、`docs/onnx-tract-native-text.md`、`docs/onnx-tract-native-threads.md`。

## 評価

- **効果は限定的**：FP32保持で短縮できるのは512 tokensで約7%である。公式Jeffとの差（約34%）の大部分は、変換以外の要因にある。候補は、DeltaNetの逐次更新（`backbone.rs`の`delta_recurrence`はtokenごとのscalar loop）と、GEMMの実装差（Candle gemmとPyTorchのoneDNN／MKL）。ただし、Nativeの演算別の内訳はまだ測っていない。
- **メモリの代償が大きい**：peakは約2.5倍（4.6〜4.8 GB）になり、公式Jeff（約3.8 GiB）より大きい。Nativeの利点（起動1.9秒、1.5〜1.9 GiB）が失われる。
- **数値は保てる**：既存の実験では確率がbit単位で一致した。goldenと既存の結果は変わらない見込み。
- **thread**：4 threadsで約26%短縮したが、短い入力で反復時の確率差が1e-6を超える問題（KazeJudgeで未解決）があり、そのままでは採用できない。

## 方針案

1. **先に内訳を測る**：Nativeのforwardを、BF16→FP32変換、GEMM（linear）、DeltaNetの逐次更新、attention、その他に分けて計時する、診断用のexampleを追加する。結果を変えず、凍結sourceも変えない。これで、どれを改善すると効くかを決める。
2. **FP32保持はopt-inのoptionにする**：既定はBF16 mmapのままにする。workerのCLIまたはProviderの設定でFP32保持（text用320 tensorのみ）を選べるようにし、bundle manifestのpolicyや出力は変えない。runtimeのsourceが変わるため、build hashが変わり、`jeff lock`のやり直しが必要になる。受入条件は、goldenとbenchmarkの全caseで、確率が既定経路とbit単位で一致すること。
3. **DeltaNetをchunk化するのは別の判断**：PyTorchの`chunk_gated_delta_rule`のようなGEMMを使う形にすれば、大きく速くなる可能性がある。ただし、演算順が変わり、確率は既存の結果とbit単位では一致しなくなる（公式参照との差1e-4以内という契約は維持できる見込み）。「既存の推論結果を変えない」という制約に関わるため、実施するかは別途判断する。
4. **複数thread**は、反復差の原因を特定してから扱う。

## 優先度

公開準備（ライセンス、CI、W4）が先。上の1は数時間で済む診断なので、公開後の最初の作業に向く。2はその結果、変換の比率が大きいとわかった場合に実施する。
