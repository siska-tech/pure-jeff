# Tract driver内部の診断 — 2026-10-10

**起動時のcodegenは、重複node探索とnode名整理が支配していた。** 計時経路のcodegen中央値42.601秒に対し、重複探索29.926秒、名前整理9.765秒、compaction 0.625秒。探索と名前整理は各runの全体の約93%を占めた。次の最適化対象をこの2箇所に絞る。今回の変更は計時だけで、高速化はまだ実装していない。

前回の[callback／driver内訳](onnx-tract-codegen-profile.md)でcallback外側が約40秒を占めたため、固定Tract内部に計時点だけを追加する独立artifactを作成した。通常probe・Native・公開API・Decision Report・Cargo cacheは変更しない。

証跡：[raw record・生成source索引](research/jeff-onnx-tract/driver-profile-2026-10-10/README.md)。

## 実測結果

秒、各n=3。下表の内訳は子領域を除いた時間で、patch適用全体の包含時間は別行に分けた。

| 区間 | 中央値 | p95 | 呼出数／run |
| --- | ---: | ---: | ---: |
| 対照codegen（timer無効） | 43.009 | 44.585 | 1 |
| 計時codegen全体 | 42.601 | 43.958 | 1 |
| 重複node探索 | 29.926 | 31.032 | 39,045 |
| node名整理 | 9.765 | 9.786 | 34,290 |
| compaction | 0.625 | 0.629 | 676 |
| garbage除去 | 0.195 | 0.199 | 34,290 |
| patch適用のその他 | 0.330 | 0.333 | 34,290 |
| patch適用全体・包含時間 | 40.079 | 41.347 | 34,290 |

包含時間には重複探索・名前整理・garbage除去を含むので、下の行を上の内訳と加算しない。中央値は区間ごとに計算するため、内訳中央値の和と全体中央値は厳密一致しない。内部timerは子modelも含む全呼出を捕捉するので、前回のtop-level callback返却patch数34,236とは測定範囲が異なる。

計時あり−なしのblock差は−0.416秒、−0.626秒、+0.697秒。未制御の負荷・温度やtimer overheadを含む観測差であり、timerが高速化したという意味ではない。compactionを減らすことだけを優先する根拠も、この実測からは得られない。

全6プロセス・9 forwardでgolden確率誤差≤1e-4、判断・token数一致。最大確率誤差は4.9173831939697266e-6。candidate-requestのraw255 logitsは通常／計時の全6回で完全一致した。生涯Peak Working Set最大3.052 GiB、期限・メモリguard発動と実行失敗は0件。forward性能や認識品質の改善を示す測定ではない。

## 独立ビルドと計測範囲

`prepare_driver_profile.py`は固定revision `9e0cfaa9b3a9251f41f74101801dc2c937b1660a`と対象sourceのGit差分を確認し、未使用のworkspace内`.venv` directoryへprobe、既存data patch、tract-coreを複製する。元の全sourceにhashを付け、anchorが一意に一致した場合だけ計時呼出しを挿入する。生成物全体のhash一覧と変更元／変更後hashを保存する。coreの演算・探索・patch適用・compactionの処理順は変更しない。

計時領域はpatch適用全体、重複node探索、garbage除去、node名整理、graph compaction。thread-localの入れ子timerを使い、各領域の呼出数・包含時間・子領域を除いた時間を記録する。包含時間は重なるので足し合わせない。子領域を除いた時間もtimer管理のoverheadを含み、純粋なalgorithm時間の保証ではない。callback wrapperの時間と内部timerも重なり得るため別集計とする。

同じ診断exeで内部timerとcallback timerの両方を無効／有効にし、3 blockを交互に測る。対照も計時呼出しのある診断sourceからのビルドであり、未変更coreそのものとは区別する。SingleThread、同一step1113 NNEF、process-cold、資産hash preflightは親で行って除外する。初回profileは4 golden、それ以外はcandidate-requestを検査し、計9 forwardすべてに確率誤差≤1e-4・判断一致・token数一致を要求する。

storage cache・背景負荷・温度・throttleは未制御で、power/affinity snapshotも再取得しない。n=3のnearest-rank p95は観測最大。forwardの性能比較や正式SLOではなく、まだ高速化の実装でもない。期限600秒、Peak Working Setは最大8 GiB／物理RAM50%の小さい方で監視する。

## 再現

```powershell
$env:CARGO_HOME = Join-Path $PWD '.venv/tract-cargo-home'
$upstream = (Get-Item .venv/tract-cargo-home/git/checkouts/tract-*/9e0cfaa).FullName
vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/prepare_driver_profile.py --upstream $upstream --output .venv/new-driver-probe
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/new-driver-target'
cargo build --offline --release --manifest-path .venv/new-driver-probe/Cargo.toml --bin bench
vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/profile_codegen.py --artifact experiments/runs/nnef-pilot-20261010/artifact.json --source-job experiments/runs/performance-pilot-20261010/primary/resident-0-tract.job.json --output experiments/runs/new-driver-profile --executable .venv/new-driver-target/release/bench.exe --driver-provenance .venv/new-driver-probe/generation.json
```

初回buildでは元lockからtract-coreのsourceだけをlocal pathへ変更し、実行時は変更後lockのhashを記録する。生成時のsource一覧には変更前lockを含むため、測定前検査ではlockだけを除外し、実際にbuildで使ったlockを別に固定する。元packageのversionを上げる作業とは区別する。

元のcore LICENSE／LICENSE-APACHE／LICENSE-MITは生成sourceに保持する。[開発用NOTICE](../runtime/tract-driver-profile/NOTICE.md)も参照。通常運用にPython依存や内部timerを追加しない。

## 次の実装候補と受入

1. **重複探索を先に検討する。** 固定`ModelPatch::apply`のループは、一致時の`continue`が内側の探索ループに作用し、探索後も`add_node`とoutput mappingの上書きへ進む。探索削除・修正・index化のどれを選ぶかは、この現在の意味を小型graphで確認してから決める。単に早期breakを加えると同値nodeの選択やmappingの意味を変え得るため、速度だけで受け入れない。
2. **名前管理を検討する。** 名前重複確認と`unique_name`の全node探索を減らす候補を作る。既存名の重複数、`#`を含むprefix、最低の空きsuffix、garbage除去時の改名、複数output・共有constant・子modelで意味を維持することを確認する。単純なHashSetへの置換を同等と仮定しない。
3. **各変更を独立して比較する。** 未変更固定版を対照として保持し、計時なしの別artifactで4 goldenと小型のgraph構造・名前・出力回帰を通す。その後に起動n≥5、warm forward、Peak Working Setを再測定する。これまでは診断上の支配項であり、除去可能時間や高速化倍率の予測値には換算しない。

この2箇所の改善が成立しない場合は、現行Nativeの維持とTractモデルの常駐再利用を代替とする。推論そのものの約12秒には別のoperator profile・多スレッド比較が必要である。upstreamへの投稿は未実施。
