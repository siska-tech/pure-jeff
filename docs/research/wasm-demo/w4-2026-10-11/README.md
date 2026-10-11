# W4証跡（2026-10-11）

[W4結果](../../../web-demo-w4-results.md)の証跡。

| dir | 内容 | 判定 |
| --- | --- | --- |
| `chrome/` | W4構成（HTTPS、別originのモデル、中止を含む）のChrome。スクリーンショット7枚を含む（`01b-aborted.png`は中止の直後） | 合格 |
| `edge/` | 同じ構成のEdge | 合格 |
| `chrome-w3/` | 同一originのHTTP構成（W3）のChrome。回帰確認 | 合格 |
| `build-info-split.json`、`build-info-same.json` | 使った2つの配信物（別origin用、同一origin用）の各fileのhash | — |

各dirには、事前登録、集計、E2Eの全記録、サーバーの要求ログ（W4ではサイトとモデルを別々に）がある。TLSの秘密鍵は含めていない。`build-info`の`source_dirty`がtrueなのは、commit前の作業treeからbuildしたためである。driver、E2E script、Web fileのhashは`a496261`と一致する。
