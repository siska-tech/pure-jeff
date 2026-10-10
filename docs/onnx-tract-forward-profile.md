# Jeff Tract forward内訳・スレッドpilot

2026-10-10の作業から継続したWindows測定。測定開始はJST 2026-10-11 00:00:40（UTC 2026-10-10 15:00:40）。開始UTCは[事前登録](research/jeff-onnx-tract/forward-profile-2026-10-10/preregistration.json)に記録する。

**同一Tract buildのスレッド増加でforward短縮を確認した。8-threadは中央値で最短だが、4-threadとの差は小さく、p95は4-threadの方が短かった。次の候補は4／8-threadを残す。Nativeの置換や正式SLOの受入には至っていない。**

## 実測結果

各threadのwarm forwardはn=6、独立2セッション。各セッションのwarmupは集計から除外する。秒単位、nearest-rankで集計した。

| threads | forward中央値 | forward p95 | セッション別中央値 | 起動中央値／p95（n=2） | Peak Working Set最大（n=2） |
| ---: | ---: | ---: | --- | --- | ---: |
| 1 | 11.744 | 12.255 | 12.050／11.744 | 19.525／20.205 | 3.0513 GiB |
| 2 | 9.746 | 9.941 | 9.812／9.746 | 19.730／19.848 | 3.0515 GiB |
| 4 | 8.869 | 9.071 | 8.705／9.046 | 19.406／19.691 | 3.0515 GiB |
| 8 | 8.694 | 9.294 | 8.694／8.731 | 19.649／19.665 | 3.0517 GiB |

8-threadと4-threadの中央値差は約0.175秒。n=6と背景負荷未制御の条件から、8-threadが安定して優位とは判定しない。起動やmemoryの小差にも改善の判定を付けない。確率算出の中央値は1／2／4／8-threadで6.0／6.8／7.5／7.1 µs、p95は6.5／7.4／7.7／12.1 µsだった。事前作成tensorからのprepare中央値は24.9／29.5／31.1／29.2 µsで、Tokenizer時間ではない。

全14 process・56 forwardで成功し、timeout／memory guard発火は0。4 goldenと全反復を通して対照とのraw logits最大差は0、goldenとの最大確率差は`4.9173831939697266e-6`、判断・token数は全件一致した。gate／warmup／計測ありの結果はwarm性能matrixへ含めない。[raw・再集計証跡](research/jeff-onnx-tract/forward-profile-2026-10-10/README.md)を保存した。

## 演算内訳と次の候補

1-threadの計測ありforward中央値は12.117秒／p95 12.155秒、n=3。callback内側のplan総時間中央値は12.111秒、operator合計は12.094秒、差分のdriver・計測処理は0.017秒。外側のforwardには集計・JSON生成も含む。この差分はcallback導入による総overheadの推定値ではない。計測あり／なしを交互比較した実験ではないため、通常forwardとの差を厳密なoverheadには換算しない。

| top-level operator | calls／forward | wall time中央値 | p95 | plan時間に対する比率の中央値 |
| --- | ---: | ---: | ---: | ---: |
| OptMatMul | 4,213 | 7.046秒 | 7.123秒 | 58.00% |
| ScatterElements | 144 | 1.902秒 | 1.907秒 | 15.70% |
| MoveAxis | 378 | 1.157秒 | 1.199秒 | 9.78% |
| Trilu | 18 | 0.693秒 | 0.695秒 | 5.74% |
| OptMatMulPack | 6,265 | 0.443秒 | 0.460秒 | 3.77% |
| Scan（子plan込み） | 18 | 0.001430秒 | 0.001666秒 | 0.0122% |

比率はforwardごとのoperator時間／plan時間から集計した。各行の中央値は同じforwardを代表するとは限らず、単純加算しない。Scanが小さいことをGated DeltaNet全体が軽い根拠にはしない。exportで展開された演算は他のoperatorにも現れるため、ONNX由来nodeとshapeの対応付けが必要である。今回の内訳は1-threadだけで、8-threadに残るコストの内訳は未測定。

次の最適化候補は以下の順に検証する。ここでの期待効果は未実測であり、短縮秒数を割り当てない。

1. 4／8-threadでも同じcallback診断を別実験として実施し、OptMatMulをshape・由来node・call数で分ける。多数の小型GEMM、packing、thread dispatchのどれが残るかを確定する。
2. ScatterElements／MoveAxis／Triluの実装を調べ、copy／allocation／index処理とDeltaNet変換の対応を固定する。小型再現例と単一変更で比較し、重複indexや非連続layout等の意味を変えない。
3. 4／8-threadの独立セッション数を増やし、有効256／384／511／512-tokenのrequestへ広げる。固定物理512と実token数を分け、Nativeとの同形状・保持dtype・thread条件の比較を追加する。

次回検証用の**実験予算仮説**は、今回の4／8-thread・候補requestのwarm forwardを12秒（観測p95最大9.294秒×1.2を秒へ切上げ）、初期化を25秒（観測最大20.205秒×1.2を切上げ）、memoryを4 GiB（観測最大3.0517 GiB×1.25を0.5 GiB刻みで切上げ）とする。少数標本からの保証や製品SLOではない。以前のNative CLIの8秒SLO候補を変更せず、Tract API E2Eは接続・別測定後に判断する。

## 比較条件

同一step1113・batch1・物理512 tokens・FP32のdeclutter済みNNEFを使用する。温度、候補数、左padding、判断閾値とgoldenは前回から不変。受入済みの重複探索削除版を基準にし、棄却したsuffix探索変更を含めない。Native・通常Tract probe・公開API・Decision Report契約は変更しない。

Tract 0.23.8の固定commit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a` では、CPU多スレッド演算は`tract-linalg/multithread-mm`機能で有効になる。独立生成したbuildでこの機能を有効にし、同一exeから1／2／4／8のexecutorを選択する。実poolサイズ、panel threshold、element thresholdを初期化イベントへ出力し、指定と不一致なら失敗させる。poolサイズは各演算が常にその全threadを使う保証ではない。

従来のfeature無効版と今回のfeature有効1-thread版を、4 goldenで接続検証する。その後、2／4／8-thread版も全4件の確率・判断・token数gateに通す。既存の確率許容差1e-4、確率和許容差1e-6を維持し、raw logitsは255個の有限値と対照との差最大1e-3を追加条件とした。許容値と実測誤差を区別する。

性能matrixはcandidate-request（有効128、物理512 tokens）のみ。各threadにつき独立2セッション、各1 warmup＋3測定でn=6。順序は1→2→4→8、次に8→4→2→1とする。反復の依存性が残るためセッション別中央値も記録する。nearest-rank p95はn=6では観測最大値になる。起動時間・Peak Working Setは各2セッションの観測であり、cold受入試験の代わりにはしない。

演算診断は同じexeの1-thread、独立1セッション、1 warmup＋3測定。公開`run_plan_with_eval` callbackでtop-level operatorのwall timeを測り、通常の`plan::eval`へ委譲する。Scan等の子planは親operatorの時間に包含される。Gated DeltaNet専用kernelの時間やCPU利用時間には換算しない。計測は既定で無効で、計測ありの結果を性能matrixへ混ぜない。

CPUはIntel Core i7-1360P（12 core／16 logical）、電源policyはバランス。CPU affinity・温度・背景負荷・storage cacheは制御しない。資産hash検証は子process起動前、ビルド・試験は測定の外側で行う。各processは600秒とmin(8 GiB,物理RAMの50%)の監視guardを使用する。Peak Working Setはmapped/shared pagesを含むprocess生存期間のpeakで、private RSSではない。

## 再現・依存・残作業

[生成script](../runtime/onnx/prepare_forward_experiment.py)、[測定script](../runtime/onnx/benchmark_forward.py)、[callback](../runtime/tract-driver-profile/forward_profile.rs)、[開発手順](../runtime/onnx/README.md)を保存する。新規Cargo targetを分離し、既存の対照exeをhash固定する。`forward.Cargo.lock`でRayon／Crossbeamの追加5 packageを固定し、license宣言・本文・crate checksumを証跡へ保管する。これは配布承認ではない。Pythonは開発側の監視・集計だけで、Rust推論runtimeへ依存を追加しない。

このpilotはprepared tensorのforward診断である。Tokenizer、TractBackendのAPI E2E、入力長matrix、正式SLO、実OCR/ASRの品質は未受入。過去のNativeはunpadded形状・別の重み保持方式・1-threadの測定なので、今回の値からNativeに対する高速化倍率や採用判定を出さない。

ローカル検証はPython小型回帰24試験（skip 0）、実験buildのrelease clippy、追加Rust callbackのrustfmtで合格した。最終generatorを新規ディレクトリへ再実行し、測定treeの全生成ファイルhashと一致した。追加CIへ同じ生成・locked build・clippy・小型試験を組み込んだが、GitHub上のCI実行は確認していない。
