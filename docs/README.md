# docs

## pure-jeffとしての文書

| 文書 | 内容 |
| --- | --- |
| [oss-release-plan.md](oss-release-plan.md) | 独立OSS公開に向けた計画と進捗 |
| [clean-environment-check.md](clean-environment-check.md) | clean環境でのbuild・試験・数値再現 |
| [licensing.md](licensing.md)、[license-audit.json](license-audit.json) | ライセンスの監査と公開blocker |
| [benchmark-plan.md](benchmark-plan.md)、[benchmark-results-2026-10-11.md](benchmark-results-2026-10-11.md)、[benchmark-results-2026-10-12.md](benchmark-results-2026-10-12.md) | 公式Jeff・Native・Wasmの比較（2回目はNative改善後の再測定） |
| [benchmark-parity-plan.md](benchmark-parity-plan.md)、[benchmark-parity-results-2026-10-13.md](benchmark-parity-results-2026-10-13.md)、[benchmark-parity-full-2026-10-14.md](benchmark-parity-full-2026-10-14.md) | 性能同等の判定基盤（公開API経路、入力catalog、共通数値gate、事前登録の統計と受入規則）と、そのbaseline、全長の受入（main `4e1794d`） |
| [web-demo-w4-results.md](web-demo-w4-results.md)、[w4-hosting.md](w4-hosting.md) | Webデモの公開準備と配信構成 |
| [web-demo-deployment-2026-10-12.md](web-demo-deployment-2026-10-12.md) | Webデモの公開と、公開サイトでのE2E |
| [web-demo-build-deploy-2026-10-17.md](web-demo-build-deploy-2026-10-17.md) | Webデモ：rust-src由来のpath混入の解消と、deploy直後のengine不一致への対策（#30） |
| [native-fp32-retention-plan.md](native-fp32-retention-plan.md)、[native-forward-profile-2026-10-12.md](native-forward-profile-2026-10-12.md) | Native推論の改善計画と、forwardの内訳 |
| [native-delta-recurrence-2026-10-12.md](native-delta-recurrence-2026-10-12.md) | DeltaNetの逐次更新の高速化（出力はbit単位で不変） |
| [native-elementwise-2026-10-12.md](native-elementwise-2026-10-12.md) | forwardの処理ごとの内訳と、要素ごとの演算の融合（出力はbit単位で不変） |
| [native-weight-load-2026-10-12.md](native-weight-load-2026-10-12.md) | 重みをbytesから直接FP32へ変換し、embeddingは必要な行だけ読む（出力はbit単位で不変） |
| [native-weight-buffers-2026-10-13.md](native-weight-buffers-2026-10-13.md) | 重み変換先の共有buffer（既定、128群で性能同等に）と、FP32保持（opt-in）の比較（出力はbit単位で不変） |
| [native-attention-blocks-2026-10-14.md](native-attention-blocks-2026-10-14.md) | full attentionのquery-block化：8192 tokensのpeakを7.85→2.06 GiBに（出力はbit単位で不変） |
| [native-threads-diagnosis-2026-10-17.md](native-threads-diagnosis-2026-10-17.md) | 複数threadの診断：1〜16 threadで1 threadとbit一致、速度は4 thread以上で公式に及ばない（#18、診断のみ） |
| [native-threads-breakdown-2026-10-18.md](native-threads-breakdown-2026-10-18.md) | thread数ごとの処理別時間と、DeltaNetのhead並列化の実験（bit一致、4 threadで約8〜9%短縮、#18） |
| [native-delta-threads-plan-2026-10-18.md](native-delta-threads-plan-2026-10-18.md) | DeltaNet逐次更新の複数thread化の事前登録：工程別診断（D1）と採否条件（E1／E2）（#18） |
| [native-delta-threads-2026-10-18.md](native-delta-threads-2026-10-18.md) | DeltaNet逐次更新の工程別時間と方式比較：逐次の準備・書き戻しが主因、`fused`で16 thread 15.7%短縮、E1合格（#18、診断のみ） |
| [native-delta-heads-e2e-plan-2026-10-18.md](native-delta-heads-e2e-plan-2026-10-18.md) | DeltaNet headの複数thread化をライブラリに組み込んだ版のE2（公開API E2E）事前登録と、E2後に追加したE2b（#18） |
| [native-delta-heads-2026-10-18.md](native-delta-heads-2026-10-18.md) | E2／E2bの結果：bit一致・速度（4 thread以上で8〜15%短縮）は合格、sampling PrivateでE2不合格（記録として維持）、生涯peakのE2bと最終検証は合格。例外承認で採用（#18） |
| [native-delta-heads-final-check-2026-10-18.md](native-delta-heads-final-check-2026-10-18.md) | rebase後の最終commitで代表ケースの数値（1〜16 thread、mainの1 threadとbit一致、timeout再利用）とメモリ（生涯peak比≤1.0017）を確認、合格（#18） |
| [native-host-matrix-2026-10-19.md](native-host-matrix-2026-10-19.md) | Intel hybrid CPU（i7-1360P）での検証：P-coreから起動すれば1〜16 threadでbit一致、E-coreから起動するとCACHE_INFOが変わり最大3.55e-6の差。Linux／ARM64のCI（#18） |
| [commit-map.md](commit-map.md) | 履歴の書き換え前後のcommit hashの対応 |
| [crate-release-plan.md](crate-release-plan.md)、[crate-release-results-2026-10-12.md](crate-release-results-2026-10-12.md) | crates.io v0.1.0に向けたライブラリ化の計画と検証結果 |
| [../CHANGELOG.md](../CHANGELOG.md)、[release-notes-v0.1.1.md](release-notes-v0.1.1.md)、[release-0.1.1-2026-10-12.md](release-0.1.1-2026-10-12.md) | crateの変更履歴、v0.1.1のRelease notes、v0.1.1の公開の記録 |
| [release-gate.md](release-gate.md)、[release-0.2.0-verification-2026-10-14.md](release-0.2.0-verification-2026-10-14.md)、[release-notes-v0.2.0.md](release-notes-v0.2.0.md)、[release-0.2.0-2026-10-14.md](release-0.2.0-2026-10-14.md) | リリース前のモデル付きgate（必須手順）、0.2.0の最終受入、v0.2.0のRelease notes、v0.2.0の公開の記録 |
| [ci-process-tests-2026-10-15.md](ci-process-tests-2026-10-15.md) | CI：Python worker試験の不安定さの原因、試験の修正、残るリスク（#26） |
| [benchmark-cratesio-2026-10-17.md](benchmark-cratesio-2026-10-17.md) | crates.io版Candle（`pure-jeff` 0.2.0）での性能同等：short・longとも全入力群で同等（#28） |
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

