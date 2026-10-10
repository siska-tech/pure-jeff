# Jeff ONNX / Tract互換性マトリクス

2026-10-10。**静的な演算子調査では解決候補を絞れたが、Tractでの実モデル実行は未確認。現行checkpointとの同一性も成立していない。** [実装計画](onnx-tract-plan.md)へ戻る。

## 調査対象と証拠の強さ

| 対象 | 固定revision / 出典 | 今回確認した範囲 |
| --- | --- | --- |
| 現行Jeff | `jeff-legacy/Jeff-Qwen3.5-0.8B@51552f39a943d62e8387c4ea5e17026a1408729f` | 手元の11資産とconfig、既存golden、hash索引 |
| 公開ONNX | `Zatsepin/jeff-qwen3.5-0.8b-onnx@e42ca8299574aed4981d711d1c29ad66674ff4b1` | API metadata、設定、LICENSE、239 MBの実graph。外部dataは未取得 |
| exporter | `Partysun/jigor@cbd9a629f1a3d9b6829399f6f88bd3363693f9bb` | `scripts/jeff/export_onnx.py`のコードを取得・読解。実行なし。配布ONNXを実際に生成したcommitとの一致は未証明 |
| Tract release | v0.23.8 = `9e0cfaa9b3a9251f41f74101801dc2c937b1660a` | 公式tag APIを確認し、既存local Git objectを`git show`して登録表・loaderを監査 |
| ローカルTract | `ff1741fd1f617997d1cc3ccd2c3e9e52a3737688`、`x86-depthwise` branch | 作業ツリーclean。ただしreleaseと別なので採用版に混ぜない |
| pure-onnx-ocr | `59a6c2c33c72e4dc8e7e5500f544d6674b0e6643` | sourceとlockを確認。lock上Tract 0.23.8。OCRの実測値をJeffの予測に流用しない |

ONNX graphのSHA-256は`4e38fcec2ed74ad6daebd345d8e10bff8bd4534cf428066c1f7f8ea847072a24`で、Hugging FaceのLFS metadataと取得bytesが一致した。外部dataの公表hashは`3635efce97cd5f0964c58e58e9fe40df28bde8647c4ecb927a121475af32cbf3`（未ダウンロードなのでbytes照合は未実施）。[API記録](research/jeff-onnx-tract/hf-metadata.json)

解析は[stdlibのみの調査helper](research/jeff-onnx-tract/inspect_assets.py)でONNX protobufの必要fieldを読み取った。ONNX checker、shape inference、Tract importer実行の代用ではない。field番号はTractに同梱されたONNX schemaを参照。解析JSONは[全ノード集計](research/jeff-onnx-tract/onnx-static-inventory.json)に保存。

## checkpoint・入出力

| 項目 | 現行Native | 公開ONNX | 判定と次の確認 |
| --- | --- | --- | --- |
| 学習step | 1113 | 960 | 異なるcheckpoint provenance。runtime差の比較として扱わない |
| training run | `0.8b-20260929-2258` | `0.8b-20260928-0540` | train digestも異なる。元重みtensorの照合/再exportが必要 |
| base model revision | `2fc06364715b967f1860aea9cf38778875588b17` | 同じ | baseが同じでも学習済みモデル同一とはならない |
| temperature | 1.0845714325759162 | 0.9629933669102758 | 差あり。ONNX側へ現行値を上書きして同一モデルに見せない |
| codes/token_ids | 255 codes | 全要素一致 | 互換。回答code数と入力長上限は別制約 |
| tokenizer | 固定JSON | LFS SHAが現行bytesと一致 | tokenizer本体はmetadata照合。公開本体の再取得は省略 |
| chat template / processor / tokenizer config | 固定bytes | 取得bytesのSHAがすべて一致 | 構築するprompt bytes・encode設定も実装側で一致検査 |
| prompt layout | state-first | state-first | 相互互換の候補。question/candidate-ID表記はKazeJudge仕様を維持 |
| token長 | 可変、上限8192 | 静的512 | drop-in置換不可。長文3 goldenは未対応として拒否 |
| batch | 1 | symbolic `batch` | 最初はB=1に固定。B>1は後段の別評価 |
| graph入力 | unpadded u32 IDs、mask不要の専用処理 | `input_ids` / `attention_mask` / `mm_token_type_ids`、すべてINT64 `[B,512]` | 3本すべて供給。name/順序/dtype/shapeを固定 |
| padding | なし | 左pad、右端は実token | pad IDを設定から取得。maskを左0/実token1にする |
| mm入力/position | text-onlyの専用RoPE | graph内の処理 | exporterのexport例は実token mm=2、pad mm=0、check例ではpad mm=2。この差を無視せず、固定公式processorとgraphで正しい規則を検証 |
| head | hidden最終位置→別readout | graph終端Gemmで`readout.weight [255,1024]` | graph出力はFP32 `[B,255]` raw logits。softmax済みではない |
| temperature/候補mask | Rust readoutが実施 | caller側で実施 | headの後に1回だけ適用。末尾N以降mask→temperature→softmaxの順序を維持 |
| weight dtype | 主にBF16格納、FP32計算 | initializer 322個がすべてFLOAT | FP32化の出典確認。モデル同一性や数値一致をdtypeだけでは証明しない |

[設定比較JSON](research/jeff-onnx-tract/checkpoint-comparison.json)、[固定ONNX設定](https://huggingface.co/Zatsepin/jeff-qwen3.5-0.8b-onnx/blob/e42ca8299574aed4981d711d1c29ad66674ff4b1/decision_config.json)、[exporter](https://github.com/Partysun/jigor/blob/cbd9a629f1a3d9b6829399f6f88bd3363693f9bb/scripts/jeff/export_onnx.py)を根拠とする。

公開cardは確率差約1e-3を報告するが、今回その結果を再現しておらず、KazeJudgeの7ケースや同checkpointの結果でもない。現行1e-4基準を満たす証拠にはならない。FP32/BF16差を理由に丸め差を「bit-exact」と扱うこともしない。[公開model card](https://huggingface.co/Zatsepin/jeff-qwen3.5-0.8b-onnx)

## 演算子とTract importer

実graphはIR version 10、default ONNX domainのopset 18のみ。producer metadataは`pytorch 2.14.0+cu130`（実行deviceの証明ではない）。graph 1個、local function 0、ノード113,333個、48種類。全113,333ノードが出力logitsへの依存経路にある。全48種類の件数・登録先は[演算子一覧](research/jeff-onnx-tract/operators.md)。

| 演算群 | 静的結果 / Tract 0.23.8 | 評価 |
| --- | --- | --- |
| SplitToSequence (24) / SequenceAt (66) | importer未登録。未登録nodeはUnimplementedOpになる | **原graphの実行を妨げる既知の問題**。定数分割/indexだけをSplit/Sliceへlowerする案 |
| MatMul (3097) / Gemm (1) | 登録あり | 高rank/broadcast、transpose、packing、headの属性を実shapeで検証 |
| CumSum (18) | 登録あり、typed段階でTract内部Scanへlower | 軸が定数である必要。chunk内の累積decayの数値・性能を確認 |
| Trilu (36) | 登録あり | upper/kの意味、非finite mask、rankを検証 |
| ScatterND (148) / ScatterElements (148) | 登録あり | 更新index、reduction、copyとaliasの挙動・メモリを検証 |
| Conv (18) | 登録あり | linear attentionのdepthwise Conv1D：group/shape/pad/strideを検証 |
| ReduceMean (79) / ReduceSum (36)、Pow/Sqrt/Reciprocal | 登録あり | RMS/L2のepsilon・演算順・FP32蓄積誤差を確認 |
| Softmax (6) | 登録あり | full attention内部。出力255 logitsへのsoftmaxとは別 |
| Cast (24407) / CastLike (2617) / Reshape (24931) / Constant (34258) | 登録あり | graph膨張・定数化・解析時間の候補。ノード数とCPU時間は比例すると仮定しない |
| Slice/Concat/Expand/Gather/GatherND/Shape/Range等 | 登録あり | dynamic batch由来shape式、負軸、空tensor、INT64計算を確認 |
| 算術・比較・Where、Sigmoid/Softplus、Sin/Cos等 | 登録あり | overflow/NaN、bool broadcast、RoPE精度を検証 |
| Loop / ONNX Scan / 専用GatedDeltaNet | 実graphにはない | 「ONNX Loop未対応だからDeltaNet不可」という判定は誤り |

登録の根拠は[固定版opsソース](https://github.com/sonos/tract/tree/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops)、未知op処理は[model.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/model.rs)。演算子名が登録されている46種類についても、今回実行成功を認定していない。

### Gated DeltaNet

取得したexporterは64-token chunk単位の再帰を固定長で展開し、三角系の処理をblock単位のMatMul/Concat/Sliceへ置き換える。512では8 chunks。実graphで専用custom opやLoopがないことと整合するが、取得したexporter版が当該配布graphの生成に使われたことまでは証明できていない。

数学上の等価性とFP32の丸め差は分ける。同checkpointで公式の逐次/既存chunk処理、exporterの置換処理、ONNX参照実行、Tractを比較し、最初に差が出るlayer/chunkを特定する。近似Neumann系列など別演算を高速化目的で無断採用しない。1e-4を超える場合は最終分布だけでなくhidden、raw logits、temperature前後を調査する。

### Sequence正規化の具体的な範囲

18個はaxis=-1、split長`[2048,2048,2048]`。6個はscalar split幅256。66個のSequenceAt indexはすべて定数0/1/2（それぞれ24/24/18個）。これらの入力・attributes・定数と出力到達性は[JSONのsequence_nodes](research/jeff-onnx-tract/onnx-static-inventory.json)に保存した。

データtensor自体を変えず分割結果を直接tensor出力にする変換が候補。scalar/vector splitの意味、最後の短いslice、axis正規化、keepdims、consumer対応を検証し、条件外なら変換失敗にする。一般sequence型サポートを新設するより狭い変更で検証できる可能性があるが、まだ変換・実行はしていない。

## 外部重み・メモリ・NNEF

| 項目 | 確認結果 | 実装条件 |
| --- | --- | --- |
| graphサイズ | 239,145,817 bytes | protobuf parse/shape metadataの時間・peakも計測 |
| external data | 3,010,658,304 bytes（API値） | 取得後に公表SHAと全bytesを検証 |
| graph＋data | 3,249,804,121 bytes（約3.25 GB / 3.03 GiB） | tokenizer等を除いたサイズ。runtimeメモリ推計とは区別 |
| external initializer | 285個、locationはすべて`model.onnx.data` | 各offset+length、alignment、dtype/shape、重複/欠落を検査 |
| 最大offset+length | 3,010,658,304、metadataのfile長と一致 | 宣言整合のみ確認。実ファイル内容は未確認 |
| loader | Tractにlocation/offset/length resolverがある | path-based loadかmodel directoryを持つresolverを使用 |
| memory | resolverはmmapからVecにコピーしTensorを作る経路 | zero-copyとは扱わない。inference/optimized/packed plan共存時のpeakを測る |
| path保護 | 0.23.8には絶対path/`..`を拒否する検査 | KazeJudge側でもcanonical path、symlink/reparse、file集合、hash、不変性を検証 |
| NNEF | Tractの事前変換形式の候補 | import成立後にround-tripとregistry/versionを固定。未対応sequenceの解決を省略しない |

[外部tensor loader](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/tensor.rs)、[resolver](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/data_resolver.rs)。

## 採用版・依存・ライセンス

PoC第一候補は公式0.23.8を厳密固定し、`tract-onnx`はdefault featuresを切って必要分だけ検討する。実graphには専用Attention opがないため、初期にtransformers featureを有効にする根拠はない。MatMul並列は`tract-linalg/multithread-mm`を明示した別条件で測る。[固定Cargo manifest](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/Cargo.toml)

ローカルCargo cache内の0.23.8はVCS情報にdirty表示があり、公式release commitとも異なったため、この調査の互換性根拠には使わず公式releaseのGit objectを読んだ。実装時は新しい隔離したCargo home/targetで公式source・checksum・lock・feature graphを固定する。mainや隣接forkを評価する場合は比較対象を増やした別recordにする。

TractのWindows x86_64 buildは内部ASMを`ml64.exe`で組み立て、静的ライブラリをlinkする。Python/ORT DLL不要という条件と、全sourceがRustのみという条件は区別する。buildで使うassemblerは実行時依存ではないが、Pure Rustの依存監査から省略しない。[build.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/linalg/build.rs)

公開ONNXにはApache-2.0のLICENSE本文がある。Tract crateはMIT OR Apache-2.0、pure-onnx-ocrはApache-2.0。現行Jeff参照sourceのMIT、checkpoint/base modelのLICENSE/NOTICE、jigorからコードを取り込む場合のApache-2.0、変更したexporter/graphの出典を個別に保持する。公開モデルcardの一括表記を既存sourceのlicenseへ上書きしない。適合性の法的判断や配布受入は今回の範囲外。
