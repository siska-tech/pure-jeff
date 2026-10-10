# codegen内訳診断の証跡 — 2026-10-10

結論・数表・処理範囲：[codegen内訳調査](../../../onnx-tract-codegen-profile.md)。元のモデル・NNEF準備は[前回のNNEF証跡](../nnef-pilot-2026-10-10/README.md)。同じstep1113、同じNNEF hash、同じbench exeを3 blockで交互に実行した。

| ファイル | 内容 |
| --- | --- |
| [preregistration.json](preregistration.json) | 測定前に固定したexe/source/asset hash、block順序、forward検査範囲、SingleThread、期限・メモリ制限 |
| [summary.json](summary.json) | 秒単位の通常／計時codegen、callback別中央値・p95、返却patch数、block差、最大誤差・peak |
| block-*.job.json | 人工fixtureの本文・入力512 tokens・候補順・temperature・実行順序・profile_codegen flag |
| block-*.stdout.jsonl／stderr.log／process.json | Rust exeの元出力、区間ns、callback counts、process全体の時間・生涯peak・guard・終了コード |
| block-*.validated.json | 全9 forwardの確率・判断・token数gateとraw255 logitsを含む検証済みrecord |
| [reaggregation.json](reaggregation.json) | cold区間・callback・peak等の再集計一致と、candidate-requestの通常／計時raw logits完全一致 |
| [upstream-inspection.json](upstream-inspection.json) | pinned Tractのoptimizer・patch・graph sourceのhashと対象3ファイルのrevision差分なし。個別関数時間は未測定 |
| [native-preservation.json](native-preservation.json) | 128基準ファイルを照合。既存.gitignore変更のみでNative不変 |
| [source-index.json](source-index.json)、[validation.json](validation.json) | 計測sourceのhash、Python 17試験、Rust境界値1試験、clippy/fmt、診断CLI help成功 |

通常経路ではwrapperを使用せず、計時経路だけpublic TypedPassのcallbackを計時する。optimizer driverは同じ固定版を呼び、pass順・反復・patch適用の意味を変更しない。wrapperのDebug表示は元passに委譲する。callback時間の差引残余はdriverと計測処理を含む値であり、compactionや重複探索だけの計測値ではない。返却patch数を適用数と同一視しない。

初回profileだけ4ケース、それ以外はcandidate-requestの1ケースで数値を確認する。すべてprocess-coldで、常駐forwardの性能比較や製品E2Eではない。3標本のnearest-rank p95は観測最大。温度・throttle・背景負荷・storage cacheを制御していない。power/affinity snapshotは再取得していない。block差をinstrumentation overheadの上限とは扱わない。実測中に別build・test・exportは実行していない。

全6プロセスが成功し、deadline／working-set guard発動は0件。生涯Peak Working Setにはmapped/shared pagesを含み、private RSSや要求別peakではない。元のrunはignoredな`experiments/runs/codegen-profile-20261010/`に保持する。既存の性能raw recordやモデル資産は上書きしていない。追加GitHub CIは未実行。

全証跡のbytes/hash：[file-index.json](file-index.json)。モデル本体・exe・進行中snapshotは転載しない。
