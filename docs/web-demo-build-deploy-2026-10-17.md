# Webデモ：buildのpath混入とdeploy直後のengine不一致（#30）

2026-10-17。0.2.0の公開作業で見つかった、Webデモの2つの問題を直した（[公開の記録](web-demo-deployment-2026-10-12.md#再deployv0202026-10-14)）。推論logic、公開API、v0.2.0の証跡は変えていない。再deployはしていないので、公開中のサイトには、次のdeployから反映される。

## 1. rust-srcがあるとengineにlocal pathが入る

**原因**：toolchainにrust-src componentが入っていると、rustcは標準libraryのpathを、`/rustc/<commit>`ではなくlocalのtoolchainの下（利用者のhome directory）で埋め込む。`tools/build_wasm.py`は、repository、CARGO_HOME、target directoryのpathしか置き換えていなかった。

**修正**：`build_wasm.py`が、使うtoolchainの`rustc --print sysroot`と`rustc -vV`のcommit-hashを読み、`<sysroot>/lib/rustlib/src/rust`を`/rustc/<commit>`へ置き換える。

| 確認 | 結果 |
| --- | --- |
| stable（rust-srcあり）でbuildしたengine | host pathは0件 |
| rust-srcのない同じ版のtoolchain（1.97.1）でのbuildとの比較 | byte単位で同一（SHA-256 `a25d75fc…`） |
| 0.2.0で公開中のengine（strip前） | 同じ`a25d75fc…` |

## 2. deploy直後にengineのhash不一致で読込が止まる

**原因**：deployの直後に、ページが新しい`demo-config.json`と古い`engine.wasm`（またはその逆）を受け取ることがある。engineのworkerはhashを照合して不一致のengineを実行しない。この動作は正しいが、利用者には失敗として見える。

**修正**：

- **engineのfile名**：`build_demo.py`は、engineを`engine-<SHA-256の先頭16桁>.wasm`という名前で出力し、その名前を`demo-config.json`に書く。同じ名前で別のbuildのbytesが届くことはなくなる。
- **再試行**：`app.js`は、engineのhashが一致しないとき、1.5秒待ってから`demo-config.json`を取り直し、1回だけ再試行する。不一致のengineを実行しない点は変わらない。待っている間に利用者が中止した場合は、再試行しない。
- **E2Eの模擬**：`run_w3.py --stale-engine-once`では、localのserverが、最初のengine要求にだけ別のbytesを返す。新しいgate `engine_retry`は、次の2つを要求する。
  - ページがengineを取り直すこと。
  - ほかのgateがすべて合格すること。
- **`deployed` gate**：`demo-config.json`に書かれたengineの名前で取得するようにした。

| 確認（local、モデルはlocalから配信） | 結果 |
| --- | --- |
| Chrome、通常 | 全gate合格 |
| Chrome、`--stale-engine-once` | 全gate合格。engineの要求は、古いbytes（33 bytes）の後に本物（4,492,394 bytes） |
| Edge、`--stale-engine-once` | 同上 |
| Chrome、`--stale-engine-once`、再試行を除いた`app.js`（main） | 0.2.0のdeploy直後と同じく、「ダウンロード待ちのtimeout」で失敗した。gateは、再試行がないことを検出できる |

Webデモの単体試験（Python、`test_i18n.cjs`）と、JavaScriptの構文検査にも合格した。

## 残るリスク

- **次のdeployの時点**：すでに開いているページは古い`app.js`のままである。engineのfile名が変わるので、そのページがdeployの後でモデルを読み込むと、engineを取得できずに止まる。これは今回の修正前と同じで、再読込すれば解消する。この修正が効くのは、次のdeploy以降に開いたページである。
- **配信の切り替えが長い場合**：再試行は1回（1.5秒後）だけである。配信の切り替えがそれより長く続くと、失敗が表示される。
- **本番のdeployでは確かめていない**：今回の確認は、localのserverでの模擬である。Cloudflareでの実際の切り替えは、次のdeployで公開サイトのE2Eによって確かめる。

## 証跡

[research/web-demo-build-deploy-2026-10-17/](research/web-demo-build-deploy-2026-10-17)：

- 4回のE2Eの事前登録・集計・log。stack traceのlocal pathは`/pure-jeff`に置き換えた。
- 確認に使ったbuildの`build-info.json`。
