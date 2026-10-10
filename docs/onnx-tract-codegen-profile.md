# Tract codegenの内訳調査 — 2026-10-10

**codegenの約96%はtop-level pass callbackの外側で消費されていた。** 計時経路のcodegen中央値42.371秒に対し、callback合計は1.820秒、driverと計測処理の残余は40.551秒。起動時間の次の調査対象をpatch適用・重複探索・compactionへ絞る。これら個別の寄与はまだ分離しておらず、高速化は今回実装していない。

NNEFからの再ロード後にも残る約40秒のcodegenを調べる。これは起動時の診断で、forward性能や正式SLOの受入ではない。Native runtime、公開API、Decision Report、Tractのvendor patchは変更していない。

証跡：[raw recordと索引](research/jeff-onnx-tract/codegen-profile-2026-10-10/README.md)。同じstep1113 checkpointのNNEFを使う。

## 実測結果

秒。各区間n=3。passのcallback時間にはreset・next・run_directを含む。

| 区間 | 中央値 | p95 |
| --- | ---: | ---: |
| 通常経路codegen | 41.609 | 42.313 |
| 計時経路codegen全体 | 42.371 | 43.273 |
| callback合計 | 1.820 | 1.942 |
| driver＋計測処理の残余 | 40.551 | 41.331 |
| PropConst callback | 0.659 | 0.786 |
| MergeConsecutiveSameRoleAxes callback | 0.013 | 0.019 |
| codegen callback | 0.711 | 0.714 |
| declutter callback | 0.185 | 0.186 |
| PushSplitDown callback | 0.206 | 0.218 |
| fuse callback | 0.042 | 0.044 |

各区間の中央値は別々に算出するため、pass中央値の和がcallback合計の中央値に厳密一致するとは限らない。driver残余の割合は各runで約95.5〜95.7%だった。これはGEMM単独やweight packing単独の時間を示す値ではない。

3回とも返却patch数は同一：PropConst 409、codegen 20,057、declutter 12,687、PushSplitDown 2、fuse 1,081、計34,236。これはcallbackが返した数で、watchdogで除外され得るpatchを含み、実際の適用数とは区別する。

同じblockの計時あり−なしの差は+0.058秒、+2.651秒、−1.384秒で、観測ばらつきがある。この差から計測overheadの上限や高速化効果を断定しない。将来の改善の受入測定は計時なしartifactで別に行う。

全6プロセス・9 forwardが数値・判断gateに合格。goldenとの最大確率誤差4.9173831939697266e-6。candidate-requestの255 raw logitsは通常／計時経路の全6回で完全一致した。生涯Peak Working Set最大3.052 GiB。guard発動・実行失敗は0件。forward latencyはこの診断から比較しない。

## 計測方法

固定Tract revision `9e0cfaa9b3a9251f41f74101801dc2c937b1660a`の公開`TypedPass`をwrapperで包み、`reset`・`next`・`run_direct`のcallback時間、呼出数、返却patch数を集計する。optimizerのpass順、clone、Debug表示、session、固定点反復、patch適用・compactionのdriverは元の`Optimizer::codegen().optimize()`を使用する。callbackが返したpatchを別driverで処理する方式には変更しない。

計測範囲はtop-level callbackである。callbackから呼ばれる子model処理もそのcallbackに含まれる。callback時間の合計をcodegen全体から引いた残余にはpatch適用、compaction、driverの検査、計測wrapperのmutex・集計等が含まれる。残余をcompaction単独の実測値と呼ばない。weight packing単独の時間もこの粒度では分離しない。

同一NNEF・同一bench exe・SingleThreadで、計時なし／ありを3 block交互に実行する。順序はcontrol→profile、profile→control、control→profile。parent asset hashは事前検査し、子の計測に含めない。process-coldだがstorage cache、温度、throttle、背景負荷は未制御。初回profileは4 goldenすべてを検査し、それ以外はcandidate-requestだけを検査する。このためprocess全体やforwardのlatency比較は行わない。直前の推論負荷も完全には揃わず、paired差を計測overheadの因果推定とは扱わない。

3標本の中央値・nearest-rank p95を記録するが、p95は観測最大で、安定したtailではない。全forwardでgolden確率誤差≤1e-4、判断一致、token数一致を要求する。600秒・最大8 GiBまたは物理RAM50%の小さい方のPeak Working Set guardを使う。

## 再現

```powershell
$env:CARGO_HOME = Join-Path $PWD '.venv/tract-cargo-home'
cargo build --locked --offline --release --manifest-path runtime/tract/Cargo.toml
vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/profile_codegen.py --artifact experiments/runs/nnef-pilot-20261010/artifact.json --source-job experiments/runs/performance-pilot-20261010/primary/resident-0-tract.job.json --output experiments/runs/new-codegen-profile
```

小型CumSum NNEFの通常経路と計時経路でraw logitsが完全一致すること、繰り返し推論で状態がリセットされること、pass数・callback合計・残余の時間集計が成立することを`test_tract_nnef.py`で検査する。配布のPython実行依存は追加しない。

## driver側の次の調査候補

固定sourceの`core/src/model/patch.rs::ModelPatch::apply`には、追加するpatch nodeごとにtargetの全nodeへ`dyn_eq`と入力比較を行うループがある。`core/src/optim/mod.rs`は多数のpatchを適用し、passや反復の区切りで`compact`を呼ぶ。`core/src/model/graph.rs::compact`にはeval order計算とnodeの再配置がある。これらは**sourceからの候補**であり、個別の実測時間ではない。

次の段階では、別の診断artifactでpatch適用・重複探索・compactionを分けて計時する。全node探索のindex化や既知の同値nodeの再利用は、対応する個別区間が支配的だと確認できた場合の最適化候補とする。専用推論kernelの追加やGEMM変更を、この起動診断だけを理由に進めない。forwardの約12秒は別途operator profileと実parallel executorの比較を必要とする。

変更候補は小型の重複node・共有constant・複数outputのgraphで意味を維持することを検査し、同一checkpointの4 golden gateを通した後に、計時なしartifactで起動n≥5を再測定する。起動短縮、常駐forward、メモリは別々に判定し、計時wrapperを製品経路へ導入しない。
