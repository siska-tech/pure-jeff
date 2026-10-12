# 公式Jeff／Native：性能同等の判定基盤（計画）

2026-10-12。issue #13（親 #5）。最適化の前に、公開APIの経路を含めて公式Jeffと比べる測定と、「性能同等」の合否基準を固定する。[前回までの横並び比較](benchmark-plan.md)の結果・合否・閾値は変更しない。この文書と`bench/`のコードは**測定の前に**commitし、各runの`preregistration.json`にも同じ内容（計画・hash・環境）を書き出す。

対象は固定のJeff commit `3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0`、checkpoint revision `51552f39a943d62e8387c4ea5e17026a1408729f`、CPU FP32・batch 1・text-onlyに限る。thread数・入力ID・policy（0.7／0.1）はすべての系統で揃える。本家HEAD、別モデル、認識品質全体の同等性は対象外。

## 前回からの変更点

| | 前回（2026-10-11／12） | 今回 |
| --- | --- | --- |
| Nativeのresident | 内部module（tokenize・forward・readout・policy）を直接呼び出す | **既定は公開API**：`Model::load`と`Model::decide`（request検査、byte／token／forward予算、deadline、artifact、`Observation::validate`を含む）。内部経路は`--path internal`の診断用 |
| 公式Jeffのresident | prepare・forward・softmax・policy | **既定は`jeff_worker.infer`のload後の処理と同じ**（request検査、option上限、予算付きprepare、deadline、`pack_observation`の検査） |
| 入力 | 128〜512 tokensの6件 | 重複を除いた35件（下記）と、policy境界付近の探索で決める入力 |
| 標本 | 各n＝6、合否なし | 6独立block（AB／BA均衡）、各case・系統24観測。事前に決めた統計と合否 |
| Wasm | 凍結した研究用probe | **現行のWebデモengine**（`apps/web-demo/engine`、公開時と同じexport除去、デモのWorkerで実行）。別のbaselineとして扱う |

## 測定の境界

| 名前 | 範囲 |
| --- | --- |
| api（resident、合否に使う） | 1判断：Nativeは`Model::decide`の呼出の前後、公式は`infer`のload後の処理全体。requestのparseは含まない |
| internal（resident、診断） | tokenize＋forward＋readout＋policyを直接呼び、段階の間に計時を入れる。API検査を含まないので速度の主張に使わない |
| load | Native：`Model::load`（全資産のhash検証、tokenizer、mmap）。公式：bundle検証＋`import torch`等＋`DecisionModel`構築 |
| 初回 | load後の最初の判断（warm-upの1件目） |
| warm | 測る全長でwarm-upを済ませた後の判断 |
| one-shot | 既定のCLI worker経路で1要求につき新しいprocessを起動し、親から見た経過時間（起動・検証・load・1判断・応答書込）を測る |
| wasm | Worker内の`demo_evaluate`の経過時間。loadはdownload＋逐次hash＋Cache API書込＋open |

計時を挟む経路（internal、`forward_breakdown`の計時版backbone）は速度の判定に使わない。`forward_breakdown`は、計時版の最終hiddenがライブラリの`backbone::forward`とbit単位で一致することを毎回確かめる。今回、計時のないライブラリforwardも同じprocessで交互に測り、計時のoverheadを記録するようにした。

## 入力（`bench/cases/catalog.json`）

`bench/build_catalog.py`が、これまでの入力をrequestの正規化SHA-256で重複除去する（golden 7件、比較用6件、移管済み28件、W2の参照8件。別名は`aliases`に残す）。残った35件に、生成した入力とpolicy境界付近の入力を加える。

- **長さ**：127／128／129、256、384、511／512／513、874、3206、8192。さらに拒否される8193。127と129は`synthetic-ocr-ja-2-128`の原文末尾の詰め物（` a`）を1つ減らす／増やして作る（`bench/make_length_requests.py`）。
- **候補数**：2／3／8／255。
- **その他**：Unicode、日本語、特殊token風の文字列、候補の反転。
- **token長の検証**：各入力について公式processorのtoken ID列（長さ制限なし）とNativeの`jeff prepare`のID列が一致すること、8192を超える入力は両方が拒否することを検査し、IDのSHA-256を記録する。固定promptの外枠より短いseq（seq＝1など）はrequestでは作れないので、ここでは扱わない（kernel単体の試験の範囲）。
- **参照**：各入力を公式Jeff（CPU FP32、1 thread、workerと同じ呼出）で1回判断した確率・判断・token数。以前に保存した公式参照とも差を記録する。

### policy境界

`bench/search_policy_boundary.py`は、1文字だけ違う2候補または3候補の人工OCR／ASR入力を約500件生成し、Native（API経路）で判断する。そのうえで次の入力を固定する。どれも境界からの距離が数値gateの許容差の2倍（2e-4）以上あるものに限り、許容範囲の差では判断が変わらないようにする。

- `policy-top1-above`／`policy-top1-below`：top1が0.7の直上（選択）／直下（保留、marginは0.1以上）。
- `policy-near-tie`：1位と2位の差が最小のもの（保留）。
- `policy-margin-near`：3候補でmarginが0.1に最も近いもの。

なお、min_probability＝0.7ではmarginの閾値0.1は判断を左右しない（top1≥0.7ならmargin≥0.4）。marginが閾値と等しい場合、閾値の直後の値（nextafter）、同点の扱いは、request単位では作れない。これらは今回の性能測定の入力とは分け、policy単体の試験（`tests/fixtures/jeff-golden/boundaries.json`）で扱う。

## 数値gate（`bench/validate.py`）

warm-up・測定・gate用を問わず、**全系統のすべての判断**に同じ検査をかける。1件でも違反があればrunは無効とする。

- 入力ID（catalogのcase）、候補IDとその順序、token数が一致すること。系統がtoken IDのdigestを出す場合はそれも一致すること。
- 確率はすべて有限のfloatで、[0, 1]の範囲にあること。和と1の差が1e-6以下であること。
- 公式参照との確率の最大絶対差が1e-4以下であること。
- 選択した候補、または保留が参照と一致すること。forwardは1回であること。
- 状態が系統ごとの期待どおりであること。例：Wasmで512 tokensを超える入力は`budget_exceeded`。
- 同じ系統・同じ経路では、同じcaseの確率がbit単位で一致すること（反復の一致）。

既定経路を最適化するときは、同じbuild・計算条件での変更前と比べ、確率がbit単位で一致することを`bench/compare_runs.py`で確かめる。依存のversionが違う場合のbit一致は前提にしない。sourceを変えたら、CLI用のbundleを`jeff lock`で作り直す。

## 標本・統計・終了規則（`bench/stats.py`）

- **block**：1 blockで、各系統が新しいresident sessionを1つずつ実行する。jobと入力順は両系統で同じ。系統の順はblockごとにAB／BAを交互にする（6 blockで3対3）。
- **session**：最初に、測る全case（＝全長）を長い順に1回ずつwarm-upする。次に、各caseを4回ずつ、seed（`seed*1000+block`）で並べた固定順に測る。block 0だけ、最後にgate用の全入力を判断する。
- **標本数**：short・longとも6 block、各case・系統24観測（20以上）。
- **統計量**：blockと入力群ごとに、群内caseの（Nativeの中央値／公式の中央値）の幾何平均をとる。block間でlog比の平均を求め、片側95%のt限界を計算する。session内の観測は独立とみなさない。
- **同等**：入力群ごとに、点推定≤1.00かつ片側95%上限≤1.05。下限>1.00なら「遅い」、それ以外は**証拠不足**とする。入力群をまたいで平均しないので、短文の退行を長文で相殺しない。各caseの推定も記述として出す。
- **追加規則**（shortだけ）：6 blockの後に「証拠不足」の群が1つでもあれば、登録済みの追加6 blockを1回だけ実行し、全12 blockで判定する。それ以上は追加しない。gate違反があれば追加せず、runを無効とする。
- **one-shot**：既定経路（CLI worker）で、128と512の2入力を10 block測る。blockごとに系統の順を交互にする。中央値とpeak working setを記録し、`compare_runs.py`で、baselineに対し5%を超える悪化を退行として検出する。区間は付けないので、検出された場合は測り直す。
- **p95**：今回は主張しない。主張するには、caseごとに100観測以上を目安に別途設計し、区間とsession内の相関も評価する。

## 受入の段階

1. **short**：入力群128／256／384／512。gateは513 tokens以下の全入力。
2. **long**：入力群874／3206／8192。gateは全入力（8193の拒否を含む）。8192 tokensの公式forwardは1回約144秒かかるので、別のrunにする。
3. **全長の受入**は、shortとlongの両方が同等と判定された場合だけとする。
4. **wasm**と**one-shot**は、上と同じgateで記述的なbaselineを取る。Wasmは同等判定の対象外。

## 記録

- **事前登録**：計画、全入力のrequest hash、seed、順序、warm-up、gate入力、統計規則、追加規則。
- **hash**：driver・wrapper・exe・bundle・`Cargo.lock`（root、CLI）・Jeffの`uv.lock`、source commitとdirty状態、feature、`rustc -Vv`。
- **環境**：開始と終了の時点、さらに各sessionの前後に記録する。
  - AC電源と電池の状態、電源設定。
  - CPU負荷（背景負荷）、processor performance、周波数（WMI。名前が言語設定に依存しないclassを使う）。
  - 温度（読めれば）。
  - 子processのaffinity mask（CPUの固定はしない）。
- **実kernel**：
  - Native：実行時に検出したCPU feature、compile時に有効だったfeature、Candleの`with_avx`／`with_f16c`／MKL、thread数。
  - 公式：`torch.backends.cpu.get_cpu_capability()`、`parallel_info`。transformersのQwen3.5 linear attentionは、CPUではPyTorchの参照実装（`causal_conv1d`、`chunk_gated_delta_rule`のfallback）で動く。
- **build・downloadとの非重複**：開始時と各sessionの前に、build・install・他のbenchmarkのprocess（cargo、rustc、link、uv、pip、jeff、resident_benchなど）がないことを確かめる。あれば止める。
