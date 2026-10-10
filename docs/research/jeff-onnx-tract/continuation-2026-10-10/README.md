# Tract続行の検証証跡 — 2026-10-10

現行step1113の同一checkpointに対し、修正版Tractの全体forwardと4件の数値回帰が成立した。公開step960との比較ではない。全記録のhashは[file-index.json](file-index.json)。大きいONNX・外部重みは従来のignored保存先に保持する。

| Gate | 記録 | 結果 |
| --- | --- | --- |
| Native保全 | [native-preservation.json](native-preservation.json) | 128件を再照合、既知の.gitignore変更のみ |
| Sequence変換の精度 | [normalized-oracle.json](normalized-oracle.json) | CPU ORT、4件合格、変換前後の候補確率差0 |
| I64修正後の全体型推論 | [current-patched-type.json](current-patched-type.json) | 成功 |
| 標準最適化 | [current-patched-optimize.json](current-patched-optimize.json) | ChangeAxes／CumSum Scanのreshapeで失敗 |
| 最初の全体実行 | [current-patched-run-typed.json](current-patched-run-typed.json) | 最適化なし、candidate-request成功 |
| 全体数値回帰 | [parity/parity.json](parity/parity.json) | 4件合格、最大確率差はgolden比3.039836883544922e-6、oracle比1.7285346984863281e-6 |
| Slice小型再現 | [slice-patched-v2.json](slice-patched-v2.json) | 成功。先行失敗もslice-patched.jsonに保存 |
| 開発試験 | [python-tests.log](python-tests.log)、[rust-test.log](rust-test.log) | Python 12件、Rust 1件成功。clippy/fmtもローカル成功 |

Tract本体は固定commit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a`。probeにのみ[local data patch](../../../../runtime/tract/vendor/NOTICE.md)を適用した。I64→TDimがi32を経由し、ONNX SliceのINT64_MAXを-1へ切り詰めていたため、I64に限定して直接変換する。原本26ファイルのhashを保持し、唯一の変更箇所tensor.rsと修正版hashを自動検査する。ライセンス本文も保持する。

14ノードの再現例は別途、入力と重複するvalue_infoによりimporterがI64型を消していた。analyze段階でONNXの宣言済み入力型を復元し、形状は維持した。実モデルのtype/run経路は従来通り明示i64[1,512]である。

`run-typed`はtyped graphを直接planへ変換し、標準最適化を省く明示的な調査経路。失敗時に自動で選ばれるfallbackではない。各caseは独立process・180秒の期限付き。255個の有限raw logitsを確認し、候補maskと既存temperatureから候補確率を計算、許容1e-4とgolden判断一致を検査した。raw logitsの最大絶対差も保存している。

probe記録の秒数は単発調査の経過時間で、Nativeとの性能比較やSLOには使用しない。API接続、最適化済みforward、長入力、Windowsの定量benchmark、実OCR/ASR品質、配布NOTICE受入は未完了。追加CIはGitHubで未実行。次はChangeAxes／Scanの再現例と最適化passを切り分け、変更後に同じ数値gateを実行する。
