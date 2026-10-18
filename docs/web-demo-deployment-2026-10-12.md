# Webデモの公開（2026-10-12）

Webデモを **https://pure-jeff.siska-tech.workers.dev** に公開し、公開したサイトに対してChrome 153とEdge 153でE2Eを実施した。**全条件に合格した。**

## 構成

- Cloudflare Workersの静的assets（Worker名`pure-jeff`、server codeなし）。配信物はcommit `a112b04`の内容からbuildした（`build-info.json`の`source_dirty`はfalse）。
- モデルは、ブラウザがHugging Faceの固定revision（`jeff-legacy/Jeff-Qwen3.5-0.8B` `51552f39…`）から直接取得する。pure-jeffは重みを再配布しない。bundle manifestだけをサイトの`bundle/manifest.json`に置く。
- `_headers`で`nosniff`、`no-referrer`と、自サイト・`huggingface.co`・`*.hf.co`だけを許可するCSPを適用した（応答headerで確認）。
- 構成の理由と料金は[W4 hosting](w4-hosting.md)にある。

## E2E（公開サイト、`run_w3.py --site-url`）

| 条件 | Chrome | Edge |
| --- | --- | --- |
| 公開物がbuildと同一（`demo-config.json`と`engine.wasm`のhash） | 合格 | 合格 |
| 取得の同意（押す前にモデルのhostへ要求しない） | 合格 | 合格 |
| 中止：転送途中で止めるとcacheに残らず、「未取得」、判断ボタン無効 | 合格 | 合格 |
| 2回目の取得で`model.safetensors`の要求は1回だけ。その後はCache Storageから読む | 合格 | 合格 |
| 通信先はサイト、`huggingface.co`、`us.aws.cdn.hf.co`だけ。判断中の通信なし | 合格 | 合格 |
| 公式参照との一致（128／206／512 tokens） | 最大2.4e-6 | 最大2.4e-6 |
| 失敗系、Attempt、JSON保存、取消・再読込後のbit一致、削除 | 合格 | 合格 |
| main threadの最大間隔（基準250 ms） | 70 ms | 70 ms |

確率の誤差は、W3・W4のローカル検証と同じ値（5.4e-7、2.4e-6、1.8e-6）だった。Hugging Faceからの取得（1.73 GB）と準備に約130秒、保存済みからの読込は約5秒（この測定環境の回線での単発の値）。

## 途中の失敗

- **ローカルでのHugging Face取得のrun**（`failed-local-hf/`）：判定が1件不合格になった。Hugging Faceはresolve URLを`/api/resolve-cache/…`へredirectする。判断中の通信がないことを確かめる判定が、このredirectを「想定外の通信先」と数えた。判定の規則（許可するURLのprefix）がhost単位の判定と食い違っていたためで、判断中の通信は0件だった。規則をhost単位に揃え（`a112b04`）、記録は不合格のまま残した。
- **公開サイトへの最初のrun**：browser側の手順はすべて完了したが、最後にdriverが公開物を取得する確認で、CloudflareがPythonの既定User-Agentを403で拒否した。User-Agentを付けるよう直し（`fdf1c79`）、両browserで新しく実行し直した。

## 証跡

[research/wasm-demo/deploy-2026-10-12/](research/wasm-demo/deploy-2026-10-12)：各browserの事前登録・集計・E2Eの全記録、Chromeのスクリーンショット、配信物の`build-info.json`、不合格だったローカルrunの記録。

## 再deploy（2026-10-12）

最初に公開した`engine.wasm`には、依存crateのsource pathとして、build machineの利用者名を含む絶対path（`C:\Users\…\.cargo\…`）が7種類含まれていた（panic messageの位置情報）。`tools/build_wasm.py`でpathを`/pure-jeff`、`/cargo`、`/target`へ置き換えてbuildし直し、再deployした（Version `edf744d3…`）。公開中の`engine.wasm`にhost pathがないことを`tools/check_no_host_paths.py`で確認した。CIも同じ検査を行う。旧versionはCloudflareのversion履歴（非公開）に残る。

同時に、中止したダウンロードの残り（小さいfile）をページから削除できるようにした。再deploy後のサイトに対してE2Eを実施し、Chrome／Edgeとも全条件に合格した。中止の直後は「途中まで取得したデータが残っています」と表示され、削除ボタンが有効になる。削除するとcacheは残らない。確率の誤差は前回と同じ（最大2.4e-6）。証跡は[research/wasm-demo/deploy-2026-10-12/redeploy/](research/wasm-demo/deploy-2026-10-12/redeploy)。

## 再deploy：ライブラリ化と3言語対応（2026-10-12）

commit `63324e0`からbuildして置き換えた（Version `b6d629ac-a129-4fca-9ee2-977423ecfaab`、Cloudflare account `siska-tech`）。旧version `edf744d3…`はCloudflareのversion履歴に残る。

- engineは`pure-jeff`ライブラリの`memory::Session`で照合・判断する（[ライブラリ化の結果](crate-release-results-2026-10-12.md)）。`engine.wasm`（strip前のSHA-256 `c022f0e8…`）は、ローカルE2Eで検証したbuildとbyte単位で同一。host pathは0件。
- 名前の変更に伴い、manifestは`pure_jeff.bundle.v1`、出力のAttemptは`pure_jeff.attempt.v1`になった（[対応表](naming-map.md)）。manifestのhashが変わったので、Cache Storageの名前も`pure-jeff-model-351c907ed106c6fb`に変わった。以前にモデルを保存した利用者は、次に開いたときに再取得が必要になる（古いcacheはページが自動で削除する）。
- 画面は日本語・英語・ベトナム語。言語は`?lang=`、前回の選択、ブラウザの言語の順で決まり、該当がなければ英語。
- 公開物のうち`demo-config.json`、`engine.wasm`、`app.js`、`i18n.js`、`index.html`、`bundle/manifest.json`がbuildと同一であることを確認した。`/index.html`は`/`へ307でredirectし、queryは保たれる。応答headerのCSP等は従来どおり。

公開サイトに対するE2E（`run_w3.py --site-url`、ページは`?lang=ja`で開く）は、Chrome・Edgeとも全条件に合格した。条件は従来の項目（公開物の同一性、取得の同意、中止、取得は1回だけ、通信先、判断中の通信なし、公式参照との一致、失敗系、Attempt、JSON保存、取消・再読込後のbit一致、main thread、削除）と、新しい`languages`（英語・ベトナム語へ切り替えて日本語が残らず、日本語へ戻る）である。公式参照との確率差は最大2.384e-6（従来と同じ）、main threadの最大間隔は約65 ms。証跡は[research/wasm-demo/deploy-2026-10-12/redeploy-63324e0/](research/wasm-demo/deploy-2026-10-12/redeploy-63324e0)（英語・ベトナム語画面のスクリーンショットを含む）。

## 再deploy：v0.1.1（2026-10-12）

pure-jeff 0.1.1のcommit `12a8f15`からbuildして置き換えた（Version `f3375f3e-3961-4e06-9075-62e307606a60`、Cloudflare account `siska-tech`）。旧version `b6d629ac…`はCloudflareのversion履歴に残る。

- engineは、0.1.1のNative改善（DeltaNetの逐次更新、要素ごとの演算の融合、重みのbytesからの直接変換）を含むライブラリでbuildした。`engine.wasm`（strip前のSHA-256 `f1614589…`、strip後`655bc8e1…`）は、リリースブランチの検査でbuildしたものとbyte単位で同一。host pathは0件。
- bundle manifestは前回と同じ（`351c907e…`）。そのためCache Storageの名前`pure-jeff-model-351c907ed106c6fb`も変わらず、モデルを保存済みの利用者は再取得しなくてよい。
- 前回の配信物から変わったのは、`engine.wasm`と、そのhashを記録する`demo-config.json`（と`build-info.json`）だけ。ほかの12ファイルはbyte単位で同一で、Cloudflareへのuploadも3ファイルだった。

### 確認

| 確認 | 結果 |
| --- | --- |
| deploy前のローカルE2E（Chrome、同じengineとmanifestで、モデルはローカルから配信） | 全条件に合格 |
| 公開サイトのE2E（`run_w3.py --site-url`、Chrome・Edge） | 両方とも全13条件に合格（公開物の同一性、取得の同意、中止、取得は1回だけ、通信先、判断中の通信なし、公式参照との一致と失敗系、Attempt、JSON保存、取消・再読込後のbit一致、main thread、言語、削除） |
| 公式参照との確率差 | 5.4e-7、2.4e-6、1.8e-6（128／206／512 tokens）。従来と同じ |
| 前回の公開版との比較 | 3つのsampleと取消後・再読込後の判断の確率（各browser 17個）が、前回の公開サイトでのE2Eの記録と完全に一致した |
| main threadの最大間隔（基準250 ms） | Chrome 65.5 ms、Edge 71 ms |

Hugging Faceからの取得と準備は約130秒、保存済みからの読込は約5秒だった（この測定環境の回線での単発の値）。**ブラウザでの推論速度は測っていない。**

### 途中の失敗

deploy前の最初のローカルE2Eは、`run_w3.py`に`--manifest`を渡し忘れたため、既定の古いmanifest（`models/jeff-rust-bundle.json`）が配信された。ページはmanifestの大きさの不一致を検出して読込を止め、E2Eはダウンロード待ちのtimeoutで失敗した（ページの動作は想定どおり）。正しいmanifestを指定して新しくやり直し、合格した。

証跡は[research/wasm-demo/deploy-2026-10-12/redeploy-12a8f15/](research/wasm-demo/deploy-2026-10-12/redeploy-12a8f15)。

## 再deploy：v0.2.0（2026-10-14）

pure-jeff 0.2.0のcommit `4572a8d`からbuildして置き換えた（Version `37de8ccf-534b-4e46-ba45-bcfcb86fb300`、Cloudflare account `siska-tech`）。旧version `f3375f3e…`は、Cloudflareのversion履歴に残る。

- **engine**：0.2.0のライブラリでbuildした。
  - browserの`memory::Session`は、0.2.0のNative向けの変更（共有buffer、FP32保持）を使わない。
  - 512 tokens以下なのでattentionも1 blockで、計算は前回と同じ。
  - `engine.wasm`のSHA-256は、strip前が`a25d75fc…`、strip後が`8b2bc45a…`。host pathは0件。
  - この機械のstable toolchainには`rust-src`が入っていて、標準libraryのpathが埋め込まれる。そのため、`rust-src`のない同じ版のtoolchain（1.97.1）でbuildした。
- **bundle manifest**：前回と同じ（`351c907e…`）。Cache Storageの名前も変わらず、モデルを保存済みの利用者は再取得しなくてよい。
- **配信物**：前回から変わったのは、`engine.wasm`、`demo-config.json`、`build-info.json`だけ。ほかの12ファイルはbyte単位で同一で、Cloudflareへのuploadも3ファイルだった。

### 確認

| 確認 | 結果 |
| --- | --- |
| deploy前のローカルE2E（Chrome、同じengineとmanifestで、モデルはローカルから配信） | 全条件に合格 |
| 公開サイトのE2E（`run_w3.py --site-url`、Chrome・Edge） | 両方とも全14条件に合格（Chromeは2回目） |
| 前回の公開版との比較 | 3つのsampleと、取消後・再読込後の判断の確率（各browser 17個）が、前回の公開サイトでのE2Eの記録と完全に一致した |

### 途中の失敗

deploy直後に実行したChromeの1回目は、ページが「推論エンジン（wasm）のhashが一致しません」と表示して読込を止めた。E2Eはダウンロード待ちのtimeoutで失敗した。

- **原因の推定**：deploy直後で配信が切り替わる途中だったため、新しい`demo-config.json`と古い`engine.wasm`（またはその逆）を受け取ったと考えている。
- **ページの動作**：設計どおりで、不一致のengineを実行しない。
- **確認と再実行**：
  - 直後に`demo-config.json`のengine hashと、配信中の`engine.wasm`のSHA-256を3回取得した。どれもbuildと一致した。
  - Edge（2番目に実行）は合格していた。
  - Chromeを新しい出力先でやり直し、合格した。
- **利用者への影響**：deployの直後に開いた利用者も、同じ表示で読込が止まることがありうる。再読込すれば解消する。

証跡は[research/wasm-demo/deploy-2026-10-14-v020/](research/wasm-demo/deploy-2026-10-14-v020)にある。Chromeの1回目の記録も、失敗時の画面を含めて残した。stack traceに含まれていたlocalのpathは`/pure-jeff`に置き換えた。

## 再deploy：配信切替の対策（2026-10-18）

#30の修正（engineのfile名にhashを入れる、hash不一致のときに1回だけ再試行する、rust-srcのpathを置き換える）を本番に反映した。

- **build**：main `1c7d799`からbuildした（`source_dirty=false`）。
- **配信先**：Version `79e8e4be-bdfa-45db-ab58-89ccab0832b0`、Cloudflare account `siska-tech`（`99360706…`）、Worker `pure-jeff`、`https://pure-jeff.siska-tech.workers.dev`。deployの前に、`wrangler deployments list`で、配信中のversion（`37de8ccf…`、0.2.0）と記録が一致することを確かめた。旧versionは、Cloudflareのversion履歴に残る。
- **crate**：公開crate（0.2.0）は変えていない。

### 変わったもの

- **engine**：bytesは0.2.0と同じ（strip前`a25d75fc…`、strip後`8b2bc45a…`）で、file名だけが`engine.wasm`から`engine-8b2bc45a32c742e2.wasm`に変わった。
- **その他の変更**：`app.js`（再試行）と`demo-config.json`（engineの名前）。ほかの12 fileはbyte単位で同一で、uploadは3 fileだった。
- **bundle manifestとCache Storageの名前**：前回と同じ（`351c907e…`、`pure-jeff-model-351c907ed106c6fb`）。

### 確認

| 確認 | 結果 |
| --- | --- |
| deploy前のローカルE2E（Chrome、通常と`--stale-engine-once`） | どちらも全gate合格 |
| deploy前：公開中の0.2.0で、Chrome・Edgeの永続profileにモデルを保存（`run_deploy_cache.py prepare`） | 両方合格 |
| deployの直後：同じprofileで新しいサイトを開く（`run_deploy_cache.py reuse`） | Chrome・Edgeとも全gate合格。詳細は下 |
| 公開サイトのE2E（`run_w3.py --site-url`、Chrome・Edge） | 両方とも全13条件に合格。配信中のengineはbuildと一致（`8b2bc45a…`） |
| 前回の公開版との比較 | 3つのsampleと、取消後・再読込後の判断の確率（各browser 17個）が、0.2.0の公開サイトでのE2Eの記録とbit単位で一致した |

`run_deploy_cache.py reuse`の内容：

- **モデルキャッシュの再利用**：0.2.0で保存したモデルが、ページを開いた時点で「保存済み」と表示され、どのモデル資産も取得せずに読み込まれた（Hugging Faceへの要求は0件）。Cache Storageの名前もprepareと同じだった。
- **engineのhash整合性**：全Attemptの`wasm_engine`が、配信中の`demo-config.json`のengine hashと一致し、engineはhash付きの名前で取得されていた。
- **配信切替**：deployの直後に開いたが、engineの取得は1回で、再試行は要らなかった（配信は切り替わり済みだった）。切り替えの途中に起きる場合の再試行は、ローカルの模擬（`--stale-engine-once`）で確かめている。
- **オフライン推論**：ページとWorkerの通信を切った状態で（fetchが失敗することを確認）、sample 0と5の判断が完了した。結果は、オンラインでの判断と0.2.0でのprepareの結果に、bit単位で一致した。

### 途中の失敗

`run_deploy_cache.py`の最初の試行は、ローカルで2回失敗した。

1. 1回目：Workerをdebuggerで止める設定のまま、自動でattachしていた。
2. 2回目：browserのprofileのpathが長く（約150文字）、Cache Storageの`open`がinternal errorになった。Windowsでは、profileの下に深く作られるCache Storageのpathが、上限を超えるためと考えている。そのため、profileのpathを80文字までに制限した。

修正後は、ローカル・本番とも合格した。

証跡は[research/wasm-demo/deploy-2026-10-18-1c7d799/](research/wasm-demo/deploy-2026-10-18-1c7d799)にある（local pathは置き換えた）。

