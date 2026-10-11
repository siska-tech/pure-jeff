# ONNX＋Tract実装の進捗

2026-10-11更新（2026-10-10からの継続）。Phase 0の保全、現行checkpointのONNX再exportと数値照合に続き、**限定修正したTractで、最適化なし／ChangeAxesを除いた限定最適化の両経路でJeff全体forwardと4件の数値回帰が成立した。標準最適化の修正・公開API統合・性能評価は未完了。既存Native・公開API・Decision Reportは維持している。**

計画：[実装計画](onnx-tract-plan.md)。証跡：[今回の索引](research/jeff-onnx-tract/implementation-2026-10-10/README.md)。開発手順：[ONNX tooling](../runtime/onnx/README.md)、[Tract probe](../runtime/tract/README.md)。

続行分の証跡：[Tract全体forward・数値gate](research/jeff-onnx-tract/continuation-2026-10-10/README.md)。

最適化続行の証跡：[ChangeAxes再現例と限定最適化](research/jeff-onnx-tract/optimizer-2026-10-10/README.md)。

性能pilot：[Windows CPUの測定結果・暫定予算](onnx-tract-performance-pilot.md)。同一checkpoint・1 thread・今回の短文群では高速化は確認できず、Nativeを維持する。正式なPhase 3受入は未完了。

## 達成した判定基準

| 項目 | 実測・検証結果 | 判定 |
| --- | --- | --- |
| Phase 0：資産保全 | 128ファイルの独立複製とhash照合。初回commitと計画commitを作成。改行を含む113 Git blobの一致を再確認 | 完了。コピーは同一ディスク上の保全で、別媒体backupではない |
| 既存回帰 | Rust 34＋Python 18試験、既存3 packageのclippy/fmt成功。7実forwardでprompt・tokens・候補順・判断一致。最大確率誤差5.066394805908203e-6 | 合格。goldenは不変 |
| KazeNhanh依存版 | 未コミット変更を含む実際のcore 21ファイルを独立複製しhash固定 | ローカル再現用記録を保存。隣接repoは未変更 |
| B：左512 padding | 4 golden、CPU FP32、pad ID 248044・pad mm=0。最大確率差6.556510925292969e-7、全判断一致 | 合格 |
| export用DeltaNet置換 | 同4件で公式のpadded出力と比較。最大確率差2.384185791015625e-7 | 合格。専用Rust kernelは未追加 |
| 同一checkpointの再export | 現行step1113、batch=1、512、opset18、head込みraw logits。ONNX checker成功 | 成功。現行モデルとの比較が可能になった |
| C：ONNX参照実行 | CPUExecutionProviderのみ、threads=1、graph最適化無効。同4件でgoldenとの差最大1.3113021850585938e-6、公式paddedとの差最大1.7285346984863281e-6、判断一致 | 合格。公開step960と混同しない |
| sequence限定変換 | 現行版・公開版ともSplitToSequence 24／SequenceAt 66をSplit／Identityへ置換。checker成功。現行版4件の変換前後ONNX候補確率差0 | 現行checkpointの変換後全体oracleも合格 |
| Tract最小試作 | 公式0.23.8のcommitを新規Cargo cacheへ固定。小型ONNXのimport/type/optimize/run、入力長拒否を確認。追加Python 13試験＋Rust境界値1試験とclippy/fmt成功 | probe成立。DecisionProviderとしての統合は未実装 |
| Tract実モデル | I64→TDimの限定修正で現行版の全体型推論を通過。最適化なしの全体forward成立 | 最適化はChangeAxes／CumSum Scanで停止。性能・公開API統合は未受入 |
| Tract全体数値回帰 | 現行step1113、4件。最大確率差は正規化ONNX oracle比1.7285346984863281e-6、golden比3.039836883544922e-6。候補選択・保留が全件一致 | 許容1e-4で合格。小規模goldenのみで、認識品質の評価ではない |
| 限定最適化の全体回帰 | top-level ChangeAxesのみ除外し、残りのdeclutter＋codegenを実行。4件すべて合格、最大確率差はgolden比4.9173831939697266e-6、oracle比4.649162292480469e-6 | 明示的な実験経路として成立。標準最適化の修正・性能受入ではない |
| Phase 3 pilot | process-cold各5回、resident各1セッション・4入力各5回、warm-up各5回。Native API別5回。計65 forward数値一致。warm計算中央値Native 2.977〜4.266秒、Tract 11.636〜11.836秒 | 現行短文・1 threadで速度目的のTract採用根拠なし。threads／長さmatrix・独立session・Tract E2Eは未測定 |
| NNEF保存・再ロードpilot | codegen前のモデルを保存・別processで再ロード。cold 5回＋resident 25 forward全件数値一致。初期化中央値49.504秒／p95 50.664秒、warm計算中央値11.825〜12.231秒 | 起動短縮を確認。codegen後は小型例のIntoShape serializerで停止。forward高速化・正式SLO・API統合の受入ではない |
| codegen内訳診断 | 同一exeで通常／計時を3 block交互実行。計時codegen中央値42.371秒のうちcallback 1.820秒、driver＋計測処理40.551秒。全9 forward数値一致 | 支配項をcallback外側へ限定。個別寄与は次行の独立診断で追跡。[詳細](onnx-tract-codegen-profile.md) |
| driver内部診断 | 独立生成した固定coreに計時点のみ追加。3 block交互、重複探索中央値29.926秒、名前整理9.765秒、compaction 0.625秒。全9 forward数値一致 | 起動改善対象を探索・名前管理へ限定。まだalgorithm変更・高速化倍率・SLO受入ではない。[詳細](onnx-tract-driver-profile.md) |
| 重複探索の削除実験 | 内部timerなし・別targetの単一変更版。4件gate後、cold各5回を交互比較。起動中央値49.706→19.341秒／p95 50.343→19.399秒。全14 process・30 forwardのraw logits一致、Python小型回帰20試験合格 | 起動短縮を確認。warm forward 11.844→11.875秒で改善なし。Native・通常probe・公開APIは不変。実験経路の局所受入のみ。[詳細](onnx-tract-duplicate-search.md) |
| suffix探索の変更実験 | 前回版を対照にcold各5回。起動中央値19.708→20.265秒／p95 20.063→21.020秒、全5組で遅延増。warm forward 11.912→11.917秒。全30 forwardのraw logits一致、Python21試験・Rust命名集合試験合格 | 数値・命名回帰は合格、性能改善版として不採用。前回版を維持し、operator／thread評価を優先する。[詳細](onnx-tract-name-index.md) |
| forward内訳・thread pilot | 同一exe・固定512・各2独立セッション、warm各n=6。1／2／4／8 threads中央値11.744／9.746／8.869／8.694秒、p95 12.255／9.941／9.071／9.294秒。全14 process・56 forwardのraw logits一致。1-thread内訳はOptMatMul 7.046秒、ScatterElements 1.902秒、MoveAxis 1.157秒。Python24試験skip 0、release clippy・callback fmt・全生成source再現照合に合格 | Tract内のthread増加による短縮を確認。次の候補は4／8 threads。1-thread profileから8-threadの残余内訳は推定しない。Native比較・正式SLO・API E2E・品質は未受入。[詳細](onnx-tract-forward-profile.md) |
| 4／8-thread残余診断 | 前回exe固定、各2独立セッション・計測あり各n=6。OptMatMul中央値3.262／3.295秒、ScatterElements 2.024／2.021秒、MoveAxis 1.342／1.289秒、Trilu 0.786／0.761秒。全24 forwardのraw logits一致、Python27試験skip 0。ONNX名の完全一致56・未対応16を区別してshape監査 | 主要な残余を演算・index／layout処理へ限定。次はTriluの最小変更を独立比較する。profileありの値を通常forwardや新たな高速化実績へ換算しない。[詳細](onnx-tract-thread-profile.md) |

| Trilu行単位処理実験 | 4-thread固定対照、独立AB／BA／AB各3 session・warm各n=9。中央値8.963→8.361秒／p95 9.900→8.666秒、全3組で短縮。全10 process・40 forwardのraw logits一致。Python28試験skip 0、Rust4試験、clippy／fmt、173生成ファイル再現照合に合格 | この実験経路の局所受入。起動短縮・正式SLO・Native比較・API統合・品質は未受入。次はScatterElementsの意味を監査。[詳細](onnx-tract-trilu-rows.md) |

| ScatterElements行単位コピー実験 | 受入済みTrilu版を固定対照に4-thread・独立3組・warm各n=9。中央値8.284→6.884秒／p95 8.467→7.341秒、全3組で短縮。全40 forwardのraw logits一致。Python29試験skip 0、helper Rust2＋対照／候補各2試験、clippy／fmt、174生成ファイル再現照合に合格 | 実験経路で局所受入。I64 reductionの既存拒否64条件を別記録。正式SLO・Native同条件比較・API E2E・品質は未受入。次は受入候補でthread／長さmatrix。[詳細](onnx-tract-scatter-rows.md) |

| 受入候補の4／8-thread再評価 | 同一Scatter版exe・独立3組・warm各n=9。4／8中央値6.973／6.518秒、p95 7.097／7.167秒。全32 forwardのraw logits一致。24件のRust長さfixtureを生成し、golden prompt／IDs・予算ちょうど／1不足・513拒否を確認 | 8はp95改善条件を満たさず次のpilotは4を維持。fixtureのoracle／全体gate・入力長性能は未受入。[詳細](onnx-tract-accepted-threads.md) |

| 固定512 graphの入力長pilot | 24件の同一step1113 ONNX参照を固定。4-thread・3独立resident session・128／256／384／511／512各n=12、forward中央値6.260／6.408／6.431／6.517／6.476秒、p95 7.189／6.862／7.116／7.102／7.198秒。全103 forwardの確率・判断・tokens gate合格、反復raw一致。初期化中央値20.020秒、process peak最大約3.054 GiB | 人工入力の数値受入と長さ別pilot完了。初回oracle監視範囲・count adapterの失敗を別保存。物理512共通、n=12 p95は最大値。正式SLO・Native同条件比較・API E2E・品質は未受入。[詳細](onnx-tract-length-pilot.md) |

| Native／Tract共通512形状pilot | 同一step1113・有効／物理512の4人工request・1 compute thread、独立3組AB／BA／AB、各n=12。compute中央値Native 9.892／Tract 9.626秒、p95 10.703／10.133秒。全46 forwardの確率・判断・tokens gate合格、Native確率反復一致・Tract rawが前回4-thread gateと一致 | 形状／threadを共通化した運用構成比較を完了。3組ともTract中央値は短いが1入力中央値と最終組p95はNativeが短い。保持dtype・algorithmは非対称で、runtime単体の効果・採用・正式SLOは未受入。[詳細](onnx-tract-common512-pilot.md) |

| Native FP32重み保持実験 | 参照実装から独立生成した同一exeでmmap／FP32保持を切替。1-thread・共通512・独立3組・各n=12、compute中央値9.789→9.073秒／p95 10.407→9.675秒。全46 forwardの候補確率が固定Nativeと完全一致。Rust4試験・clippy／fmt・9生成ファイル再現照合に合格 | 全組中央値が短縮しwarm性能のみ局所受入。初期化中央値2.054→3.806秒、process peak最大約1.947→4.835 GiB。未使用visual 153 tensorsも保持しており、除外候補は未測定。Tract再比較・正式SLO・API統合・品質は未受入。[詳細](onnx-tract-native-retained.md) |

| Native text320保持実験 | 全473保持版を固定対照に、未使用visual 153 tensorsを保持から除外。1-thread・共通512・独立3組・各n=12、全46 forwardの候補確率が固定Nativeと完全一致。Rust7試験・clippy／fmt・11生成ファイル再現照合に合格 | 全3組でpeakが約0.60 GB減り、最大5.191→4.591 GBでメモリのみ局所受入。compute中央値9.206→8.930秒／p95 9.608→9.312秒、初期化中央値3.823→3.544秒は記述的観測。速度・正式SLO・Tract再比較・API統合・品質は未受入。[詳細](onnx-tract-native-text.md) |

| FP32保持Native／Tract再比較 | Candle source／feature tree／compute thread監査後、固定text320 Nativeと受入TractをFP32保持・共通512・1 thread・独立3組・各n=12で比較。全46 forward数値gate合格、Native確率／Tract rawが固定参照と一致 | compute中央値Native 9.006／Tract 9.670秒、p95 9.226／9.947秒。全3組・本文の中央値／p95はNativeが短い。peak最大4.591／3.277 GBでTractが低い。運用構成比較の完了で、runtime単体効果・採用・正式SLOは未受入。[詳細](onnx-tract-fp32-common512.md) |

| Native thread matrix | text320から独立wrapperを生成し、1／2／4／8 compute threadsを均等化した4 block・各n=16で比較。全112 forward数値gate、Rust9試験・clippy／fmt・13生成ファイル再現照合に合格 | compute中央値9.095／7.121／6.738／7.158秒、p95 10.013／7.438／7.478／7.393秒。事前条件で次pilot候補は4。1／4は確率完全一致、2／8は許容内の小差。4のp95は他の複数thread設定より大きく、採用・正式SLO・Tract比較は未受入。[詳細](onnx-tract-native-threads.md) |

| Native2／4確認・Tract4比較 | 固定exeの3構成を6順列・各n=24で比較。全114 forward数値gate・独立検証合格。今回のNative2／4は各38 forwardの確率が固定Nativeと完全一致、Tract rawも固定gateと一致 | Native4は全6組中央値とpooled中央値／p95でNative2より短くwarm局所確認。compute中央値Native2 7.169／Native4 6.870／Tract4 6.842秒、p95 7.548／7.088／7.552秒。Tractの中央値は僅かに短いがtail・startup／memoryのtradeoffあり。採用・API E2E・正式SLOは未受入。[詳細](onnx-tract-native-confirm.md) |

| Native4／Tract4長さ別比較（停止） | 固定exe・FP32常駐・4 threads、3組・各長さn=12を計画。全6 child／156 forwardはONNX確率・判断・tokens条件合格、Tract raw78件一致 | 2組目Nativeの6観測・4ケースで反復上限1e-6を超え、最大3.5465e-6。第3組未実施、閾値不変。時間変動・512の8秒超も観測。成功した性能比較・SLOへ数えず、次は反復診断と環境条件の監査。[詳細](onnx-tract-length-compare.md) |

| Native反復数値診断 | 失敗4ケース＋512 control、固定exe 1／4 threads・各2 process・3反復、全60 forward ONNX確率・判断・tokens条件合格。source／raw／pool／cache／span・CPU差分の独立監査合格 | 同process／process間／旧gateの差を分離。5ケースの診断であり全28件再受入・原因修正・性能SLOではない。元の停止runと閾値を維持。[詳細](onnx-tract-native-repeat-diagnostic.md) |

| Native cache初期化診断 | 全16 logical CPUから2種類のcache情報を確認。初期化時のみmain threadを固定し復元、AB／BA各2 process・128／512各2反復、全16 forward数値gate合格。Rust9試験・clippy／fmt・156 package feature一致・17生成ファイル再現とraw独立照合合格 | 入力ID・hidden／raw・旧gate／停止sessionとの差で発生条件を検証。全28件再受入・修正・性能SLOは未完了、元失敗と閾値維持。[詳細](onnx-tract-native-cache-diagnostic.md) |

| Native固定cache全28件再検証 | 同一診断exe・cacheB初期化固定、7件×4 chunkを2巡し8 process・56 forward。ONNX数値／判断／tokens、旧gate比とprocess間差≤1e-6、pool／cache／入力／resource条件とraw独立照合に合格 | この診断条件・人工fixtureに限り局所再受入。性能用exe・長いresident・正式SLOは未受入。次は診断出力を除いた独立wrapperを同条件で検証。[詳細](onnx-tract-native-cache-fixed-gate.md) |

| Native固定cache性能用wrapper数値受入 | request診断出力を除いた独立exe。156 package feature一致・16生成ファイル再現・Rust9試験／clippy／fmt合格。全28件gate＋resident各2反復、8 child・84 forwardが数値gateとraw独立照合に合格 | 計測exeの診断版同等性・14-request resident反復のみ局所受入。次は固定exeでNative／Tract長さ別pilot、正式性能・SLO・長期residentは未受入。[詳細](onnx-tract-native-cache-timing-gate.md) |

| 固定cache Native4／Tract4長さ別pilot | 新規14 child・206 forward、各長さ128／256／384／511／512で各backend n=12。旧Native gate／全観測ペア≤1e-6、Tract raw一致、AC／省電力・resource条件とraw／全統計の独立照合に合格 | 数値gateと記述的pilot完了。shape／algorithm／区間の非対称性と未制御条件あり、正式SLO・採用・API E2Eは未受入。[詳細](onnx-tract-cache-fixed-lengths.md) |

| Windows環境継続記録 | 30秒31標本、7 unit tests、正常／exit7／deadlineの3 child検証、固定Native／Tract各3 forwardとraw独立監査に合格。電源・CPU topology／park・OS報告周波数を継続保存 | 記録機能のみ受入。温度取得不可、observer負荷・compute配置・背景負荷は未制御。次は記録あり／なし比較と未使用入力。[詳細](onnx-tract-host-observer.md) |

再現可能なNativeの基準commitは `eb77645b89ae8bf7d07f6a8572ec474be3c61c68`。初回commit `6b80547`では先行stage時の改行変換が一部blobに残ったため、作業ファイルを変えず元bytesへ修正し、全113 blobをhash照合した。実装着手後の128 baselineとの差は`.gitignore`のTract target除外追加だけである。

再export資産はignoredな `experiments/runs/onnx-current-step1113-v2/` に保存した。

| 資産 | bytes | SHA-256 |
| --- | ---: | --- |
| model.onnx | 217,616,222 | `6faa35aaa8ca87638cdabeb59d25aae5f0e55775e8bcd35f9b3992b66d2d6725` |
| model.onnx.data | 3,010,658,304 | `1b7c0e8a7b7902fe8631b9dec3a702858152f6693cdf5f501df1dfd710afb1a5` |
| model.normalized.onnx | 下記normalization証跡参照 | `4808e28131967e8ed33f8b50d46c4212e11c19b79e6dfb5209cf9b6931cd9b0c` |

## Tractの停止箇所

公開graphのdynamic batchを単にinput fact=1へ上書きすると、中間の`batch`と衝突した。`batch`と`8192*batch`をすべて具体化する限定passを追加してcheckerを通した。中間shape情報の一括削除は行っていない。現行再exportは初めから固定batch=1である。

その後、両モデルの `node_slice_1` で `StridedSlice` が出力shapeを `[2,1,512]` と推論し、ONNXの `[3,1,512]` と衝突した。sequence変換後も同じ箇所で停止する。実graphから切り出した14ノードでも再現した。ONNX full checker／strict shape inferenceとCPU oracleでは `[4,1,512][1:] → [3,1,512]` が成立し、出力値も一致した。

原因はTract dataのI64→TDim castで、i32の中間変換によりINT64_MAXが-1へ切り詰められることだった。独立probe内に固定版data crateを保全し、I64だけ直接TDimへ変換する9行の修正を追加した。26ファイルの原本hashを保存し、差分がtensor.rsだけであることを試験する。Native・隣接checkoutには適用していない。14ノードの再現例では重複value_infoにより入力I64型が消える問題もあり、probeのanalyze段階で宣言済み入力型だけを復元した。境界値Rust試験と再現例が成功した。

現行checkpointのsequence変換版は型推論を通過した。標準最適化はChangeAxesがCumSumのScan bodyへReshape(2,[8,64],[512])を伝播すると、bodyの[1,16,8,1]と衝突して停止する。`run-typed`を追加し、最適化を省いた経路で全体forwardが成立した。これは修正版Tractの成立性確認であり、未修正の公式Tractや最適化済みbackendの合格とは扱わない。

## 次に進める順序

1. 5ノードのCast→Reshape→CumSum→Reshape→Sliceで標準最適化の同じエラーを再現した。`run-no-change-axes`では固定版declutterのtop-level ChangeAxesを1個だけ除去し、残りとcodegenを実行する。構成が変われば明示失敗し、自動fallbackはしない。小型例は解析的な累積和と一致し、Jeff全体4件も合格。標準Tract側の修正とupstream投稿は未実施で、投稿は明示的な依頼があったときに行う。
2. 最適化を変更するたびに同一checkpointの4件数値gateを再実行する。各段階を別process・期限付きで記録し、OOM／panic／deadlineも失敗として残す。
3. 型推論・全体forward成立後に、既存DecisionProvider／worker wireへ接続する独立TractBackendを実装する。512超の明示拒否、prompt/tokenizerの同一性、温度処理、期限・異常応答の契約試験を追加する。既存RustProviderを廃止・改名しない。
4. Phase 3は独立計測wrapperでpilotまで実施し、1／2／4／8-thread版の各2独立sessionと4／8-threadの演算内訳も測った。TriluとScatterElementsの単一変更をそれぞれ4-thread・独立3組で比較し局所受入した。受入候補の4／8-threadを独立3組で再評価し、8はp95条件を満たさないため4を維持した。24件の長さfixtureのONNX oracle／全体gateと5長さ各n=12のpilotも完了した。同条件化の監査後、有効／物理512・1 thread・各n=12のNative／Tract運用構成比較を独立3組で実施した。続いてNativeを変更しない独立exeでFP32保持を3組比較し、数値・warm性能を局所受入したが、初期化／peakが増え、未使用visual重み153 tensorsの保持も判明した。text使用320 tensorsだけを保持する候補も独立3組で比較し、全46 forward数値一致・peak削減を確認してメモリのみ局所受入した。Nativeのcompute thread条件をsource／feature treeで監査し、固定text320版とTractをFP32保持・1 threadで独立3組再比較した。全46 forward数値一致、compute中央値はNative 9.006／Tract 9.670秒でNativeが短く、process peakはTractが低い。独立Native wrapperの1／2／4／8-thread matrixも均等化4 block・各n=16で実施し、全112 forwardの数値gateが合格した。中央値最小の4を事前条件どおり次pilot候補に選ぶが、p95は他の複数thread設定より大きい。新しい独立sessionでNative2／4とTract4を6順列・各n=24で再測定し、全114 forward数値gateが合格した。同じ4入力の確認で入力hold-outではない。Native4は全組中央値とpooled中央値／p95でNative2より短くwarm局所確認、Tract4は中央値が僅かに短いがp95が大きい。続いてNative4／Tract4長さ別比較を開始したが、2組目Nativeの反復条件1e-6違反で停止した。全156 forwardはONNX確率1e-4／判断／tokens条件に合格したが、Native6観測・4ケースの反復差が最大3.546476364135742e-6となり、第3組は未実施。長さ別性能の成功受入には数えず、反復診断60 forwardとcache初期化条件を操作した16 forwardの独立診断まで進めた。同cache条件の診断exeで全28件・独立8 process／56 forwardを元の数値閾値により局所再受入した。診断出力を持たない性能用wrapperも全28件gate＋resident各2反復の84 forwardで数値同等性を局所受入した。今回の25 requests／residentを超える長期履歴は未受入。新規Native／Tract長さ別pilotも14 child・206 forwardで数値gateを維持して完了した。power条件とsystem負荷を記録したが、温度・周波数・背景負荷・推論core配置は未制御。次は条件の記録／制御を固定し、未使用入力・独立block・正式標本を増やす。API E2E・独立session増加・正式測定は残る。compute p95≤8秒は測定済み4-thread／512条件の暫定SLO候補として提案し、達成済みとは扱わない。 旧停止runでは512の8秒超と大きい時間変動を観測した。今回完了した固定cache長さ別pilotでも512 p95はNative20.906秒／Tract19.241秒で8秒候補を超え、正式SLOは未受入。algorithm差は残るためruntime単体の効果を断定しない。固定512の今回値から可変長Nativeとの差や正式SLOを推定しない。以前の単発probe秒数・export時間と、事前登録したbenchmark結果を混同しない。
5. Phase 4はプロファイルに基づいて選定。Phase 5は確認済みOCR/ASR正解とN-bestが必要で、現在の人工goldenでは認識品質を判定しない。 2026-10-11のユーザー回答で実データは現在未準備と確認し、Phase 5はデータ準備待ちとする。

限定最適化の調査では、推論前のgraph処理にも大きなコストが観測された。単発probeの秒数を速度倍率やSLOには換算しない。実験wrapperでモデル・planの再利用を実装した後、[NNEF保存・再ロード](onnx-tract-nnef-pilot.md)も検証した。ONNX拡張registry、資産hash、4件数値回帰、別process再ロードは合格。codegen前のNNEFによる初期化短縮を確認したが、codegenの約40秒とwarm forwardの約12秒は残る。codegen後のplan永続化・配布可搬性・公開API統合は未受入である。

## 開発環境・ライセンス・未受入

Python 3.12.14の既存vendor venvは不変。ONNX 1.23.2、ONNXScript 0.7.2、ONNX Runtime 1.31.0等はhash付きlockで `.venv/onnx-tools/` へ隔離した。配布・通常実行にPython／ONNX Runtimeを追加していない。Tractは公式commit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a` を `.venv/tract-cargo-home/` で取得し、dirtyな既存registry sourceは使用していない。

jigor exporterの固定source、Apache-2.0本文、出典とNOTICE確認結果を `runtime/onnx/upstream/` に保持した。TractのWindows依存103 package、license宣言／本文hash、build scripts、PE直接importsを記録した。Tractはbuild時に`cc`とWindows assemblerを使用する。配布物の第三者NOTICE収集、全source review、既存projectのライセンス未決事項は引き続き配布受入の残作業であり、今回のprobeを配布承認とは扱わない。

初回exportはcp932でTorchの進捗記号を出力できず停止し、UTF-8へ修正して新規出力先で成功した。実行時のwrapper版とhashも証跡に保存している。現在のwrapperにはgolden hashと4件gateの追加検査があり、保存した実行版とはhashが異なる。

既存CIは不変。追加CIは小型graph用の独立workflowを作成したが、GitHub上では未実行。実モデルTractの標準最適化・公開API統合、性能SLO、実認識品質、clean host配布受入は未完了である。
