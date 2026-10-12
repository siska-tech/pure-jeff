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
