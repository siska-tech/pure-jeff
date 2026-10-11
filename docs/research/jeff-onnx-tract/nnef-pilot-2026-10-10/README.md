# NNEF pilotの証跡 — 2026-10-10

結論・条件・数表：[NNEF保存・再ロードの性能調査](../../../onnx-tract-nnef-pilot.md)。元のONNX／Native実験は[別の証跡](../performance-pilot-2026-10-10/README.md)に保持し、今回のrecordで上書きしていない。

| ファイル | 内容 |
| --- | --- |
| [analysis.json](analysis.json) | 単位を秒で明記した集計。cold 5回、resident 1 session、4入力各5回。warm-up 5回除外。全30 forward数値合格 |
| [artifact.json](artifact.json)、[pack-preregistration.json](pack-preregistration.json) | NNEFのbytes/hash、元ONNX・外部重み・pack exe・Cargo.lockのhashとoptimizer profile |
| pack-decluttered.* | 一度だけのONNX→decluttered NNEF保存。raw events、process時間、OS peak、期限・メモリguard |
| [reload/preregistration.json](reload/preregistration.json) | 測定前のn・warm順序・1 thread・memory/deadline・資産hash・旧pilotとの比較範囲 |
| reload/*job.json／stdout.jsonl／stderr.log／process.json／validated.json | 全6プロセスの人工fixture・入力・温度・順序、raw255 logits、確率、区間時間、process生涯peakと数値検査結果 |
| [reload/summary.json](reload/summary.json) | harnessの元集計。coldの`*_ns`は元eventの区間名で、集計値の単位は`units: seconds`。読みやすい区間名はanalysis.jsonを参照 |
| [serializer-repro/result.json](serializer-repro/result.json)、[stderr](serializer-repro/stderr.log) | codegen後の小型モデルの保存失敗。IntoShape serializer未対応。実モデル全演算の保存可否を断定しない |
| [source-index.json](source-index.json) | 実験source・patch・lock・exeのhash。prepare_nnef.pyは初回測定後に追加した再現用wrapper |
| [native-preservation.json](native-preservation.json) | 128 baselineの照合。既存の.gitignore除外追加のみでNative不変 |
| [validation.json](validation.json) | Rust境界値1試験、Python 17試験、clippy/fmt、両新規CLIのhelp成功。追加CIはGitHub上で未実行 |
| [reaggregation.json](reaggregation.json) | cold・warm・process時間・peak・最大確率誤差の全集計がrawと厳密一致 |
| [preflight-incident.json](preflight-incident.json) | 初回harnessでWindows cp932による読取エラー。子process起動前に停止し、UTF-8指定へ修正して新出力先で測定 |

元資産・大きなNNEF本体はignoredな`experiments/runs/nnef-pilot-20261010/`に保持する。最初のpackは`benchmark_pilot.invoke`を直接呼んだ一度だけの開発用実行で、その後同じ監視を呼ぶprepare_nnef.pyを追加した。packはn=1の成立性調査であり、cold再ロードn=5と混ぜて集計しない。小型再現に使ったモデルは[既存の5ノードONNX](../optimizer-2026-10-10/cumsum-reshape.onnx)。

ハードウェアの参照情報は[前回のhost record](../performance-pilot-2026-10-10/host.json)。今回のpower/affinity snapshotは再取得していない。温度・throttle・背景負荷・storage cacheは未制御。以前とは非pairedでbench exeも更新した。資産hash preflightは親で行い、子のstartupに含めない。NNEF loadにtyped model構築を含め、codegenは毎起動に残る。全実測中に別build・test・exportは実行していない。

Peak Working Setは直接起動したRust exeの生涯観測値で、mapped/shared pagesを含む。residentのpeakは要求別に分解しない。全forwardの確率誤差許容は1e-4、判断一致。n=5のnearest-rank p95は観測最大で、独立resident sessionや正式SLOの代用ではない。

全ファイルのbytes/hash：[file-index.json](file-index.json)。進行中snapshot・空の失敗artifact・モデル本体はこの索引に入れない。
