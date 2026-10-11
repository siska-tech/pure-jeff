# Jeff Pure Rust Runtime：ONNX＋Tract調査と実装計画

実装着手後の結果は[進捗と判定結果](onnx-tract-progress.md)を参照。以下は策定時点の調査・計画である。

2026-10-10。対象はWindows x86_64 CPU、固定Jeff 0.8B、text-only。**現行Native Rustを参照経路として維持し、Tractは独立した実験経路として段階導入する。現時点では採用・高速化を確認していない。**

今回は現状分析と計画まで。既存runtime・公開API・tests・CI・golden・モデル資産を変更せず、TractBackendの実装、ONNX変換、Tractでのforward、性能測定は行っていない。公開ONNXのグラフだけを取得して静的解析した。約3.01 GBの外部重みは未取得。

関連成果物：[互換性マトリクス](onnx-tract-compatibility.md)、[定量ベンチマーク計画](onnx-tract-benchmark-plan.md)、[静的解析JSON](research/jeff-onnx-tract/onnx-static-inventory.json)、[checkpoint比較](research/jeff-onnx-tract/checkpoint-comparison.json)、[現行128ファイルの保全索引](research/jeff-onnx-tract/native-baseline.json)。

## 1. 判断と優先順位

1. **公開ONNXを現行checkpointの代替とは扱えない。** 学習step・run・temperatureが異なる。公開版はimport/graph変換の調査用とし、正式な数値・速度比較は現行checkpointから再exportした別資産で行う。
2. **無加工の公開ONNXはTract 0.23.8でそのまま実行できる見込みではない。** 静的解析で`SplitToSequence` 24個と`SequenceAt` 66個を検出。公式releaseの標準importerに登録がなく、全ノードが出力へ到達する。まず定数分割を`Split`／`Slice`へ置換する限定変換を検証する。
3. **Gated DeltaNetの専用カーネルは最初から作らない。** 公開graphは標準演算へ展開済み。opset 18・48種類・113,333ノードで、ONNXの`Loop`／`Scan`／独自domainはない。演算子名の対応だけでは巨大graphの最適化、メモリ、実forwardの成立は保証できない。
4. **512-token経路として独立させる。** 現行の8192-token対応は維持。切り捨てや暗黙のNative/Python fallbackはしない。512超はTract側で明示拒否し、アプリが事前にNativeを選ぶ設計は別途明示する。
5. **性能比較は同一モデル・同一寿命条件で行う。** 常駐Tract対one-shot Nativeだけを比較して、Tract自体の効果と呼ばない。初期化、重み変換、graph最適化、padding計算、再利用を分離する。

## 2. 現行runtimeの構造分析

```text
KazeNhanh RecognitionReport
  → adapter：validate / 明示scope・reason / N-best順序保持
  → DecisionRequest → evaluate：opt-in、bytes・期限・予算、結果検査
  → NativeProcessProvider：1要求1子process、wire v1、kill/wait
  → Rust worker → RustProvider
      → bundle検証 → tokenizer検証 → prompt/tokenize
      → safetensors mmap → 24層backbone → readout → temperature/softmax
      → policy：Selected / Abstained → Observation → Attempt
```

| 層 | 現行実装・責務 | Tract導入時の扱い |
| --- | --- | --- |
| core | `src/lib.rs`：DecisionProvider、Request、Observation、Limits、Failure、Attempt | 公開型、serialization、意味を維持。重いTract依存をrootへ追加しない |
| process | `src/process.rs`：native/Python起動、1 MiB応答上限、期限、直接子の終了・回収 | 新worker executableを既存NativeProcessProviderで呼べる構成を優先 |
| bundle | `runtime/rust/src/bundle.rs`：11資産、config/tensor spec、hash/build fingerprint検査 | 現行manifestは不変。ONNX用は別schema・別manifest |
| prompt/tokenizer | `prompt.rs` / `tokenize.rs`：固定質問、chat template、回答codeの単一token検査 | prompt bytes・非padding token列・候補順を同一にする |
| backbone | Candle CPU演算＋独自Qwen3.5処理、BF16資産からFP32計算 | Native実装を参照として残す。Tractは同じ数学的モデルのgraph実行 |
| readout | 最終tokenのhidden `[1,1024]` × 重み `[255,1024]` | ONNXはhead込みのraw logitsを返す。headを二重適用しない |
| scoring/policy | N以降を−1e9でmask、temperature除算、softmax、確率/margin閾値 | 現行の演算順・出力契約を維持。temperatureを二重適用しない |
| adapter | `integrations/kaze_nhanh`：元report全体を保持し追加Attemptを分離 | recognition risk/base decisionを書き換えない |

現行text configは24層（linear attention 18層、full attention 6層）、hidden 1024、FFN 3584。full attentionは8 query heads・2 KV heads・head_dim 256、partial RoPE 64次元。linear attentionは16 heads・key/value各128次元、conv幅4。model config上の最大位置数とは別に、runtimeは8192 tokensを上限とする。

固定資産はJeff source `3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0`、checkpoint `jeff-legacy/Jeff-Qwen3.5-0.8B@51552f39a943d62e8387c4ea5e17026a1408729f`。backbone SHA-256は`080ff4a5b419aaf59f5c5059c492de88a063f34087361fb3c3ff120d95d5396f`。質問IDは`transcription-candidate.v1`、state-first、thinking無効のchat prefix、候補IDと本文を回答codeに対応させる。詳細は[固定参照](jeff-reference.json)と[baseline索引](research/jeff-onnx-tract/native-baseline.json)。

### ソースから分かる最適化候補（効果は未測定）

- `backbone.rs::weight`は呼出時に重みをloadしてFP32へ変換する。モデルをmmapしただけでは全変換が終わらず、現行profilerもforwardに変換時間を含める。
- `delta_recurrence`はTensorからVecへコピーし、token×head×128×128の逐次更新を行う。時間方向は依存するがhead方向は独立。現時点でボトルネック割合は測っていない。
- attentionはmask、RoPE、GQA repeat、contiguous化等でテンソルを作る。再利用・コピー削減余地はプロファイルで確認する。
- `RustProvider`は呼出ごとにbundle/hash/tokenizer/重みを準備する。one-shot方式とTractのplan保持では寿命が違うため、常駐効果を別軸で測る。

### pure-onnx-ocrから採用する設計

隣接checkout `59a6c2c33c72e4dc8e7e5500f544d6674b0e6643`（作業ツリーclean）を確認。Rustが前後処理・session・エラーを所有し、Tractが演算を実行する。`onnx_model.rs`にはshape別の容量制限付きplan cache、`threading.rs`にはengine単位のexecutorと`multithread_tract_scope`がある。Jeffではまずbatch=1・512のplanを1個だけ保持し、poolをbackend単位で管理する。[参照ソース](https://github.com/siska-tech/pure-onnx-ocr/tree/59a6c2c33c72e4dc8e7e5500f544d6674b0e6643/src)

OCR固有の中間shape情報の全消去、OCRでの速度倍率、画像shape別plan数、既定16 threadsはJeffへそのまま流用しない。特にFP32 Jeffは外部重みだけで約3 GBあり、shape別planの複製はメモリを増やし得る。OCR READMEの古い「Scan等未対応」の例より、固定Tractソースと実graphを優先する。

## 3. Phase 0：保全と初回コミット計画

今回の確認ではKazeJudgeは初回コミットなし、追跡ファイル0。ソース・tests・CI・docsはuntracked。既存のモデル、venv、vendor、run出力はgitignore対象。前の同日監査でRust 34件・Python 18件、3 packageのclippy/fmt、portable-p4c実モデルsmokeが成功している。今回これらを再実行したとは扱わない。[監査記録](completion-audit-2026-10-10.md)

**今回固定したもの**：現行source/tests/CI/証跡、7 goldenと境界入力、3組のCargo lock、11 checkpoint資産、P3 manifest・exe、p4c索引など128ファイルのbytes/SHA-256。[索引](research/jeff-onnx-tract/native-baseline.json)は改変検知用であり、バックアップやGitコミットの代替ではない。

初回コミット時は次の順序とする（今回は実行しない）。

1. baseline索引と照合し、変更があれば理由と別baselineを記録。モデル・exe・ignored run出力は、hashで識別する別保管先にも保存する。
2. `src/`、`runtime/`（target除外）、`integrations/`（target除外）、`tests/`、`examples/`、`.github/`、既存docs、Cargo manifests/locks、README、gitignoreを明示的にstage。rootから無差別な`git add .`は使わない。モデル重み・venv・downloaded ONNXは入れない。
3. staged diff、サイズ、秘密情報・個人データ、第三者本文の出典を確認。`chore: preserve native Jeff runtime baseline`として現行実装の初回コミットを作る。今回のONNX計画・解析資料は別のdocsコミットに分ける。ライセンスを勝手に選ばない。
4. 固定toolchainで既存52試験とclippy/fmtを再実行。Nativeの7実forward照合を明示jobで実行し、結果を上書きせずcommit IDと結び付ける。既存CIを残し、追加Tract CIは別jobにする。
5. KazeNhanhはHEAD `8ababecbf8a2f68d7120f946d1a89084dfcc0ce3`に未コミットのcore変更がある。HEADだけでは現行adapterを再現できない。使用するcoreのsource hashを保存し、同repo側で版が固定されてから接続CIへ渡す。今回、隣接repoの変更・コミットは行わない。

### 回帰基準の固定

| 既存golden | tokens | Native | 512固定Tract |
| --- | ---: | --- | --- |
| candidate-request / reversed | 各128 | 成功・既存分布/判断維持 | 同一checkpoint再export後に数値照合 |
| asr-unicode | 206 | 同上 | 同上 |
| special-token-text | 182 | 同上 | 同上 |
| long-text | 874 | 同上 | BudgetExceeded、forwardなし |
| maximum-candidates | 3206 / 255候補 | 同上 | BudgetExceeded、候補削除禁止 |
| token-limit-8192 | 8192 | 同上 | BudgetExceeded、切り捨て禁止 |

Nativeの全7件についてprompt bytes・token IDs・候補順・判断が一致し、最終分布最大絶対誤差≤1e-4を維持する。現在の最大観測誤差は5.066e-6。Tractでは実token予算ちょうど／1不足、511/512/513、padding、NaN/Inf、同点・閾値近傍、期限、異常応答も追加する。未対応3件を「一致成功」に数えない。既存goldenは書き換えない。

## 4. Phase 1：モデル適合性と比較の分離

[互換性マトリクス](onnx-tract-compatibility.md)が静的調査結果の本体。次の比較系列を分離する。

| 系列 | 固定するもの | 判定できること |
| --- | --- | --- |
| A | 現行step1113、公式Python FP32 ↔ 凍結Native | 既存互換性の回帰 |
| B | 現行step1113、公式の無padding ↔ 同じ公式の左512 padding | padding・position・mask・mm入力による差 |
| C | 同step1113、同じ512入力、公式FP32 ↔ 再export ONNXを開発用参照engineで実行 | 演算変換・定数化・丸め差 |
| D | 同一ONNX graph/weights、開発用参照engine ↔ Tract | runtime差 |
| E | 同step1113、同request、Native ↔ Tract | 実用上の全体数値一致と性能 |
| P | 公開step960 ONNX | importer、shape、外部data、graph変換の調査のみ |

ONNX Runtime/PythonをC・Dの開発用oracleとして用いる場合は開発環境だけへ隔離し、CPUExecutionProviderを明示、CUDA等への自動切替を禁止する。配布・通常実行はRustのみ。外部oracleを用意できなければ変換差とruntime差の分離は未完了と記録する。

公開版と現行版はtokenizer/template/回答codeが一致していても学習済み重みの同一性は未証明で、provenanceは異なる。同一checkpoint再exportができない場合、P系列の成立性調査までで止め、現行に対する数値互換・backend高速化倍率を報告しない。旧step960の元checkpointをhash付きで回収できれば、旧モデル内のNative/Tract比較を補足として行えるが、現行の受入とは別結果にする。

再exportでは入力checkpoint/source/exporter/dependency lock、CPU FP32、mask/position、opset、graphと外部data、全変換passと出力hashを保存する。backbone/readoutの名前・shape・FP32変換後のtensor値も照合し、base_modelのrevision一致だけで同一checkpointと判断しない。

## 5. Phase 2：独立TractBackendの試作設計

### APIとパッケージ境界

- `NativeRustBackend`は比較harness側で現行`RustProvider`／既存workerを包む。既存の`RustProvider::new`、`DecisionProvider::decide`、CLI引数の意味は維持する。
- 新しい独立package `runtime/tract`（名称案）に`TractBackend`と専用workerを置く。rootの既定依存・default backendを変更しない。比較harnessは両backendを明示選択し、`DecisionProvider`を共通入口にする。
- Tract workerも`worker --manifest ... --request ... --response ...`と`kaze_judge.worker.v1`を実装すれば、既存`NativeProcessProvider`で監視できる。初期は1要求1子process。`--backend tract`は後の追加選択肢であり既存`rust|python`の意味を変えない。
- prompt/scoring/policyは同じ仕様を使う。現行Tokenizerはnative Bundle型に結合しているため、ONNX manifestを無理に渡さない。初期は独立adapterをgoldenで検証し、共通化は別差分として行う。将来の内部抽出でも公開APIを維持し、古いexe/manifestを保存、新buildは新manifestへ固定する。

処理境界は「request検査 → 資産検証 → 固定prompt/tokenizer → backend用テンソル → raw 255 logits → 候補mask/temperature/softmax → policy → Observation」。Native側は既存処理を使い、診断harnessでraw logitsも採取する。Tract graphのhead込みforwardとNativeのbackbone単体を同名で時間比較しない。

### 最小の実装順序

1. ONNX用bundle schemaを新設。graph/external-data、tokenizer、decision config、元checkpoint、exporter・変換pass、Tract revision/features、backend build、shape/dtype/padding/position規則をhashで固定。現行bundle v1を別の意味に転用しない。
2. 原graphの未登録演算を静的診断し、外部data取得後にparse → shape inference → typed → optimize → runnable → forwardの各段階を別々に記録。最初は入力3本を`i64 [1,512]`に固定する。単なるload成功を実行成功にしない。
3. `SplitToSequence + SequenceAt`の**定数パターンだけ**を正規化する。18箇所は末尾軸の`[2048,2048,2048]`、6箇所は幅256の分割、取り出しindexは0/1/2。scalar splitは指定幅の分割なので、shapeから出力個数・末尾の長さを確認する。一般の動的sequenceは対象外。等価性とraw/変換後のoracle一致を小graphと実モデルで確認する。
4. `CumSum`、`Trilu`、Scatter、dynamic-batch由来shape式、broadcast、reduction、非finite maskの実形状を小graphで再現。失敗時はnode名、opset/domain、入力dtype/shape、attributes、段階、backtrace、再現資産hashを保存する。
5. graphが成立したら、4つの512内goldenと新規境界集合で数値照合する。実token数とpadding後512を別々に記録。公開Observationの`input_tokens`は既存の非padding token数を維持し、計算量は診断sidecarの`physical_tokens`で説明する。
6. load/optimizeが支配的な場合にNNEF/tract-OPLの事前変換を試す。ONNX→NNEF→reloadの出力一致、必要な拡張registry、Tract版との互換性、CPU ISA、hash、licenseを固定。NNEFは未対応演算や数値不一致を自動解決しない。
7. 専用カーネルは最後。必要ならGated DeltaNet recurrence 1種類を対象に、shape/dtype、状態初期化、deadline、数値誤差の契約を定義する。ONNX importer全体やQwen backboneの再実装へ膨らむ場合は中止判定へ戻る。

失敗は既存Failureへ写像する：入力契約違反=InvalidRequest、512超/予算不足=BudgetExceeded、期限=Timeout、ロード/未対応構成=Unavailable、不正分布=InvalidOutput。詳細は別診断記録に残し、wireへ未知fieldを足さない。起動前opt-outは子を起動せず、モデルロード・最適化も親deadlineに含む。

### 常駐化時の条件

plan/重み/tokenizerを再利用しても、recurrent state・execution state・入出力bufferの要求間汚染を禁止する。同一入力の反復と異なる要求の交互実行で検査する。hard timeout後はworkerを破棄・回収し、新workerでhash検証から再起動する。既存one-shot wireを無断で常駐通信へ変更せず、内部の別transportとして設計する。

## 6. Phase 3：性能評価とSLO

詳細は[ベンチマーク計画](onnx-tract-benchmark-plan.md)。同じWindows機、CPU/電源/ISA、同じcheckpoint・prompt・tokenizer・policy・thread数で、Native/Tractを交互に単独実行する。中央値・nearest-rank p95・標本数・失敗数を必ず保存する。

現行の既存探索値は短文128〜206 tokens、1 thread・one-shotでRust p50 5.52〜6.87秒、worker peak working set約1.49 GiB。これは比較設計の参考であり、新Tractの予測値でもSLOでもない。8192-tokenの約202秒は並行build等を伴う互換性診断値のため性能表に流用しない。[既存測定範囲](p4-acceptance.md)

## 7. Phase 4：最適化候補と順序

| 候補 | 期待する作用（未測定） | 実測・受入条件 |
| --- | --- | --- |
| graph定数化・Cast/Reshape整理 | 113kノードの解析・dispatch負担を減らす | 変換前後oracle一致、node数・最適化時間・RSS・forwardを比較 |
| GEMM/SIMD/packing | 線形層とchunk演算の計算を効率化 | CPU ISA別profile。packingを初期化へ移しただけの効果と定常計算を分離 |
| thread並列 | 大きい行列積や独立headを並列化 | 1/2/4/8/最大16、実poolサイズ、p95とメモリ、oversubscriptionを確認 |
| Gated DeltaNet | chunk GEMMまたは最小fused recurrence | decay・conv・L2/RMS・maskを同一化し、層ごとのhidden/logits差を検証 |
| allocation/copy削減 | Tensor↔Vec、transpose/contiguous、一時bufferを減らす | allocation数/bytesとピーク、同じ出力、要求間状態分離 |
| モデル常駐・重み再利用 | hash/load/FP32変換/plan compileを償却 | 両backendの同条件resident比較、起動からの償却回数、timeout後復旧 |
| バッチ2/4/8 | throughput向上の可能性 | 公開graphのdynamic Bを検証。待ち時間込みp95、1件ごとのdeadline・予算・出力対応を保持 |
| FP16 | 帯域・格納量削減の可能性 | 対象CPUの演算対応とfallback確認。蓄積精度、再帰の安定性、再校正を検証 |
| INT8 | 行列積と重み格納の効率化の可能性 | 実kernel対応、dequant費用、calibration/test分離、数値・品質評価 |
| INT4 | 重み圧縮の可能性 | packed形式・kernel・export対応を先に確認。FP32へ展開するだけなら速度改善と扱わない |
| Tract upstream | 汎用の定数sequence lowering、CumSum等の改善 | 最小ONNXとtestを用意、license/出典を確認、固定forkで再現。提案の作成と送信は別段階 |

現在の実測効果欄はすべて「未測定」。量子化はFP32互換移植の後に独立実験として行い、FP32の1e-4基準を黙って緩和しない。量子化用の許容劣化を評価前に定義する。FP16/INT8/INT4に同じ高速化期待を置かない。

## 8. Phase 5：KazeNhanh統合・品質評価

現時点で適格な実N-best付き評価集合はない。既存OCR 15行は明示N-bestがなく、8行は転記未確認。品質スコアは算出しない。[入力監査](p4-quality-input-audit.json)

必要データはrecognizer由来の1-best/N-best、rank・scoreと意味、OCR document/originまたはASR speaker/session、確認済み正解、候補正誤、request全体のtoken数。正解から候補を作らない。正解がN-bestに存在しない例も残し、oracle candidate coverageを報告する。

- document/origin/speakerで非重複のdevelopment・calibration・held-out testを固定。routing/閾値はcalibrationで決定しtestでは変更しない。日本語OCR/ASRとdomain別に集計する。
- 同じreportで「KazeNhanh単独」「同じrouting＋Native」「同じrouting＋Tract」を比較する。base reportは不変とし、追加観測を採用する仮想policyの結果を別recordに保存する。
- 追加検出：baselineが検出しなかった誤りを新たにreview/警告できた件数・率。追加誤警報：baselineが警告しなかった正しい例に新たな警告が出た件数・率。母数と分母を明示し、選択の誤訂正率も別に出す。
- 正解選択率は全eligible例、selected例、正解が候補内にある例の3つを報告。abstention coverage、誤選択率、risk-coverage曲線、必要ならCER/WERを副指標にする。
- routing率=routed/全有効segment。512超除外、N-best欠測、skip、失敗/timeoutを別計数し、都合のよい短文だけの選択biasを示す。全体costは実際のrouting・token・resident寿命分布から積算する。
- temperatureはまずcheckpointの値を維持。認識用途の校正は別policy/versionとしてtop-choice correctnessのreliability、ECE（binと標本数を固定）、Brier等で検証し、選択的routingによる偏りも明記。候補内確率を認識正解率と同一視しない。
- pilotはOCR/ASR各200有効segmentを収集目安とするが合格標本数ではない。paired差の区間をdocument/speaker単位でbootstrapし、稀な誤警報の許容増分から必要件数を再設計する。例えば独立な正しい例で追加誤警報0件でも、片側95%上限は概ね3/n。clusterがあれば単純式で保証しない。

**採用は二重の判定**：性能が改善しても品質を悪化させれば不採用。数値が一致してもJeff自体の品質利益が示されなければ自動採用しない。品質改善とbackend性能改善の結果表を分ける。

## 9. Phase別ロードマップと完了・中止基準

本表のPhaseは今回のONNX計画。既存Pure Rust移行計画のP0〜P5とは別番号体系。

| Phase | 次に実施する成果 | 完了・次段階へ進む条件 | 中止・保留条件と代替 |
| --- | --- | --- | --- |
| 0 保全 | Git baseline、資産保管、回帰job、使用KazeNhanh版固定 | source/資産hash一致、既存52試験と7実forward成功、再現手順が揃う | 出典欠落・baseline不一致なら移植を始めず保全を修復 |
| 1 適合性 | 同一checkpoint再export、全op/dtype/shape表、padding検証、依存監査 | 同一モデルの証明、変換前後数値≤1e-4と判断一致、未対応opの限定解決案 | 同一モデルを取得/再exportできなければ公開版PoCのみ。変換誤差超過なら演算差を調査しNative維持 |
| 2 試作 | 独立TractBackend/worker、小graph、実golden、失敗診断 | typed/optimized/runnable実行、4成功golden＋3長文拒否、追加境界とprocess契約成功 | 正規化・小graph調査をまず2人日で区切る。大規模sequence engine・複数専用kernelが必要なら継続費用を再評価。NaN/不一致を容認しない |
| 3 計測 | raw samples、段階別時間、memory、cold/warm/threads/length表、SLO案 | 公平な条件、所定n、数値再確認、区間付き比較、呼出側予算に適合する案 | 改善が測定誤差内、memory/初期化が予算外なら既定採用しない。小token export/NNEF/Native常駐を比較 |
| 4 最適化 | 必要なprofile駆動差分を1件ずつ | 基準とのpaired比較で実用効果、数値/品質/期限/メモリの受入維持 | 数値・状態隔離・配布依存が悪化した変更だけを棄却。量子化は別gate |
| 5 統合/品質 | 実OCR/ASRのheld-out比較、routing/cost、校正、clean host/NOTICE | 事前に定めた誤警報/誤選択許容差内、品質利益と性能適合を別承認、配布受入成功 | データ不足なら品質判定保留。品質不良ならJeff採用を保留しKazeNhanh単独維持 |

Phase 1の限定変換検証とPhase 2の最小loader調査は同じPoC枝で往復可能だが、性能評価へ進む条件を飛ばさない。最初の進捗到達点は「同一checkpointの512 graphが、必要最小限の正規化でTract上の既存4短文goldenを通ること」。

## 10. 主なリスクと代替案

| リスク | 対処・代替 |
| --- | --- |
| 旧モデルを使った見かけの差 | 現行から再export。できなければ成立性調査と旧モデル比較だけに限定 |
| 113kノードの最適化時間/メモリ | 定数batch、限定正規化、NNEF事前変換、短い固定長export。単なるshape書換えで長さを変えない |
| paddingでDeltaNet/positionが変わる | 公式側padded/unpadded比較を先に行う。mask、mm、last real token、状態減衰を明示 |
| FP32 weights/packed weightsによる膨張 | compileとrunのpeakを別測定、plan数1、FP32常駐Nativeとも比較。後で量子化 |
| Tractが遅い・対応工数過大 | Nativeの重み再利用、head並列、コピー削減を独立候補として残す。既存Nativeを廃止しない |
| generic operator対応と実shape対応の差 | 48演算子の実shape/attribute/値域を採取し小graphで検査。名前の登録だけで合格にしない |
| build由来・cacheの混同 | 公式Tract 0.23.8 release commitを基準。隣接tractは別branch、ローカルCargo cacheもVCS dirty表示があり、そのまま公式版として採用しない |
| Pure Rustの意味の相違 | Windows Tractは内部ASMを組み立て静的linkする。Rustがpipelineとengineを所有し外部推論runtime不要という構成と「全演算ソースがRustのみ」は別。strictな後者が必要ならgeneric Rust kernel構成を実証するまで適合未判定 |
| 配布・ライセンス | ONNXにはApache-2.0本文、TractはMIT OR Apache-2.0宣言。これだけで配布完了とせず、base model、Jeff source、exporter、変換物、全依存NOTICEを新bundleごとに確認 |

公開ONNXのファイル一覧にNOTICEは見当たらず、自プロジェクトlicense未確定も従来の未達として残る。今回の確認は出典・本文・宣言の棚卸しであり法的適合性の判断ではない。Python/ORT/libtorch等がruntime依存に入らないことをCargo features・build inputs・PE imports・clean Windows起動で確認する。`cc` build dependencyの名前だけでC/C++推論依存と断定せず、実際に組み立てたsource/objectを記録する。[Tract固定版build](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/linalg/build.rs)
