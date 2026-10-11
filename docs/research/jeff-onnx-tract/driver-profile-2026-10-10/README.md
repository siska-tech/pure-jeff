# driver内部診断の証跡 — 2026-10-10

結論・数表・次の実装候補：[driver内部診断](../../../onnx-tract-driver-profile.md)。NNEF資産は[以前の同一step1113](../nnef-pilot-2026-10-10/artifact.json)。通常のprobeは上書きせず、独立した診断exeを用いた。

| ファイル | 内容 |
| --- | --- |
| [preregistration.json](preregistration.json) | 測定前のexe・source・NNEF・生成provenance・実lock hash、3 block順、SingleThread、期限・memory guard |
| [summary.json](summary.json)、[region-shares.json](region-shares.json) | 秒単位の全体・callback・driver内部、呼出数、区間割合。内側を除いた時間と包含時間を区別 |
| block-*.job.json／stdout.jsonl／stderr.log／process.json／validated.json | 全6プロセス・9 forwardの人工fixture、温度・入力順・有効token数、raw255 logits・確率・判断gate、process生涯peakとguard |
| [generation.json](generation.json) | 固定revision、generator/timer hash、生成直後の全source hash、変更したcore3ファイルの原本／診断版hash |
| [core-instrumentation.diff](core-instrumentation.diff)、[driver_timing.rs](driver_timing.rs)、[generated-bench.rs](generated-bench.rs) | 計時呼出しの差分、実際に使ったtimer、内部timerを有効／無効化するbenchのsource |
| [baseline.Cargo.lock](baseline.Cargo.lock)、[diagnostic.Cargo.lock](diagnostic.Cargo.lock)、[dependency-diff.json](dependency-diff.json) | 既存と診断buildのlock。packageの追加・version変更はなく、tract-coreのsourceだけがGit→local pathに変わったことを検査 |
| [reaggregation.json](reaggregation.json) | callback・driver region・process peak等の再集計一致、candidate-request raw logitsの通常／計時全6回完全一致 |
| [preservation.json](preservation.json) | Native基準128ファイルの照合と通常probe exe不変。既知の.gitignore変更のみ |
| [validation.json](validation.json)、[source-index.json](source-index.json) | Python全18試験、入れ子timer Rust 1試験、診断bench release clippy、両CLI help、関連sourceのhash |
| LICENSE／LICENSE-APACHE／LICENSE-MIT | 生成したtract-coreに含まれる元のlicense本文。追加診断の説明は[NOTICE](../../../../runtime/tract-driver-profile/NOTICE.md) |

生成sourceはignoredな`.venv/tract-driver-probe/`、exeは`.venv/tract-driver-target/release/bench.exe`。元の全source・生成manifest・診断lockはそのまま保持し、Git上にはhash一覧と計時差分を保存する。Cargo cacheのtracked core sourceには書き込んでいない。通常probeとNativeは不変。内部タイマーを配布runtimeへ接続したものではない。

生成時のfile一覧のCargo.lockはbuild前の元lockである。buildによってcoreのsourceを差し替えたため、測定前検査ではこの1ファイルを除外して全sourceのhashを確認し、実際のbuild lockを別hashで固定した。sourceの置換以外に依存差がないことはdependency-diff.jsonで検査した。

重複探索はpatch適用内にあるので包含時間を足し合わせない。exclusive時間は子timer領域を除くが、計時処理のoverheadも含む。全core呼出を捕捉する内部timerとtop-level callback時間も重なり得る。各中央値は別々に算出し、medianの和を全体medianと同一視しない。無効timerの対照も診断source由来であり、元coreそのものの無改変artifactとは区別する。

全9 forwardが確率誤差≤1e-4・判断・token数一致。guard発動・実行失敗0件。初回profileは4 golden、その他はcandidate-requestのみなのでforward latency比較は行わない。process-cold・storage cache未制御。温度・throttle・背景負荷は未制御、power/affinity snapshotは再取得していない。n=3のnearest-rank p95は観測最大で、正式SLOではない。実測中に別build・test・exportは実行していない。

Windows GetProcessMemoryInfoで直接Rust exeの生涯Peak Working Setを監視する。mapped/shared pagesを含み、private RSSや要求別peakではない。進行中snapshot、モデル本体、exeは転載しない。追加CIは更新したがGitHub上では未実行。全証跡のbytes/hash：[file-index.json](file-index.json)。
