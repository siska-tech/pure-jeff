# Native Rust / Tract：定量ベンチマーク計画

実行済みの部分と数値は[Windows CPU性能pilot](onnx-tract-performance-pilot.md)を参照。以下は正式比較を含む測定設計であり、全matrixを完了したことを意味しない。

2026-10-10。[実装計画](onnx-tract-plan.md)のPhase 3仕様案。**以下は測定設計であり、Tractの実測値・改善倍率・確定SLOではない。** 同一checkpointの数値受入に成功してから実行する。

## 1. 比較の公平性

測定単位は同じrequest JSON、prompt bytes、tokenizer、非padding IDs、候補数・順序、temperature、policy、CPU thread数。weightは現行step1113からの同一変換元に固定する。公開step960をそのまま使う計測は「別モデルの参考値」とし、本比較表へ混ぜない。

| 系列 | Native | Tract | 目的 |
| --- | --- | --- | --- |
| one-shot E2E | 現行exe、1要求1子、全hash/loadを含む | 新worker、1要求1子、全hash/import/optimizeを含む | 実際の既存呼出方式の費用 |
| resident E2E | 参照とは別の実験wrapperでtokenizer/検証済み資産を保持 | tokenizer/plan/重みを保持 | 共通の再利用条件での費用 |
| prepared forward | 準備済み重み、backbone＋readout | 準備済みplan、head込みgraph | 演算engineの差。入力変換・weight conversionも別記録 |
| start＋N requests | N=1/5/20/100 | 同じN | 常駐初期化の償却とメモリ推移 |
| graph表現 | — | raw正規化ONNX / NNEF | 読込・compile方式の差。既定採用前に数値一致 |

Nativeの現行forwardにはBF16→FP32変換が含まれる。mmapだけを保持するresidentとFP32 tensorを保持するresidentを区別し、後者を実装できない間は「対称なprepared forward比較は未完了」と記録する。凍結Nativeを最適化版で上書きしない。

同じ有効token数でもTract512は512位置を計算し、Nativeはunpadded長だけを計算する。この差は製品としての費用に含めて報告する。operator比較は同じshapeのmicrobenchmarkへ分離し、512/Lで機械的に補正した倍率を作らない。

## 2. 再現条件

Windows edition/build、CPU型番・P/E core・物理/論理数・ISA、RAM、電源plan、AC接続、温度/throttle、compiler/linker/toolchain、target flags、最適化level、Cargo.lock/features、exe/資産hashを保存。初期は可搬なCPU target、`target-cpu=native`等は別条件にする。

Native/Tractをseed付きrandomized blockまたはAB/BA交互順で測る。別backend、build、export、copy、hash監査を同時に走らせない。CPU affinityは初期値で固定し記録し、P-core限定等は別の実験にする。OS cacheを消したと称するために単にprocessを再起動しない。

thread数は1、2、4、8、min(16, logical cores)、重複を除去。総並列要求数は初期1。Candle/Rayon/Tractの実executor設定を保存し、要求並列×GEMM並列の入れ子を別実験にする。thread設定が反映できないcellは除外理由を残す。

## 3. 計測区間

| 項目 | 定義 |
| --- | --- |
| parent E2E | 呼出側が要求を受けた時刻からvalidated Attemptを得るまで。spawn、IPC、wait、出力検査を含む |
| worker E2E | 子の開始から応答write完了まで。parentとは別scope |
| asset verification | manifest、graph/weights/tokenizerのbytes/hash、path/config検査 |
| tokenizer initialization | tokenizer loadと回答語彙/設定検証 |
| prompt/tokenize | prompt構築と非padding encode。tokenizer初期化と分ける |
| tensor preparation | 左padding、attention/mm/position規則、i64変換、buffer割当 |
| graph load / type / optimize / plan | protobuf・external data load、shape/type inference、optimization、runnable/packingを可能なAPI境界で分ける |
| weight conversion | Native BF16→FP32やTract packing等。APIで分離できない場合は包括区間の名前に明記 |
| forward | Nativeはbackbone＋readoutまで、Tractはhead込みraw logitsまで。対称性を保つ |
| score/policy | 候補mask、temperature、softmax、閾値、Observation構築・検査 |
| serialization/IPC | 出力bytesの生成/write、parent read。多重計上しない |
| peak memory | workerのOS PeakWorkingSetSize。parentは別に保存。compileピークとrunピークを区別 |

単調clockで採取し、各区間の開始/終了と包含関係を定義する。p95の各区間値を加算してE2E p95としない。profileあり/なしのoverheadをpilotで比較する。Tractの1つのAPIが最適化とpackingを兼ねる場合、推定で分割せず包括値と記録する。

## 4. cold / warm / repeatedの定義

- **process-cold / cache-uncontrolled**：新process、モデル未load。OS file cacheは制御せず記録。既存P4と比較できる基本条件。
- **storage-cold**：別の検証hostまたは再起動直後など、cache条件を明示して測定。条件を制御できなければ未測定とする。最低10回は参考、p95受入には30回以上を集める。
- **model-warm**：同じprocess、同じ検証済みmodel/tokenizer/planを保持。warm-up 5回を別保存してから測定。初回inferに遅延packingがあれば初回をstartup costへ計上する。
- **repeated/mixed**：同一入力の反復と、異なる4 golden・候補順・長さの交互入力を別測定。各要求のrecurrent/execution stateは初期化する。出力の履歴依存を検出する。

OS PeakWorkingSetSizeはprocess生涯最大値なので、同じresident processの各要求へ「要求別peak」としてコピーしない。セッション単位peakと、要求前後のcurrent working set/private bytesを分ける。10 ms sampleを補助にし、OS peak counterを保持したprocess handleから終了時にも読む。sample総和はshared pageを重複計上し得るため、private RSSと呼ばない。

## 5. 入力・標本数

### 第1段階：pilot

数値合格済みの4 goldenで、backend 2 × threads 1/代表最大 × mode cold/warmを各5回。warm-upは別。これは計測費用・外れ値・resource guardの確認用で、改善を採用判定する標本数ではない。

### 第2段階：主要比較

request全体のencode長を128、256、384、511、512に合わせた人工集合を作り、候補2/3/8件、OCR/ASR・日本語/ASCII/Unicodeを分散させる。各token長につき少なくとも4種類の異なる本文を用意し、同じcellの入力集合・順序を両backendで共有する。完全に同じ内容で長さを変えることはできないため内容差と長さ差を記録する。

主要matrixは2 backend × 5 token長 × 最大5 thread条件 × 2 mode = 最大100 cell。coldは各cell n=30（最大1500 one-shot runs）、warmは各cell n=100を10セッション×10測定に分ける（最大5000測定、別に各セッション5 warm-up）。cellごとに本文の内訳も記録し、既存4 goldenは実request別の比較表も残す。

CPU budget不足ならpilot後に対象cellを事前登録して縮小し、欠測cellを埋めたふりはしない。最終候補はcold n=100、warm n=300以上へ増やし、別日または3回以上の独立実験blockで再確認する。反復が独立ではないことを踏まえ、区間推定はsession/blockを単位にする。

### 境界・別実験

511/512/513の成功/拒否、max token予算ちょうど/1不足、2候補/多候補、長文874/3206/8192は機能試験として別集計。512超を速度の成功分母に含めず、短文だけのcoverageを明示する。raw tensorで64 tokens等のmicrobenchmarkを行う場合、KazeJudgeの完全promptとして有効なrequestと混同しない。

形状を変えた128/256/1024等のONNXは**別export資産**とする。chunkループがunrollされているためinput shapeを書き換えるだけでは代替できない。各exportでoracle一致を確認し、bucket選択・planメモリ・実token予算を測る。

batch=2/4/8はPhase 4の別matrix。throughput、batch内1件当たり計算時間、batch形成待ちを含むrequest latency、待ち列長を報告する。平均計算時間だけで単発応答の改善を主張しない。

## 6. 集計とraw record

各cellで成功/失敗/timeout/拒否の件数、p50、p95、min/max、sample数を出す。quantileはnearest-rank（p50は昇順ceil(0.5n)、p95はceil(0.95n)）と明記。外れ値は削除せず、原因が確定した別実験混入等のみ無効runとして理由付きで残して再測定する。

timeoutは成功latencyから除外したことを明記し、全attemptを母数にdeadline達成率と片側95%区間を報告する。成功だけのp95でSLO合格にしない。成功率や性能差はpaired request/blockから区間推定し、5標本のp95を安定値と扱わない。

raw JSONLに最低限以下を保存する。

```text
run_id, experiment_id, date_utc, seed, block_id, session_id, iteration
backend, backend_revision, executable_sha256, checkpoint_sha256
graph_sha256, external_data_sha256, manifest_sha256, export_passes
input_id, request_sha256, prompt_sha256, token_ids_sha256
effective_tokens, physical_tokens, candidate_count, batch_size
requested_threads, actual_executor_threads, cache_mode, warmup
stage_start/end_ns, parent_e2e_ms, worker_e2e_ms
worker_peak_working_set_bytes, parent_peak_working_set_bytes
current_working_set_bytes, private_bytes, memory_scope
outcome, failure_stage, timeout_limit_ms, guard_trigger
max_abs_probability_error, judgment_match, forwards
host/build/power/ISA metadataへの参照
```

完全なrequest本文は人工fixtureまたはアクセス管理した品質データへ置き、benchmark recordにはID/hashを使う。実データの本文を公開CIログへ出さない。

## 7. 調査用resource guardとSLO案の出し方

安全な実験上限案はload/optimize 600秒、1 forward 120秒、worker working set 8 GiBまたは物理RAMの50%の小さい方。空きRAMが4 GiB未満なら実験を開始しない。これは**計画時の暫定guardで、性能SLOではない**。構成に足りなければ黙って増やさず、失敗段階・peakと必要量を記録して再見積もりする。親が監視しkill/waitする方式で、OSによる厳密なメモリ強制上限とは区別する。

改善の目標はまず「同一品質・同じ運用条件でNativeを上回ること」とし、倍率は実測後にだけ計算する。採用候補はE2E差の95%区間が改善方向にあり、事前に合意した最小有用差を満たし、load/memoryが利用側予算内であること。call側の最小有用差が未定なら順位付けまでに留める。

測定後は次の形でSLO案を作る。

1. 実routingのtoken/thread/寿命分布で重み付けしたp50/p95とdeadline達成率を示す。平均latency×routing率でtail latencyを推定しない。
2. 最終候補の独立blockからp95の95%上限を算出し、その上限に例えば20%の余裕を加えた値をlatency SLO候補として提示する（20%自体も暫定）。cold startupとwarm requestは別SLOにする。
3. 実測peak＋同時実行数＋graph compileの一時領域を見積もり、観測最大の例えば25%余裕を初期memory予算案とする。観測最大から全将来runの上限保証はしない。
4. 候補SLOが呼出側の許容時間/メモリを超える場合、実測に合わせて製品の要求を緩めたことにせず、非採用・routing縮小・resident・Nativeを提案する。
5. 最終SLOはhold-out性能runより前に固定して別runで受入を行う。例えばtimeout率1%未満を求める場合、独立300試行で0件でも片側95%上限は約1%であり、少数試験から保証しない。

常駐化の損益分岐は初期化時間I、one-shot単価C、warm単価Wとして、C>Wなら概算N>I/(C−W)。両backendの同じ資産検証条件で算出し、memory・queue・再起動費用も合わせて判断する。

起動時graph処理については、[重複探索の削除実験](onnx-tract-duplicate-search.md)で単一変更を別targetへビルドし、4件回帰の後に交互のcold 5組と常駐forwardを比較する。内部診断の寄与時間を、そのまま除去可能時間とみなさない。n=5・1入力のpilotは上記の正式SLOや品質評価を満たさない。

[suffix探索の変更実験](onnx-tract-name-index.md)は数値・命名回帰に合格したが、cold 5組すべてで遅くなり不採用とした。既存の受入版を対照に固定し、理論上の走査削減と実測改善を分ける。次はforwardのoperator内訳とthread matrixを優先し、同じ数値gateを要求する。

[forward内訳・thread pilot](onnx-tract-forward-profile.md)では、同一多スレッド対応exeの1／2／4／8-thread executorを4件gate後に比較した。各2独立session×3測定、n=6の中央値は11.744／9.746／8.869／8.694秒。正式比較の標本数・token長matrixを満たしたとは扱わず、4／8-threadを次の候補に残す。profileは別session・1-threadだけで、8-threadの残余コストをこの内訳から断定しない。次は4／8-threadのoperator・shape・由来nodeの対応、session増加、Nativeとの同条件化を先に固定する。

[4／8-thread演算診断](onnx-tract-thread-profile.md)は前回exeを固定し、各2 session・計測ありn=6で残余を追跡した。ScatterElements約2秒、MoveAxis約1.3秒、Trilu約0.8秒が残る。計測なしの性能比較ではなく、新しい高速化実績には数えない。次はTriluのcontiguous行fillだけを別targetへ変更し、4-thread固定対照との数値gateと計測なしAB／BAを事前登録する。operatorの全観測時間を、そのまま短縮目標や高速化倍率へ換算しない。

[Trilu行単位処理実験](onnx-tract-trilu-rows.md)は4-threadの独立AB／BA／AB各3組、warm各n=9で中央値8.963→8.361秒、p95 9.900→8.666秒を観測した。全3組のsession中央値が短縮し、全40 forwardのraw logitsが一致したため局所受入とする。起動は各n=3の付随観測で、短縮は確認していない。正式SLO・8-thread・長さmatrix・Native同条件比較・API E2Eは未受入。次のScatterElementsは意味の監査と単一変更の独立比較から開始する。
[ScatterElements行単位コピー実験](onnx-tract-scatter-rows.md)は受入済みTrilu版を固定対照とし、4-thread・独立AB／BA／AB各3組・warm各n=9で中央値8.284→6.884秒、p95 8.467→7.341秒を観測した。全3組のsession中央値が短縮し、全40 forwardのraw logitsが一致したため局所受入とする。起動短縮は確認していない。I64 reductionの既存拒否64条件は成功数へ混ぜず記録した。次はこの候補を固定した4／8-thread・入力長matrixと同条件Native比較へ進める。過去の別日の対照値を差し引いた累積倍率や、演算診断からの期待倍率は提示しない。

[受入候補の4／8-thread比較](onnx-tract-accepted-threads.md)は同一Scatter版exe・独立3組・各n=9で中央値6.973／6.518秒、p95 7.097／7.167秒を観測した。8 threadsは全session中央値で短縮したがp95が増え、事前条件に従い次のpilotは4を維持する。全32 forwardのraw logitsが一致。Rust tokenizerによる24件の長さfixtureは準備済みで、oracle／Tract gate／長さ性能は未受入。128は4種、256／384／511／512は4種＋8候補1種であり、128の8候補cellは欠測として区別する。

[入力長pilot](onnx-tract-length-pilot.md)では同一step1113のONNX oracleを24件へ追加し、既存4 goldenと合わせた28件gate後に4-thread・3独立resident sessionを実施した。主要4本文×5長さ×3反復で測定60件、各長さn=12。forward中央値は128／256／384／511／512で6.260／6.408／6.431／6.517／6.476秒、p95は7.189／6.862／7.116／7.102／7.198秒。全103 forwardの数値gateが合格した。8候補追加4件はgateのみで性能分布へ混ぜない。全入力は物理512で、本文と長さも交絡する。3独立session・n=12 p95=maxの記述的pilotであり、正式比較の標本要件・SLO受入を満たさない。初期化／process peak各n=3は付随観測で、cold campaignや長さ別memoryではない。

次のNative比較は先にpadding／attention mask／保持dtype／実executor threads／資産検証と段階境界を監査する。既存NativeのBF16保持・可変長とTractのFP32保持・固定512を混ぜた差をruntime単体の効果としない。同条件化のためにNative参照実装の挙動を変えず、必要なら独立した実験経路で数値gateを再実施する。同条件化できない項目は運用構成比較として分離し、その制約を事前登録する。Tokenizer／API E2E・独立block追加・hold-out受入は別測定として残る。

[共通512形状pilot](onnx-tract-common512-pilot.md)はこの監査から、paddingなしの有効512入力と1 compute threadを共通化する。既存Nativeはpadding maskを受け取れず、保持dtypeの統一にはloader／cache実装が必要なため、今回は固定exeを変更しない運用構成比較とした。独立3組AB／BA／AB、同一request・入力順序、各session 1 warmup＋4測定、各backend n=12。Native backbone＋head/softmaxとTract forward＋scoreを集約して比較する。保持dtype・algorithm・内部分割が異なるためruntime単体の効果や高速化倍率を主張せず、request／初期化の非対称な区間は別診断として保存する。

同pilotは全46 forwardの数値gateに合格し、compute中央値Native 9.892／Tract 9.626秒、p95 10.703／10.133秒を観測した。3組のsession中央値はTract側が短かったが、Unicode入力の中央値と最後の組のp95はNative側が短い。非対称な保持・algorithm、各本文n=3・1 warmupであり、採用／正式SLOの受入には進めない。次の比較では保持dtype・変換／cache・thread条件を独立実験経路で揃えられる範囲を固定し、数値gateと事前登録を繰り返す。API E2Eとcold campaignは別測定で残る。

[Native FP32保持実験](onnx-tract-native-retained.md)は固定Nativeから別crate／targetへ生成し、同一exeのmmap／保持modeを1-thread・共通512・独立3組で比較した。全46 forwardが固定Nativeの確率と完全一致し、compute中央値9.789→9.073秒／p95 10.407→9.675秒、全組中央値が短縮したためwarm性能のみ局所受入した。初期化中央値2.054→3.806秒、process peak最大約1.947→4.835 GiBへ増加した。473 model tensorsを保持し、うち未使用visual 153 tensors／402,371,584 FP32 bytesが静的棚卸しで判明した。次はtext使用320 tensorsだけを保持する候補を独立に比較する。不要payloadは特定したが、除外後の実測peak・時間の改善は未受入。保持による差を純粋なBF16変換時間と呼ばず、別runのTract値と差し引いて新しいbackend優位性や倍率を提示しない。

[text320保持実験](onnx-tract-native-text.md)は全473保持版を固定対照に、選択するmodel tensor名だけを変更した。共通512・1-thread・独立AB／BA／AB各3組・各n=12、全46 forwardの候補確率が固定Nativeと完全一致。全組のlifetime peakが減り、pooled最大5,190,696,960→4,591,202,304 bytesで、事前条件どおりメモリ削減のみ局所受入した。compute中央値9.205510→8.929919秒／p95 9.607663→9.311753秒、初期化中央値3.822734→3.544215秒は記述的観測。2組目のcompute p95は増加した。速度の事後受入・正式SLO・warm private memory・cold campaignの成立とは扱わない。次は固定text320候補のthread実行条件を監査し、Tractとの同条件再比較を事前登録する。保持dtypeをFP32へ揃えてもpacked layout・algorithm・段階境界の差は残る。

[FP32保持・共通512再比較](onnx-tract-fp32-common512.md)ではNative thread経路を固定Candle source／feature treeで監査し、text320保持版と受入Tractを同一step1113・FP32常駐・有効／物理512・1 compute threadで独立3組比較した。全46 forwardの数値gateが合格し、各n=12のcompute中央値はNative 9.005815／Tract 9.669719秒、p95 9.225719／9.946535秒、全組／本文の中央値・p95はNativeが短い。process peak最大は4,591,132,672／3,277,074,432 bytesでTract側が低い。packed layout・algorithm・段階／startup検証範囲は異なり、運用構成の記述的pilotとして扱う。正式SLO・backend採用・runtime単体効果・速度倍率は未受入。固定Native wrapperは両envを1に上書きしpolicy≠1を拒否するため、次のthread matrixには独立wrapperを作り数値gateから再検証する。

[Native thread matrix](onnx-tract-native-threads.md)ではtext320の独立wrapperで両envを設定し、実global Rayon poolサイズとCandle設定を確認する。1／2／4／8を4 blockのWilliams順序で均等化し、1 warmup＋4測定/session、各n=16。全112 forward数値gate合格、compute中央値9.094808／7.121384／6.738168／7.158093秒、p95 10.013065／7.438257／7.478409／7.393373秒。1比で全block中央値とpooled中央値／p95が短い2／4／8を適格とし、中央値最小の4を次pilot候補に選んだ。ただし4のp95は2／8より大きく、他候補への非劣性・正式SLO・製品採用は未受入。1／4の確率は固定Nativeと完全一致、2／8の小差と反復揺らぎは事前許容内だった。次はhold-out再測定と同thread Tractの運用構成比較。n=16 p95=max、4独立blockのみで、実品質・API E2E・cold campaignは未完了。

[Native2／4確認とTract4比較](onnx-tract-native-confirm.md)は前回と独立session／seed、同じ人工4入力を使った確認で、入力hold-outではない。6順列で各n=24、全114 forward数値gate合格。Native4は全6組の中央値とpooled中央値／p95でNative2を下回りwarm局所確認した。compute中央値Native2 7.169396／Native4 6.869798／Tract4 6.841555秒、p95 7.548223／7.087960／7.552309秒。Tract4は中央値が約0.028秒短いがp95は大きく、runtime単体効果・採用の根拠にしない。測定済み4-thread／FP32常駐／batch1／共通512に限り、次のprepared-compute暫定SLO候補p95≤8秒を提案する。両4-threadの今回観測最大が8秒未満という結果に基づく計画値で、事後受入や達成済みSLOではない。新規入力・5 warmup・warm n≥300・別日または3回以上の独立blockを含む正式計画で再検証する。API E2E／cold／routingのSLOは区間を揃えて設定する。

[Native4／Tract4長さ別比較](onnx-tract-length-compare.md)は3組・各長さn=12を事前登録したが、2組目Nativeの反復誤差上限1e-6違反で停止した。全6 child／156 forwardはONNX候補確率1e-4・判断・tokens条件に合格し、Tract全78 rawは旧gateと一致。一方Native6観測・4ケースが反復条件不合格、最大3.546476364135742e-6。閾値は変えず、第3組50 forwardは未実施。各長さn=8の生観測はあるが、不合格sessionを含む未完了runの診断値とし、pooled性能・採用・SLOは未受入。Native有効長／Tract左padding物理512のshape差も区別する。両backendの時間増大、Nativeの組間変動、512の8秒超を観測し、従来の8秒候補の安定性は未確認。process snapshotは累積CPUのみで原因を断定しない。次は固定4失敗ケースの1／4-thread反復診断、元の数値条件の再受入、AC／温度／背景負荷／CPU配置の記録・制御方針を先に固定して別runへ進む。実OCR／ASR正解付きN-bestはユーザー確認により未準備でPhase 5はデータ準備待ち。

[反復数値診断](onnx-tract-native-repeat-diagnostic.md)では失敗4ケース＋512 controlを固定exeの1／4 threads・各2 process・同process3反復、全60 forwardで調べた。ONNX確率／判断／tokens条件は全件合格。最大の同process spanは1 thread 0.0、4 threads 0.0、全6観測spanは1 thread 0.0、4 threads 0.0。性能評価の再試行ではなく、元の不合格・閾値は維持する。全28件再受入・原因修正・正式SLOは未完了。


追加の[cache初期化診断](onnx-tract-native-cache-diagnostic.md)では独立crateでCPUごとのCACHE_INFOを記録し、初期化時だけmain threadを固定後に元maskへ復元した。2条件・AB／BA各2 process、128／512の2ケース・各2反復、全16 forwardがONNX確率／判断／tokens条件に合格した。入力ID・hidden・raw logitsと旧gate／停止sessionとの差は生ログから独立照合した。原因の判定範囲と実測差は同reportを参照。全28件再受入・原因修正・性能再開・正式SLOは未完了で、元失敗と閾値1e-6は維持する。


追加の[全28ケース固定cache検証](onnx-tract-native-cache-fixed-gate.md)で、前回の診断exeとcacheB初期化条件を固定し、8独立process・56 forward（各ケース2 process）を検査した。元の反復閾値1e-6・旧gate・ONNX条件を維持した局所再受入で、性能用exe・長時間resident・正式SLO・backend採用は未受入。次は診断出力を持たない独立性能wrapperの数値同等性を検証する。


追加の[固定cache性能用wrapper検証](onnx-tract-native-cache-timing-gate.md)で、request診断出力を除いた別crate／targetのexeを作成した。backbone／weights／readout／threadsは元wrapperと同一、156 package feature一致・16生成ファイル再現・Rust9試験／clippy／fmtに合格。全28件gate＋resident各2反復の84 forwardで診断版同等性と元の反復1e-6条件を局所受入した。次は固定exeでNative／Tractの新規長さ別pilotを行う。正式性能・SLO・長期resident・製品採用は未受入。


追加の[固定cache Native4／Tract4長さ別pilot](onnx-tract-cache-fixed-lengths.md)は、性能用exeの84 forward数値受入後に新規事前登録し、各backend28件gate＋3独立resident組、全14 child・206 forwardを完了した。旧gate／Native全観測ペア差≤1e-6とTract raw一致、power／resource条件を維持。各長さn=12の記述的比較で、正式SLO・API E2E・backend採用・入力hold-outは未受入。元の停止runは置換しない。


追加：Windows環境の[継続記録・結合検証](onnx-tract-host-observer.md)を実施した。既存invokeと固定exeを変えず、各3 forward・電源／CPU情報のraw記録と独立監査に合格。性能受入ではなく、次はobserver overheadのAB／BA比較、配置変更時の全数値再gate、未使用本文と正式標本数への拡大を行う。温度は取得不可、OS報告MHzはhardware実測値ではない。


追加の[observerあり／なし比較pilot](onnx-tract-observer-overhead.md)は、既存128-token入力・各backend2組の順序反転・5 warmup＋3測定で8 child／64 forwardを実施し、数値・resource・host条件と独立再計算に合格した。各条件n=6の記述的比較であり、observer負荷の同等性・正式性能・SLOは未受入。


## 2026-10-11 実OCRの取込状況更新

[kzn-dataset取込監査](onnx-tract-kzn-ocr-intake.md)で、人手確認済みdevelopment 3件を正解と分離して抽出し、KazeNhanh単独で3件保留・SLM呼出し0を確認した。実OCRは存在するが、ユーザー確認を含めN-bestは未保存。Jeff併用品質比較は未実施。test 1件は件数確認のみで推論へ渡していない。品質評価には実N-bestとraw-visual.v1の評価方針整合が必要であり、goldから候補を作らない。この1 child動作確認は性能標本に含めない。
