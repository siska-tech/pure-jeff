# Native短文の反復確率差：1／4 threads診断

2026-10-11。[入力長別比較](onnx-tract-length-compare.md)がNativeの反復上限1e-6違反で停止したため、性能評価から分離した固定数の数値診断を行った。元の失敗runや閾値は変更せず、診断結果で不合格を覆さない。既存Native参照実装・公開API・Decision Reportは不変。

## 設計

失敗した4ケース（ASR Unicode128／384、OCR ASCII128／511）とASR Unicode512 controlを、固定text320＋head1 FP32 Native thread exe・同一step1113・batch1・有効長演算で実行する。1／4 threads各2独立process、順序1→4／4→1、各caseを同process内で3反復（固定shuffle seed 4671113＋10block＋repeat）。全4 process・60 forward、各case／thread設定6観測。warmup・latencyの受入条件はなく、profileやhidden／raw-logit出力も追加していない。

ONNX確率差≤1e-4、確率和誤差≤1e-6、判断／tokens一致、期限600秒とpeak上限min(8 GiB,物理RAMの50%)は不合格時に停止する。反復1e-6超は原因調査の観測として固定60件を収集し、不合格を合格へ読み替えない。これは停止した性能runの閾値緩和・標本補充・置換runではない。全28ケースの再受入や正式性能測定は別に必要。

同一process内3件の各候補確率max−minの最大（within span）、独立2 processの初回差、全6件span、停止runの旧Native4 gate比最大差を計算する。旧4-thread gateと1-threadの差はthread設定も異なるため、1-threadの同一条件反復と混同しない。JSONのキー末尾within_1e6はsource／事前登録で比較している1e-6を指す。

各child前後にWindows power statusとsystem全体CPU累積時間を記録し、system平均busy率を再計算した。CPU busyは他processを含み、childの稼働率や競合原因の証明ではない。AC／省電力は前後snapshotのみ、温度・周波数・core配置・worker稼働・背景負荷の制御はない。開始時AC接続あり、省電力flagなし。前の性能runの電源状態まで証明しない。

## 結果

全60 forwardでONNX確率・確率和・判断・tokens条件が合格し、最大ONNX確率差は1.6093254089355469e-06。全4 child exit 0、resource guardなし。pool／cache／shape／順序と全span・CPU差分を生ログから独立に再照合した。

| threads | case | 同process最大span | process初回間差 | 全6観測span | 旧Native4 gate比最大差 | 全6件完全一致 |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 1 | synthetic-asr-unicode-2-128 | 0 | 0 | 0 | 1.430511474609375e-06 | True |
| 1 | synthetic-asr-unicode-2-384 | 0 | 0 | 0 | 1.1324882507324219e-06 | True |
| 1 | synthetic-ocr-ascii-3-128 | 0 | 0 | 0 | 3.5464763641357422e-06 | True |
| 1 | synthetic-ocr-ascii-3-511 | 0 | 0 | 0 | 1.4901161193847656e-06 | True |
| 1 | synthetic-asr-unicode-2-512 | 0 | 0 | 0 | 4.76837158203125e-07 | True |
| 4 | synthetic-asr-unicode-2-128 | 0 | 0 | 0 | 1.430511474609375e-06 | True |
| 4 | synthetic-asr-unicode-2-384 | 0 | 0 | 0 | 1.1324882507324219e-06 | True |
| 4 | synthetic-ocr-ascii-3-128 | 0 | 0 | 0 | 3.5464763641357422e-06 | True |
| 4 | synthetic-ocr-ascii-3-511 | 0 | 0 | 0 | 1.4901161193847656e-06 | True |
| 4 | synthetic-asr-unicode-2-512 | 0 | 0 | 0 | 4.76837158203125e-07 | True |

1 threads：同process span最大0、process初回間差最大0。全6観測span≤1e-6は5ケースすべてで成立、旧Native4 gate比≤1e-6は不成立。

4 threads：同process span最大0、process初回間差最大0。全6観測span≤1e-6は5ケースすべてで成立、旧Native4 gate比≤1e-6は不成立。

今回の同process内3反復では全ケースの確率が完全一致した。process間／旧gateとの差とは分けて扱い、この3反復から一般的な決定性を保証しない。

追加の独立照合では、両thread設定を合わせた各ケース12観測もすべて完全一致し、停止したresident-1-native4の同ケース観測とも完全一致した。旧gateとの差を再現した形であり、今回常に反復が揺れるという結果ではない。旧gateと後続processでどの初期条件／演算経路が異なったかは未特定。[設定間・停止session照合](research/jeff-onnx-tract/native-repeat-diagnostic-2026-10-11/cross-setting-audit.json)。

host snapshot：

| run | system平均busy（%） | AC前→後 | 省電力flag前→後 |
| --- | ---: | --- | --- |
| diagnostic-0-threads1 | 28.221 | 1→1 | 0→0 |
| diagnostic-0-threads4 | 29.346 | 1→1 | 0→0 |
| diagnostic-1-threads4 | 28.515 | 1→1 | 0→0 |
| diagnostic-1-threads1 | 18.633 | 1→1 | 0→0 |

## 判定と次の作業

この5ケース・各設定2 process／3反復の診断だけで、原因修正・全28件反復gateの再受入・backend採用・性能改善・正式SLO達成とはしない。元の長さ別runの6違反と時間変動は有効な失敗記録として維持する。1-threadで差が小さくても4-thread版の修正とは扱わず、全入力・判断境界へ一般化しない。

次は固定ケースのinput IDs／backbone出力／head前後の比較で差が出る最初の段階を特定する。必要な診断出力は参照実装を変えず独立crate／targetへ限定する。修正する場合は単一候補と固定対照で元の閾値を使い、全28件を再受入した後、新規事前登録の性能runへ戻る。許容差自体の設計見直しは今回を合格へ変更せず、判断閾値への影響と別実験の事前条件を明記する。

追加source監査ではgemm-common 0.19.0の現在のlocal sourceがCargo.lockのchecksum付きcached crateと一致した。Intel CPUIDのcache情報をprocess内で一度初期化し、その情報からkernel_params／kcを選ぶ経路がある。process開始時のCPU／cache条件によってGEMMの分割とFP32丸めが変わる可能性は調査仮説だが、今回のfrozen exeで実際に選ばれたCACHE_INFO／kernel paramsや最初の差分演算は未取得。現在sourceの整合性監査でありbuild時の全source attestationでもない。次は初期化時・forward前後のprocessor番号、CACHE_INFOと選択parameterを診断用exeで記録してこの仮説を検証する。[source監査](research/jeff-onnx-tract/native-repeat-diagnostic-2026-10-11/gemm-cache-audit.json)。

性能再開時はAC／電源・温度・背景負荷・CPU配置の記録／制御方針を固定する。今回のdiagnostic raw時間はwarmupなし・数値診断の観測であり、中央値／p95の性能実績や8秒候補の支持には使わない。API E2E・cold・正式標本と未使用本文、配布NOTICEは残る。Phase 5はユーザー確認済みの実OCR／ASRデータ準備待ち。

停止run証跡とfrozen assetsのhash一致、Native baseline127ファイル（既知.gitignore差のみ）、隣接KazeNhanh 21ファイルの不変を確認した。実行時依存・公開APIの変更はない。

[診断証跡・事前登録・生ログ・独立validator](research/jeff-onnx-tract/native-repeat-diagnostic-2026-10-11/README.md)。[診断ハーネス](../runtime/onnx/diagnose_native_repeats.py)。


追加の[cache初期化診断](onnx-tract-native-cache-diagnostic.md)では独立crateでCPUごとのCACHE_INFOを記録し、初期化時だけmain threadを固定後に元maskへ復元した。2条件・AB／BA各2 process、128／512の2ケース・各2反復、全16 forwardがONNX確率／判断／tokens条件に合格した。入力ID・hidden・raw logitsと旧gate／停止sessionとの差は生ログから独立照合した。原因の判定範囲と実測差は同reportを参照。全28件再受入・原因修正・性能再開・正式SLOは未完了で、元失敗と閾値1e-6は維持する。
