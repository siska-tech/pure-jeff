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
| [native-delta-recurrence-2026-10-12.md](native-delta-recurrence-2026-10-12.md) | DeltaNetの逐次更新の高速化（出力はbit単位で不変） |
| [native-elementwise-2026-10-12.md](native-elementwise-2026-10-12.md) | forwardの処理ごとの内訳と、要素ごとの演算の融合（出力はbit単位で不変） |
| [commit-map.md](commit-map.md) | 履歴の書き換え前後のcommit hashの対応 |
| [crate-release-plan.md](crate-release-plan.md)、[crate-release-results-2026-10-12.md](crate-release-results-2026-10-12.md) | crates.io v0.1.0に向けたライブラリ化の計画と検証結果 |
| [naming-map.md](naming-map.md) | KazeJudge由来の名前・pathと、改名後の対応 |
| [tract-development.md](tract-development.md) | ONNX／Tract経路（実験）の準備・build・数値gate・benchmarkの手順と、統合の判断 |
| [tract-migration-plan.md](tract-migration-plan.md)、[tract-migration-results-2026-10-12.md](tract-migration-results-2026-10-12.md)、[tract-migration-provenance.json](tract-migration-provenance.json) | KazeJudgeからのONNX／Tract資産の移管計画・pure-jeffでの再検証結果・移管したファイルのhash |

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

## KazeJudgeから移管したONNX／Tractの記録

2026-10-12にKazeJudge commit `ad59b25`から履歴ごと移した（[移管計画](tract-migration-plan.md)）。本文と証跡は当時のまま（利用者名を含むローカルpathだけ`<user>`に置き換えた。対応は[tract-migration-provenance.json](tract-migration-provenance.json)）。文中の性能値は当時のhostでの記録で、ほかの環境での性能を示すものではない。文中のKazeJudge、`vendor/jeff/.venv`などは当時の環境を指す。pure-jeffでの手順は[tract-development.md](tract-development.md)。

| 文書 | 内容 |
| --- | --- |
| [onnx-tract-plan.md](onnx-tract-plan.md)、[onnx-tract-progress.md](onnx-tract-progress.md) | ONNX＋Tract実装の計画と、各gateの進捗 |
| [onnx-tract-compatibility.md](onnx-tract-compatibility.md)、[onnx-tract-benchmark-plan.md](onnx-tract-benchmark-plan.md) | 演算子の互換性と、benchmarkの仕様 |
| `onnx-tract-*.md`（ほか26件） | 個別の実験（NNEF、codegen／driver内訳、重複探索、Trilu、ScatterElements、thread、入力長、Native FP32保持・thread・cache診断、host記録） |
| [research/jeff-onnx-tract/](research/jeff-onnx-tract) | 実験ごとの証跡（job、raw出力、検証、host情報） |

kzn-datasetの実OCR取込（`onnx-tract-kzn-ocr-intake.md`）はKazeNhanhの監査なので移していない。文中のリンクのうちこの文書と`architecture.md`などはKazeJudgeにだけある。

