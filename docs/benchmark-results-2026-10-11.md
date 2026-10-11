# 公式Jeff／Rust Native／ブラウザWasm：1 thread横並びベンチマークの結果

2026-10-11。[計画](benchmark-plan.md)どおりに、commit `13a35d0`で測定した。**事前登録した妥当性の条件をすべて満たした。** 性能はこの機械・この入力での記述的な観測値であり、SLOの判定、採用判断、一般的な高速化倍率ではない。

## 要点

- **one-shot（1要求ごとに新しいprocess）**：Rust Nativeが速い。中央値で公式Jeffの1.65〜2.78倍速い（128 tokensで5.45秒対15.14秒）。差の大部分は起動で、公式Jeffは`import torch`／transformersとモデルの読込に約12秒かかる。Nativeは約2秒。
- **resident（モデル常駐）**：1回の判断は**公式Jeffが最も速い**。Nativeの0.51〜0.66倍の時間（128 tokensで1.52秒対3.00秒、512 tokensで6.33秒対9.60秒）。Wasmはnativeの1.81〜2.16倍の時間。
- **メモリ**：Nativeが最も小さい（one-shot 1.49 GiB、resident 1.93 GiB）。公式Jeffは約3.8 GiB、ブラウザWasmは約2.8 GiB（browser全体、linear memoryは2.36 GiB）。
- **数値**：全判断で公式参照と判断・token数が一致した。確率差の最大は、Native 5.07e-6、Wasm 2.38e-6（基準1e-4）。各系統の反復はbit単位で一致した。

residentで公式Jeffが速いのは、load時に全重みをFP32に変換して保持し、PyTorchの最適化されたCPU kernelで計算するためと考える。Nativeはmmapした重みをforwardのたびにBF16からFP32へ変換する。KazeJudgeの実験（FP32保持、text320）では、変換をなくすとNativeのforwardが短縮されたが、メモリが増えた。この測定で原因を切り分けたわけではない。

## 結果

### one-shot（親から見た経過時間、各n＝3）

process起動、bundleのhash検証、モデル読込、推論、応答の書込を含む。

| case | tokens | 公式Jeff（秒） | Native（秒） | Jeff／Native |
| --- | ---: | --- | --- | ---: |
| candidate-request | 128 | 15.14（14.98〜15.22） | 5.45（5.44〜5.69） | 2.78 |
| asr-unicode | 206 | 16.17（16.08〜16.41） | 6.80（6.62〜6.88） | 2.38 |
| synthetic-ocr-ja-2-256 | 256 | 16.76（16.24〜16.90） | 7.72（7.48〜7.74） | 2.17 |
| synthetic-asr-unicode-2-384 | 384 | 17.85（17.80〜18.20） | 9.89（9.88〜9.92） | 1.81 |
| synthetic-asr-mixed-2-512 | 512 | 19.91（19.89〜20.10） | 12.10（12.03〜12.14） | 1.65 |
| synthetic-ocr-ascii-8-512 | 512 | 20.09（19.94〜20.52） | 12.14（11.99〜12.17） | 1.66 |

中央値（最小〜最大）。

### resident（1判断の時間、各n＝6、warm-upを除く）

prompt・tokenize、forward、readout・policyの合計。

| case | 公式Jeff（秒） | Native（秒） | Wasm（秒） | Jeff／Native | Wasm／Native |
| --- | --- | --- | --- | ---: | ---: |
| candidate-request（128） | 1.52（1.47〜1.55） | 3.00（2.97〜3.02） | 5.43（5.20〜5.49） | 0.51 | 1.81 |
| asr-unicode（206） | 2.44（2.42〜2.54） | 4.33（4.29〜4.42） | 8.37（7.99〜8.70） | 0.56 | 1.93 |
| synthetic-ocr-ja-2-256 | 3.00（2.93〜3.22） | 5.21（5.19〜5.23） | 10.40（10.27〜10.48） | 0.58 | 2.00 |
| synthetic-asr-unicode-2-384 | 4.65（4.51〜4.80） | 7.33（7.29〜7.47） | 15.16（14.73〜15.42） | 0.63 | 2.07 |
| synthetic-asr-mixed-2-512 | 6.33（6.24〜6.48） | 9.60（9.48〜10.22） | 20.63（19.97〜21.58） | 0.66 | 2.15 |
| synthetic-ocr-ascii-8-512 | 6.37（6.28〜6.48） | 9.62（9.58〜10.14） | 20.82（19.93〜21.29） | 0.66 | 2.16 |

### 起動（residentの各session、n＝3）

| 系統 | 中央値（秒） | 内容 |
| --- | ---: | --- |
| 公式Jeff | 12.41 | bundle検証約1.1秒、`import torch`／`jeff.model`約9秒、`DecisionModel`構築約2.3秒 |
| Native | 1.93 | bundle検証約1.1秒、tokenizerと回答語彙の検査約0.8秒 |
| Wasm | 7.41 | 資産の読込（127.0.0.1から）1.6〜2.2秒、open（SHA-256、tokenizer）5.2〜5.5秒 |

### メモリ（process tree、中央値／最大）

| 系統・mode | Working Setの合計の最大 |
| --- | --- |
| 公式Jeff one-shot | 3.74／3.80 GiB |
| Native one-shot | 1.49／1.51 GiB |
| 公式Jeff resident | 3.78／3.84 GiB |
| Native resident | 1.93／1.94 GiB |
| Wasm resident（browser全体） | 2.80／3.01 GiB。linear memoryは2,416 MiB |

shared pageをprocessごとに数え、100 ms間隔で採取した値である。private RSSや厳密なpeakではない。

## 条件と限界

- Core i7-1360P（16論理CPU）、Windows 11、電源設定はバランス、AC電源。利用者のVS CodeとChromeは起動したままで、背景負荷は制御していない（開始時と終了時のprocess一覧を記録）。OSのfile cacheは消していない。
- threadは公式Jeffのintra-op 1（`OMP_NUM_THREADS=1`、`MKL_NUM_THREADS=1`）、Native 1、Wasm 1。公式Jeffのinterop threadは既定の12のままだった。単一のforwardでは主にintra-opが使われると考えるが、影響は検証していない。
- 入力は人工の6件。n＝6／3と少ないため、p95やtailは評価しない。
- Wasmはheadless Chromeのみ。one-shotに相当する測定はなく、起動時間で代える。
- 重みの保持方式・演算kernel・DeltaNetの実装が系統ごとに異なる。言語やruntime単体の差とは解釈しない。

## 測定前に見つけた問題

最初のsmoke runで、Nativeの全判断が「unsupported manifest/runtime/prompt」で失敗した。Native bundle manifestは、runtimeのsourceから計算したbuild hashを固定している。そのsourceには契約crateの`src/lib.rs`も含まれる。KazeJudgeのW3（commit `5026e21`）で`Observation::validate_within`を追加したため、新しくbuildした`jeff.exe`のbuild hashが変わっていた。

pure-jeffでは、build hash以外が同一のmanifest（`models/jeff-rust-bundle-pj.json`）を`jeff lock`で作り直した。checkpointの11ファイル、policy、promptのhashは元のP3 manifestと一致する。そのうえで、公式参照6件の照合で判断の一致と最大誤差5.066e-6を再確認した（`native-golden-validation.json`）。KazeJudgeでも、次に`jeff.exe`をbuildしたときに同じ再lockが必要になる。

## 証跡

[research/benchmark-2026-10-11/](research/benchmark-2026-10-11)：事前登録（実行順、seed、全hash、開始時の環境）、集計、one-shotの各実行、residentの各session、終了時の環境、Nativeの公式参照照合。各判断の生データは`experiments/runs/bench-80e0cec/`（ignored）。
