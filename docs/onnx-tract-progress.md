# ONNX＋Tract実装の進捗

2026-10-10。Phase 0の保全、現行checkpointのONNX再exportと数値照合に続き、**限定修正したTractで、最適化なし／ChangeAxesを除いた限定最適化の両経路でJeff全体forwardと4件の数値回帰が成立した。標準最適化の修正・公開API統合・性能評価は未完了。既存Native・公開API・Decision Reportは維持している。**

計画：[実装計画](onnx-tract-plan.md)。証跡：[今回の索引](research/jeff-onnx-tract/implementation-2026-10-10/README.md)。開発手順：[ONNX tooling](../runtime/onnx/README.md)、[Tract probe](../runtime/tract/README.md)。

続行分の証跡：[Tract全体forward・数値gate](research/jeff-onnx-tract/continuation-2026-10-10/README.md)。

最適化続行の証跡：[ChangeAxes再現例と限定最適化](research/jeff-onnx-tract/optimizer-2026-10-10/README.md)。

性能pilot：[Windows CPUの測定結果・暫定予算](onnx-tract-performance-pilot.md)。同一checkpoint・1 thread・今回の短文群では高速化は確認できず、Nativeを維持する。正式なPhase 3受入は未完了。

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
| sequence限定変換 | 現行版・公開版ともSplitToSequence 24／SequenceAt 66をSplit／Identityへ置換。checker成功。現行版4件の変換前後ONNX候補確率差0 | 現行checkpointの変換後全体oracleも合格 |
| Tract最小試作 | 公式0.23.8のcommitを新規Cargo cacheへ固定。小型ONNXのimport/type/optimize/run、入力長拒否を確認。追加Python 13試験＋Rust境界値1試験とclippy/fmt成功 | probe成立。DecisionProviderとしての統合は未実装 |
| Tract実モデル | I64→TDimの限定修正で現行版の全体型推論を通過。最適化なしの全体forward成立 | 最適化はChangeAxes／CumSum Scanで停止。性能・公開API統合は未受入 |
| Tract全体数値回帰 | 現行step1113、4件。最大確率差は正規化ONNX oracle比1.7285346984863281e-6、golden比3.039836883544922e-6。候補選択・保留が全件一致 | 許容1e-4で合格。小規模goldenのみで、認識品質の評価ではない |
| 限定最適化の全体回帰 | top-level ChangeAxesのみ除外し、残りのdeclutter＋codegenを実行。4件すべて合格、最大確率差はgolden比4.9173831939697266e-6、oracle比4.649162292480469e-6 | 明示的な実験経路として成立。標準最適化の修正・性能受入ではない |
| Phase 3 pilot | process-cold各5回、resident各1セッション・4入力各5回、warm-up各5回。Native API別5回。計65 forward数値一致。warm計算中央値Native 2.977〜4.266秒、Tract 11.636〜11.836秒 | 現行短文・1 threadで速度目的のTract採用根拠なし。threads／長さmatrix・独立session・Tract E2Eは未測定 |

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

原因はTract dataのI64→TDim castで、i32の中間変換によりINT64_MAXが-1へ切り詰められることだった。独立probe内に固定版data crateを保全し、I64だけ直接TDimへ変換する9行の修正を追加した。26ファイルの原本hashを保存し、差分がtensor.rsだけであることを試験する。Native・隣接checkoutには適用していない。14ノードの再現例では重複value_infoにより入力I64型が消える問題もあり、probeのanalyze段階で宣言済み入力型だけを復元した。境界値Rust試験と再現例が成功した。

現行checkpointのsequence変換版は型推論を通過した。標準最適化はChangeAxesがCumSumのScan bodyへReshape(2,[8,64],[512])を伝播すると、bodyの[1,16,8,1]と衝突して停止する。`run-typed`を追加し、最適化を省いた経路で全体forwardが成立した。これは修正版Tractの成立性確認であり、未修正の公式Tractや最適化済みbackendの合格とは扱わない。

## 次に進める順序

1. 5ノードのCast→Reshape→CumSum→Reshape→Sliceで標準最適化の同じエラーを再現した。`run-no-change-axes`では固定版declutterのtop-level ChangeAxesを1個だけ除去し、残りとcodegenを実行する。構成が変われば明示失敗し、自動fallbackはしない。小型例は解析的な累積和と一致し、Jeff全体4件も合格。標準Tract側の修正とupstream投稿は未実施で、投稿は明示的な依頼があったときに行う。
2. 最適化を変更するたびに同一checkpointの4件数値gateを再実行する。各段階を別process・期限付きで記録し、OOM／panic／deadlineも失敗として残す。
3. 型推論・全体forward成立後に、既存DecisionProvider／worker wireへ接続する独立TractBackendを実装する。512超の明示拒否、prompt/tokenizerの同一性、温度処理、期限・異常応答の契約試験を追加する。既存RustProviderを廃止・改名しない。
4. Phase 3は独立計測wrapperでpilotまで実施した。次は独立session、多スレッドvariant、256/384/511/512-token、Tract API E2Eを測る。以前の単発probe秒数・export時間と、今回の事前登録したbenchmark結果を混同しない。
5. Phase 4はプロファイルに基づいて選定。Phase 5は確認済みOCR/ASR正解とN-bestが必要で、現在の人工goldenでは認識品質を判定しない。

限定最適化の調査では、推論前のgraph処理にも大きなコストが観測された。単発probeの秒数を速度倍率やSLOには換算しない。Phase 2の次段ではモデル・planの再利用を実装し、必要なら最適化済みNNEFの保存・再ロードも調査する。NNEFには演算子登録、外部資産hash、4件数値回帰、clean process再ロードの独立受入が必要で、初期化短縮はまだ期待効果である。

## 開発環境・ライセンス・未受入

Python 3.12.14の既存vendor venvは不変。ONNX 1.23.2、ONNXScript 0.7.2、ONNX Runtime 1.31.0等はhash付きlockで `.venv/onnx-tools/` へ隔離した。配布・通常実行にPython／ONNX Runtimeを追加していない。Tractは公式commit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a` を `.venv/tract-cargo-home/` で取得し、dirtyな既存registry sourceは使用していない。

jigor exporterの固定source、Apache-2.0本文、出典とNOTICE確認結果を `runtime/onnx/upstream/` に保持した。TractのWindows依存103 package、license宣言／本文hash、build scripts、PE直接importsを記録した。Tractはbuild時に`cc`とWindows assemblerを使用する。配布物の第三者NOTICE収集、全source review、既存projectのライセンス未決事項は引き続き配布受入の残作業であり、今回のprobeを配布承認とは扱わない。

初回exportはcp932でTorchの進捗記号を出力できず停止し、UTF-8へ修正して新規出力先で成功した。実行時のwrapper版とhashも証跡に保存している。現在のwrapperにはgolden hashと4件gateの追加検査があり、保存した実行版とはhashが異なる。

既存CIは不変。追加CIは小型graph用の独立workflowを作成したが、GitHub上では未実行。実モデルTractの標準最適化・公開API統合、性能SLO、実認識品質、clean host配布受入は未完了である。
