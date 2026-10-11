# 公式Jeff／Rust Native／ブラウザWasm：横並びベンチマーク計画

2026-10-11。KazeJudgeで作成したRust／公式Jeff比較の計画（KazeJudgeでは未commitの草案`docs/rust-jeff-sidebyside-plan.md`）を、pure-jeffの3系統に合わせて改めたもの。最初の範囲はユーザーとの合意どおり**1 threadの3者比較**とする。記述的な測定であり、SLO・採用判断・一般的な高速化倍率は導かない。

## 比較する系統

| 系統 | one-shot（1要求1 process） | resident（モデル常駐） |
| --- | --- | --- |
| **jeff**：公式Jeff（Python 3.12、PyTorch、transformers） | `runtime/jeff_worker.py`をCLI workerとして起動 | `bench/jeff_resident.py`。`DecisionModel`を1回だけ構築し、workerと同じ公式呼出（`prepare`、`model(batch)`、softmax）で判断する |
| **native**：Rust Native（Candle） | `jeff.exe worker` | `runtime/rust/examples/resident_bench.rs`。bundle検証とtokenizerを1回だけ行い、worker と同じmoduleで判断する（mmapした重み、forwardごとにBF16→FP32変換） |
| **wasm**：ブラウザWasm（Chrome 153、headless） | （対象外。起動時間はresidentの起動として記録） | `bench/wasm/bench.html`＋W2のWorker。新しいprofileで、資産読込、open、判断の順に実行 |

3系統は同じcheckpoint（11ファイルのhashが一致することを事前に検査）、同じrequest、同じpolicy（0.7／0.1）を使う。jeffはCPUのFP32でload時に全重みを変換して保持し、nativeとwasmはBF16の重みをforwardごとにFP32へ変換する。保持方式と演算実装（PyTorchのoneDNN／MKLとCandle gemm、DeltaNetの実装）は異なるので、結果は**運用構成どうしの比較**であり、言語やruntime単体の効果とは断定しない。

## thread

- jeff：bundleの`cpu_threads=1`により`torch.set_num_threads(1)`。`OMP_NUM_THREADS=1`、`MKL_NUM_THREADS=1`。interop threadsは既定のまま記録する。
- native：policyにより`RAYON_NUM_THREADS=1`、`CANDLE_NUM_THREADS=1`。実際の値を記録する。
- wasm：single-thread（SharedArrayBufferなし）。

Nativeの複数threadは、KazeJudgeで見つかった「4 threadで反復時の確率差が上限1e-6を超える」問題の診断が終わるまで対象外とする。

## 入力

公式参照がある6件。128〜512 tokens、2／3／8候補で、すべて人工データ。

| case | tokens | 候補数 |
| --- | ---: | ---: |
| candidate-request | 128 | 2 |
| asr-unicode | 206 | 3 |
| synthetic-ocr-ja-2-256 | 256 | 2 |
| synthetic-asr-unicode-2-384 | 384 | 2 |
| synthetic-asr-mixed-2-512 | 512 | 2 |
| synthetic-ocr-ascii-8-512 | 512 | 8 |

## 手順（`bench/run_benchmark.py`）

1. **事前確認**：出力先が新規であること、他のbenchmark・build processがないこと、AC電源であること。CPU、OS、電源設定、CPU使用の上位processを記録する。
2. **事前登録**：判定条件、seed、実行順、全実行ファイル・script・参照・bundleのhashを、測定の前に保存する。
3. **one-shot**：jeffとnativeで各case×3回、計36 process。実行順はseed付きで混ぜる。親から見た経過時間（process起動、hash検証、load、推論、応答書込を含む）と、process treeのメモリを測る。
4. **resident**：3 block。各blockで3系統を1 sessionずつ、blockごとに順番を入れ替えて実行する（jeff→native→wasm、native→wasm→jeff、wasm→jeff→native）。各sessionはwarm-up 1件（記録するが集計から除く）と、6 case×2回をblockごとのseedで混ぜた12件。各系統・caseのn＝6。
5. **集計**：系統・caseごとの中央値、最小、最大、n。n＝6なので、p95は出さない。比は中央値どうしの比として、参考に示す。

## 判定（測定の妥当性）

- 記録したすべての判断（one-shot、resident、warm-up）が完了し、公式参照と判断・token数が一致し、確率差が1e-4以内であること。
- 同じ系統・同じmodeで、同じcaseの判断の確率がbit単位で一致すること。
- 実際のthread数がjeff、nativeとも1であること。終了時もAC電源であること。

不合格の場合も、条件を後から変えずに記録する。性能には合否を付けない。

## メモリ

process treeを100 ms間隔で採取し、treeのWorking Setの合計の最大値、Private bytesの合計の最大値、各processのlifetime peakの最大値を記録する。shared pageをprocessごとに数えるので、private RSSや厳密なpeakとは扱わない。採取の間隔の間や子processの終了後のpeakは取りこぼす可能性がある。wasmはbrowserのprocess treeで、linear memoryも別に記録する。

## 扱わないこと

認識品質、GPU、量子化、複数thread、並列要求、cold disk（OSのfile cacheは消さない）、Firefox／Safari、モバイル。
