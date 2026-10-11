# Native4／Tract4入力長比較：反復数値gateで停止

2026-10-11。固定済みNative 4 threadsとTract 4 threadsの入力長別比較を開始したが、2組目Nativeの反復確率差が事前上限を超えたため停止した。3組目は未実施であり、成功した性能比較・正式SLO・backend採用として受け入れない。既存Native参照実装・公開API・Decision Reportは維持した。

## 設計と実行範囲

同一step1113・FP32常駐・batch1・4 compute threads。Nativeはtext320 model tensors＋head1、Tractは受入Scatter／Triluのpacked planを使用し、どちらのexeも再ビルドしていない。有効128／256／384／511／512 tokens、各長さ4人工request（2／3候補）。Nativeは有効長だけ、Tractは左paddingした物理512を演算する。512以外はshapeが異なり、layout・algorithm・kernel境界の差も残る。runtime単体効果や高速化倍率へ換算しない。

予定は28件gate／構成の後に3組AB／BA／AB（A=Native、B=Tract）、各resident sessionは混合5 warmup（各長さ1件）＋20測定、同組で同じshuffle（seed 3561113＋block）。各長さ・構成n=12を予定したが未達。実行は6 process・156 forward＝gate56＋warmup20＋測定80で、3組目の50 forwardは未実施。完了済みresidentは各構成2 session、各長さn=8の生観測があるが、1 Native sessionは登録数値gate不合格であり、pooled性能比較を成立したとは扱わない。

探索と同じ既存人工入力で、未使用本文hold-outではない。8候補の追加4件（256／384／511／512）はgateのみ、128の8候補cellは欠測。実OCR／ASRの確認済み正解・N-bestは2026-10-11のユーザー回答で現在未準備と確認した。Phase 5はデータ準備待ちであり、人工ケースを認識品質の代用にしない。

数値条件はONNX候補確率差≤1e-4、確率和誤差≤1e-6、判断／tokens一致。旧Native参照がある8ケースは差≤1e-4も要求し、全28ケースのNative反復は今回gate比≤1e-6。短いケースの旧Native参照はなく、全件が旧Nativeと完全一致とは扱わない。Tract raw logitsは旧4-thread長さgateとの完全一致を要求する。Native raw logitsは取得していない。

Core i7-1360P／Windows／Balanced。Native Rayon pool4／Candle設定4、Tract executor4を確認。poolサイズは全worker稼働・OS thread数上限ではない。process期限600秒、peak上限min(8 GiB,物理RAMの50%)、開始時空きRAM4 GiB。実行中のbuild／試験／hash監査なし。温度・affinity・背景負荷・AC状態・storage cacheは未制御。数値条件や標本数を変更した再試行は行わなかった。

## 数値監査と停止理由

全156 forwardはONNX候補確率・確率和・判断・tokens条件に合格した。最大ONNX差は4.6491622924804688e-06、旧Native参照がある観測の最大差は5.3644180297851562e-07。Tract全78 forwardのraw logitsは旧gateと完全一致した。

一方、Native全78 forward中6観測・4ケースで反復上限1e-6を超え、最大3.5464763641357422e-06だった。合格は72／78。違反は2 warmup＋4測定で、いずれもresident-1-native4にある。Native2／4確認の前回は固定512のみであり、今回の短文反復の合格を保証していなかった。

| case | iteration（0始まり） | warmup | Native gate比最大差 | ONNX参照比最大差 |
| --- | ---: | --- | ---: | ---: |
| synthetic-asr-unicode-2-128 | 0 | True | 1.430511474609375e-06 | 2.384185791015625e-07 |
| synthetic-asr-unicode-2-384 | 2 | True | 1.1324882507324219e-06 | 6.8545341491699219e-07 |
| synthetic-asr-unicode-2-128 | 6 | False | 1.430511474609375e-06 | 2.384185791015625e-07 |
| synthetic-ocr-ascii-3-511 | 12 | False | 1.4901161193847656e-06 | 1.6093254089355469e-06 |
| synthetic-asr-unicode-2-384 | 13 | False | 1.1324882507324219e-06 | 6.8545341491699219e-07 |
| synthetic-ocr-ascii-3-128 | 19 | False | 3.5464763641357422e-06 | 1.1324882507324219e-06 |

子Rust processは25 forwardをすべて完了してexit 0。その後parentが生ログを検証し、iteration 0のwarmupから反復条件不合格となり、ValueError: Native repeat mismatch／exit 1で停止した。6子processともexit 0、resource guard発火なし。失敗sessionのvalidated記録は作られておらず、raw／job／process記録と独立監査を保存した。他5 processのvalidated記録も生ログから再照合した。

この差だけでAPIのONNX数値契約（1e-4）が破れたとは扱わず、厳しい反復契約（1e-6）の不合格と区別する。FP32並列演算・shape依存の演算経路は調査候補だが、原因は特定していない。固定Candle sourceにはthread数に応じたRayon GEMM経路があるが、それを今回の差の原因とは断定しない。数値閾値を事後に緩めたり、失敗観測を除外した性能採用はしない。

## 未完了runの時間診断

以下は生観測の診断値であり、合格した比較結果ではない。各session・長さn=4、nearest-rank中央値ceil(0.5n)／p95 ceil(0.95n)（p95は最大値）。失敗Native sessionも明示して掲載する。computeは各観測でNative backbone＋head/softmax、Tract forward＋scoreを合算してから集計する。

| 有効tokens | Native組1（秒） | Tract組1（秒） | Tract組2（秒） | Native組2・反復不合格（秒） |
| ---: | ---: | ---: | ---: | ---: |
| 128 | 1.861444 / 2.327169 | 16.408277 / 16.838133 | 16.453184 / 16.746447 | 4.923366 / 5.194532 |
| 256 | 3.492865 / 3.660379 | 16.973710 / 17.327855 | 16.587944 / 16.804646 | 8.921365 / 9.741918 |
| 384 | 4.946094 / 5.260410 | 17.320245 / 17.477298 | 14.864871 / 17.109893 | 13.394651 / 14.291806 |
| 511 | 6.689358 / 6.849839 | 16.875667 / 17.413514 | 14.735218 / 17.109697 | 17.865591 / 18.544558 |
| 512 | 6.891479 / 7.889822 | 16.857647 / 18.010997 | 12.703103 / 17.194786 | 17.383434 / 18.029978 |

両backendで前回より長い推論時間を観測し、Nativeも組間で大きく変動した。8秒を超える512の診断値があり、前回提案したprepared-compute p95≤8秒候補の安定性は確認できなかった。このrunを除外して達成扱いにせず、環境条件を記録／制御した独立runで再評価する。今回の遅い値に合わせて製品要件を自動的に緩めない。

Tract組1中にprocess一覧、Tract組2中にRust bench名の軽量snapshotを各1回取得した。後者ではbenchが1 process、旧Native bench名は存在しなかった。PowerShellは存在しない名前も検索したためexit 1だが、benchmark childの失敗ではない。snapshotは累積CPU秒・Working Setで、瞬間CPU使用率や競合原因の証明ではない。背景processを停止せず、電源／温度／競合の因果原因は未特定。この短い補助診断操作も時間測定中に含まれる。

startup（秒）とprocess lifetime Peak Working Set（bytes）は付随診断。Native startupはchildのbundle検証／tokenizerを含み、Tract hash検証はparent preflightのため範囲非対称。Native requestはtokenizer／policy込み、Tractは準備済みtensorからでAPI E2Eは揃わない。peakは初期化・mapped／shared pagesを含み、要求別peakやwarm private memoryではない。

| session | startup（秒） | lifetime peak（bytes） | 登録数値gate |
| --- | ---: | ---: | --- |
| resident-0-native4 | 4.246759 | 4,593,188,864 | 合格 |
| resident-0-tract4 | 23.174892 | 3,277,996,032 | 合格 |
| resident-1-tract4 | 55.996523 | 3,278,077,952 | 合格 |
| resident-1-native4 | 4.645144 | 4,592,947,200 | 反復条件不合格 |

tokenize／head／score／request・startup内訳、各長さ・各sessionの中央値／p95／最小／最大／nは[diagnostic-summary.json](research/jeff-onnx-tract/length-compare-2026-10-11/diagnostic-summary.json)に全件保存した。段階の中央値／p95同士を足して全体値にはしない。

## 保全と次の判定

既存Native baselineは128ファイル中、既知の.gitignore差のみで127不変。固定Native original／全473保持版／text320版／thread wrapper exe、通常Tract probe、受入Tract exeと174生成source、前回thread／長さ／確認測定の証跡、隣接KazeNhanh 21ファイルも不変だった。固定済み9 Rust試験・clippy／fmt・13 source再現の証跡をexe hashとともに引き継ぐ。今回は実験ハーネスと証跡／文書のみ追加し、配布物・公開APIや実行時Python依存は変えない。配布NOTICE受入は残る。

次は失敗した4ケースを固定した最小の反復診断を性能評価から分離し、1／4 threads・独立process・同一process反復で揺らぎを再現する。input IDs／重み／確率を照合し、必要ならbackbone／readout境界を診断して差の出る段階を絞る。診断用profileの秒数を性能実績には使わない。原因を修正した候補は別crate／targetへ生成し、元の反復条件で全28件を再検証してから新規出力先で3組を再測定する。許容差の設計自体を変更する場合も今回の不合格を覆さず、判断閾値への影響を検証して別実験の事前条件として記録する。

性能測定を再開する条件は数値gate合格に加え、AC／電源状態・温度・背景負荷・CPU配置の記録／制御方針を先に固定すること。正式warm標本・未使用本文・API E2E・cold campaignは未完了、Phase 5は実データ待ち。

計測前には既存fixtureの左paddingを誤って右paddingとして検査するpreflightで停止した。出力dir作成・child起動前に左padding検査へ修正した。事前登録後のrunは1回であり、今回の反復違反を理由に条件を変えた再試行はない。

[証跡・事前登録・生ログ・独立監査](research/jeff-onnx-tract/length-compare-2026-10-11/README.md)。[測定ハーネス](../runtime/onnx/benchmark_length_compare.py)。
