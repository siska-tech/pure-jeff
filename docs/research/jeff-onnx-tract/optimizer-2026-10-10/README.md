# ChangeAxesの切り分けと限定最適化 — 2026-10-10

**現行step1113の同一checkpointで、ChangeAxesを除いた最適化経路の全体forwardと4件数値回帰が合格した。** 標準Tractの最適化エラー自体は未修正。Native・公開API・Decision Reportは不変である。

| 検証 | 記録 | 結果 |
| --- | --- | --- |
| 5ノードの独立再現例 | [cumsum-reshape.onnx](cumsum-reshape.onnx)、[標準最適化の失敗](cumsum-standard-failure.json) | checker成功、標準runは同じChangeAxes／Scan reshapeで失敗 |
| 再現例の限定最適化 | [cumsum-selected-pass.json](cumsum-selected-pass.json) | 成功、255値がブロックごとの解析的累積和に完全一致 |
| Jeff全体の限定最適化 | [parity/parity.json](parity/parity.json) | 4件合格。golden比最大確率差4.9173831939697266e-6、oracle比4.649162292480469e-6、判断一致 |
| 開発試験・静的検査 | [validation.json](validation.json) | release build、Rust 1試験、clippy、fmt、Python 13試験が成功 |
| Native資産の保全 | [native-preservation.json](native-preservation.json) | 128件再照合、既知の.gitignore変更のみ |

全証跡のhash：[file-index.json](file-index.json)。ソースのhash：[source-index.json](source-index.json)。再現例は[test_tract_optimizer.py](../../../../runtime/onnx/test_tract_optimizer.py)の`cumsum_model()`から生成できる。入力は同じディレクトリのJSONに保存した。

再現例はCast→Reshape→CumSum→Reshape→Sliceだけを使い、モデル重みを必要としない。CumSumのScan bodyではスキャン軸が1へ縮む一方、ChangeAxesが元の64を含むreshapeを伝播し、形状不一致で停止することを確認した。これは演算としてCumSumが実行できない問題ではない。

`run-no-change-axes`は固定版Tractのdeclutter pipelineからtop-level `ChangeAxes`を1個だけ取り除き、残りのdeclutterと通常のcodegenを実行する。固定版のDebug名で選び、除去数が1でなければ失敗する。Tract coreへの追加patchや専用kernelはない。既存のI64→TDim data patchは引き続き使用する。標準`run`や`run-typed`の意味は維持し、失敗時の自動fallbackは追加していない。

全体回帰は独立process・各180秒の期限付きで、同じstep1113のsequence変換後ONNXを実行した。255個の有限raw logits、候補mask、temperature、確率許容1e-4、既存goldenの選択・保留判断を検証した。小型再現例と巨大Jeff graphの両方を通しているが、4件だけの回帰で認識品質や校正を認定しない。

調査用probeには初期化・最適化・forwardの累積経過秒数を残している。推論前のgraph処理コストも観測されており、常駐planの再利用と初期化コストの分離が必要である。これらの単発記録は中央値・p95・thread条件を揃えたbenchmarkではなく、速度倍率やSLOを提示する根拠にはしない。

次は既存DecisionProvider／worker wireへの独立接続、512超の拒否・期限・温度処理・artifact契約、plan再利用を実装する。最適化済みNNEFの保存・再ロードも候補だが、演算子登録、資産hash、clean process再ロードと数値回帰は未検証で、初期化短縮は期待効果にとどまる。標準最適化のupstream修正、正式性能比較、実OCR/ASR品質、配布受入は引き続き残る。
