# Native：k分割の並列実行の改良（PR #41の追加実験）— AMD受入試験の事前登録（#18）

2026-10-21。PR #41の初回受入（[結果](native-fixed-k-chunks-amd-acceptance-2026-10-21.md)）は、warmの速度（S1）で不受入だった。この記録はそのまま残す。利用者の承認を得て、最適化の実験を1段階だけ行った。この文書は、その最終候補の受入試験を、計測の前に固定したものである。

## 調査で分かったこと（記述）

`runtime/rust/examples/gemm_chunk_profile.rs`で、forwardで分割される全ての積を、乱数の入力で測った。積ごとの時間に、forward 1回あたりの回数をかけて合計した。生データは`docs/research/native-fixed-k-chunks-2026-10-20/split-diagnosis/`にある。

- **1 thread**：分割した積は、mainの1回の呼び出し（記録機のkcは1024／896）より2〜4.5%遅い。
  - 内訳：
    - 約半分：出力への加算。chunkを足さずに書くだけの版で、差が半分になった。
    - 残り：kcが512に小さくなること自体。
  - これは区切りと加算の順序そのものなので、bitを保ったまま取り除けない。
  - chunkの呼び出しごとの固定費（buffer確保など）は小さかった。最初の呼び出しと2回目以降で、1回あたりの時間がほぼ同じだった。
- **複数thread**：分割した積は4〜15%遅い。
  - 原因：chunkごとにgemmを呼ぶので、そのたびにrayonの並列区間を開き、合流させる。
- **短い入力（128 tokens）**：どの代替方式も、安定した改善にならなかった。
- **bitの条件**：出力の分け方は加算の順序を変えない。ただし、gemmは小さな形で別のkernelを使う。そのため、分けたblockがm×n≦256（横方向の和のkernel）や、1行・1列（gemv）にならないようにする必要がある。
  - 診断では、行で分けた版が、in_proj_b／a（n＝16）で16行のblockを作り、bitが変わった。
- **候補**：「4 thread以上、512行以上の積」に限って、1つの並列区間の中で出力をthreadに分ける。各threadは自分のblockの全chunkを、gemmの1 threadで計算する。
  - 推定（forward 1回あたりの、分割した積の合計）：mainの1回の呼び出しとの差は、−2.7〜＋2.9%だった。PR #41の初版は＋4〜＋15%だった。
  - それ以外（3 thread以下、512行未満、上の形の条件に触れる積）は、PR #41の初版と同じ処理である。

## 対象

- **測定機**：AMD Ryzen AI MAX+ 395、Windows 11（記録機）。
- **baseline（旧main）**：main `4d7ec22`。初回受入と同じbuild（`.venv/wt-main`）で、bundleも同じ`models/pure-jeff-bundle-t{1,4,16}-main-4d7ec22.json`。
- **candidate**：branch `fixed-k-chunks-split`。
  - libraryはcommit `e972ed0`。PR #41（`1f4c62c`）に、`matmul`の並列実行を加えたもの。
  - 計測するsourceは、この計画をcommitしたHEADである。HEADが加えるのはdocsだけで、libraryは`e972ed0`と同じになる。
  - bundle：`models/pure-jeff-bundle-t{1,4,16}-pr41split-e972ed0.json`。
- **手順**：[初回の計画](native-fixed-k-chunks-amd-acceptance-plan-2026-10-21.md)の手順1〜5を、candidateだけ差し替えて行う。driverとseedは同じで、出力先は`experiments/runs/pr41split-amd-acceptance`。
- **Wasm E2E**：candidateのengineで行う。Wasmは`native`がないので、並列実行は入らない。

## 受入基準（すべて満たすこと。初回と同じ値）

| # | 基準 |
| --- | --- |
| N1〜N7 | 初回と同じ。数値gate、旧mainとの判断の一致、candidateの再現性、timeout後の再利用、CLIのgolden・境界、crates.io利用者build、Wasm E2E |
| N8（追加） | candidateの全39入力の出力が、PR #41の新しいbit基準（`bit-reference-candidate.json`、`1f4c62c`）と一致すること。この変更は、どのthreadが計算するかしか変えないため |
| N9（追加） | 4環境のCI（`native-hosts.yml`、run 39523540267、`e972ed0`）が合格すること。内容は、test、golden 7件、host matrix（1／2／4 thread、独立process、固定process、timeoutと再利用） |
| S1 | warm：中央値の比（candidate÷baseline）が、各(session, thread数, 入力長)で1.03以下 |
| S2 | one-shot：中央値の比が1.05以下 |
| M1 | one-shotの生涯peak。commitとWorking Setの比が1.03以下 |

すべてを両sessionで満たせば受入とする。1つでも外れれば不受入とし、その結果と原因を記録する。基準は変えない。

## この機械で確かめられないこと

- **P／Eコア起動の再現性**：記録機はAMDで、P／Eコアの区別がない。この機械で確かめられるのは、起動時のaffinityの再現性（N3）だけである。
  - Intelのhybrid CPU（PR #41で使ったi7-1360P）は、このsessionでは利用できない。
  - 根拠として言えることは次の2つ。
    - chunkの区切りは、PR #41と同じである。
    - N8で、出力がPR #41とbit単位で同じであることを確かめる。
  - ただし、P／Eコアでの実測はしていない。確認済みとして扱わない。
- **公式Jeffとの性能同等（release gateのshort／long）**：release前に別途行う。

## 証跡

`docs/research/native-fixed-k-chunks-2026-10-20/split-acceptance-2026-10-21/`：

- 初回と同じ構成。
- N8の照合結果。
- 4環境CIの記録。
- bit基準は新しいfileに保存する。既存の基準・記録・E2Eの不合格記録は書き換えない。
