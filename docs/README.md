# docs

## pure-jeffとしての文書

| 文書 | 内容 |
| --- | --- |
| [oss-release-plan.md](oss-release-plan.md) | 独立OSS公開に向けた計画と進捗 |
| [clean-environment-check.md](clean-environment-check.md) | clean環境でのbuild・試験・数値再現 |
| [licensing.md](licensing.md)、[license-audit.json](license-audit.json) | ライセンスの監査と公開blocker |
| [benchmark-plan.md](benchmark-plan.md)、[benchmark-results-2026-10-11.md](benchmark-results-2026-10-11.md) | 公式Jeff・Native・Wasmの比較 |
| [web-demo-w4-results.md](web-demo-w4-results.md)、[w4-hosting.md](w4-hosting.md) | Webデモの公開準備と配信構成 |
| [web-demo-deployment-2026-10-12.md](web-demo-deployment-2026-10-12.md) | Webデモの公開と、公開サイトでのE2E |
| [native-fp32-retention-plan.md](native-fp32-retention-plan.md)、[native-forward-profile-2026-10-12.md](native-forward-profile-2026-10-12.md) | Native推論の改善計画と、forwardの内訳 |
| [commit-map.md](commit-map.md) | 履歴の書き換え前後のcommit hashの対応 |

## KazeJudgeから引き継いだ記録

本文は当時のまま変更していない。文中の`architecture.md`、`kaze-nhanh-integration.md`、`onnx-tract-*.md`などへのリンクは、KazeJudgeにだけある文書を指す（KazeJudge commit `885e7ff`で参照できる）。

| 文書 | 内容 |
| --- | --- |
| [pure-rust-plan.md](pure-rust-plan.md)、[pure-rust-progress.md](pure-rust-progress.md) | Pure Rust化の計画と進捗（P0〜P3） |
| [jeff-runtime.md](jeff-runtime.md) | 公式Jeff（Python）参照backendの準備と制限 |
| [rust-backend-assessment.md](rust-backend-assessment.md) | Rust backendの評価（P1） |
| [p4-acceptance.md](p4-acceptance.md) | P4受入：探索的性能測定、持ち運び用package、依存・NOTICEの監査 |
| [wasm-demo-feasibility-plan.md](wasm-demo-feasibility-plan.md) | ブラウザWasmデモの計画（W0〜W4） |
| [wasm-w0-results.md](wasm-w0-results.md)〜[wasm-w2-results.md](wasm-w2-results.md)、[web-demo-w3-results.md](web-demo-w3-results.md) | W0〜W3の結果 |
| [standalone-demo-release-plan.md](standalone-demo-release-plan.md) | Windowsコンソール版デモの代替案 |
| `*.json` | 各段階の照合・境界・監査の記録 |
| [research/wasm-demo/](research/wasm-demo) | W0〜W3の証跡 |
