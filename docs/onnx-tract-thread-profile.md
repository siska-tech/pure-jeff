# Jeff Tract 4／8-thread演算診断

2026-10-11。前回commit `b41d19f` のexe・生成source・依存lock・step1113のNNEFをhash固定し、4／8-threadでtop-level wall timeを測定した。**行列演算に加えてScatterElements、MoveAxis、Triluが大きな残余コストとなった。次は小さい範囲のTrilu変更を独立実験にする。今回はruntime／optimizerの変更や新しい高速化の採用判定を行っていない。**

証跡：[raw record・hash・独立再集計](research/jeff-onnx-tract/thread-profile-2026-10-11/README.md)。前回の[計測なしthread pilot](onnx-tract-forward-profile.md)と区別する。

## 実測結果

同一exe・batch1・物理512・有効128 tokensのcandidate-request、各threadで独立2セッション、各1 warmup＋3測定。順序は4→8、8→4。各thread n=6、nearest-rank p95は観測最大である。子planを包含するtop-level wall timeであり、CPU時間ではない。

| 計測ありの項目 | 4 threads 中央値／p95 | 8 threads 中央値／p95 |
| --- | --- | --- |
| forward全体 | 8.722／9.159秒 | 8.810／9.405秒 |
| OptMatMul（4,213 calls） | 3.262／3.483秒 | 3.295／3.353秒 |
| ScatterElements（144 calls） | 2.024／2.047秒 | 2.021／2.120秒 |
| MoveAxis（378 calls） | 1.342／1.409秒 | 1.289／1.579秒 |
| Trilu（18 calls） | 0.786／0.813秒 | 0.761／0.830秒 |
| OptMatMulPack（6,265 calls） | 0.520／0.543秒 | 0.516／0.565秒 |
| Slice（4,890 calls） | 0.169／0.173秒 | 0.164／0.230秒 |
| process Peak Working Set最大（n=2） | 3.0516 GiB | 3.0520 GiB |

operator時間／plan時間をforwardごとに計算した比率の中央値は、4／8-threadでOptMatMul 37.31／36.65%、ScatterElements 22.72／22.80%、MoveAxis 15.40／14.94%、Trilu 8.82／8.81%。中央値の行を単純加算して1回の実行内訳にはしない。8-threadが4-threadより安定して速い根拠は今回も得られていない。

計測あり／なしを同じblockで比較しておらず、今回のforward時間と前回の通常forwardからprofile overheadや性能変化を推定しない。前回の1-thread内訳との比較も同時対照実験ではない。今回の目的は多スレッド構成で残る主要operatorの特定である。

両executorの4 golden gateを計測前に再実行した。全6 process・24 forward（gate／warmup込み）が成功し、対照raw logitsとの差は0、goldenとの最大確率差は`4.9173831939697266e-6`。判断・token数も一致。timeout／memory guard発火0。guardは各process600秒、min(8 GiB,物理RAMの50%)で、private RSSの厳密上限ではない。

## ノード由来と形状の監査

正規化ONNX `4808e28131967e8ed33f8b50d46c4212e11c19b79e6dfb5209cf9b6931cd9b0c` を外部重みなしで読み、保存済みmetadataだけを取得した。shape inferenceや名前のあいまい検索は行わない。[監査結果](research/jeff-onnx-tract/thread-profile-2026-10-11/onnx-provenance.json)には、測定top30の和集合72ノード中、完全一致56・未対応16を残した。完全一致はMatMul 30、Trilu 18、ScatterElements 8。未対応はoptimizerが生成した名前等で、推測でONNXへ結び付けない。

| ONNX上の宣言 | ノード数 | 保存されたdata形状・属性 |
| --- | ---: | --- |
| ScatterElements | 144 | FP32 `[1,16,8,64,128]`、axis=2、reduction=none |
| ScatterElements | 4 | FP32 `[3,1,512,32]`、axis=0、reduction=none |
| Trilu | 18 | FP32 `[1,16,8,64,64]`、upper=0 |
| Trilu | 18 | BOOL `[64,64]`、upper=1 |
| Transpose | 537 | 複数の形状・perm。全個別metadataを証跡へ保存 |

完全一致したTrilu 18件はいずれも上表のFP32 lower側、ScatterElements 8件はいずれもaxis=2側だった。ONNXの全ノード数と実行時call数は同一ではない。残りのfold／融合等をこのmetadataだけで断定しない。Scatterのindices／updatesは保存shapeが欠けるものがあり、実値・一意性・contiguous性は未確認。`None`は不明として保持し、scalarや固定shapeを補わない。

## 実装調査と最小候補

固定Tractの原本を読み、hashとlicense付きで証跡へ保存した。

- ScatterElementsはupdatesの`indexed_iter`を逐次走査し、各座標のindicesを読んで代入する。Noneとreduction付き経路が別で、負indexも扱う。現状の約2秒にはcopy・index参照・代入等が含まれ、各寄与は未分離。
- Triluは全座標を列挙し、row／colの条件で`T::default()`を書き込む。contiguousな行の消去領域をまとめてfillする経路が最小候補となる。
- MoveAxisはAxisOpからTensorの軸並べ替え経路へ入り、ndarrayの並べ替えとTensor変換を使う。共有ownershipによるclone、layout変換、copyの寄与は今回の計時だけでは分離できない。

次の単一変更実験は**Triluのcontiguous行fill**を優先する。Scatterより小さい範囲で、lower／upperとdiagonal境界の意味を独立検証できるためである。通常probeやNativeへ直接適用せず、新しい生成tree／Cargo targetとする。非標準layoutは既存経路へ戻し、空形状・長方形・batch・正負k・境界・dtypeの意味を検証する。整数境界の扱いを性能変更と混ぜず、変更範囲を明示する。

4-threadの固定対照と候補に同じ4件gateを実行し、計測なしのAB／BA・独立複数セッションで比較する。raw logits／確率／判断を維持し、両順序で改善が再現しなければ不採用とする。Triluの観測約0.8秒はそのまま削除可能時間ではなく、速度倍率は試作測定後にだけ判断する。

ScatterElementsのbulk copyや並列化は、その後の候補とする。indicesの実値、重複時の順序、reduction、負index、updates layoutを先に固定する。MoveAxisの変更はdata crateへ及ぶため、Tensor ownershipとlayoutの監査後に分離する。専用DeltaNet kernel・量子化・batchはまだ実装しない。

## 検証と未受入

Python小型回帰27試験がskip 0で合格した。由来監査では完全一致／未対応の区別、欠けたmetadata、unknown rankとscalarの区別、重複名の拒否を試験した。raw JSONLを別途検証し、operatorのn／中央値／p95／比率／call数を再集計した。Rust build・runtime依存・CI設定は今回変更していない。GitHub上のCI実行は確認していない。

Native／公開API／Decision Reportは不変。正式なPhase 3、同形状・保持dtype・thread条件でのNative比較、Tokenizer／API E2E、入力長matrix、SLO、実OCR/ASR品質は引き続き未受入。今回のdiagnosticから認識品質の改善やNativeへの優位性は判定しない。
