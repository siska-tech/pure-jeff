# Native／Tractの共通512形状pilot

2026-10-11。[Tract入力長pilot](onnx-tract-length-pilot.md)に続く、既存Nativeと受入済みScatter版Tractの運用構成比較。公開API・Decision Report・Native参照実装・既存benchmark exeを変更せず、独立Python harnessから固定Rust exeを起動する。Pythonは開発時の測定のみで、runtime依存には加えない。

## 同条件化の監査

| 項目 | Native | Tract | 判定 |
| --- | --- | --- | --- |
| checkpoint | 現行step1113 | 同じstep1113から正規化ONNX→NNEF | hash付き変換履歴と参照出力で固定。公開step960は使用しない |
| request／prompt／IDs | 既存Rust prompt・tokenizerで毎回encode | 同じRust生成fixtureの準備済みIDs | 有効512の4人工requestを主集合にする |
| shape／mask | unpadded512、causal attention、text only | batch1物理512、attention全1・mm全0 | 主集合ではpaddingなし・形状共通。短いgoldenは数値gateのみ |
| 計算dtype | FP32 | FP32 | 共通。ただし演算順・algorithmは異なる |
| 重みの保持 | BF16 mmap、forwardごとにload／FP32変換 | FP32／packed planを常駐保持 | 非対称。runtime単体の効果とは判定できない |
| threads | 固定wrapperがCANDLE／RAYON=1を設定、Candleの報告値を検証 | 実executor=1を検証 | 設定と報告値を共通化。OSの全process thread数の上限ではない |
| Gated DeltaNet | 既存の逐次recurrence | exportで展開したgraph演算 | 数値gateで比較。kernel単位の同一algorithm比較ではない |
| compute区間 | backbone＋head/softmax | forward（head込み）＋score | 集約区間を比較し、段階の個別優劣は断定しない |
| request区間 | prompt/tokenizer・policy等を含む | prepared tensor構築からscoreまで | E2E比較には使わない。別々の診断値として保存 |
| 初期化 | 子processでbundle検証・tokenizer・mmap | 親で資産検証後、子processでNNEF／plan構築 | 非対称。cold起動の優劣判定には使わない |

Nativeは`backbone::forward_checked`にpadding maskの引数がなく、unpadded専用である。短い入力にpad IDを足すだけでは同条件化できない。保持dtypeを揃えるには重みloader／cacheの実験実装が必要になるため、今回は既存Nativeを変更せず、共通形状の運用構成比較として事前登録した。

## 事前登録と受入範囲

固定済みONNX oracleから既存4 golden＋有効512の4人工requestを使用し、Native／Tract各8件の数値gateを先に実行する。候補確率誤差≤1e-4、確率和誤差≤1e-6、判断・tokens一致を要求する。Tractの全raw logitsは前回4-thread gateと完全一致、Native反復の確率は今回Native gateと完全一致を要求する。失敗時は性能集計へ進めない。

独立3組のresident sessionをNative→Tract／Tract→Native／Native→Tractの順で実行する。各sessionは1 warmup＋4測定。各組の入力順序はseed 20261012＋block番号でshuffleし、同じ組の両backendに同順で渡す。backendごとに測定n=12（4本文×3 session）、本文ごとn=3。全8 process・46 forward＝gate16＋warmup6＋測定24。operator profileは無効。中央値／p95はnearest rank、n=12のp95は観測最大で、独立session数は3である。

Core i7-1360P、Windows 11 Home build26200、Balanced電源設定。期限600秒、Peak Working Set上限min(8 GiB,物理RAM50%)、pilot開始前空きRAM4 GiB。ビルド・試験・hash監査を計測中に並行しない。温度・affinity・背景負荷・storage cacheは未制御。hash preflightでstorage cacheも影響を受けるためprocess-coldをstorage-coldとは呼ばない。1 warmupの小規模pilotであり、正式SLO・backend採用・品質改善を受け入れる測定ではない。

最初のsandbox実行はNative初期化前のアクセス拒否で終了し、forward数0・性能標本0。source・job・stderr・終了記録を残し、同じsource／資産のまま実行権限を得た別runとして再実行した。

## 結果と残作業

全8 process・46 forwardが完了し、確率・判断・tokensの数値gateが全件合格した。最大候補確率誤差はONNX oracle比4.649162292480469e-6（許容1e-4）。Nativeの常駐反復はNative gateの確率と完全一致、Tractは全forwardのraw logitsが前回4-thread gateと完全一致した。受入runはexit 0、guard発火なし。

| 常駐compute | n | 中央値（秒） | p95（秒） |
| --- | ---: | ---: | ---: |
| Native：backbone＋head/softmax | 12 | 9.892094 | 10.703172 |
| Tract：forward＋score | 12 | 9.626069 | 10.133096 |

これは各観測の段階時間を足した後で集計した値で、各段階の中央値／p95を足した値ではない。Tract forwardには出力抽出・copy・有限値検査も含む。各組は測定4入力、medianはnearest-rankの下側中央値。Tract−Nativeのsession中央値差は順に−0.567365／−0.266025／−0.142912秒だった。ただし最後の組のp95はNative 9.907314秒、Tract 9.925315秒で、Tractが短い条件は全組のp95では成立しない。

本文ごとのcompute中央値、各n=3：

| 人工request | Native（秒） | Tract（秒） |
| --- | ---: | ---: |
| OCR日本語2候補 | 9.907314 | 9.587641 |
| ASR Unicode 2候補 | 9.777379 | 9.835266 |
| OCR ASCII 3候補 | 10.085539 | 9.574103 |
| ASR混在2候補 | 9.881993 | 9.626069 |

pooled中央値／p95はTract側が短かったが、Unicode入力の中央値はNative側が短い。独立3組、各本文n=3、非対称な重み保持・algorithmであり、runtime単体の改善・全入力での優位性・採用条件の達成・正式SLOとは判定しない。以前の4-thread／別runの値との比を性能実績にしない。

測定範囲が異なるrequest診断値はNative中央値9.892757秒／p95 10.703835秒、Tract中央値9.626102秒／p95 10.133128秒。Nativeのprompt/tokenizer時間は中央値0.0006203秒／p95 0.0011764秒、head/softmaxは0.0007460／0.0008605秒、policyは0.0000010／0.0000020秒。Tractのprepared tensor構築は0.0000261／0.0000334秒、scoreは0.0000065／0.0000068秒。各n=12、JSONの`*_ns`集計は秒へ換算済み。API／IPC／parent側処理を含むE2Eではない。

初期化の付随観測は各n=3、Native中央値2.070046秒／p95 2.074405秒、Tract中央値20.154006秒／p95 20.345775秒。資産検証と準備の範囲が異なり、cold起動の優劣判定には使わない。process lifetime Peak Working SetはNative中央値2,089,185,280 bytes／最大2,089,271,296 bytes（約1.946 GiB）、Tract中央値3,276,492,800 bytes／最大3,276,890,112 bytes（約3.052 GiB）。shared／mapped pagesを含み、入力別peakやprivate memoryではない。

測定harnessは[benchmark_common512.py](../runtime/onnx/benchmark_common512.py)。Tokenizerとprepared requestを同じE2Eとして差し引かず、compute／各段階／初期化／process lifetime peakを別に保存する。今回の4人工requestにOCR/ASRの確認済み正解はない。

[証跡一式](research/jeff-onnx-tract/common512-pilot-2026-10-11/README.md)に事前登録、成功／初回失敗のjob・生出力・終了記録、段階／本文／pair別統計、source・資産hash、license／NOTICEを保存した。生ログから全件数値検証・反復一致・統計再集計を独立照合した。Native baseline 128ファイルは既知の`.gitignore`差分のみで他127ファイルは不変。隣接KazeNhanh 21ファイル・Native exe・通常probe・受入Tract exe／174生成sourceも不変。

保持dtype・変換／cache条件の同条件化、独立block追加、Tract API統合とE2E、cold campaign、正式SLO・実品質・配布受入は残る。
