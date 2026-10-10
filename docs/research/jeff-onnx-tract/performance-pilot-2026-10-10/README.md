# Windows CPU性能pilotの証跡 — 2026-10-10

結果と計測範囲：[性能評価レポート](../../../onnx-tract-performance-pilot.md)。**同一step1113・1 thread・今回の128〜206-token短文では、現行Tractの高速化は確認できなかった。** Nativeの参照実装・公開API・固定goldenは変更していない。

| 記録 | 内容 |
| --- | --- |
| [analysis.json](analysis.json) | validated raw recordから再集計したcold／warm／区間／memory／暫定予算。単位をkeyに明示 |
| [primary/preregistration.json](primary/preregistration.json) | 計測前に固定した入力・seed・AB/BA順・warm-up・各5回・scope・guard・資産hash |
| [primary/summary.json](primary/summary.json) | 実行harness自身の集計。timings_ms配下は元の_ns keyを残しているが値の単位はms。単位を改名した再集計はanalysis.jsonを使用 |
| primary/*validated.json | engine診断12セッション、全60 forwardの確率・判断・token数受入とraw event |
| primary/*process.json／stdout.jsonl／stderr.log | 直接起動したRustプロセスの経過時間・OS生涯peak・終了後query・guard・元のJSONL |
| primary/*job.json | 実行した人工fixture本文・padded入力・候補数・温度・順序。モデル・実ユーザーデータは含まない |
| [native-api/summary.json](native-api/summary.json) | 凍結Native CLI decide-processの別測定、n=5。workerを含む実API経路をRustで検証 |
| native-api/* | Native CLIのpreregistration、人工request、全raw／validated結果。memory counterは親のみで、worker memoryには使わない |
| [host.json](host.json)、[power-affinity.json](power-affinity.json) | CPU、OS、RAM、Rust、電源plan、計測中AC接続・affinity snapshot。温度/throttleは不明 |
| [source-index.json](source-index.json) | 計測wrapper、harness、lock、Tract patchのsource hash |
| [native-preservation.json](native-preservation.json) | 128 baselineの再照合。既知の.gitignore変更のみ |
| [validation.json](validation.json)、[python-tests.log](python-tests.log) | 計測後Rust試験・両wrapper clippy/fmt成功、Python 16試験成功 |

全raw fileのbyte数とhash：[file-index.json](file-index.json)。進行中のprogress snapshotと計測前smoke jobはここに転載せず、ignoredな元のrun directoryに保持している。旧probeやexportの単発経過秒数を今回のbenchmarkへ混ぜていない。

初回起動は各backend n=5、128 tokensのみ。常駐は各backend 1セッションでwarm-up 5件を別保存し、4ケース各n=5。計12 engineセッション・60 forward、さらにNative API 5 forwardがすべて成功した。p95はnearest-rank、n=5では観測最大なので正式SLO受入ではない。

TractはI64→TDimの既存修正とtop-level ChangeAxes除外を使い、明示SingleThreadでhead込みforwardを実行する。Nativeは変更していない既存ライブラリを独立wrapperから呼び、tokenizerとBF16 mmapを保持するがFP32変換は毎forwardに残る。入力の物理長もNative 128〜206／Tract 512で異なる。これらの条件を含む運用費用のpilotであり、同shape・同保持形式の純粋なengine比較ではない。

Native childのbundle検証・tokenizer初期化はcold診断に含まれる。Tractは親の資産preflightとtokenizationを子の計測に含めない。TractのDecisionProvider／worker E2Eは未測定である。OS cacheは未制御で、preflight hash読取もある。全build・testは計測の前後に実施した。

再集計はRust推論を実行せずに行える：

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/summarize_pilot.py docs/research/jeff-onnx-tract/performance-pilot-2026-10-10/primary --native-api docs/research/jeff-onnx-tract/performance-pilot-2026-10-10/native-api --output experiments/runs/pilot-recomputed.json
```

監視はWindows GetProcessMemoryInfoを10 msごとに取得し、直接起動したexeの生涯Peak Working Setを保存した。mapped／shared pageを含み、private RSSや要求別peakではない。native-apiのCLI親counterを子workerのpeakとして使わない。計測／profileのoverhead、独立resident session、多スレッド、256/384/511/512の有効入力、storage-cold、Tract API E2Eは残作業である。
