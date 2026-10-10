# Native FP32重み保持の独立実験

2026-10-11。[共通512形状pilot](onnx-tract-common512-pilot.md)で残ったNativeのBF16 mmap／forwardごとのFP32変換を分離する。Native参照実装・公開API・Decision Report・既存exeは不変。独立生成した1つのRust exe内で、従来相当のmmap方式とFP32保持方式を切り替える。

## 変更と数値受入

[生成器](../runtime/onnx/prepare_native_retained.py)はhash固定したNative backbone・readout・benchmark wrapperから、ignoredな独立crateを作る。backboneの計算式はそのまま、重み型をMapped／Retainedのenumへ差し替える。retainedでは全model tensorとreadoutをCPU FP32の所有Tensorへ初期化時に変換し、元mmapを解放する。forwardは同じTensorをcloneして共有し、既存の`to_dtype(F32)`は同型のため再変換しない。embeddingも保持対象で、選択後のBF16→FP32からFP32選択へ変わる点を別途検証する。量子化・GEMM・DeltaNetの計算式・thread数は変更しない。

controlは同じ新規exeで元のmmap読込／変換を行い、readoutは既存関数を使用する。retainedは同じreadout計算式を使って保持済みheadを読む。既存Native exeの測定値を別日の対照値にせず、両方式を同一buildで交互に測る。生成sourceには未使用の`forward`入口へのdead-code注記とrustfmt整形を含み、差分を保存する。初回の開発buildで未使用入口の警告を検出し、計測前に注記・整形を適用して別生成先へ再生成した。

既存4 golden＋有効512の4人工requestを両方式各8件gateに使う。ONNX参照との確率誤差≤1e-4、確率和誤差≤1e-6、判断・tokens一致に加え、全forwardの候補確率は前回固定Native gateと完全一致を要求する。controlが元のNativeを再現することと、retainedの数値を同時に検証する。これは候補確率の完全一致であり、取得していないNative raw logitsの完全一致とは呼ばない。

新規weight helperの試験は共有Tensor identity・不足キー拒否・cacheサイズと、BF16 embedding選択／FP32変換の順序交換を検証する。既存backboneのDeltaNet状態／decay・RoPE試験も複製した計算式で実行する。releaseの4試験、clippy、fmtが合格し、9生成ファイルは独立再生成と完全一致した。依存版は既存Native wrapperのlockを維持し、既存依存のcandle-nnをrootへ明示するentryだけ追加した。Candle core／nnは固定commitからの差分なし。新たなPython実行時依存は加えない。

## 性能の事前登録

Core i7-1360P／Windows CPU／Balanced電源設定。1 compute thread、batch1、unpadded512の同一4本文・候補数2／3。各sessionは1 warmup＋4測定、独立3組control→retained／retained→control／control→retained、同じ組に同じshuffle順序を渡す（seed 1113512＋block）。各方式n=12、各本文n=3。全8 process・46 forward＝gate16＋warmup6＋測定24。温度・affinity・背景負荷・storage cacheは未制御。計測中にbuild・試験・hash監査を並行しない。

computeは各観測のbackbone＋head/softmaxを足してから集計する。tokenizer・policy・request、初期化・FP32保持準備、process lifetime Peak Working Setも別記録する。FP32保持に移したコストを除外して全体が短縮したと扱わない。初期化／peakは各n=3の付随観測で、cold campaignではない。peakには保持中のtensorに加え、初期化中のmmapと変換領域も含まれる。

process期限600秒、Peak Working Set上限min(8 GiB,物理RAMの50%)、pilot開始前空きRAM4 GiB。局所的なwarm性能受入条件は全3組のsession中央値とpooled中央値／p95の短縮、数値gate・resource guard合格である。n=12のnearest-rank p95は最大値、独立組は3つだけであり、正式SLO・配布・backend採用を受け入れる条件ではない。

## 結果と残作業

全8 process・46 forwardが完了した。候補確率はcontrol／retainedとも全件で固定Native gateと完全一致し、ONNX参照比の最大候補確率誤差は3.7550926208496094e-6、判断・tokensも全件一致した。exit 0、guard発火なし。生ログからの全件検証・統計再計算を独立照合した。

各方式のcomputeはn=12、初期化・peakはn=3。中央値／p95（nearest rank、n=12 p95は観測最大）：

| 項目 | mmap control | FP32 retained |
| --- | ---: | ---: |
| compute（秒） | 9.788883 / 10.407099 | 9.072797 / 9.675129 |
| backbone（秒） | 9.788093 / 10.406329 | 9.072730 / 9.675067 |
| head/softmax（秒） | 0.0007773 / 0.0012839 | 0.0000631 / 0.0002243 |
| prompt/tokenizer（秒） | 0.0006418 / 0.0016632 | 0.0006328 / 0.0010047 |
| request（秒） | 9.789535 / 10.407750 | 9.073540 / 9.675771 |
| 初期化（秒） | 2.054322 / 2.116281 | 3.806320 / 3.873206 |
| 保持準備（秒、初期化に含む） | 0.0000015 / 0.0000023 | 1.727732 / 1.869487 |
| process lifetime peak（bytes） | 2,089,676,800 / 2,090,037,248 | 5,190,864,896 / 5,191,053,312 |

policyはcontrol中央値0.0000011秒／p95 0.0000015秒、retained 0.0000008／0.0000018秒。requestは公開API／IPCのE2Eではない。JSONの`*_ns`集計は秒へ換算済み。computeは観測ごとのbackbone＋head/softmaxの和から集計し、各段階の中央値／p95を加算していない。

3組のretained−control session中央値差は−0.950074／−0.638687／−0.363487秒。全組の中央値・pooled中央値／p95が短縮したため、事前条件どおり**実験経路のwarm性能のみ局所受入**とする。保持方法の介入には重みload／変換／共有・embedding保持・head再利用を含むため、差の0.716086秒を純粋なBF16変換時間とは呼ばない。初期化は長くなり、process peak最大も約1.947→4.835 GiBに増えた。このtradeoffを含む製品採用・SLO・Tractとの優劣は未受入。

本文ごとのcompute中央値、各n=3：

| 人工request | control（秒） | retained（秒） |
| --- | ---: | ---: |
| OCR日本語2候補 | 9.848227 | 9.111465 |
| ASR Unicode 2候補 | 9.774332 | 9.072797 |
| OCR ASCII 3候補 | 9.711485 | 9.350184 |
| ASR混在2候補 | 9.862295 | 8.980669 |

保持payloadはmodel 473 tensors／3,411,943,680 bytesとhead 1 tensor／1,044,480 bytesだった。測定後のsafetensors headerと固定backboneの名前からの静的棚卸しにより、text推論で参照する320 tensors／3,009,572,096 FP32 bytesと、参照しない`visual.*` 153 tensors／402,371,584 FP32 bytesを区別した。この実験は**visual重みも保持したまま測定**している。未使用分の除外で減らせるtensor payloadは特定できたが、除外後のprocess peak・初期化・latencyは未測定で、改善実績には数えない。

測定harnessは[benchmark_native_retained.py](../runtime/onnx/benchmark_native_retained.py)。生成source・exe・モデルはignored資産をhashで固定し、事前登録・生出力・失敗・統計・保全を証跡に残す。

[証跡一式](research/jeff-onnx-tract/native-retained-2026-10-11/README.md)に生成source／差分／lock、build・4試験・clippy・fmt、事前登録、生出力、段階・本文・pair別統計、静的重み棚卸し、source／資産hash、license／NOTICEを保存した。Native baseline 128ファイルは既知の`.gitignore`差分のみで他127ファイルは不変。既存Native exe・通常Tract probe・受入Tract exe／174生成source、隣接KazeNhanh 21ファイルも不変。既存CIは変更せず、GitHub CIは今回未実行。配布用の全依存source／NOTICE監査は引き続き残る。

次はtext使用320 tensorsだけを保持する独立候補を作り、今回版を固定対照に数値gate・初期化／peak／warmの比較を行う。除外の効果を測る前に、この版をTractと保持条件が等しいと扱わない。Tractとの再比較、4-threadを含むNative thread条件の監査・評価、短い入力への一般化、API統合／E2E、正式SLO・cold campaign、実OCR/ASRの確認済み正解による品質評価は未完了。
