# 公式Jeff／Native：性能同等の判定（baseline）

2026-10-13。issue #13。[計画](benchmark-parity-plan.md)どおりに、HEAD（commit `ebe0870`。ライブラリは`0c71911`から変更なし）と公式Jeffのbaselineを、公開APIの経路で取得した。計画、入力、統計、規則は測定前にcommitし、各runの`preregistration.json`にも保存した。測定後に変更したものはない。

## 要点

- **short（128〜512 tokens）：不受入。** 入力群128で、Nativeは公式Jeffより**13%遅い**と判定された（点推定1.134、95%区間1.108〜1.160）。256／384／512は同等と判定された（0.981／0.907／0.860）。
- **long（874／3206／8192 tokens）：受入。** 3群とも同等で、Nativeが12〜14%速い（0.885／0.876／0.858）。
- **全長の受入（short かつ long）：不受入。** 128群が残る課題である。
- **数値gate：全run・全系統の全判断で違反はなかった。** 公式参照との最大差は、Native 4.74e-6、Wasm 2.86e-6、公式Jeff 0（参照と同じ環境）。同じ系統・同じ経路の反復は、すべてbit単位で一致した。
- **one-shot（既定のCLI worker）：** Nativeは128 tokensで4.04秒（公式Jeffは13.04秒）、512 tokensで7.87秒（同18.07秒）。peak working setはNative 1.0 GiB、公式Jeff 3.8〜3.9 GiB。
- **メモリの逆転：** 8192 tokensでは、Nativeのpeak（7.8 GiB）が公式Jeff（5.2 GiB）を上回った。512 tokens以下では、Native 1.07 GiBに対し公式Jeff 3.86 GiB。

## 結果

### short（6 block、各case・系統24観測、API境界、warm）

入力群ごとの判定。値は、blockごとの（Nativeの中央値／公式の中央値）の幾何平均を、block間で集計したもの。

| 入力群 | case | 点推定 | 片側95%区間 | 判定 |
| --- | --- | ---: | --- | --- |
| 128 | 127／128（2件）／129 | 1.134 | 1.108〜1.160 | **遅い** |
| 256 | ja-2、ascii-8 | 0.981 | 0.961〜1.001 | 同等 |
| 384 | asr-unicode-2、ascii-8 | 0.907 | 0.888〜0.926 | 同等 |
| 512 | 511／512（2件）／513 | 0.860 | 0.856〜0.865 | 同等 |

case別の中央値（秒）。

| case | tokens | 公式Jeff | Native | Native／Jeff |
| --- | ---: | ---: | ---: | ---: |
| synthetic-ocr-ja-2-127 | 127 | 1.486 | 1.682 | 1.137 |
| candidate-request | 128 | 1.480 | 1.685 | 1.144 |
| synthetic-ocr-ja-2-128 | 128 | 1.484 | 1.681 | 1.134 |
| synthetic-ocr-ja-2-129 | 129 | 1.505 | 1.689 | 1.120 |
| synthetic-ocr-ja-2-256 | 256 | 2.949 | 2.924 | 0.988 |
| synthetic-ocr-ascii-8-256 | 256 | 2.991 | 2.919 | 0.974 |
| synthetic-asr-unicode-2-384 | 384 | 4.652 | 4.174 | 0.902 |
| synthetic-ocr-ascii-8-384 | 384 | 4.647 | 4.189 | 0.911 |
| synthetic-ocr-ja-2-511 | 511 | 6.350 | 5.474 | 0.864 |
| synthetic-ocr-ja-2-512 | 512 | 6.350 | 5.483 | 0.863 |
| synthetic-ocr-ascii-3-513 | 513 | 6.432 | 5.495 | 0.853 |
| synthetic-ocr-ascii-8-512 | 512 | 6.374 | 5.481 | 0.861 |

128群の4件は、どれも単独でも「遅い」と判定された（上限1.14〜1.18）。全block・全群で証拠不足がなかったので、登録した追加blockは実行していない。

その他の境界の値（中央値、各n＝6）：

| 境界 | 公式Jeff | Native |
| --- | ---: | ---: |
| load | 10.35秒（verify＋import＋model構築） | 1.91秒（`Model::load`） |
| 初回の判断（513 tokens、warm-upの1件目） | 6.53秒 | 5.84秒 |

### long（6 block、各case・系統24観測）

| 入力群 | case | 公式Jeff（秒） | Native（秒） | 点推定 | 片側95%区間 | 判定 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 874 | long-text | 10.90 | 9.49 | 0.885 | 0.856〜0.915 | 同等 |
| 3206 | maximum-candidates（255候補） | 43.58 | 38.18 | 0.876 | 0.870〜0.882 | 同等 |
| 8192 | token-limit-8192 | 144.88 | 125.03 | 0.858 | 0.837〜0.879 | 同等 |

公式Jeffの8192 tokensは、139〜153秒と幅が広い。Nativeは124〜126秒だった。

### one-shot（既定のCLI worker、10 block、AB／BA交互）

| case | 公式Jeff 中央値（範囲） | Native 中央値（範囲） | peak WS 公式／Native |
| --- | --- | --- | --- |
| candidate-request（128） | 13.04秒（12.99〜13.21） | 4.04秒（4.02〜4.09） | 3.81／1.04 GiB |
| synthetic-ocr-ja-2-512 | 18.07秒（17.87〜18.30） | 7.87秒（7.82〜7.89） | 3.93／1.06 GiB |

範囲は中央値の±1%に収まっている。このため、`compare_runs.py`による5%を超える退行の検出には十分な分解能がある。動作確認として、smoke run（1 block）をこのbaselineと比べた。差は±1%以内で、確率はbit単位で一致した（`research/.../compare-runs-selfcheck.json`）。

### Wasm（現行のWebデモengine、6 session、各case 24観測）

| tokens | 中央値（秒） | 範囲（秒） |
| --- | ---: | --- |
| 127〜129 | 3.57〜3.63 | 3.25〜7.34 |
| 256 | 6.94〜6.96 | 6.32〜12.51 |
| 384 | 10.27〜10.29 | 9.31〜16.11 |
| 511〜512 | 13.76〜13.78 | 12.59〜21.59 |

load（engine取得、資産のdownload、逐次hash、Cache API書込、open）は8.34秒、初回の判断は12.93秒、browser全体のpeakは4.38 GiB、linear memoryは最大2.42 GiB（いずれも中央値・最大）。最大値は中央値の1.5〜2倍になることがあり、tailのばらつきが大きい。512 tokensを超える入力は、すべて`budget_exceeded`で拒否された（gateで確認）。Wasmは同等判定の対象外である。

### メモリ（process treeのWorking Setの最大）

| run | 公式Jeff | Native |
| --- | ---: | ---: |
| short（513 tokens以下、gateを含む） | 3.86 GiB | 1.07 GiB |
| long（8192 tokensまで、gateを含む） | 5.17 GiB | **7.80 GiB** |

## 入力と数値gate

- **catalog**：39件（`bench/cases/catalog.json`）。これまでの入力を重複除去した35件に、生成した127／129 tokensの2件と、policy境界付近の4件を加えた。
- **token ID**：全件で公式processorとNativeのID列が一致した。8193 tokensは両方が拒否した。
- **以前の公式参照との差**：今回取り直した公式参照は、以前に保存した公式参照（golden、W2）と最大2.4e-6の差で、判断はすべて一致した。
- **policy境界**：Native（API）で651件を探索して固定した。公式も同じ判断で、差は最大4.7e-6だった（[探索log](research/benchmark-parity-2026-10-13/policy-search.json)）。

| 入力 | top1 | margin | 判断 |
| --- | ---: | ---: | --- |
| policy-top1-above | 0.702196 | 0.404 | 選択 |
| policy-top1-below | 0.699019 | 0.398 | 保留 |
| policy-near-tie | 0.379 | 0.0025 | 保留 |
| policy-margin-near（3候補） | 0.444 | 0.0859 | 保留 |

  移管済みの`synthetic-asr-unicode-2-128`も、top1＝0.7030と境界に近い。marginの閾値（0.7／0.1の下では判断を左右しない）、等号、nextafter、同点は、policy単体試験の範囲として区別した。
- **gateを通した判断の数**：shortは各系統95件（block 0）＋60件×5、longは54件＋15件×5、Wasmは94件＋55件×5、one-shotは40件。

## 診断経路

`forward_breakdown`（計時版のbackbone copy）を測った（128 tokens・512 tokensで各4回）。計時版の最終hiddenは毎回ライブラリとbit単位で一致し、同じprocessで交互に測ったライブラリforwardとの差は−1〜＋2%だった。API境界の値（128 tokensで1.68秒）は、forwardだけの値（1.67〜1.69秒）とほぼ同じで、`Model::decide`の検査とartifact作成の費用は誤差の範囲だった。速度の判定には、計時を入れないAPI経路だけを使った。

## 条件

- **機械**：AMD Ryzen AI MAX+ 395（16コア32 thread、AVX-512）、Windows 11、電源設定はバランス、AC電源。温度はWMIで読めなかった（`null`として記録）。CPUの固定はしていない（affinity maskは全CPU）。背景負荷は各sessionの前後で0〜10%、processor performanceは111〜160%。
- **前回の測定との比較**：前回の結果（[2026-10-11](benchmark-results-2026-10-11.md)、[2026-10-12](benchmark-results-2026-10-12.md)）とは**機械が違う**（前回はCore i7-1360P）ため、比較できない。旧runの合否・閾値は変更していない。
- **公式Jeff**：torch 2.14.0（CPU capability AVX512、oneDNN、MKL、OpenMP 1 thread）、transformers 5.17.0。
  - Jeffの`uv.lock`から`uv sync --no-default-groups`で構築した。
  - Qwen3.5のlinear attention（`causal_conv1d`、`chunk_gated_delta_rule`）は、PyTorchの参照実装へのfallbackで動いた（transformersの警告どおり）。
- **Native**：rustc 1.97.1、固定revisionのCandle（`has_mkl=false`、`with_avx=true`）、1 thread。
  - compile時にはAVX系のtarget featureを有効にしていない（実行時の検出は、AVX2、FMA、AVX-512、AVX-VNNI）。
- **Wasm**：HeadlessChrome 154。export除去済みの`engine.wasm`を、デモの`engine-worker.js`経由で動かした。
- **他processとの重複**：build・installと測定は重ねていない。各sessionの前に確認した。
  - VS Codeの拡張機能が常駐させている`uv tool run`のserverは、installではないので許容し、背景負荷として記録した。
  - 4つのrunは連続して実行した（short→one-shot→wasm→long、計約7時間）。

## 次の作業への含意

- 128群（短いprompt）の約13%の遅れが、同等を阻む唯一の項目である。長さに比例しない固定費（weight変換、層ごとの準備など）が候補だが、今回は原因を切り分けていない。改善は別のissueで扱い、このbaselineと同じ計画・同じseedで再測定する。
- 8192 tokensでNativeのメモリが公式Jeffを上回る点は、長い入力で問題になりうる。

## 証跡

[research/benchmark-parity-2026-10-13/](research/benchmark-parity-2026-10-13)：

- run別のdirectory（`short`、`long`、`oneshot`、`wasm`）。それぞれに事前登録、集計、session別の生データ（全判断・gate結果・前後の環境）、終了時の環境、driverのlogがある。
- Nativeのgolden 7件の照合（最大誤差5.066e-6）。
- policy境界の探索log。
- 診断copyのoverhead。
- `compare_runs.py`の動作確認。
