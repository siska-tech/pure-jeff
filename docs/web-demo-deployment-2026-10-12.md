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
