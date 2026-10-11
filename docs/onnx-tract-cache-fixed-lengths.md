# 固定cache Native4／Tract4：長さ別比較pilot

2026-10-11。[性能用wrapperの数値受入](onnx-tract-native-cache-timing-gate.md)後に新規事前登録したrun。過去の停止runに標本を補充・置換せず、元の失敗と閾値は維持する。既存Native・公開API・Decision Reportは不変。

## 条件と測定範囲

同一step1113・FP32常駐・batch1・4 compute threads。Nativeはtext320＋head1保持の受入済み性能用exeで、cacheBをlogical CPU0で初期化し、main thread maskを65535へ復元してからpool／model／forwardを作る。Tractは受入済みScatterElements行コピー版exeと固定NNEF。どちらも今回のrunでビルドし直していない。

28-case gateを各backend 7件×4 childで実施後、AB／BA／ABの3独立resident組を実行した。各sessionは5 mixed-length warmup（長さごと1件）と20測定（4本文×5長さ）。各backend・長さ128／256／384／511／512でn=12、各入力n=3、全14 child・206 forward（各backend103）。8候補のextraはgateのみで128 cellがなく、性能表へ含めない。seed7901113、入力順・warmup本文・受入条件は推論前に固定した。

ONNX確率差≤1e-4・確率和誤差≤1e-6・判断／tokens一致、Native既存参照≤1e-4、旧28-case gateと今回の全観測ペア差≤1e-6、Tract raw logitsの旧length gate完全一致を必須とした。pool・保持payload・cache／affinity・期限600秒・peak上限min(8 GiB,物理RAMの50%)も照合した。各child前後のAC接続・省電力flagなしを必須条件とし、system CPU累積時間を記録した。

Nativeは有効長を演算し、Tractは左paddingした物理512を演算する。短い入力のshape、packed layout／algorithm、初期化の検証区間、Native tokenize／policyとTract prepared-inputのrequest境界は非対称で、runtime単体効果を測る比較ではない。prepared computeはNative backbone＋head/softmax、Tract forward＋scoreを集約した。request時間はAPI E2Eではない。温度・周波数・背景負荷・推論core配置は未制御、同じ既存人工入力でhold-outではない。

## 数値・resource gate

全206 forwardが数値・判断・tokens・resource条件に合格し、全14 child exit0、guardなし。最大ONNX確率差4.6491622924804688e-06、既存Native参照差最大0、Native gate比反復差最大0。Tract全103 forwardのraw logitsが旧gateと一致した。生ログから全差分・全観測ペア・入力順・pool／cache／power／resourceとすべての統計を独立再計算した。

## 長さ別warm prepared-compute（秒）

各cell n=12。nearest-rank中央値／p95を使い、n=12のp95は最大値である。

| 有効tokens | Native中央値 | Native p95 | Tract中央値 | Tract p95 | n／backend |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 128 | 5.441 | 5.770 | 17.722 | 18.463 | 12 |
| 256 | 10.363 | 10.836 | 17.895 | 18.948 | 12 |
| 384 | 15.140 | 15.540 | 17.892 | 18.721 | 12 |
| 511 | 20.041 | 20.744 | 18.281 | 19.567 | 12 |
| 512 | 20.071 | 20.906 | 18.130 | 19.241 | 12 |

## 独立組ごとのcompute中央値（秒）

| block | backend | 128 | 256 | 384 | 511 | 512 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | native4 | 5.389 | 10.402 | 14.602 | 20.041 | 19.973 |
| 0 | tract4 | 17.936 | 18.128 | 17.892 | 18.444 | 18.699 |
| 1 | native4 | 5.405 | 10.293 | 15.140 | 19.853 | 20.337 |
| 1 | tract4 | 16.602 | 16.795 | 17.283 | 17.537 | 18.008 |
| 2 | native4 | 5.468 | 10.363 | 15.371 | 19.213 | 19.543 |
| 2 | tract4 | 16.110 | 16.194 | 17.857 | 18.277 | 18.599 |

## 段階・メモリ

Nativeのtokenize／backbone／head／policy、Tractのprepare／forward／scoreと各requestの中央値・p95・nはsummary.jsonに保存した。初期化とlifetime peakはresident session各n=3の付随観測で、storage-cold campaignやwarm private memoryではない。

| backend | startup中央値 (s) | startup p95 (s) | lifetime peak中央値 (GiB) | peak最大 (GiB) | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| native4 | 6.001 | 6.265 | 4.277 | 4.277 | 3 |
| tract4 | 74.256 | 75.534 | 3.053 | 3.053 | 3 |

電源・system CPUの前後snapshot：

| run | AC前→後 | 省電力flag前→後 | system平均busy (%) |
| --- | --- | --- | ---: |
| gate-native4-0 | 1→1 | 0→0 | 30.143 |
| gate-native4-1 | 1→1 | 0→0 | 30.450 |
| gate-native4-2 | 1→1 | 0→0 | 30.107 |
| gate-native4-3 | 1→1 | 0→0 | 30.937 |
| gate-tract4-0 | 1→1 | 0→0 | 27.396 |
| gate-tract4-1 | 1→1 | 0→0 | 27.280 |
| gate-tract4-2 | 1→1 | 0→0 | 27.755 |
| gate-tract4-3 | 1→1 | 0→0 | 28.139 |
| resident-0-native4 | 1→1 | 0→0 | 30.090 |
| resident-0-tract4 | 1→1 | 0→0 | 29.610 |
| resident-1-tract4 | 1→1 | 0→0 | 30.265 |
| resident-1-native4 | 1→1 | 0→0 | 30.483 |
| resident-2-native4 | 1→1 | 0→0 | 31.065 |
| resident-2-tract4 | 1→1 | 0→0 | 30.564 |

system平均busyは他processを含む累積時間差であり、child利用率や競合原因の証明ではない。前後のpower snapshotからrun全時間の電源状態を保証しない。

## 判定と次の作業

128 tokensではpooled中央値がNative側で短く、p95はNative側で短かった。

256 tokensではpooled中央値がNative側で短く、p95はNative側で短かった。

384 tokensではpooled中央値がNative側で短く、p95はNative側で短かった。

511 tokensではpooled中央値がTract側で短く、p95はTract側で短かった。

512 tokensではpooled中央値がTract側で短く、p95はTract側で短かった。

512の今回p95はnative4, tract4で8秒候補を超えた。8秒SLOは未達成・安定性未確認の計画値のままとし、このrunを支持証拠へ読み替えない。

この固定exe・入力・host条件の数値gateと記述的な長さ別pilotを完了した。今回の大小関係を未使用本文や別hostへ一般化せず、速度倍率・runtime単体効果・製品backend採用の根拠にはしない。p95は最大値、3独立組・各入力n=3、順序は部分均等化のみである。旧停止runの数値不合格や時間変動は別の有効な証跡として維持する。

次は独立blockと未使用入力を増やし、AC／電源・背景負荷・CPU配置／温度／周波数の記録・制御方針を固定する。正式warm測定は5 warmup・n≥300と別日または3回以上の独立blockを含め、成立する区間・入力・host条件から現実的なSLOを再提案する。API E2E・cold／warm差・storage cache・warm private memory・batch／量子化は別測定が残る。14-request数値反復と25-request性能sessionを超える長期resident履歴やportable cache初期化方針も未受入である。

既存Native/API・baseline127ファイル（既知.gitignore差のみ）・隣接KazeNhanh21ファイル・frozen assets・前回証跡は不変。Pythonは開発用のみ。正式SLO、公開TractBackend統合、配布NOTICE・clean host、Phase 5の確認済み実OCR／ASR N-best品質評価は未完了である。

[事前登録・生ログ・全段階の中央値／p95／n・独立validator](research/jeff-onnx-tract/cache-fixed-lengths-2026-10-11/README.md)。[比較ハーネス](../runtime/onnx/benchmark_cache_fixed_lengths.py)。


追加：Windows環境の[継続記録・結合検証](onnx-tract-host-observer.md)を実施した。既存invokeと固定exeを変えず、各3 forward・電源／CPU情報のraw記録と独立監査に合格。性能受入ではなく、次はobserver overheadのAB／BA比較、配置変更時の全数値再gate、未使用本文と正式標本数への拡大を行う。温度は取得不可、OS報告MHzはhardware実測値ではない。
