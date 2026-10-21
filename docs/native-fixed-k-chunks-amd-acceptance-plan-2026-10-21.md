# Native：k分割（PR #41）のAMD記録機での受入試験 — 事前登録（#18）

2026-10-21。PR #41（行列積のk分割をcrate側で固定する）を、記録機で受け入れるかどうかを判定する。手順、比較対象、基準、証跡は、計測の前にこの文書としてcommitする。結果は別の文書に書く。基準は、計測後に変えない。

mainへのmergeは、この結果を報告した後、利用者の判断を待つ。

## 対象

- **測定機**：AMD Ryzen AI MAX+ 395（16コア32 thread）、Windows 11。0.2.0のrelease gateを行った記録機と同じ。
- **baseline（旧main）**：main `4d7ec22`（#40をmergeした時点）。`.venv/wt-main`のworktreeで、`--release --locked`でbuildする。
- **candidate（新実装）**：PR #41のbranch `fixed-k-chunks`。
  - libraryはcommit `1f4c62c`（unsafe呼び出しの安全性の検査とtestを追加したもの）。
  - 計測するsourceは、この計画をcommitしたHEADである。HEADが加えるのはbenchとdocsだけで、libraryは`1f4c62c`と同じになる。
- **bundle**：armごとに、そのbuildの`jeff lock`で作る（policy 0.7／0.1、checkpoint `51552f39…`）。両者の違いは`runtime_build_sha256`だけであることを、driverが確かめる。
  - baseline：`models/pure-jeff-bundle-t{1,4,16}-main-4d7ec22.json`。
  - candidate：`models/pure-jeff-bundle-t{1,4,16}-pr41-1f4c62c.json`。
- **toolchain**：両armとも、同じローカルのRust（stable）を使う。

## 手順

1. **A/B計測（公開API）**：
   ```
   python -B bench/ab_acceptance.py --output experiments/runs/pr41-amd-acceptance --baseline .venv/wt-main/runtime/rust/target/release --candidate runtime/rust/target/release --baseline-bundle "models/pure-jeff-bundle-t{n}-main-4d7ec22.json" --candidate-bundle "models/pure-jeff-bundle-t{n}-pr41-1f4c62c.json"
   ```
   - **thread数**：1／4／16。
   - **session**：2回。session 0はthread数の昇順、session 1は降順で実行し、各段で2つのarmのどちらを先にするかを入れ替える。
   - **warm**：armとthread数ごとに、resident processを1つ立てる。
     - warm-up（256 tokens）を1回判断する。
     - 128／512／874／8192 tokensを各3回、固定のshuffle順（seed 20261021）で判断する。
     - 続いて、catalogの残りの35入力を各1回判断する。境界（127／128／129、511／512／513）、候補順の変更、policyの境界、3206 tokens、8193 tokens（期待どおりの失敗）を含む。
   - **one-shot**：入力ごとに新しいprocessを立てる。128／512／874 tokensは3回、8192 tokensは1回。processの終了後に、OSの生涯peak（`PeakPagefileUsage`と`PeakWorkingSetSize`）を読む。
   - **affinity**：candidateの4 threadで実行する。起動直後、読込の前に、process affinityをCPU 0〜15またはCPU 16〜31に制限し、catalogの全39入力を判断する。
   - **timeout**：candidateの1／4／16 threadで`timeout_reuse`を実行する。8192 tokensの途中で3秒の期限を切り、同じ`Model`で再び判断する。
2. **集計**：
   ```
   python -B bench/ab_acceptance_summary.py experiments/runs/pr41-amd-acceptance
   ```
   `summary.json`と、bit基準`bit-reference-baseline.json`・`bit-reference-candidate.json`を書く。どのfileも既存のものは上書きしない。
3. **CLIのgolden・境界**（candidateの`jeff.exe`、t1のbundle）：
   - `runtime/validate_migration_cases.py`：golden 7件（`token-limit-8192`を含む）。
   - `runtime/check_rust_boundaries.py`。
4. **crates.io利用者build**：`python -B tools/check_package.py --work <新しいdir> --manifest models/pure-jeff-bundle-t1-pr41-1f4c62c.json --cases --msrv 1.88.0`。
5. **Wasm engine**：このbranchではengineのbytesがmainと変わる（main `08ec63a8…` → PR `cc2d9753…`）。
   - `tools/build_wasm.py engine`でbuildする。
   - `apps/web-demo/build_demo.py`で組み立てる。
   - `apps/web-demo/run_w3.py`で、ChromeとEdgeのローカルE2Eを行う。
   - 再deployはしない。

## 受入基準（すべて満たすこと）

### 数値と判断

| # | 基準 |
| --- | --- |
| N1 | 両armの全判断が、既存の数値gate（`bench/validate.py`）に合格すること。公式との最大絶対差≤1e-4、確率和の誤差≤1e-6、非有限値なし、選択／保留と候補順の一致、8193 tokensは`budget_exceeded`。全processが正常終了し、判断の欠けがないこと |
| N2 | catalogの全39入力で、candidateの判断がbaselineと一致すること。一致を見るのは、選択／保留と選ばれた候補、候補順、token数、promptのhash、失敗の種類 |
| N3 | candidateの同一環境での再現性。各入力の出力（確率のbit、判断）が、candidateの全判断で1種類であること。範囲は、両session、独立process、thread数1／4／16、同じprocess内の反復、one-shot、affinityの2種の起動 |
| N4 | timeoutが起き、同じ`Model`での次の判断がtimeout前とbit一致すること（1／4／16 thread） |
| N5 | CLIのgolden 7件と境界の試験が合格すること |
| N6 | crates.io利用者buildの検査が合格すること。package、`[patch]`なしのbuild、golden 7件、catalogの数値gate、`retain_f32`の有無でのbit一致、MSRV 1.88.0 |
| N7 | Wasm engineのローカルE2E（Chrome、Edge）で、全gateが合格すること |

- **記録のみ（基準ではない）**：
  - baselineとcandidateでbitが異なる入力の数と、最大差。k分割で出力が変わるのは想定どおりである。
  - baseline自身の再現性。

### 速度（candidate÷baseline）

| # | 基準 |
| --- | --- |
| S1 | warm：判断時間の中央値の比が、各(session, thread数, 入力長)で1.03以下であること |
| S2 | one-shot：process時間（load＋初回判断）の中央値の比が、各条件で1.05以下であること |

### メモリ（candidate÷baseline）

| # | 基準 |
| --- | --- |
| M1 | one-shotの生涯peak。private commitとWorking Setの両方で、各(session, thread数, 入力長)の最大値どうしの比が1.03以下であること |

E2でsamplingのPrivateが計器の取りこぼしで外れた経験から、メモリの計器は最初から生涯peakに決めておく。

### 判定

- N1〜N7、S1〜S2、M1のすべてを、両sessionで満たせば**受入**とする。
- 1つでも外れれば**不受入**とする。その結果と原因を記録し、基準は変えない。

## 範囲外（release前に別途行う）

- **公式Jeffとの性能同等（release gateの3、short／long）**：#41は記録機で出力を変えるので、公開の前にrelease gateの手順で測り直す。この受入は、旧mainとの比較で退行がないことを確かめるものである。
- **OSの間でのforward全体のbit一致**：要求しない（`exp`・`ln_1p`の差）。
- **Linuxの実機、ARM64の実機、Intel hybrid CPU**：この受入の範囲外。#18の残課題として扱う。

## 証跡

`docs/research/native-fixed-k-chunks-2026-10-20/amd-acceptance-2026-10-21/`：

- 事前登録（`preregistration.json`。commit、exe／bundleのhash、job、環境）。
- 全processの記録。
- `summary.json`。
- bit基準2つ。旧main用と新実装用を別のfileにする。
- CLI、package、Wasm E2Eの出力。
- 終了時の環境。
- 既存のbit基準や記録は書き換えない。
