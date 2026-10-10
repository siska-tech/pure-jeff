# FP32保持・共通512でのNative／Tract再比較

2026-10-11。[text320保持実験](onnx-tract-native-text.md)で固定したNative候補と、受入済みScatter／Trilu Tract候補を再比較する。元Native参照実装・公開API・Decision Report・既存exeは変更しない。今回は既存exeを再ビルドせず使う。

## thread条件の監査

[監査script](../runtime/onnx/audit_native_threads.py)はCandle commit `c68b24997319b8d76e5a4e775dab197c7f26322a`、core／nnのgit差分なし、固定候補のCargo feature treeを確認する。MKL／Accelerate／CUDA／Metal機能は有効でない。sourceのhashと行番号付き抜粋を証跡に保存する。

Native wrapperはpolicy.cpu_threads=1を要求し、tokenizer／tensor初期化前に`RAYON_NUM_THREADS=1`と`CANDLE_NUM_THREADS=1`を設定する。Candleの`get_num_threads()`は前者を読み、CPU GEMMは1なら`Parallelism::None`を選ぶ。大きな要素演算は後者を読むbarrier poolを使い、1では補助worker数が0になる。Native DeltaNetの時刻・head・state更新は直列Rustループ。Tract wrapperは1で明示的に`SingleThread` executorを選択し、executor設定値を検査する。

これは**source／設定値と初期化eventのcompute thread監査**で、OSの全thread数や実行中workerのtelemetryを測ったものではない。tokenizer等の補助OS threadが存在しないとは主張しない。固定Native wrapperは環境変数を上書きし、policy≠1も拒否するため、外部envだけを変えた4-thread測定は成立しない。将来のNative thread matrixには独立wrapperと数値gateが必要である。

監査scriptの初回実行はCargo treeのUTF-8をcp932でdecodeして停止した。明示UTF-8へ修正し、監査・事前登録・モデル起動前に解決した。性能標本への影響は0件。モデルsource・build・exeの変更はない。前回のRust7試験・clippy／fmt証跡とexe hashを引き継ぐ。

## 共通条件と残る差

同一step1113 checkpoint／prompt／候補、batch1、物理／有効512、paddingなし、textのみ、1 compute thread、FP32重みを常駐保持する。Nativeは320 model tensors／3,009,572,096 bytes＋head1／1,044,480 bytes、TractはFP32 packed planである。FP32保持を揃えてもlayout・kernel・exportされたDeltaNetと直列再帰のalgorithm差は残る。

比較computeはNative backbone＋head/softmax、Tract forward＋scoreを各観測で合算する。Tractのheadはforward内、Nativeは別関数で境界が異なる。Native requestはprompt/tokenizer／policyを含み、Tract requestは準備済みtensorからで、公開API E2Eの同条件比較ではない。Native startupはchild内のbundle検証とtokenizerを含み、Tract資産hash検証はparent preflightなので、startup差を同一検証範囲のロード時間差とは扱わない。

Core i7-1360P／Windows CPU／Balanced。4 golden＋4人工requestを各engine8件gate後、独立3組Native→Tract／Tract→Native／Native→Tract。同一組に同じshuffle順序（seed 3201113＋block）、1 warmup＋4測定、各engine n=12、各本文n=3。全8 process・46 forward＝gate16＋warmup6＋測定24。入力は2／3候補で実OCR／ASRの品質ラベルはない。

数値条件はONNX参照との候補確率誤差≤1e-4、確率和誤差≤1e-6、判断／tokens一致。Native候補確率は固定Native、Tract raw logitsは前回4-thread gateとの完全一致も全forwardで要求する。Native raw logitsの一致は取得していない。性能は記述的pilotと事前登録し、採用・速度倍率・SLOの受入条件は設定しない。

process期限600秒、peak上限min(8 GiB,物理RAMの50%)、開始前空きRAM4 GiB。計測中のbuild・試験・hash監査なし。温度・affinity・背景負荷・storage cacheは未制御。nearest-rank中央値ceil(0.5n)／p95 ceil(0.95n)を使い、n=12のp95は最大値。startupとprocess lifetime peakは各n=3の付随観測で、warm private memory・cold campaignとは異なる。

## 結果

全8 process・46 forwardの数値gateが合格した。Native候補確率は固定Nativeと完全一致、Tract raw logitsは前回4-thread gateと完全一致。ONNX参照比の最大候補確率誤差は4.649162292480469e-6、判断／tokensも一致した。全process exit 0、guard発火なし。生ログの数値・順序・cache／executor設定・全統計を独立に照合した。

中央値／p95。compute等は各n=12、startup／peakは各n=3：

| 項目 | Native text320 FP32 | Tract FP32 packed plan |
| --- | ---: | ---: |
| compute（秒） | 9.005815 / 9.225719 | 9.669719 / 9.946535 |
| request（秒、範囲非対称） | 9.006443 / 9.226340 | 9.669749 / 9.946569 |
| startup（秒、範囲非対称） | 3.500689 / 3.578931 | 19.844861 / 20.259371 |
| lifetime peak（bytes） | 4,590,768,128 / 4,591,132,672 | 3,276,390,400 / 3,277,074,432 |

全3組のTract−Native session compute中央値差は＋0.590471／＋0.611261／＋0.631738秒。pooled中央値／p95と全組の中央値／p95はNativeが短く、各本文の中央値／p95もNativeが短かった。この条件では速度を理由にTractへ切り替える根拠は得られなかった。一方、process lifetime peak最大はTract側が低い。**記述的な運用構成比較の完了**であり、Native／Tractの製品採用や正式SLOを受け入れる判定ではない。以前のBF16 mmap版比較からの結果の変化を、別run同士の差し引きでFP32保持だけの因果効果と呼ばない。

Native段階の中央値／p95（秒）はbackbone 9.0057425／9.2256534、head/softmax 0.0000651／0.0002103、prompt/tokenizer 0.0006469／0.0008268、policy 0.0000008／0.0000013。初期化内のFP32保持準備は1.4583290／1.4786407秒（n=3）。Tractはforward 9.6697121／9.9465290、score 0.0000063／0.0000069、prepared tensor準備0.0000264／0.0000752秒。computeは各観測の和から集計しており、段階の中央値／p95を加算していない。

初期化eventの事後の記述的集計（各n=3、秒、範囲非対称）では、Native bundle検証1.1878574／1.2280479、tokenizer load 0.8561640／0.8627300、mmap作成0.0005275／0.0005747。Tract NNEF load 8.8490025／8.9424602、optimize/codegen 10.5356704／10.7932717、plan作成0.4994569／0.5027807だった。NNEF経路の独立type処理は0と記録されている。各段階の中央値を足した値がstartup中央値に一致するとは限らない。

本文ごとのcompute中央値／p95、各n=3：

| 人工request | Native（秒） | Tract（秒） |
| --- | ---: | ---: |
| OCR日本語2候補 | 9.005815 / 9.180394 | 9.584988 / 9.946535 |
| ASR Unicode 2候補 | 9.007569 / 9.109567 | 9.670281 / 9.787783 |
| OCR ASCII 3候補 | 8.967289 / 9.225719 | 9.716783 / 9.837285 |
| ASR混在2候補 | 9.057094 / 9.146730 | 9.577433 / 9.688832 |

Native baseline 128ファイルは既知の`.gitignore`差分のみで他127ファイル不変。固定Native・全473保持版・text320版exe、通常Tract probe、受入Tract exe／174生成source、前回のtext／共通512／長さ証跡、隣接KazeNhanh 21ファイルも不変だった。

## 残作業

次はNative thread matrix用の独立wrapperを作り、GEMM／要素演算の設定を明示し、数値gateから検証する。Tractの4-thread値とNativeの1-thread値を差し引いてruntime単体の効果としない。短文・独立session増加・hold-out受入、API統合／E2E、cold campaign、正式SLO、確認済みOCR／ASR正解での品質評価も残る。標準Tract最適化の停止、配布用全依存source／NOTICE監査は未解決。

測定は[benchmark_fp32_common512.py](../runtime/onnx/benchmark_fp32_common512.py)。[証跡一式](research/jeff-onnx-tract/fp32-common512-2026-10-11/README.md)へ監査source抜粋／feature tree／hash、事前登録、生出力・統計・独立検証・保全・license／NOTICEを保存した。既存CIは不変、GitHub CIは未実行。新しいPython実行時依存は追加しない。
