# ONNX＋Tract実装の進捗

2026-10-10。計画の実装に着手し、Phase 0の保全、現行checkpointのONNX再exportと数値照合、独立Tract probeまで実施した。**TractでJeff全体のforwardはまだ成立していない。既存Native・公開API・Decision Reportは維持している。**

計画：[実装計画](onnx-tract-plan.md)。証跡：[今回の索引](research/jeff-onnx-tract/implementation-2026-10-10/README.md)。開発手順：[ONNX tooling](../runtime/onnx/README.md)、[Tract probe](../runtime/tract/README.md)。

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
| sequence限定変換 | 現行版・公開版ともSplitToSequence 24／SequenceAt 66をSplit／Identityへ置換。checker成功 | 小型graphのCPU oracle・Tract forwardで一致。変換後Jeff全体の数値照合は未完了 |
| Tract最小試作 | 公式0.23.8のcommitを新規Cargo cacheへ固定。小型ONNXのimport/type/optimize/run、入力長拒否を確認。追加10試験とclippy/fmt成功 | probe成立。DecisionProviderとしての統合は未実装 |
| Tract実モデル | 公開版・現行再export版とも外部重みロードまで成功。型推論でSliceに停止 | Phase 1／2の残課題。全体forward・数値一致・性能の合格ではない |

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

小型の直接initializer版SliceはTractで通るため、一般のSlice非対応とは扱わない。定数、Cast／Reshapeを通るbound、および型推論による扱いの組合せをさらに切り分ける必要がある。root causeの修正や、Jeff全体で他の問題がないことは未確認である。

## 次に進める順序

1. 保存した14ノードの再現例から、Tractのbound評価と型推論の差を特定する。必要なら専用branch／独立patchで最小修正し、oracleと比較する。既存Nativeや隣接Tract checkoutへ直接patchしない。upstream投稿は別途明示的な依頼があったときに行う。
2. 変換後の同一checkpointについてONNX oracleとの4件比較、Tractのtype→optimize→runを順に通す。各段階を別process・期限付きで記録し、OOM／panic／deadlineも失敗として残す。
3. 型推論・全体forward成立後に、既存DecisionProvider／worker wireへ接続する独立TractBackendを実装する。512超の明示拒否、prompt/tokenizerの同一性、温度処理、期限・異常応答の契約試験を追加する。既存RustProviderを廃止・改名しない。
4. 系列D／Eの数値受入後にPhase 3の比較を実施する。初期化、warm/cold、threads、入力長、p95・中央値・標本数、Peak Working Setを測る。現在のprobe経過秒数や開発用export時間は性能benchmarkとして使用しない。
5. Phase 4はプロファイルに基づいて選定。Phase 5は確認済みOCR/ASR正解とN-bestが必要で、現在の人工goldenでは認識品質を判定しない。

## 開発環境・ライセンス・未受入

Python 3.12.14の既存vendor venvは不変。ONNX 1.23.2、ONNXScript 0.7.2、ONNX Runtime 1.31.0等はhash付きlockで `.venv/onnx-tools/` へ隔離した。配布・通常実行にPython／ONNX Runtimeを追加していない。Tractは公式commit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a` を `.venv/tract-cargo-home/` で取得し、dirtyな既存registry sourceは使用していない。

jigor exporterの固定source、Apache-2.0本文、出典とNOTICE確認結果を `runtime/onnx/upstream/` に保持した。TractのWindows依存103 package、license宣言／本文hash、build scripts、PE直接importsを記録した。Tractはbuild時に`cc`とWindows assemblerを使用する。配布物の第三者NOTICE収集、全source review、既存projectのライセンス未決事項は引き続き配布受入の残作業であり、今回のprobeを配布承認とは扱わない。

初回exportはcp932でTorchの進捗記号を出力できず停止し、UTF-8へ修正して新規出力先で成功した。実行時のwrapper版とhashも証跡に保存している。現在のwrapperにはgolden hashと4件gateの追加検査があり、保存した実行版とはhashが異なる。

既存CIは不変。追加CIは小型graph用の独立workflowを作成したが、GitHub上では未実行。実モデルTract、性能SLO、実認識品質、clean host配布受入は未完了である。
