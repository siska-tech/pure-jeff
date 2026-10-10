# NNEF保存・再ロードの性能調査 — 2026-10-10

**NNEFによる起動短縮は確認したが、常駐forwardの高速化は確認できなかった。Nativeを維持する。** 初期化中央値はONNX経路の100.957秒からNNEF経路の49.504秒へ短縮した。ただし後続・非pairedのpilotであり、正式な速度倍率やSLOではない。

同じstep1113 checkpointのsequence正規化済みONNXを、固定Tract 0.23.8でNNEFへ保存する実験を追加した。Native runtime、公開API、Decision Reportは変更していない。配布・通常実行のPython依存も追加していない。

証跡：[raw recordと索引](research/jeff-onnx-tract/nnef-pilot-2026-10-10/README.md)。前回：[ONNX／Native pilot](onnx-tract-performance-pilot.md)。今回の起動5回＋常駐25回（warm-up 5回を含む）の計30 forwardは、すべて数値・判断gateに合格した。最大確率誤差はgolden比4.9173831939697266e-6、guard発動・実行失敗は0件。

## 実測結果

一度だけのNNEF準備：型推論まで6.402秒、ChangeAxes除外declutter追加51.613秒、保存追加19.695秒、親process全体77.944秒。保存時の生涯Peak Working Setは5.743 GiB。n=1なのでp95は推定しない。保存ファイルは3,033,435,136 bytes、SHA-256 `ace9bfbee3f8d3a0817d8ea22d14df9392eb9e3afdae72b9a4e3eba419e4c0d5`。モデル資産はignoredなrun directoryに保持する。

利用時の起動、秒（各n=5）：

| 区間 | NNEF中央値 | NNEF p95 | 前回ONNX中央値 | 前回ONNX p95 |
| --- | ---: | ---: | ---: | ---: |
| load（NNEFはtyped model構築込み） | 8.634 | 8.725 | 2.796 | 3.015 |
| 別区間のONNX型推論 | — | — | 3.506 | 3.561 |
| optimize（NNEFはcodegen、ONNXはdeclutter＋codegen） | 40.408 | 41.717 | 94.341 | 98.961 |
| plan構築 | 0.440 | 0.446 | 0.293 | 0.360 |
| 初期化全体 | 49.504 | 50.664 | 100.957 | 105.635 |
| 128 tokens・1推論を含む親process全体 | 61.825 | 62.124 | 113.124 | 117.737 |

常駐計算＋softmax、秒（各入力n=5、各backend 1 resident session）：

| 入力・有効tokens | NNEF中央値／p95 | 前回ONNX中央値／p95 | 前回Native中央値／p95 |
| --- | ---: | ---: | ---: |
| candidate-request・128 | 11.825／12.674 | 11.636／12.217 | 2.977／3.182 |
| reversed・128 | 12.231／12.308 | 11.819／12.194 | 3.148／3.200 |
| asr-unicode・206 | 11.897／12.314 | 11.836／12.669 | 4.266／4.365 |
| special-token-text・182 | 12.223／12.892 | 11.737／12.531 | 4.128／4.395 |

NNEFの生涯Peak Working Setはcold 5回の最大3.052 GiB、resident 1回3.051 GiB。前回ONNXはcold最大3.265 GiB／resident 3.265 GiBだった。mapped／shared pagesを含むprocess全体の観測値で、要求別peakやprivate RSSではない。

起動時のdeclutterを事前計算へ移す効果はあるが、codegenの約40秒は残る。常駐計算は前回ONNXと同程度で、今回の短文・1 thread条件ではNativeを上回らない。製品のlatency SLOを緩めてTractを採用する根拠にはしない。FP32 weights・物理512 tokensを保持するTractと、BF16 mmap・128〜206 tokensのNativeの条件差も継続している。

残るcodegenの内訳は[pass callbackとdriver残余の診断](onnx-tract-codegen-profile.md)に分離して記録する。

## 保存できる段階

codegen後のモデルをそのまま保存する案は、小型のCast→Reshape→CumSum→Reshape→Sliceで失敗した。`IntoShape`にserializerがないためで、Jeff全体の全演算が保存可能という判断には進めない。

代わりに、top-level ChangeAxesを除いたdeclutterまでを一度実行し、codegen前のtyped modelを保存する。再ロード時はNNEFの型付きモデルを読み込み、codegenのみを行う。通常の`into_optimized()`を呼ぶとChangeAxesを再実行してしまうため、この経路は明示的な`nnef-decluttered` modeに限定する。自動fallbackは行わない。

`tract-nnef`は既存の推移依存と同じGit revisionを直接依存として明記した。追加の依存packageはない。NNEF本体とONNX拡張registryを登録し、入力名・型・shapeを検査する。保存先は新規fileに限り、既存資産を上書きしない。失敗したfileは成功資産として扱わない。

## 計測の範囲

初回変換は単発の成立性調査であり、中央値やp95を推定しない。保存済みNNEFからの利用時起動は、別processで5回計測する。さらに常駐1セッションでwarm-up 5件を除外し、以前のpilotと同じ4入力・順序で各5回計測する。全forwardでgolden確率誤差≤1e-4、判断一致、token数一致を要求する。

executorはSingleThread、物理入力長512、事前tokenized入力、同じ温度・候補順・policy。親processで資産hashを検証し、その時間は子の起動計測に含めない。600秒の期限と最大8 GiB／物理RAMの50%の小さい方のPeak Working Set制限を設ける。

NNEFの`load_ns`にはgraphの解析・重み読取・typed model構築を含む。別区間の`type_ns=0`は、型の処理コストがゼロという意味ではなく、NNEF loaderの中に含まれるためである。

OS storage cache、CPU温度・throttle、背景負荷は制御していない。前回ONNX pilotとは別時点・bench exe更新後の測定であり、交互のpaired比較ではない。n=5のnearest-rank p95は観測最大で、正式SLO受入ではない。Tract DecisionProvider／tokenizer／worker E2Eも含まない。

## 再現手順

```powershell
$env:CARGO_HOME = Join-Path $PWD '.venv/tract-cargo-home'
cargo build --locked --offline --release --manifest-path runtime/tract/Cargo.toml
# 出力先は未使用の新規directoryにする。準備時も期限・メモリ監視を行う。
vendor/jeff/.venv/Scripts/python.exe runtime/onnx/prepare_nnef.py --output experiments/runs/new-nnef-pack
# artifact.jsonでNNEF本体のhash・bytesとpack-preregistration.jsonのhashを固定する。
vendor/jeff/.venv/Scripts/python.exe runtime/onnx/benchmark_nnef.py --artifact experiments/runs/new-nnef-pack/artifact.json --source-pilot experiments/runs/performance-pilot-20261010/primary --output experiments/runs/new-nnef-reload
```

小型の解析的累積和との一致、別processの再ロード、同一planでの繰り返し推論による状態リセット、上書き拒否は`test_tract_nnef.py`で検査する。NNEFの可搬性・clean host配布受入・多スレッドの効果はこの調査の対象外である。

## 次の完了・中止判定

| 対象 | 完了条件 | 中止・別案への切替条件 |
| --- | --- | --- |
| NNEF成立性 | 実モデルの保存、clean process再ロード、4 goldenで確率・判断一致 | serializer未対応、数値不一致、期限・メモリ超過。失敗資産を採用しない |
| 起動短縮 | 同条件で初期化・codegen・plan・process全体を分け、nとp95を記録 | codegen後の保存が未対応なら「最適化済みplanの永続化」とは呼ばない |
| 常駐性能 | warm-up除外、4入力各5回、全forward数値gate | Nativeを上回らなければ速度目的のbackend切替根拠にはしない |
| 次の起動調査 | codegen内のpass・weight packing・graph処理を計測し支配項を特定 | 観測前に専用kernelやserializer拡張を増やさない |
| スレッド比較 | multithread-mmを有効にした独立artifactを作り、実executor・数値回帰を確認して2/4/8/16を測定 | thread指定だけで並列化したと扱わない。品質差・メモリ・tail悪化も記録 |
| 正式Phase 3 | 独立session、入力長matrix、API E2E、実利用予算でhold-out受入 | 今回のn=5・単一resident sessionを正式SLOへ昇格しない |

NNEFはモデル準備を移す選択肢であり、GEMMやGated DeltaNet自体の高速化を保証しない。現行Nativeを参照経路として維持し、実OCR/ASRの認識品質・routing率・確率校正は別のPhase 5で判定する。
