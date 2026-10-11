# Native 2／4 threadsの確認測定とTract 4 threads比較

2026-10-11。[Native thread matrix](onnx-tract-native-threads.md)で中央値が最短だった4 threadsを、新しい独立セッションで再測定する。2 threadsのp95が前回は小さかったためNative 2／4を確認し、同じ4 threadsのTractとも比較する。既存exeを再ビルドせず、Native参照実装・公開API・Decision Reportを変更しない。

## 設計と判定

固定Native thread wrapper（text320 model tensors＋head1、owned FP32）と受入Scatter／Trilu Tract（FP32 packed plan）を使う。同一step1113、同一prompt／候補、batch1、物理／有効512、paddingなし、textのみ。Native実Rayon poolサイズとCandle設定、Tract executor設定を各processで検証する。poolサイズは全worker稼働やOS全thread数の上限を意味しない。Nativeの判断policy・manifestは元のcpu_threads=1のままで、実験jobでcomputeだけを指定する。DeltaNetの直列再帰は不変。

各構成8件（4 golden＋4人工request）のgate後、Native2／Native4／Tract4の6通りの順列を1回ずつ使う。各構成は各実行位置に2回現れる。各sessionは1 warmup＋4測定、同じblockでは同一shuffle（seed 2461113＋block）、各構成n=24、各本文n=6。全21 process・114 forward＝gate24＋warmup18＋測定72。探索に使った前回とsession・seedは分けるが、入力は同じ4件で**未使用入力のhold-outではない**。実OCR／ASRの正解ラベルもない。

数値条件はONNX候補確率誤差≤1e-4、確率和誤差≤1e-6、判断／tokens一致。Nativeは固定Native確率との差≤1e-4、各構成gateからの反復差≤1e-6。Tract raw logitsは前回4-thread gateとの完全一致も要求する。Native raw logitsの一致は取得していない。既存9 Rust試験・clippy／fmt・13 source再生成と依存feature照合の証跡を、固定exe hashとともに引き継ぐ。

**Native4の局所warm確認条件**は、全6組のsession中央値とpooled中央値／p95がNative2より短く、数値／resource gateが合格すること。固定標本数で測り、条件の後付け・合格するまでの再測定はしない。Native4／Tract4は運用構成の記述的比較とし、runtime単体効果・速度倍率・backend採用・正式SLOは判定しない。保持dtypeを揃えてもpacked layout・kernel境界・DeltaNet algorithmは異なる。

Core i7-1360P／Windows CPU／Balanced。process期限600秒、peak上限min(8 GiB,物理RAMの50%)、開始前空きRAM4 GiB。計測中のbuild・試験・hash監査なし。温度・affinity・背景負荷・storage cacheは未制御。nearest-rank中央値ceil(0.5n)、p95 ceil(0.95n)を使い、n=24のp95は23番目＝2番目に大きい値。独立blockは6のみ、1 warmup、信頼区間・正式SLOの根拠には足りない。

computeはNative backbone＋head/softmax、Tract forward＋scoreを各観測で合算して集計する。Native requestはprompt/tokenizer／policyを含み、Tractは準備済みtensorからで、API E2Eは揃わない。Native startupはchild bundle検証／tokenizerを含み、Tract hash検証はparent preflightのため範囲非対称。startup／lifetime peakは各n=6の付随観測で、cold campaignやwarm private memoryではない。

## 結果

全21 process・114 forwardの数値gateが合格した。ONNX参照比の最大候補確率差は4.649162292480469e-06、固定Native比は0、Nativeの設定内反復差は0。判断／tokens一致、exit 0、guard発火なし。生ログの数値・順序・pool／cache設定・全統計を独立に再照合した。

構成ごとの中央値／p95。compute等は各n=24、startup／peakは各n=6：

| 構成 | compute（秒） | startup（秒、範囲非対称） | lifetime peak最大（bytes） |
| --- | ---: | ---: | ---: |
| Native 2 | 7.169396 / 7.548223 | 3.491340 / 3.631723 | 4,591,652,864 |
| Native 4 | 6.869798 / 7.087960 | 3.458658 / 3.528207 | 4,592,287,744 |
| Tract 4 | 6.841555 / 7.552308 | 19.942277 / 20.078501 | 3,277,443,072 |

全6組のNative4中央値とpooled中央値／p95がNative2より短く、事前条件どおり**Native4のwarm性能をNative2比で局所確認**した。
今回の結果は同じ人工4入力・6組・1 warmupの範囲に限る。正式SLO・製品採用・新規入力への一般化は受け入れない。

各組のcompute中央値／p95、各cell n=4。差はsession中央値から算出：

| block | Native2（秒） | Native4（秒） | Tract4（秒） | Native4−2（秒） | Tract4−Native4（秒） |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 7.104274 / 7.548223 | 6.742825 / 7.017381 | 6.530696 / 7.100189 | -0.361450 | -0.212128 |
| 2 | 7.021094 / 7.266561 | 6.869331 / 7.087960 | 6.889798 / 7.761094 | -0.151763 | +0.020467 |
| 3 | 7.080386 / 7.589345 | 6.868508 / 7.013685 | 6.825375 / 7.135971 | -0.211878 | -0.043133 |
| 4 | 7.113797 / 7.246057 | 6.869798 / 7.130357 | 6.714663 / 6.912855 | -0.243999 | -0.155134 |
| 5 | 7.169396 / 7.339690 | 6.763335 / 6.979836 | 6.841555 / 7.552308 | -0.406061 | +0.078221 |
| 6 | 7.249102 / 7.375092 | 6.826596 / 6.966359 | 6.748251 / 7.215716 | -0.422505 | -0.078346 |

Native4／Tract4は同thread・同shape・FP32保持の運用構成比較として記録する。片方をruntime単体で優れていると結論せず、別runとの差し引きによる倍率も出さない。process lifetime peakは初期化中のmmap／packing等を含み、warm private memoryや要求別peakではない。startupの検証範囲とrequestの入力準備範囲は非対称である。

本文別compute中央値／p95、各cell n=6：

| 人工request | Native2（秒） | Native4（秒） | Tract4（秒） |
| --- | ---: | ---: | ---: |
| OCR日本語2候補 | 7.154612 / 7.375092 | 6.869798 / 7.013685 | 6.909216 / 7.552308 |
| ASR Unicode 2候補 | 7.169396 / 7.548223 | 6.898162 / 7.130357 | 6.825375 / 7.508701 |
| OCR ASCII 3候補 | 7.080386 / 7.339690 | 6.742825 / 7.009201 | 6.904594 / 7.761094 |
| ASR混在2候補 | 7.228732 / 7.589345 | 6.868508 / 7.017381 | 6.714663 / 7.276863 |

Nativeの確率完全一致件数（gate・warmupを含む各38 forward）：

| 構成 | 固定Native確率と完全一致 | 最大固定差 | 最大反復差 |
| --- | ---: | ---: | ---: |
| Native 2 | 38 / 38 | 0 | 0 |
| Native 4 | 38 / 38 | 0 | 0 |

Tractは全38 forwardのraw logitsが固定4-thread gateと完全一致した。Nativeは上表のとおり完全一致と許容誤差内の一致を区別する。Native raw logitsは未取得である。

段階別の中央値／p95（秒）は次のとおり。独立した段階の中央値／p95を加算してcompute／request中央値等にはしない。

Native 2：compute 7.169396 / 7.548223、request 7.170175 / 7.548938、backbone 7.169324 / 7.548144、head_softmax 0.000066 / 0.000077、tokenize 0.000722 / 0.001134、policy 0.000001 / 0.000001。
startup内訳（n=6）：mmap 0.000520 / 0.000571、retention_load 1.430550 / 1.576376、tokenizer_load 0.823947 / 0.883624、verify 1.160261 / 1.205180。

Native 4：compute 6.869798 / 7.087960、request 6.870581 / 7.089064、backbone 6.869703 / 7.087893、head_softmax 0.000069 / 0.000096、tokenize 0.000888 / 0.001376、policy 0.000001 / 0.000001。
startup内訳（n=6）：mmap 0.000535 / 0.000602、retention_load 1.414599 / 1.503768、tokenizer_load 0.840770 / 0.875894、verify 1.196848 / 1.232199。

Tract 4：compute 6.841555 / 7.552308、request 6.841597 / 7.552354、forward 6.841548 / 7.552302、score 0.000008 / 0.000009、prepare 0.000032 / 0.000039。
startup内訳（n=6）：load 8.777323 / 8.920407、optimize 10.506635 / 10.789068、plan 0.491179 / 0.515751、type 0.000000 / 0.000000。

Native baseline 128ファイルは既知の`.gitignore`差分のみで他127ファイル不変。固定Native・全473保持版・text320版・thread wrapper版exe、通常Tract probe、受入Tract exe／174生成source、前回thread／長さ証跡、隣接KazeNhanh 21ファイルも不変だった。

## 残作業

今回のNative4／Tract4は中央値6.869798／6.841555秒、p95 7.087960／7.552309秒だった。Tractのpooled中央値は約0.028秒短いが、session中央値ではTractが短いのは6組中4組、p95はNativeが短いのが6組中5組である。中央値差だけでTractへ切り替える速度上の根拠にはしない。process peak最大はNative4 4,592,287,744 bytes／Tract4 3,277,443,072 bytesでTract側が低いが、startup中央値は範囲非対称の3.458658／19.942278秒。このtradeoffとAPI統合・品質を含む採用判断は残る。

測定済みのWindows CPU・4 threads・FP32常駐・batch1・有効／物理512という範囲で、次のprepared-compute検証の**暫定SLO候補はp95≤8秒**を提案する。今回の両4-thread構成の観測最大（Native 7.130357秒／Tract 7.761094秒）が8秒未満という実測に基づく計画値であり、事後の受入条件や達成済みSLOではない。新規入力、5 warmup、warm n≥300、別日または3回以上の独立blockを含む既定の正式ベンチマーク計画で再検証する。API E2E・cold startup・routingを含むSLOは、区間を揃えてから設定する。

実測に応じた演算内訳診断、短文・新しい入力群・独立session増加、API統合／E2E、正式cold campaignとSLO、確認済みOCR／ASR N-bestでの品質評価が残る。過去runの値と差し引いた累積倍率は提示しない。標準Tract最適化・配布用全source／NOTICE監査も未完了。

測定は[benchmark_native_confirm.py](../runtime/onnx/benchmark_native_confirm.py)。[証跡一式](research/jeff-onnx-tract/native-confirm-2026-10-11/README.md)に事前登録、生出力、段階・本文・block別統計、独立検証・保全hash、引継いだsource／依存検証・license／NOTICEを保存した。Pythonは測定用で推論時依存に追加しない。既存CIは不変、GitHub CIは未実行。
