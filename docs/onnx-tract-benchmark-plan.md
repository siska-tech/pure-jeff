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
