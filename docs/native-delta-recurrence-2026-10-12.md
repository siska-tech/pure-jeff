# DeltaNetの逐次更新の高速化（2026-10-12）

[issue #1](https://github.com/siska-tech/pure-jeff/issues/1)。[forwardの内訳](native-forward-profile-2026-10-12.md)で約21〜26%を占めていた`delta_recurrence`（`src/backbone.rs`）を、**出力をbit単位で変えずに**書き換えた。ライブラリ、CLI、Webデモengineは同じ`src/backbone.rs`を使うので、3系統すべてに効く。

## 変更

状態`S`（headごとに128×128）の列`j`について、`delta[j]`、`S`の更新、`output[j]`は列`j`の値だけで決まる。そこで、loopの順序を「token → head → 全列」から「head → 32列のblock → token」に変えた。

- 32列×128行（16 KiB）の状態がL1 cacheに載ったまま、全tokenを処理する。変更前はtokenごとに全headの状態（1 MiB）を3回走査していた。
- decayの乗算と`delta`の累積を1回の走査にまとめた（走査は3回から2回になる）。
- 入力は`Vec<Vec<Vec<f32>>>`ではなく連続した`Vec<f32>`で受け取り、`exp(g)`と`q / sqrt(K)`は1回だけ計算する。

各要素が受ける演算と、`i`（K次元）についての加算の順序は変更前と同じである。FMAは使わず、`target-feature`も変えていない（既定のx86-64、Wasmはsimd128のまま）。そのため結果はbit単位で一致する。

列blockの幅は、512 tokens相当の入力で再帰部分だけを測って選んだ（1層あたり、変更前は約0.16秒）。8列で約0.047秒、16列で約0.039秒、32列で約0.032秒、64列で約0.039秒だった（単発の観測値）。

## 数値の確認

| 確認 | 結果 |
| --- | --- |
| 単体試験`delta_recurrence_is_bitwise_equal_to_the_reference` | 変更前の実装（試験内に原文のまま残した）と、乱数入力（seq 1／3／37）で全要素のbitが一致。x86-64のrelease・debug、wasm32-wasip1＋simd128（Node.js 24.21.0で実行）で合格 |
| 公式参照7件（128〜8192 tokens、最大255候補） | 最終hidden stateのSHA-256が、全件で変更前と一致。各2回の反復も一致。判断は公式と一致し、確率差の最大は4.679e-6（変更前と同じ値） |
| crates.io用package（`tools/check_package.py --manifest`） | crates.ioのCandle 0.11.0でbuildした利用者projectで、公式参照7件が合格。最大確率差3.457e-6で、0.1.0公開時の[記録](crate-release-results-2026-10-12.md)と同じ値 |
| Webデモengine | `tools/build_wasm.py engine`でbuildでき、host pathを含まない |

公式参照7件の照合には、新しい診断用example `runtime/rust/examples/forward_check.rs`を使った。golden fixtureのrequestをtokenizeしてtoken IDsが公式と一致することを確かめ、forwardを実行する。最終hidden stateのf32 bytesのSHA-256、forwardの時間、公式との確率差を出力する。bundle manifestのbuild hashは照合しない（変更前後で同じmanifestを使うため）。

変更前の版は、commit `cdaae95`に`forward_check.rs`だけを加えてbuildした（実行ファイルのSHA-256 `2e45e6b5…550d15`）。変更後の版は`6e79d1e2…28c0544`。

ブラウザでモデルを使うE2E（`apps/web-demo/run_w3.py`）は実行していない。Wasmでの一致は、上の単体試験（同じ入力で変更前の実装とbitが一致）によって確かめた。

## 時間

変更前と変更後を交互に（前・後・後・前）実行し、1 thread、各caseで変更前・変更後それぞれ4回測った。forwardだけの時間の中央値（最小〜最大）。

| case | tokens | 変更前（秒） | 変更後（秒） | 後／前 |
| --- | ---: | --- | --- | ---: |
| candidate-request | 128 | 3.14（2.92〜3.51） | 2.65（2.46〜2.81） | 0.84 |
| asr-unicode | 206 | 4.28（4.18〜4.33） | 3.52（3.47〜3.53） | 0.82 |
| long-text | 874 | 15.78（15.41〜16.13） | 12.70（12.57〜12.79） | 0.80 |
| maximum-candidates | 3206 | 63.01（62.91〜63.12） | 51.24（51.04〜51.31） | 0.81 |

8192 tokensは交互計測に含めていない。照合のための実行（各2回）では、変更前が204〜315秒、変更後が159〜160秒だった。ただし、変更前の実行中は並行してbuildしていたので、比較には使わない。

forwardは16〜20%短くなった。内訳での逐次更新の比率（21〜26%）から見ると、逐次更新の時間の大部分がなくなった計算になる。残りは主に行列積と要素ごとの演算である（[#2](https://github.com/siska-tech/pure-jeff/issues/2)）。

条件：Core i7-1360P、Windows 11 Home、Rust 1.99.0、AC電源。背景負荷は制御していない（VS Codeなどは起動したまま）。この機械での記述的な観測値であり、SLOや他の環境での性能を示すものではない。公式Jeffとの比較は測り直していない。

## 利用者への影響

- 出力は変わらない。goldenと既存の記録はそのまま有効である。
- runtimeのsourceが変わったので、build hashが変わる。CLIで使うbundle manifestは`jeff lock`で作り直す。ライブラリは既定ではbuild hashを照合しない（`LoadOptions::require_runtime_build`）。

## 証跡

[research/native-delta-recurrence-2026-10-12/](research/native-delta-recurrence-2026-10-12)：`golden.jsonl`（公式参照7件、変更前・変更後）、`interleaved.jsonl`（交互計測の各block）。
