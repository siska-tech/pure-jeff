# 要素ごとの演算の内訳と融合（2026-10-12）

[issue #2](https://github.com/siska-tech/pure-jeff/issues/2)。[forwardの内訳](native-forward-profile-2026-10-12.md)で「その他」（17〜22%）としていた要素ごとの演算を、処理ごとに分けて測った。そのうえで、大きいものを**出力をbit単位で変えずに**書き換えた。[DeltaNetの逐次更新](native-delta-recurrence-2026-10-12.md)（#1）の後の`src/backbone.rs`が対象である。

## 方法

`runtime/rust/examples/forward_breakdown.rs`を追加した。中身は`src/backbone.rs`のcopyに、処理ごとの計時を加えたもの（`profiled`）である。

- 計時は排他的に数える。入れ子になった区間の時間は、外側の区間から差し引く。
- 毎回、最終hidden stateが`pure_jeff::backbone::forward`とbit単位で一致することを確かめる。
- 1 thread、各case 3回の中央値。

変更前の内訳は、変更前の`src/backbone.rs`のcopyで測った（[証跡](research/native-elementwise-2026-10-12/forward_breakdown-before.rs.txt)）。commitしたexampleは、変更後のcopyである。

## 変更前の内訳

forwardに占める割合。計時できた区間の合計は、forwardの95〜98.5%だった。

| 区分 | 128 tokens | 206 | 874 | 3206 |
| --- | ---: | ---: | ---: | ---: |
| 行列積（linear） | 49.5% | 54.4% | 60.9% | 56.7% |
| BF16→FP32変換 | 13.6% | 9.7% | 2.7% | 0.7% |
| 重みの読込 | 6.9% | 4.9% | 1.4% | 0.3% |
| **conv1d（4 tapの因果畳み込み）** | **6.8%** | **7.6%** | **9.1%** | **8.1%** |
| DeltaNetの逐次更新 | 5.1% | 6.1% | 7.3% | 7.6% |
| embedding | 4.1% | 2.9% | 0.8% | 0.2% |
| MLPのsilu×積 | 1.9% | 2.2% | 2.7% | 2.3% |
| conv後のsilu | 1.8% | 2.0% | 2.3% | 2.1% |
| q・kのL2正規化 | 1.1% | 1.3% | 1.4% | 1.3% |
| zのsilu×ゲート | 0.8% | 0.9% | 1.1% | 0.9% |
| RMSNorm | 0.6% | 0.7% | 1.2% | 1.1% |
| full attentionのscore行列積 | 0.3% | 0.5% | 1.9% | 6.5% |
| full attentionの確率×V行列積 | 0.2% | 0.3% | 1.3% | 4.3% |
| maskとsoftmax | 0.2% | 0.3% | 1.2% | 3.9% |
| その他（各0.8%以下の10区分。最大はDeltaNet出力の正規化） | 1.9% | 2.1% | 2.5% | 2.3% |
| 計時なし（文字列の生成など） | 5.1% | 4.1% | 2.1% | 1.5% |

forwardの時間は2.42／3.46／12.65／51.73秒。

要素ごとの演算で目立つのはconv1dだった。計算量はわずかなのに、forwardの7〜9%を使っていた。4回のshiftのたびに`narrow`、`pad_with_zeros`（zerosの確保と連結）、broadcast積、加算で配列を確保し直していたためである。

## 変更

要素ごとに独立した演算だけを、Candleのopの組み合わせから1本のloopへ書き換えた。

- **conv1d＋silu**（`conv_silu`）：出力の各要素は、0.0から始めて、tap 0〜3（`3 - j` token前の入力。先頭より前は0.0）と重みの積を順に足す。最後にsiluをかける。元の「0で初期化し、shiftしてpaddingした積を順に足す」計算と、要素ごとの演算と順序が同じになる。
- **MLPのsilu×積、zのsilu×ゲート**（`zip_map`）：中間の配列を作らずに、要素ごとに`silu(g) * u`、`a * silu(z)`を計算する。
- **silu**は、Candleのf32実装と同じ式`v / (1.0 + (-v).exp())`で書いた。この式は、リポジトリで使う固定revisionとcrates.ioの0.11.0で同じである。
- 入力は`storage_and_layout`でcopyせずに読む。連続していない入力のときは、copyしてから読む。

総和・平均（RMSNorm、L2正規化）、softmax、行列積は書き換えていない。これらはCandleの版によって加算の順序が変わりうるので、Candleに任せたままにする。

## 数値の確認

| 確認 | 結果 |
| --- | --- |
| 単体試験`fused_element_wise_steps_are_bitwise_equal_to_candle_ops` | conv1d＋silu、silu×積、silu×ゲートについて、元のCandleの計算と乱数入力（seq 1／2／3／4／9。tapが入力の外にはみ出す短い入力を含む。連続していない入力も含む）で、全要素のbitが一致した。x86-64のrelease・debug、wasm32-wasip1＋simd128で合格した。siluの式を`v * (1 / (1 + exp(-v)))`に変えると失敗することも確かめた |
| 公式参照7件（128〜8192 tokens） | 最終hidden stateのSHA-256が、全件で0.1.0（#1より前）の基準値と一致した。各2回の反復も一致した |
| `forward_breakdown` | 変更前・変更後とも、計時つきcopyの出力は全24回で本物のforwardとbit単位で一致した |
| crates.io用package（`tools/check_package.py --manifest`） | crates.ioのCandle 0.11.0で、公式参照7件に合格した。ケースごとの確率差は#1の検証時と同じ値だった |
| Webデモengine | `tools/build_wasm.py engine`でbuildでき、host pathを含まない |

## 時間

変更前（#1の後のmain）と変更後を交互に（前・後・後・前）実行し、1 thread、各caseで変更前・変更後それぞれ4回測った。forwardだけの時間の中央値（最小〜最大）。

| case | tokens | 変更前（秒） | 変更後（秒） | 後／前 |
| --- | ---: | --- | --- | ---: |
| candidate-request | 128 | 2.66（2.39〜2.84） | 2.57（2.30〜2.66） | 0.97 |
| asr-unicode | 206 | 3.44（3.35〜3.51） | 3.24（3.18〜3.28） | 0.94 |
| long-text | 874 | 12.47（12.15〜12.64） | 11.41（11.38〜11.54） | 0.92 |
| maximum-candidates | 3206 | 51.42（51.01〜51.56） | 47.03（46.78〜47.38） | 0.91 |

128 tokensでは、変更前後の範囲が重なっている。内訳で見た処理ごとの時間（中央値）は次のとおり。

| 処理 | 128 tokens | 874 tokens | 3206 tokens |
| --- | --- | --- | --- |
| conv1d＋silu | 0.208 → 0.051秒 | 1.437 → 0.373秒 | 5.261 → 1.315秒 |
| MLPのsilu×積 | 0.047 → 0.031秒 | 0.335 → 0.231秒 | 1.211 → 0.809秒 |
| zのsilu×ゲート | 0.019 → 0.013秒 | 0.140 → 0.097秒 | 0.478 → 0.335秒 |

条件：Core i7-1360P、Windows 11 Home、Rust 1.99.0、AC電源。背景負荷は制御していない。この機械での記述的な観測値である。

実行ファイルのSHA-256：forward_check 変更前`6e79d1e2…28c0544`／変更後`6b7fa455…2a383ed`、forward_breakdown 変更前`daf05acb…117a051b`／変更後`60609203…8477cbe7`。

## 残り

要素ごとの演算で残るのは、各1.5%以下である（L2正規化、RMSNorm、DeltaNet出力の正規化など）。どれも総和を含むので、bit単位で保つにはCandleの加算順序に合わせる必要がある。効果に対して手間が大きいので、今回は対象にしない。

大きいのは次の処理で、いずれも要素ごとの演算ではない。

- **行列積**：50〜61%。
- **短い入力での重みの読込とBF16→FP32変換**：128 tokensで約20%。重みの読込とBF16→FP32変換の間で配列を1回copyしているので、直接変換すればメモリを増やさずに減らせる可能性がある（[#4](https://github.com/siska-tech/pure-jeff/issues/4)の前段として検討できる）。embeddingも、表全体（約500 MB）を読んでから必要な行を選んでいる。
- **長い入力でのfull attention**：3206 tokensで約15%（score・確率の行列積とsoftmax）。

## 利用者への影響

- 出力は変わらない。
- runtimeのsourceが変わるので、build hashが変わる。CLIで使うbundle manifestは`jeff lock`で作り直す。

## 証跡

[research/native-elementwise-2026-10-12/](research/native-elementwise-2026-10-12)：

- `breakdown-before.jsonl`、`breakdown-after.jsonl`：内訳
- `golden.jsonl`：公式参照7件、変更後
- `interleaved.jsonl`：交互計測
- `forward_breakdown-before.rs.txt`：変更前の計時つきcopy
