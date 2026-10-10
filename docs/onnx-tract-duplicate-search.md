# Tract重複探索の削除実験

## 実測結果・2026-10-10

**起動短縮は確認できたが、forwardの改善は確認できなかった。** 現行step1113の同一NNEFを使用し、以下は各版n=5、秒単位。p95は観測最大である。

| 区間 | 対照 中央値／p95 | 削除版 中央値／p95 |
| --- | ---: | ---: |
| NNEF load | 8.803／9.134 | 8.634／8.731 |
| codegen | 40.626／41.119 | 10.208／10.319 |
| plan構築 | 0.429／0.442 | 0.445／0.449 |
| cold起動全体 | 49.706／50.343 | 19.341／19.399 |
| cold process全体・1 forward込み | 61.047／61.959 | 30.765／31.790 |
| 常駐forward・candidate-request | 11.844／12.274 | 11.875／12.425 |

起動の候補−対照の5組差は−31.215、−29.608、−30.366、−29.957、−31.001秒で、全組短縮した。各区間の中央値は別々に算出するため合計は起動中央値と厳密一致しない。process全体はprobeの入出力・JSON・確率処理を含むが、tokenizerや公開APIのend-to-endではない。

coldの生涯Peak Working Set中央値／p95は両版とも丸めて3.051／3.051 GiB。常駐process peakも両版約3.051 GiBで、メモリ改善の根拠はない。回帰用gateも含む最大は3.067 GiB。mapped/shared pagesを含むOSのprocess peakで、private memoryとは区別する。

全14 process・30 forwardで4 goldenの判断・token数・確率許容差を満たし、同じ入力のraw255 logitsは両版・全繰り返しで完全一致した。golden比最大確率差4.9173831939697266e-6。性能集計対象はcandidate-requestだけなので、そのsummary内の最大差6.556510925292969e-7とは範囲が異なる。失敗・期限・メモリguard発動は0件。

[保存証跡](research/jeff-onnx-tract/duplicate-search-2026-10-10/README.md)に事前登録、全job／stdout／process／検証record、再集計、生成sourceのhash一覧、実際のCargo.lock、対象ループのdiff、licenseを保持した。Native保全対象128ファイルは既知の`.gitignore`差分だけで、通常probe exeも過去の固定hashと一致した。小型Python回帰20試験はskipなしで合格し、候補のrelease clippy（警告をエラー化）と追加Rust回帰コードのfmtも成功した。追加CIは設定済みだがGitHub上では未実行。

**実験経路の局所的な受入条件は満たした。通常backendへの採用・正式SLO・Phase 3全体の完了とはしない。** 次は名前整理の意味を固定して独立変更を検討し、候補版に残るcodegenの内訳も測る。前回診断の名前整理時間を、そのまま候補版の残余時間とはみなさない。常駐forwardの改善には別途operator／thread評価が必要であり、Nativeに対する採用判断は更新しない。

## 変更と判定範囲

固定Tract 0.23.8の`ModelPatch::apply`にある重複node探索だけを、独立生成した実験版で削除する。通常probe、Native runtime、公開API、Decision Reportは変更しない。名前整理、GEMM、DeltaNet kernel、量子化は今回の変更に含めない。

元のループは一致したnodeのoutput mappingを書き込むが、`continue`は内側の探索を継続する。その後は必ず新nodeを追加し、同じoutput mappingを新nodeで上書きする。今回の削除は有効なtyped graphと現在の演算実装でこの最終結果を保つことを検証するもので、一般的な重複除去の新設ではない。`dyn_eq`に副作用を持つ独自opや不正graphのpanicまで同一とする保証はない。

`prepare_duplicate_experiment.py`は固定revisionと元coreのGit差分を検査し、workspace内の未使用directoryへ複製する。診断用generatorの出力から元coreの3ファイルとbenchを復元し、内部timer moduleを除去したうえで、対象ループだけを一意なanchorで削除する。coreとdataのライセンスは保持し、元source・生成source・lock・exeをhashで固定する。対照と候補には別のCargo target directoryを使用する。

## 回帰と性能計測

小型試験は同値Identity、連鎖したpatch node、共有定数、garbage除去、複数model output、出力label、2出力TopKを含む。変更前後でnode ID・名前・op・edge・output slot・label・実行値を比較する。別途、Cast／Reshape／CumSumを含む小型NNEFで繰り返しraw logitsの完全一致を要求する。これは網羅的なTract互換性証明ではない。

実モデルは現行step1113から生成した同じdecluttered NNEF、batch=1・物理512 tokens・SingleThread。両exeで4 goldenを先に実行し、確率差≤1e-4、判断・token数一致、raw255 logits完全一致を確認する。回帰用processは性能集計から除く。

性能は各5回のprocess-coldをAB／BA交互で比較し、各版1セッションの常駐実行でcandidate-requestをwarm-up 1回＋測定5回実行する。load、codegen、plan、起動全体、1 forward込みのprocess時間、forward時間、生涯Peak Working Setを記録する。モデルhash検査は親processで実行し、子の起動時間には含めない。両版とも内部timerを含まず、callback計測も無効。期限600秒、メモリ上限は8 GiBと物理RAM半分の小さい方。

中央値とnearest-rank p95を使用し、n=5のp95は観測最大となる。storage cache・背景負荷・温度は未制御。常駐測定は1入力・1セッションで、認識品質・Tract API end-to-end・正式SLOを判定するものではない。

## 再現

```powershell
$env:CARGO_HOME = Join-Path $PWD '.venv/tract-cargo-home'
$upstream = (Get-Item .venv/tract-cargo-home/git/checkouts/tract-*/9e0cfaa).FullName
vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/prepare_duplicate_experiment.py --upstream $upstream --output .venv/new-duplicate-candidate --remove-duplicate-search
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/new-duplicate-candidate-target'
cargo build --offline --release --manifest-path .venv/new-duplicate-candidate/Cargo.toml --bin bench --bin patch_semantics
vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/benchmark_duplicate.py --candidate .venv/new-duplicate-candidate-target/release/bench.exe --generation .venv/new-duplicate-candidate/generation.json --output experiments/runs/new-duplicate-pilot
```

小型回帰のexe指定は[追加CI](../.github/workflows/tract-probe.yml)の独立実験stepを参照。GitHub上の実行結果とは区別する。元のI64→TDim patchとChangeAxes除外の制約は引き続き残る。[前回の内部診断](onnx-tract-driver-profile.md)と[開発用NOTICE](../runtime/tract-driver-profile/NOTICE.md)も参照。
