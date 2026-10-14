# pure-jeff 0.2.0の最終受入（#19）

2026-10-14。0.2.0の候補（commit `358fae4`で版を0.2.0に変更、`e8ccda8`でcrates.io利用者の検査を拡張）について、[リリース前のモデル付きgate](release-gate.md)を初めて全部実施した。**すべてに合格した。** 公開（crates.io、tag、GitHub Release、Webデモの再deploy）はこの文書の範囲外で、別の手順で行う。

対象は、固定Jeff commit `3720e7c…`と0.8B checkpoint `51552f39…`、CPU FP32、batch 1、text-only、1 thread、policy 0.7／0.1。

## 結論

| 範囲 | 環境 | 結果 |
| --- | --- | --- |
| 短文（128〜512 tokens）：速度 | 基準機（Windows、AMD Ryzen AI MAX+ 395）、リポジトリbuild | **達成**：4群とも同等（Native／公式Jeff 0.955〜0.821） |
| 全長（874〜8192 tokens）：速度 | 同上 | **達成**：3群とも同等（0.862〜0.884） |
| メモリ（peak Working Set） | 同上 | **達成**：Nativeは、513 tokens以下で1.09 GiB（公式3.88 GiB）、8192 tokensまでで2.09 GiB（公式5.17 GiB） |
| 数値（公式との一致） | 基準機：リポジトリbuild、crates.io版Candleのbuild、現行Wasm engine | **達成**：全入力で数値gateに合格。最大差は4.74e-6（リポジトリ）、3.96e-6（crates.io）、2.86e-6（Wasm） |
| 0.1.1との出力の同一性 | リポジトリbuild、crates.io版Candleのbuild | **達成**：catalog 39入力の確率・判断・失敗がbit一致 |
| 速度（crates.io版Candle） | — | **証拠不足**：測っていない |
| 独立した別CPU、Linux | — | **証拠不足**：この環境では実行できない（WSL・Dockerなし）。Linux CIはモデルを使わない検査だけ |
| 複数thread | — | **対象外**：#18（P5）は未着手。1 threadの値だけを主張する |

## 1. 公開crate（crates.io版Candle 0.11.0）

`tools/check_package.py --manifest … --cases --msrv 1.88.0`：

- **package**：29ファイル、`cargo publish --dry-run`に合格した。
- **golden 7件**：判断・token数が一致した。最大差3.457e-6（0.1.0／0.1.1と同じ）。`retain_f32`の有無で確率がbit一致した。
- **catalog 39入力**：数値gateに合格した（最大差3.96e-6）。
- **MSRV**：Rust 1.88.0で`cargo check`が成功した。
- **0.1.1との同一性**：crates.ioの0.1.1に依存する別projectで同じ39入力を判断した。確率・判断・失敗が、0.2.0のpackageとすべてbit一致した。

## 2. CLI（固定Candle版、jeff.exe `a2aca036…`）

- **golden 7件**（worker process、子processのPATHからPythonを除外）：判断・token数が一致した。誤差は0.1.1と同じ（最大5.066e-6）。
- **境界**：128 tokens予算ちょうどは成功、127は拒否した。255候補（3206 tokens）は成功、1 token不足は拒否した。256候補は拒否した。8192 tokensの上限は守られた。
- **timeout**：常駐APIで8192 tokensに3／30秒のdeadlineを与えると、`Timeout`（停止は3.9／31.6秒）になった。その後、同じModelの判断はbit一致した。
- **契約試験**：process境界、timeoutとkill、異常応答、bundle照合は、`cargo test`（CIと同じ一式）に合格した。

## 3. 性能同等（事前登録のbenchmark、`e8ccda8`）

### short（6 block、各case・系統24観測）

| 入力群 | Native／公式Jeff（片側95%区間） | 判定 |
| --- | --- | --- |
| 128 | 0.955（0.925〜0.986） | 同等 |
| 256 | 0.889（0.872〜0.906） | 同等 |
| 384 | 0.845（0.837〜0.853） | 同等 |
| 512 | 0.821（0.811〜0.830） | 同等 |

128 tokens：公式1.48秒、Native 1.42秒。512 tokens：公式6.43秒、Native 5.26秒。load：公式10.42秒、Native 1.87秒。

### long（6 block）

| 入力群 | 公式Jeff（秒） | Native（秒） | Native／公式（片側95%区間） | 判定 |
| --- | ---: | ---: | --- | --- |
| 874 | 10.80 | 9.18 | 0.862（0.828〜0.898） | 同等 |
| 3206 | 43.00 | 37.91 | 0.882（0.873〜0.891） | 同等 |
| 8192 | 144.00 | 126.06 | 0.884（0.865〜0.905） | 同等 |

### メモリ（各runのprocess単位の最大）

| run | 公式Jeff peak WS | Native peak WS | Native Private |
| --- | ---: | ---: | ---: |
| short（513 tokens以下、gateを含む） | 3.88 GiB | 1.09 GiB | 0.20 GiB |
| long（8192 tokensまで、全入力のgateを含む） | 5.17 GiB | 2.09 GiB | 1.16 GiB |

### one-shot（既定のCLI worker、10 block）

| case | 公式Jeff | Native | 0.1.1相当のbaselineとの比較（時間／peak） |
| --- | --- | --- | --- |
| 128 tokens | 13.09秒、3.72 GiB | 3.80秒、1.02 GiB | 0.940／1.009、確率bit一致 |
| 512 tokens | 17.93秒、3.83 GiB | 7.64秒、1.06 GiB | 0.971／1.017、確率bit一致 |

5%を超える退行はなかった。

### 要求数別の総時間とFP32保持（`request_curve.py`）

| 128 tokens | 起動 | warm | 1回 | 10回 | 100回 | peak WS | page fault |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.1.1相当 | 1.88 | 1.685 | 3.9 | 19.1 | 170.7 | 1.02 GiB | 66.8M |
| 0.2.0既定 | 1.87 | 1.410 | 3.6 | 16.4 | 143.2 | 1.03 GiB | 18.8M |
| 0.2.0＋`retain_f32` | 2.48 | 1.342 | 3.8 | 16.0 | 136.7 | 2.87 GiB | 18.7M |

- **FP32保持の損益分岐**：0.2.0既定に対して、128 tokensで8.9要求、512 tokensで5.5要求。
- **FP32保持の増分メモリ**：約1.9 GiB（512 tokens以下でpeak 2.9 GiB、8192 tokensで3.92 GiB）。
- **paging**：page faultはsoft faultを含む。最大のPrivate bytesは2.99 GiBで、物理メモリ31.6 GiBの範囲に収まる。
- **bit一致**：0.1.1相当・0.2.0既定・保持の3構成の確率が、全sessionでbit一致した。

## 4. Webデモ（現行`apps/web-demo/engine`、engine入力hash `59680dea…`）

- **E2E**（`run_w3.py`）：ChromeとEdgeの両方で、全gateに合格した。
  - 同意前の取得なし、1回だけのdownload、推論中の通信なし。
  - 公式参照との一致、Attemptの内容、保存したJSON。
  - 取消後と再読込後の結果がbit一致。
  - main threadの応答性、3言語、削除。
- **速度とメモリ**（benchmarkのwasm stage、6 session、各case 24観測）：

| tokens | 中央値（秒） | 範囲（秒） |
| ---: | ---: | --- |
| 127〜129 | 3.25〜3.30 | 3.18〜7.65 |
| 256 | 6.32〜6.33 | 6.18〜15.01 |
| 384 | 9.34〜9.36 | 9.21〜21.65 |
| 511〜512 | 12.56〜12.64 | 12.44〜29.27 |

  - load 8.91秒、初回の判断13.78秒、browser全体のpeak 4.38 GiB。
  - 最大値が中央値の2倍を超えることがあり、tailのばらつきが大きい。
  - 512 tokensを超える入力は、すべて`budget_exceeded`で拒否された。
- **Native専用の機能**：FP32保持と共有bufferはWasmに適用していない（`memory::Session`は従来の経路のまま）。
- **deploy時の注意**：この機械でbuildしたengineには、rustupの`rust-src`由来の標準libraryのpathが1件埋め込まれ、host pathの検査に通らない。main（0.1.1相当）でも同じで、CIのbuildでは起きない。deployにはCIのbuildを使う。

## 条件と限界

- **測定機**：AMD Ryzen AI MAX+ 395（16コア32 thread）、Windows 11、電源設定はバランス、AC電源。CPUの固定はしていない。背景負荷は、各sessionの前後で記録した。
- **公式Jeff**：torch 2.14.0、transformers 5.17.0（Jeffの`uv.lock`）。Qwen3.5のlinear attentionは、PyTorchの参照実装で動く。
- **入力**：人工の39入力。認識品質の評価ではない。
- **p95**：主張しない。
- **longの事前登録**：`dirty`に、測定中に作成した未追跡の文書`docs/release-gate.md`が1件記録されている。source・exe・bundleには影響しない。
- **旧runの合否・閾値**：変更していない。

## 証跡

[research/release-0.2.0-2026-10-14/](research/release-0.2.0-2026-10-14)：

- benchmark（short、long、one-shot、wasm、request curve）の事前登録・集計・session別の生データ・log
- one-shotのbaseline比較
- CLIのgoldenと境界、timeout
- crates.io利用者のcatalogの結果と、0.1.1での同じ入力の結果（比較に使ったprojectのsource付き）
- Webデモ E2E（Chrome、Edge）の集計
