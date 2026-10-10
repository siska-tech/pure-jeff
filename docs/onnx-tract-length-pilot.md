# Jeff 固定512 graphの入力長pilot

2026-10-11。[入力長fixture準備](onnx-tract-accepted-threads.md)に続き、現行step1113の正規化ONNX oracleで24件の参照出力を固定し、受入済みScatter版Tractの数値gateと入力長別の性能pilotを完了した。Native・通常probe・公開API・Decision Reportは変更していない。

## 数値受入と監視範囲

参照はCPUExecutionProviderのみ、ONNX Runtime 1.31.0、FP32、1 thread、graph最適化無効。同一checkpointからの正規化ONNXと外部重みをhash確認し、既存4 goldenに続いて24件のRust生成requestを計算する。既存goldenの確率誤差≤1e-4・判断一致を再確認する。新しい人工requestにOCR/ASRの正解ラベルはない。

Windowsのvenv Python launcherは実体のPythonを子として起動するため、最初のoracle runでは親の約5 MiBだけを監視していた。今回この問題を検出してworkerを手動停止し、初回source・途中出力・process情報・終了記録を保存した。途中出力を参照受入や性能集計に使用しない。

再実行は`sys._base_executable`の実体Pythonを直接起動し、実計算プロセスのPeak Working Set・期限を監視する。worker自身のinterpreter identityとexe hashを確認し、最低512 MiBの観測も監視範囲の検査に使う。受入runは28件完了、期限600秒・Peak Working Set上限8 GiB内、実観測peak 4,932,820,992 bytes。Python／ONNX Runtimeは開発用oracleのみで、Rust runtimeの実行時依存には追加しない。過去のNative／Tract性能測定は直接Rust exeを監視しており、このlauncher問題の影響を受けない。

Tractでは同一step1113のdeclutter済みNNEFと受入済みexe・174生成sourceを固定する。4 threads、FP32、batch1、物理512。まず4 golden＋24 fixtureの28件gateを別processで実行する。有限raw logits 255個、ONNX参照との候補確率最大絶対差≤1e-4、確率和誤差≤1e-6、判断・tokens一致を要求する。既存4 goldenのTract raw logitsは固定値との完全一致も要求する。

ONNX／Tract間のraw logits最大絶対差は診断値として保存し、確率・判断の受入基準と混同しない。その後のTract反復は、この28件gateのraw logitsと完全一致を要求する。gate失敗時は性能測定へ進めない。

最初のTract gateは、測定harnessが新fixtureの`candidate_count`をdriver用の`count`へ渡していなかったため、4 goldenの実行後に`invalid count`で停止した。初回source・job・stderr・終了記録を保存し、候補数をrequestから変換して既存metadataとの一致をpreflightするよう修正した。fixture・runtimeは変更せず、全28件gateを新しい出力先でやり直す。初回runには性能標本がない。

## 事前登録した性能pilot

主要集合は有効128／256／384／511／512 tokensそれぞれ4種類、候補数2／3。8候補の追加4件は数値gateだけに使い、性能分布へ混ぜない。全requestは既存Rust prompt/tokenizerでencodeし、左padding後は物理512。state末尾の人工suffixで長さを合わせており、内容と長さは交絡する。

独立3 resident session、各5 model warmup＋20 measured forwards。warmupは各長さ1件ずつでsessionごとに本文variantを変更し、測定20件の順序はseed 20261011＋session番号でshuffleした。各長さn=12（4本文×3 session）、各本文n=3。全4 process・103 forward（gate28＋warmup15＋測定60）を完了した。operator profileは無効。warmup・gateはlatency分布へ混ぜない。

初期化・process lifetime peakはresident各n=3として集計する。モデル・planはsession内で保持し、各requestは独立にrunする。要求別・長さ別のpeakとしてprocess peakを複製しない。prepare／forward／score／prepared requestを別集計し、各段階のp95を加算しない。

Core i7-1360P／Windows CPU／Balanced電源設定。温度・affinity・背景負荷・storage cacheは未制御。ビルド・試験・hash監査を計測と並行させない。各processの期限600秒、Peak Working Set上限min(8 GiB,物理RAMの50%)、開始前空きRAM4 GiB。peakはmapped/shared pagesを含む。

各長さn=12のnearest-rank p95は最大値で、独立sessionは3つだけである。信頼区間・正式SLO・Nativeとの優劣や高速化倍率を判定する実験ではない。固定512 graphでは有効長が短くても物理512を処理するため、長さ比から速度を予測・補正しない。

## 実測結果

すべて秒、中央値／p95。各長さ4本文×3 session、n=12。prepareは準備済みIDのJSON値からの配列復元・tensor構築で、tokenizerを含まない。forwardはplan実行・出力抽出／copy・有限値検査を含む。scoreは候補mask・temperature・確率算出。prepared requestはこれらを含むdriver内の測定で、公開APIのE2Eではない。JSONの`*_ns`集計値は記録時に秒へ換算済み。

| 有効tokens | forward | prepare | score | prepared request |
| ---: | ---: | ---: | ---: | ---: |
| 128 | 6.259686 / 7.188954 | 0.0000318 / 0.0003063 | 0.0000078 / 0.0000146 | 6.259733 / 7.189284 |
| 256 | 6.408078 / 6.862202 | 0.0000300 / 0.0000327 | 0.0000077 / 0.0000088 | 6.408125 / 6.862247 |
| 384 | 6.431165 / 7.115709 | 0.0000302 / 0.0000643 | 0.0000076 / 0.0000189 | 6.431215 / 7.115753 |
| 511 | 6.516816 / 7.102379 | 0.0000295 / 0.0000377 | 0.0000079 / 0.0000086 | 6.516865 / 7.102426 |
| 512 | 6.476182 / 7.198114 | 0.0000306 / 0.0000657 | 0.0000076 / 0.0000136 | 6.476229 / 7.198166 |

常駐sessionの初期化はn=3、中央値20.019750秒／p95 20.267051秒。process lifetime Peak Working Setはn=3、中央値3,278,077,952 bytes／p95 3,278,958,592 bytes（約3.054 GiB）。これは開始から終了までの観測で、入力長別のpeakでもprivate memoryでもない。3 sessionともexit 0、guard発火なし。

ONNX oracle比の最大候補確率誤差は4.649162292480469e-6、全103 forwardで判断・tokensが一致した。既存4 goldenのTract raw logitsは前回固定値と完全一致し、常駐75 forwardは今回gateの対応raw logitsと完全一致。ONNX／Tractのraw logits最大絶対差4.100799560546875e-5は診断値として保存した。

この集合では有効長128〜512でforward中央値は6.260〜6.517秒に収まり、長さに比例した増加は観測していない。物理512が共通で、内容・session差もあるため、短文の速度保証や全入力への一般化はできない。本文ごとのn=3統計も[summary.json](research/jeff-onnx-tract/length-pilot-2026-10-11/summary.json)へ保存した。以前の別runとの差を最適化効果とは扱わない。

## 再現と残作業

[参照生成](../runtime/onnx/prepare_length_oracle.py)と[測定script](../runtime/onnx/benchmark_lengths.py)を保存する。実モデル・重み・exe・生成treeはignored資産のままhashで固定する。入力fixtureとrequest／prompt／token hash、raw出力、初回監視範囲の失敗、事前登録、集計・保全を証跡へ残す。

[証跡一式](research/jeff-onnx-tract/length-pilot-2026-10-11/README.md)に、成功runに加え初回oracle停止と初回Tract gate失敗も保存した。生出力からの全件数値検証・確率／policy再計算・統計再集計を独立に照合した。Native baseline 128ファイルは既知の`.gitignore`差分のみ、他127ファイル・隣接KazeNhanh 21ファイル・通常probe・受入exe／174生成sourceは不変。公式Tract checkoutにも差分はない。

Tokenizer／API E2E、同形状・保持dtype・threadでのNative比較、cold campaign、正式SLO、TractBackend統合、実OCR/ASR品質、配布受入は未完了。
