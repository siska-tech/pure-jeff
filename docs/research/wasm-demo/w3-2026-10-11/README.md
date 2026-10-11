# W3証跡（2026-10-11）

[W3結果](../../../web-demo-w3-results.md)の証跡。配信物はcommit `5991887`から作成し、作成時の作業ツリーに未commitの変更はなかった（`build-info.json`、エンジンのwasmはSHA-256 `c89f0fac42d1…`）。

| dir | 内容 | 判定 |
| --- | --- | --- |
| `chrome/`, `edge/` | 事前登録、集計、E2Eの全記録（各手順の時刻・結果・ページとWorkerの通信）、サーバーの要求ログ。`chrome/`には画面のスクリーンショット6枚 | 合格 |
| `failed-a280fdc/` | 最初の最終確認（Chrome）。候補欄が改行を消す不具合で、見本2が公式参照と一致しなかった | 不合格（記録として保持） |
| `build-info.json` | 配信物の元commitと各ファイルのhash | — |

このほかに、開発時の確認run（`experiments/runs/web-demo-w3-dev1`、ignored）と、CSSの不具合に気付いて途中で止めたChromeのrun（commit `5026e21`の配信物）がある。どちらも判定には使っていない。

スクリーンショット：`01-initial`（未取得）、`02-ready`（取得後）、`03-result`（判断結果）、`04-budget`（予算超過）、`05-after-reload`（再読込後の保存済み表示）、`06-deleted`（削除後）。入力は説明用の人工データで、日本語OCR／ASRの品質評価ではない。
