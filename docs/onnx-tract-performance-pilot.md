# Windows CPU性能pilot — 2026-10-10

**今回の128〜206-token短文群、1スレッド、現行step1113では、512固定Tractによる高速化は確認できなかった。Nativeを参照経路として維持する。** Tractの常駐計算もNativeの今回の実装より遅く、初期化ではgraph最適化が支配的だった。これは現在の実装・保持形式・入力shapeを含む運用条件の結果であり、演算エンジン固有の優劣や多スレッド性能の判定ではない。

証跡：[索引とraw record](research/jeff-onnx-tract/performance-pilot-2026-10-10/README.md)。計測設計：[定量ベンチマーク計画](onnx-tract-benchmark-plan.md)。Phase 3はpilotまでの部分完了で、正式SLO受入ではない。

起動コストの追加調査は[NNEF保存・再ロードの性能調査](onnx-tract-nnef-pilot.md)に分離して記録する。以下はONNXから毎回準備する経路の測定値である。

## 条件と数値受入

- Windows 11 Home build 26200、Intel Core i7-1360P、12 physical／16 logical cores、物理RAM約31.6 GiB。
- AC接続、電源planはバランス。CPU affinityは全16 logical coresを継承し、固定しない。温度・throttle・他アプリの負荷は制御していない。
- Rust 1.99.0、release、追加RUSTFLAGSなし。Tractは固定版0.23.8＋既存I64→TDim修正＋top-level ChangeAxes除外。executorは明示SingleThread。Nativeの固定manifestも1 thread。
- 同じstep1113 checkpoint・golden・候補順・temperature・policy。Tractは同じcheckpointからexportしたsequence変換版。公開step960は使用しない。
- 起動はcandidate-requestを各backend 5回、AB／BA交互。常駐は各backend 1セッションでwarm-up 5回、その後4入力を各5回、seed 1113で同じ順序にする。計測中にbuild・export・別benchmarkは実行しない。
- engine診断12セッション・60 forwardが成功。うち10 warm-upは本集計から除外。既存Native CLIも別途5回成功。計65 forwardすべてで確率誤差≤1e-4・判断一致。最大確率誤差はNative約5.07e-6、Tract約4.92e-6。
- p50とp95はnearest-rank。各cell n=5なのでp95は観測最大であり、安定したtail推定ではない。外れ値の削除・失敗の除外はない。

## 初回起動とモデル常駐

秒。診断プロセスは起動から応答出力・process exitまでを親で計測した。

| 測定範囲 | n | 中央値 | p95 |
| --- | ---: | ---: | ---: |
| Native診断プロセス、128 tokens・1 forward | 5 | 5.626 | 5.694 |
| Tract診断プロセス、同じ有効128 tokens・物理512 | 5 | 113.124 | 117.737 |
| 凍結Native CLI `decide-process`、親＋worker＋Attempt検証 | 5 | 5.516 | 5.873 |

Native診断の初期化にはbundle hash・tokenizer初期化が含まれる。Tract診断は事前tokenized入力を使い、資産hashは親のpreflightで行い、子の起動計測に含めない。このため上の診断プロセス間の倍率を製品E2Eの倍率とは扱わない。TractのDecisionProvider／worker API経路は未実装で、製品E2Eは未測定である。

OS storage cacheは消していない。計測前hash読取もあるため、ここでいう初回起動は**process-cold／storage cache uncontrolled**であり、storage-coldではない。

初期化の内訳、秒（各n=5）：

| 区間 | 中央値 | p95 |
| --- | ---: | ---: |
| Native bundle hash＋metadata検証 | 1.138 | 1.172 |
| Native tokenizer load＋回答語彙検証 | 0.803 | 0.825 |
| Native mmap | 0.000559 | 0.000638 |
| Native初期化全体 | 1.956 | 2.007 |
| Tract graph＋外部重みload | 2.796 | 3.015 |
| Tract型推論 | 3.506 | 3.561 |
| Tract限定最適化、declutter＋codegen | 94.341 | 98.961 |
| Tract runnable plan構築 | 0.293 | 0.360 |
| Tract初期化全体 | 100.957 | 105.635 |

包括区間を含むため、表の各区間を合計して全体p95を作らない。Nativeのmmapは全重みのFP32常駐化ではなく、BF16→FP32変換はforward内に残る。

## warmの計算＋確率処理

秒、各case・backend n=5。Nativeはbackbone＋readout・mask・temperature・softmax、Tractはhead込みforward＋同じ意味のFP32確率処理。prompt/tokenizer、policy、IPC、資産検証はこの比較区間に含めない。

| 入力 | 有効tokens | Native物理tokens | Tract物理tokens | Native中央値／p95 | Tract中央値／p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| candidate-request | 128 | 128 | 512 | 2.977／3.182 | 11.636／12.217 |
| reversed | 128 | 128 | 512 | 3.148／3.200 | 11.819／12.194 |
| asr-unicode | 206 | 206 | 512 | 4.266／4.365 | 11.836／12.669 |
| special-token-text | 182 | 182 | 512 | 4.128／4.395 | 11.737／12.531 |

NativeはtokenizerとBF16 mmapを保持するが、FP32 weight変換を毎forwardで行う。TractはFP32／packed planを保持する。対称な「FP32重み保持済みengine同士」の比較は未完了である。Tractは短い有効入力でも512位置を計算するため、その差とengineの差を分離するには別exportや同shape比較が必要で、512/Lによる補正は行わない。

常駐セッションは各backend 1つなので、独立セッションの95%区間は出していない。mixed順序で全判断が一致したことは確認したが、少数goldenによる認識品質評価ではない。

補助区間、ms（candidate-request、n=5）：

| 区間 | 中央値 | p95 |
| --- | ---: | ---: |
| Native prompt構築＋tokenize | 0.2551 | 0.2662 |
| Native readout＋mask＋temperature＋softmax、包括値 | 0.6773 | 0.7426 |
| Native policy | 0.0009 | 0.0010 |
| Tract準備済み入力のtensor化 | 0.0267 | 0.0294 |
| Tract mask＋temperature＋softmax | 0.0060 | 0.0065 |

Nativeのreadout APIではhead演算とsoftmaxを個別計測できないため包括値を記録した。Tractにはtokenizerを接続していないので、tokenizer時間を0と扱わない。今回の測定範囲ではtokenize／scoreよりforward・Tract最適化が支配的である。

## Peak Working Set

GiB＝2^30 bytes。Windows GetProcessMemoryInfoの**プロセス生涯最大値**を10 msごとに取得し、終了後counterも確認した。mapped／shared pageを含み、private RSSではない。

| backend | process-cold n=5の最大peak | residentセッションpeak、n=1 |
| --- | ---: | ---: |
| Native診断wrapper | 1.492 | 1.952 |
| Tract診断 | 3.265 | 3.265 |

resident peakを個別要求のpeakとして扱わない。coldは128 tokensのみ、residentは182／206 tokensも含む。NativeとTractの保持形式の違いを含む。既存CLI経路で採取したcounterはCLI親だけなので、worker memoryの比較表には使用していない。

resource guardは1 process 600秒・8 GiB Working Set、開始時空きRAM≥4 GiB。guard発火・timeout・process失敗は0。Native API測定は親180秒・worker120秒で成功した。monitor／profileありなしのoverhead比較は未実施である。

## 暫定SLO案と次の判定

**Native CLIの128-token・1-thread経路は、次回独立検証用のSLO候補を8秒とする。** 観測p95×1.2を秒単位で切り上げた値であり、呼出側の要件を満たすかは別途判定する。n=5だけで受入せず、独立block・より大きい標本数・長さ別条件で検証する。KazeNhanhのrouting、待ち行列、adapterまでを含むSLOではない。

その他は製品SLOではなく、次回実験用の予算仮説とする。計算時間は観測したcase別p95の最大×1.2を秒へ切上げ、memoryは観測最大×1.25を0.5 GiB刻みで切上げた。

| 範囲を限定した実験予算 | Native | Tract |
| --- | ---: | ---: |
| warm計算＋確率処理、今回の短文群 | 6秒 | 16秒 |
| cold診断process、128 tokens | 7秒 | 142秒 |
| process memory、今回の観測範囲 | 2.5 GiB | 4.5 GiB |

Tractの製品E2E SLOはAPI接続後に測定する。これらの仮説から将来の最大latency／memoryを保証しない。

次は、まずTractの約94秒の最適化を再利用できるかを調べる。最適化済みNNEFの保存・再ロードは候補だが、数値・operator登録・資産hash・architecture制約の受入が必要で、初期化短縮は未実測の期待効果である。forwardには512固定計算、DeltaNet展開、GEMM、state構築・tensor allocationのprofileを追加する。2/4/8/16 threadsは現在の単一threadビルドとは別variantで実executorを有効化し、数値受入後に比較する。

正式比較のn≥30、独立residentセッション、256/384/511/512-tokenの有効request、storage-cold、同shape／FP32保持条件、Tract API E2E、実routing分布は未測定である。現時点で速度を目的にTractを既定backendへ置き換える根拠は得られていない。
