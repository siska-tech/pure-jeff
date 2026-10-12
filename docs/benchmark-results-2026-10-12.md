# 公式Jeff／Rust Native／ブラウザWasm：1 thread横並びベンチマークの再測定

2026-10-12。Nativeの改善3件（[#1](native-delta-recurrence-2026-10-12.md)、[#2](native-elementwise-2026-10-12.md)、[#8](native-weight-load-2026-10-12.md)）の後のcommit `b642011`で、[前回](benchmark-results-2026-10-11.md)と同じ[計画](benchmark-plan.md)・同じseed（実行順も同じ）で測り直した。**事前登録した妥当性の条件をすべて満たした。** 性能はこの機械・この入力での記述的な観測値であり、SLOの判定、採用判断、一般的な高速化倍率ではない。

## 要点

- **resident（モデル常駐）**：Nativeの1判断は前回より31〜32%短くなった（128 tokensで3.00秒→2.06秒、512 tokensで9.60秒→6.77秒）。公式Jeffはまだ速いが、比（公式Jeff／Native）は0.51〜0.66から0.74〜0.94に縮んだ。512 tokensでは差が6%になった。
- **one-shot（1要求ごとに新しいprocess）**：Nativeは公式Jeffの1.97〜3.02倍速い（前回1.65〜2.78倍）。
- **メモリ**：Nativeのresidentは1.94 GiBから1.07 GiBに減った。公式Jeffは約3.8 GiBのまま。
- **数値**：全判断で公式参照と判断・token数が一致した。確率差の最大は、Native 5.07e-6、Wasm 2.38e-6（前回と同じ）。各系統の反復はbit単位で一致した。
- **対照**：公式Jeffのresidentと、Wasm（研究用probe。下記のとおり今回の変更を含まない）は、前回とほぼ同じ値だった（差は2%以内）。測定環境の状態は前回と比べられる範囲にある。

## 結果

### resident（1判断の時間、各n＝6、warm-upを除く）

中央値（最小〜最大）。prompt・tokenize、forward、readout・policyの合計。

| case | 公式Jeff（秒） | Native 前回（秒） | Native 今回（秒） | Wasm（秒） | Jeff／Native 前回→今回 |
| --- | --- | ---: | --- | --- | --- |
| candidate-request（128） | 1.52（1.49〜1.53） | 3.00 | 2.06（2.05〜2.07） | 5.48（5.27〜5.52） | 0.51 → 0.74 |
| asr-unicode（206） | 2.47（2.42〜2.55） | 4.33 | 2.98（2.96〜3.08） | 8.42（8.11〜8.59） | 0.56 → 0.83 |
| synthetic-ocr-ja-2-256 | 2.98（2.91〜3.09） | 5.21 | 3.56（3.54〜3.60） | 10.51（10.45〜11.47） | 0.58 → 0.84 |
| synthetic-asr-unicode-2-384 | 4.59（4.53〜4.64） | 7.33 | 5.12（5.10〜5.32） | 15.34（14.76〜15.63） | 0.63 → 0.90 |
| synthetic-asr-mixed-2-512 | 6.34（6.24〜6.37） | 9.60 | 6.77（6.69〜6.83） | 21.02（20.04〜22.25） | 0.66 → 0.94 |
| synthetic-ocr-ascii-8-512 | 6.36（6.25〜6.42） | 9.62 | 6.74（6.69〜6.76） | 21.06（20.06〜21.73） | 0.66 → 0.94 |

公式Jeffの前回値は1.52／2.44／3.00／4.65／6.33／6.37秒、Wasmの前回値は5.43／8.37／10.40／15.16／20.63／20.82秒。

### one-shot（親から見た経過時間、各n＝3）

| case | 公式Jeff 前回→今回（秒） | Native 前回→今回（秒） | Jeff／Native 前回→今回 |
| --- | --- | --- | --- |
| candidate-request（128） | 15.14 → 13.02 | 5.45 → 4.31 | 2.78 → 3.02 |
| asr-unicode（206） | 16.17 → 14.11 | 6.80 → 5.23 | 2.38 → 2.70 |
| synthetic-ocr-ja-2-256 | 16.76 → 14.75 | 7.72 → 5.89 | 2.17 → 2.50 |
| synthetic-asr-unicode-2-384 | 17.85 → 16.10 | 9.89 → 7.47 | 1.81 → 2.15 |
| synthetic-asr-mixed-2-512 | 19.91 → 18.14 | 12.10 → 9.05 | 1.65 → 2.01 |
| synthetic-ocr-ascii-8-512 | 20.09 → 17.76 | 12.14 → 9.03 | 1.66 → 1.97 |

公式Jeffのone-shotも約2秒短くなった。主な差は起動（residentの起動の中央値が12.41秒から10.44秒）で、Pythonの`import torch`などにかかる時間だと考えている。公式Jeffの環境は前回と別のdirectory（`.venv/jeff-ref`、torch 2.14.0+cpu、transformers 5.17.0）で作り直したもので、原因は切り分けていない。そのため、one-shotの比は参考値として扱う。

### 起動（residentの各session、n＝3）

| 系統 | 前回（秒） | 今回（秒） |
| --- | ---: | ---: |
| 公式Jeff | 12.41 | 10.44 |
| Native | 1.93 | 1.93 |
| Wasm | 7.41 | 7.67 |

### メモリ（process tree、Working Setの合計の最大）

| 系統・mode | 前回 | 今回 |
| --- | ---: | ---: |
| 公式Jeff one-shot | 3.80 GiB | 3.84 GiB |
| Native one-shot | 1.51 GiB | 1.03 GiB |
| 公式Jeff resident | 3.84 GiB | 3.82 GiB |
| Native resident | 1.94 GiB | 1.07 GiB |
| Wasm resident（browser全体） | 3.01 GiB | 2.84 GiB |

Nativeの減少は、embedding表全体のcopyをやめたこと（#8）による。100 ms間隔の採取で、shared pageはprocessごとに数えている（前回と同じ）。

## 条件と限界

- 前回と同じ機械（Core i7-1360P、Windows 11、電源設定はバランス、AC電源）とChrome（153.0.8010.48）。背景負荷は制御していない。
- 前回と変えたもの：
  - **Nativeのsource**：commit `b642011`。bundle manifestは`models/pure-jeff-bundle-b642011.json`として`jeff lock`で作り直した。
  - **公式Jeffのbundle**：schema名を改名した`models/pure-jeff-reference-bundle.json`を使った。checkpointのhashとpolicyは前回と同じ。
  - **driverとworker**：名前の変更（`kaze_judge`→`pure_jeff`）だけ。
  - **Wasm probe**：今のmainからbuildし直した。
- **Wasmの数値は、今回のNativeの改善を含まない。** benchmarkのWasm系統は研究用probe（`runtime/wasm`）で、凍結した`backbone`を使うため。公開中のWebデモのengineはライブラリの`src/`を使うので改善を含むが、このbenchmarkでは測っていない。
- **Nativeは、リポジトリ内のbuild（固定revisionのCandle）で測った。** crates.ioの0.1.0にはまだ改善が入っていない。
- 実行時、consoleのcode pageがUTF-8（65001）だったため、driverが電源設定の出力をcp932で読めず、測定前に止まった。`PYTHONUTF8=1`を設定して最初から実行し直した。測定の手順と条件は変えていない。
- 入力は人工の6件。n＝6／3と少ないため、p95やtailは評価しない。

## 証跡

[research/benchmark-2026-10-12/](research/benchmark-2026-10-12)：事前登録（実行順、seed、全hash、開始時の環境）、集計、one-shotの各実行、residentの各session、終了時の環境、Native CLIの公式参照6件との照合（`native-golden-validation.json`。判断一致、最大確率差5.066e-6）。各判断の生データは`experiments/runs/bench-b642011/`（ignored）。
