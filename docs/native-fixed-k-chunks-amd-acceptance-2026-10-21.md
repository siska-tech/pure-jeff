# Native：k分割（PR #41）のAMD記録機での受入試験 — 結果（#18）

2026-10-21。計画と基準は[事前登録](native-fixed-k-chunks-amd-acceptance-plan-2026-10-21.md)のとおりで、計測後に変えていない。

## 判定

**事前登録の基準では「不受入」である。** 外れた基準は、warmの速度（S1）の1つだけである。

| 基準 | 結果 |
| --- | --- |
| N1 数値gate（全判断）、process・判断の欠け | **合格**：137 process、違反0、欠けなし |
| N2 旧mainとの判断の一致（39入力） | **合格**：39入力すべて一致 |
| N3 candidateの同一環境での再現性 | **合格**：39入力すべてで、出力が1種類 |
| N4 timeout→同じ`Model`での再利用 | **合格**：1／4／16 thread |
| N5 CLIのgolden 7件・境界 | **合格** |
| N6 crates.io利用者build | **合格** |
| N7 Wasm engineのローカルE2E（Chrome、Edge） | **合格**：両方とも全10 gate |
| S1 warmの比が1.03以下（24条件） | **不合格**：4条件で超過（下記） |
| S2 one-shotの比が1.05以下 | **合格**：最大1.027 |
| M1 生涯peakの比が1.03以下 | **合格**：commit最大1.0016、Working Set最大0.9999 |

mainへのmergeは保留したままで、利用者の判断を待つ。

## 条件

- **測定機**：AMD Ryzen AI MAX+ 395、Windows 11、AC電源。
- **source**：`f181385`（未commitの変更なし。libraryは`1f4c62c`と同じ）。
- **baseline**：main `4d7ec22`。
- **driver**：`bench/ab_acceptance.py`。集計は`bench/ab_acceptance_summary.py`。
- **環境**：開始・終了時のCPU負荷は9〜10%。
- **絶対時間について**：この日は、両armとも10-18より遅かった。例えば、mainの1 thread・128 tokensは1.50秒から1.72〜1.82秒になった。比は同じ日に交互に測った値どうしで求めているので、この差は比に入らない。

## 数値と判断

| 項目 | 結果 |
| --- | --- |
| 旧mainとbitが異なる入力 | 39入力中36。k分割は、この機械（12-way L1）で出力を変えると想定していた |
| 旧mainとの確率の最大差 | 3.55e-6 |
| 判断の違い | 0（選択／保留、選ばれた候補、候補順、token数、promptのhash、失敗の種類） |
| 公式との最大差（candidate） | 3.52e-6。旧mainの0.2.0での値は4.74e-6 |
| candidateの再現性 | 全判断で1種類。範囲は下記 |
| 旧main自身の再現性（記録のみ） | 1種類 |

- **再現性の範囲**：2 session、独立process、1／4／16 thread、同じprocess内の反復、one-shot、起動時のaffinity（CPU 0〜15とCPU 16〜31）。
- **timeoutの停止時刻**（期限3秒）：1 threadで4.63秒、4 threadで3.99秒、16 threadで3.58秒。いずれも、その後の判断はbit一致した。
- **CLIのgolden 7件**：判断・token数・候補順が一致した。最大差は3.99e-6（8192 tokens）。境界は次のとおり。
  - 128 tokens予算ちょうどは成功、127は拒否。
  - 255候補は成功、1 token不足は拒否。
  - 256候補は拒否。
  - 8192 tokensの上限を守った。
- **crates.io利用者build**：次のすべてに合格した。
  - `cargo publish --dry-run`。
  - `[patch]`なしでのbuild。
  - golden 7件（最大差1.73e-6）。
  - catalog 39入力の数値gate（違反0、最大差3.40e-6）。
  - MSRV 1.88.0での`cargo check`。
- **Wasm**：engineのbytesはmainと変わる（main `08ec63a8…` → PR `cc2d9753…`）。ローカルE2Eは、ChromeとEdgeの両方で全10 gateに合格した。公式参照との結果の照合を含む。再deployはしていない。

## 速度（candidate÷baseline、warmは判断時間の中央値の比）

| threads | 128 | 512 | 874 | 8192 |
| ---: | --- | --- | --- | --- |
| 1 | 0.966／1.020 | 1.005／1.015 | 1.022／1.006 | 1.013／1.025 |
| 4 | 1.010／**1.037** | 1.028／1.012 | 0.998／0.968 | 0.986／0.981 |
| 16 | **1.071**／0.974 | 1.029／1.020 | 1.022／**1.030** | 1.022／**1.031** |

各セルは「session 0／session 1」である。太字が基準（1.03）を超えた条件。

- **全体**：24条件の比の中央値は1.017（0.966〜1.071）で、24条件中18で1を超えた。この機械では、新実装の方が約1.5〜2%遅い傾向がある。
- **16 thread・128 tokensの1.071（session 0）**：次の理由から、雑音の影響が大きいと考える。
  - session 1では0.974で、向きが逆である。
  - session 0の各3回は、baselineが0.724〜0.760秒、candidateが0.784〜0.797秒だった。
- **ほかの3条件（1.030〜1.037）**：基準のすぐ上で、上の「約2%遅い」傾向と合っている。
- **原因の仮説（未確認）**：この機械では、gemmが一部の積でk方向に512より大きいblockを使っていた。k分割は、これを512以下の等分に固定する。そのため出力への加算passが増え、そのぶん遅くなる、と考えている。ノート機（i7-1360P）での記録は0.967〜1.032（PR本文）だった。
- **one-shot**：比は0.995〜1.027（中央値1.013）で、S2を満たした。

## メモリ（one-shotの生涯peak、candidate÷baseline）

| 指標 | 比の範囲 |
| --- | --- |
| private commitのpeak | 0.9989〜1.0016 |
| Working Setのpeak | 0.9952〜0.9999 |

24条件すべてで1.03以下だった。8192 tokens・16 threadの例：commitは1.17 GiBで同じだった。

## bit基準

新しいbit基準は、旧基準と別のfileに保存した。既存の記録は書き換えていない。

- `bit-reference-baseline.json`：旧main `4d7ec22`の39入力の出力（確率のhex、判断、候補順、token数、promptのhash、失敗）と、そのSHA-256。
- `bit-reference-candidate.json`：新実装`1f4c62c`の同じもの。

どちらも、この記録機・Windowsで、1〜16 threadとaffinityの起動を通じて1種類だった出力である。

## 採否の判断材料

- **満たしたもの**：数値、判断、再現性、メモリ、one-shot、CLI、利用者build、Wasmは、すべて基準を満たした。
- **満たさなかったもの**：warmの速度は、24条件中4条件で1.03を超えた。全体ではこの機械で約1.5〜2%遅い。
- **選択肢**：
  1. この速度差を受け入れて、例外として採用する。
  2. 不受入として、k分割の速度を改善してから再試験する。
     - 改善の例：chunkごとのgemm呼び出しと加算の費用を測って減らす。
     - ただし、chunkを512より大きくすると、kcが512のhostでgemmがさらに分割し、cacheへの依存が戻る。そのため、chunkの上限そのものは変えられない。
- **release前に別途要るもの**：公式Jeffとの性能同等（release gateのshort／long）。この機械は出力を変えるので、性能同等も測り直す。

## 証跡

[research/native-fixed-k-chunks-2026-10-20/amd-acceptance-2026-10-21/](research/native-fixed-k-chunks-2026-10-20/amd-acceptance-2026-10-21)：

- 事前登録（`preregistration.json`）。
- 全137 processの記録（`work/`）。
- `summary.json`。
- bit基準2つ。
- 終了時の環境。
- driverのlog。
- `gates/`：CLIのgolden・境界、package checkのlogと判断、Wasm E2Eの集計。local pathは置き換えた。
