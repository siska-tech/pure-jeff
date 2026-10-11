# Native text320 FP32のthread matrix

2026-10-11。[FP32保持Native／Tract比較](onnx-tract-fp32-common512.md)で確認した固定Native wrapperの1-thread制約に対し、独立wrapperで1／2／4／8 compute threadsを測る。元Native参照実装・公開API・Decision Report・既存exeを変更しない。

## 実験wrapperと検証

[生成器](../runtime/onnx/prepare_native_threads.py)は固定text320候補の証跡・source hashを検証し、別crate／Cargo targetを作る。backbone・readout・weights・inventoryは前回版とbyte単位で同一。model320 tensors／3,009,572,096 FP32 bytesとhead1／1,044,480 bytesを保持し、DeltaNet再帰は直列のまま。既存lockのRayon 1.12.0をrootの直接依存へ明示するだけで依存package版は変えない。

jobの`threads`は整数1／2／4／8のみ受け付ける。tokenizer／tensor／pool初期化前に`RAYON_NUM_THREADS`と`CANDLE_NUM_THREADS`を設定し、global Rayon poolを明示構築する。実poolサイズとCandleのGEMM設定を照合してeventへ出す。barrier補助worker数threads−1も記録するが、これはsourceからの期待数で実測telemetryではない。poolサイズは全workerが同時稼働する保証やOS全thread数の上限ではない。manifestのpolicy.cpu_threads=1は参照資産として維持し、この実験jobでcompute条件だけを上書きする。判断policyは同一。

release9試験は既存演算／保持試験に加え、対応整数と不足・null・文字列・小数・負数・未対応値等の拒否を確認する。clippy／fmt合格、13生成ファイルは独立再生成と一致。追加Pythonは開発用のみで実行時依存は増やさない。前回Candle source／feature tree監査も固定hashで再確認する。

計測後のCargo tree比較でも、root pathと重複markerを除いた依存package／有効feature集合は前回text320版と一致した。Rayonを直接依存へ加えても機能の統合結果は変わらない。Candle core／nnのHEADからの差分も0だった。

各thread設定で4 golden＋4人工requestの8件gateを先に実行する。全forwardでONNX参照との候補確率誤差≤1e-4、確率和誤差≤1e-6、判断／token数一致、固定Native確率との差≤1e-4を要求する。1-threadは固定Nativeとの確率完全一致も要求する。各設定内のgateとの反復差は≤1e-6。複数threadの確率は許容誤差で評価し、取得していないraw logitsの一致とは呼ばない。

## 測定条件・判定

Core i7-1360P／Windows CPU／Balanced、batch1、物理／有効512、paddingなし、text320 FP32保持。同じ4本文・2／3候補を全設定で用いる。4独立blockの順序は1→2→4→8、2→8→1→4、4→1→8→2、8→4→2→1。各設定が各実行位置に1回現れ、隣接する有向組合せも1回ずつとなるWilliams順序を使う。

各sessionは1 warmup＋同じblock内で同一shuffleの4測定（seed 1248320＋block）。各設定n=16、各本文n=4。全20 process・112 forward＝gate32＋warmup16＋測定64。computeは各観測のbackbone＋head/softmaxを合算して集計する。requestはprompt/tokenizer・policyを含むが公開API／IPC E2Eではない。

事前登録した次pilot候補の選び方は、1-thread比で全4 blockのsession中央値とpooled中央値／p95が短い設定を適格とし、その中でpooled中央値が最小のthread数を選ぶ。該当なしなら1を維持する。これは探索用候補選択で、正式SLO・製品採用・Tractへの優位性の受入ではない。別の候補とのp95非劣性もこの条件には含めていない。

process期限600秒、peak上限min(8 GiB,物理RAMの50%)、開始前空きRAM4 GiB。計測中にbuild・試験・hash監査を並行しない。温度・affinity・背景負荷・storage cacheは未制御。nearest-rank中央値ceil(0.5n)／p95 ceil(0.95n)で、n=16のp95は最大値。startup／lifetime peakは各n=4の付随観測でcold campaign・warm private memoryではない。人工入力は確認済み認識正解を持たない。

## 結果

全20 process・112 forwardが完了し、数値gateが全件合格した。ONNX参照比の最大候補確率差は3.7550926208496094e-6、固定Native比は2.682209014892578e-6、設定内gateとの反復差は最大5.364418029785156e-7だった。判断／tokensは全件一致、exit 0・guard発火なし。生出力から順序・cache・実poolサイズ・数値・統計を独立に再検証した。

1／4 threadsの全forwardは固定Nativeの候補確率と完全一致した。2 threadsは初期gateでは完全一致したが、全forwardでは固定Native差・反復差とも最大5.364418029785156e-7だった。8 threadsは固定Native差最大2.682209014892578e-6、反復差最大5.364418029785156e-7。これらは事前条件の固定Native差≤1e-4・設定内反復差≤1e-6を満たす。複数threadすべてが完全一致したとは扱わない。

computeは各n=16、startup／peakは各n=4。中央値／p95（秒）、peakは観測最大：

| threads | compute（秒） | startup（秒） | lifetime peak最大（bytes） |
| --- | ---: | ---: | ---: |
| 1 | 9.094808 / 10.013065 | 3.565162 / 3.641020 | 4,590,968,832 |
| 2 | 7.121384 / 7.438257 | 3.559633 / 3.658502 | 4,591,214,592 |
| 4 | 6.738168 / 7.478408 | 3.533285 / 3.559962 | 4,591,370,240 |
| 8 | 7.158093 / 7.393373 | 3.505096 / 3.576640 | 4,591,632,384 |

2／4／8はいずれも全4 blockの中央値とpooled中央値／p95が1-threadより短く、次pilot適格となった。そのうちpooled中央値最小の**4 threadsを次pilot候補に選ぶ**。4の全block中央値も2／8より短かったが、pooled p95は2／8より大きい。1組目では4のp95が2／8より大きかった。事前条件は1との比較であり、2／8へのp95非劣性・正式SLO・製品採用は受け入れない。候補比較の再測定でこの差を確認する。

各blockのcompute中央値／p95、各cell n=4：

| block | 1 thread（秒） | 2 threads（秒） | 4 threads（秒） | 8 threads（秒） |
| --- | ---: | ---: | ---: | ---: |
| 1 | 8.899065 / 9.498579 | 7.040302 / 7.147667 | 6.991118 / 7.478408 | 7.285558 / 7.393373 |
| 2 | 9.058477 / 9.573716 | 7.145187 / 7.438257 | 6.647685 / 6.785165 | 7.170568 / 7.181634 |
| 3 | 9.778164 / 10.013065 | 7.083760 / 7.282723 | 6.738168 / 6.858665 | 6.985307 / 7.065210 |
| 4 | 8.928949 / 9.112791 | 6.881525 / 7.380872 | 6.719190 / 6.827818 | 7.158093 / 7.303933 |

段階別中央値／p95（秒、各n=16）。保持準備のみstartupに含む各n=4：

| 段階 | 1 thread | 2 threads | 4 threads | 8 threads |
| --- | ---: | ---: | ---: | ---: |
| backbone | 9.0947431 / 10.0129952 | 7.1213079 / 7.4381855 | 6.7381003 / 7.4783221 | 7.1580052 / 7.3932061 |
| head/softmax | 0.0000656 / 0.0001004 | 0.0000659 / 0.0000761 | 0.0000688 / 0.0000864 | 0.0000966 / 0.0001841 |
| prompt/tokenizer | 0.0006515 / 0.0018882 | 0.0007141 / 0.0011681 | 0.0008762 / 0.0021411 | 0.0010865 / 0.0028974 |
| policy | 0.0000006 / 0.0000011 | 0.0000007 / 0.0000010 | 0.0000008 / 0.0000010 | 0.0000011 / 0.0000015 |
| request | 9.0955987 / 10.0137440 | 7.1220821 / 7.4390126 | 6.7389429 / 7.4793001 | 7.1598165 / 7.3943185 |
| FP32保持準備 | 1.465458 / 1.668375 | 1.455512 / 1.520239 | 1.445625 / 1.501427 | 1.485244 / 1.488375 |

本文別compute中央値／p95、各cell n=4：

| 人工request | 1 thread | 2 threads | 4 threads | 8 threads |
| --- | ---: | ---: | ---: | ---: |
| OCR日本語2候補 | 9.112791 / 10.013065 | 7.040302 / 7.145187 | 6.785165 / 6.991118 | 7.170568 / 7.303933 |
| ASR Unicode 2候補 | 9.202893 / 9.867422 | 7.145061 / 7.387226 | 6.694183 / 7.119005 | 7.174921 / 7.345913 |
| OCR ASCII 3候補 | 9.044183 / 9.778164 | 7.103940 / 7.146954 | 6.735800 / 6.827818 | 6.985307 / 7.086159 |
| ASR混在2候補 | 8.928949 / 9.716091 | 7.147667 / 7.438257 | 6.647685 / 7.478408 | 7.158093 / 7.393373 |

startup・保持準備・peakは付随観測で、thread設定による初期化やメモリの改善は受け入れない。phase別の全観測・最小／最大・統計はJSONに保存した。過去の別runのTract値との差し引きでNative／Tractの優劣や倍率を出さない。

Native baseline 128ファイルは既知の`.gitignore`差分のみで他127ファイル不変。固定Native・全473保持版・text320版exe、通常Tract probe、受入Tract exe／174生成source、前回text320証跡、隣接KazeNhanh 21ファイルも不変だった。

## 残作業

次候補のhold-out再測定、同thread条件の固定Tractとの運用構成比較、短い入力と独立session増加、API統合／E2E、正式cold campaign・SLO、実OCR／ASRの品質評価が残る。GEMMと要素演算のthread設定を同時に変えるため、差を個別kernelやDeltaNetの改善量へ分解しない。必要なら別診断で演算内訳を確認する。標準Tract最適化・配布用全source／NOTICE監査も未完了。

測定は[benchmark_native_threads.py](../runtime/onnx/benchmark_native_threads.py)。[証跡一式](research/jeff-onnx-tract/native-threads-2026-10-11/README.md)へ事前登録、生成source／差分／lock、9試験・build・clippy／fmt、生出力と統計、数値・資産保全の独立検証、license／NOTICEを保存した。既存CIは不変、GitHub CIは未実行。
