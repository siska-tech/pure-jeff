# W0証跡（2026-10-11）

[W0結果](../../../wasm-w0-results.md)の証跡。各runの事前登録（閾値、成果物・browser・driver・goldenのhash）と集計を保存した。browserが返した生の演算値（各約20 MB）とnative参照の出力は、ignoredな`experiments/runs/wasm-w0-*-20261011/`にある。

| dir | 内容 | 判定 |
| --- | --- | --- |
| `v1-chrome-failed/` | 最初のrun。v1閾値、native参照12 threads。v1 driver本体と、float64による診断を同梱 | 不合格（GEMM 2件の要素相対誤差、driverの反復比較の不具合） |
| `v2-chrome/`, `v2-edge/` | v2閾値、native参照1 thread。`cargo fmt`前の成果物 | 合格 |
| `final-chrome/`, `final-edge/` | v2閾値。最終source・最終成果物 | 合格（最終証跡） |
| `tokenize-job.json` | golden 7件から作ったtokenize job（全runで同一） | — |

入力は説明用の人工goldenで、日本語OCR／ASRの品質評価ではない。
