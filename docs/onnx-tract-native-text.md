# Native text重み限定FP32保持の実験

2026-10-11。[全473 tensors保持実験](onnx-tract-native-retained.md)を固定対照に、text推論で使う320 tensorsだけを保持する独立候補を比較する。Native参照実装・公開API・Decision Reportは変更しない。

## 変更と数値検証

[生成器](../runtime/onnx/prepare_native_text.py)は前回の証跡とsource hashを検証し、前回生成crateを複製する。変更は保持するmodel tensor名の選択だけで、backbone・readoutの計算式、wrapper、Cargo manifest／lockは前回版とbyte単位で同一。checkpointの全473 tensor名が固定inventoryと一致することを要求し、不足・重複・未知の名前は拒否する。別ファイルのDecision Head 1 tensorは両版で保持する。

保持model payloadは473 tensors／3,411,943,680 bytesから320 tensors／3,009,572,096 bytesへ変わる。除外する153個のvisual重みは402,371,584 FP32 bytes。headは双方1,044,480 bytes。このpayload差と、初期化中のmmap・変換領域を含むprocess lifetime Peak Working Setの実測差は別の値である。warm時のprivate memoryは測っていない。

releaseの7試験は既存DeltaNet／RoPE、共有Tensor・不足キー・cacheサイズ、BF16 embedding変換順序に加え、正確な320名の選択と異常inventory拒否、head維持を確認する。clippy／fmtも合格し、11生成ファイルは独立再生成と一致した。Pythonは開発・測定用のみで、推論時の依存追加はない。

4 golden＋有効512の人工4 requestを各版8件gateに使用する。全forwardでONNX参照との候補確率誤差≤1e-4・確率和誤差≤1e-6・判断／tokens一致、さらに固定Nativeの候補確率との完全一致を要求する。取得していないNative raw logitsの完全一致とは呼ばない。

## 測定条件と判定

Core i7-1360P／Windows CPU／Balanced、1 compute thread、batch1、物理／有効512、paddingなし。同じ4本文・候補数2／3を用い、独立3組full→text／text→full／full→text、各sessionは1 warmup＋同一shuffleの4測定（seed 320473＋block）。各版n=12、各本文n=3、全8 process・46 forward＝gate16＋warmup6＋測定24。

事前登録した受入条件は**メモリ削減のみ**で、数値／resource gate合格に加え、全3組のprocess lifetime peakとpooled最大値が減ること。warm性能・初期化時間は記述的観測とし、速度改善・非劣性の受入条件を後付けしない。process期限600秒、peak上限min(8 GiB,物理RAMの50%)、開始前空きRAM4 GiB。計測中のbuild・試験・hash監査は実施しない。

中央値とp95はnearest rank（中央値ceil(0.5n)、p95 ceil(0.95n)）。n=12のp95は最大値で、独立組は3つのみ。温度・affinity・背景負荷・storage cacheは未制御。startup／保持準備／peakは各n=3の付随観測でcold campaignではない。computeは各観測のbackbone＋head/softmaxを足してから集計し、段階の中央値を足さない。requestは公開API／IPCのE2Eではない。

## 結果

全8 process・46 forwardが完了し、固定Nativeの候補確率と全件完全一致した。ONNX参照比の最大候補確率誤差は3.7550926208496094e-6で、判断／tokensも一致。exit 0、guard発火なし。生出力から入力順序・cacheサイズ・数値gate・統計を独立に再検証した。

中央値／p95。compute等は各n=12、startup／保持準備／peakは各n=3：

| 項目 | 全473保持 | text320保持 |
| --- | ---: | ---: |
| compute（秒） | 9.205510 / 9.607663 | 8.929919 / 9.311753 |
| backbone（秒） | 9.205450 / 9.607599 | 8.929859 / 9.311689 |
| head/softmax（秒） | 0.0000652 / 0.0001897 | 0.0000635 / 0.0003130 |
| prompt/tokenizer（秒） | 0.0006767 / 0.0025321 | 0.0006321 / 0.0015302 |
| policy（秒） | 0.0000007 / 0.0000014 | 0.0000009 / 0.0000012 |
| request（秒） | 9.206140 / 9.608318 | 8.930617 / 9.312407 |
| 初期化（秒） | 3.822734 / 3.959594 | 3.544215 / 3.565743 |
| 保持準備（秒、初期化に含む） | 1.686457 / 1.784963 | 1.446822 / 1.577689 |
| process lifetime peak（bytes） | 5,190,656,000 / 5,190,696,960 | 4,591,173,632 / 4,591,202,304 |

全3組のtext−full peak差は−599,494,656／−599,482,368／−599,543,808 bytes。全組とpooled最大値が減り、数値／resource gateも合格したため、**実験経路のメモリ削減を局所受入**する。peak最大は約4.834→4.276 GiB。この差をFP32 payload削減量402,371,584 bytesと同一視しない。peakには一時mmap等が含まれ、各領域の寄与は分離していない。

warm computeのsession中央値差は−0.391609／−0.134536／−0.288912秒、pooled中央値は9.205510→8.929919秒だった。ただし2組目のp95は9.184749→9.311753秒へ増えた。速度改善／非劣性の事前受入条件は設定しておらず、これらは記述的観測のみである。初期化短縮も各n=3の付随観測で、正式cold campaignやSLOの受入ではない。

本文ごとのcompute中央値／p95、各n=3：

| 人工request | 全473保持（秒） | text320保持（秒） |
| --- | ---: | ---: |
| OCR日本語2候補 | 9.195307 / 9.387496 | 9.113254 / 9.311753 |
| ASR Unicode 2候補 | 9.210595 / 9.607663 | 8.760130 / 8.878259 |
| OCR ASCII 3候補 | 9.351738 / 9.369471 | 8.921683 / 9.109544 |
| ASR混在2候補 | 9.205510 / 9.292792 | 8.958641 / 8.987755 |

Native baseline 128ファイルは既知の`.gitignore`差分のみで他127ファイル不変。固定Native exe、前回の全473保持版exeと証跡、通常Tract probe、受入Tract exe／174生成source、隣接KazeNhanh 21ファイルも不変だった。

## 残作業

今回の比較は全473保持版とtext320保持版の単一変更比較である。過去のmmap版や別runのTract値との差し引きによる優位性・倍率は提示しない。Native thread条件の監査、固定したtext320版とTractの再比較、短文・独立session増加、API統合／E2E、正式SLOとcold campaign、確認済みOCR／ASR正解による認識品質評価が残る。Tractの標準最適化問題と配布用依存source／NOTICE監査も未完了。

測定harnessは[benchmark_native_text.py](../runtime/onnx/benchmark_native_text.py)。[証跡](research/jeff-onnx-tract/native-text-2026-10-11/README.md)には事前登録、生成sourceと差分、lock、生出力と段階／本文／pair別統計、独立検証、保全hash、build／試験ログ、license／NOTICEを保存した。既存CIの変更・GitHub CIの実行はない。
