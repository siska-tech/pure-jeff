# 実装着手後の証跡

[進捗本文](../../../onnx-tract-progress.md)。以下は性能benchmarkではなく保全・数値一致・importerの判定結果である。

| ファイル | 内容 |
| --- | --- |
| `phase0.json` | 128保全コピー／113 Git blobのhash照合、基準commit、既存52試験の集計 |
| `native-regression.json` / `native-checks.log` | 7実forwardの回帰と既存試験log |
| `sibling-core-index.json` | adapterが使用するKazeNhanh coreの実作業ツリーhash。コピー本体はignoredなruns配下 |
| `padding.json` | 系列B、同checkpointの無padding／左512 padding比較、raw logitsを含む |
| `current-patch-gate.json` | export用DeltaNet置換と公式padded出力の比較 |
| `current-export.json` | step1113再exportの資産hash、checker結果。記録された秒数は開発用export時間 |
| `current-export-wrapper-executed.py` | 実行時wrapperのbytes。patch-gate内のwrapper hashと一致。現行toolには追加の入力検査がある |
| `current-oracle.json` | 系列C、CPU専用ONNX oracleと公式／patch／goldenの4件比較 |
| `current-normalization.json` | 同再exportのsequence限定変換、checker成功、入出力graph hash |
| `current-tract-original-type.json` / `current-tract-normalized-type.json` | 同checkpointの原本／sequence変換版のSlice型推論失敗 |
| `public-checker.json` | 公開step960の原本／sequence変換版checker成功。外部重み取得・hash照合後の実行 |
| `public-normalization.json` | 先行変換時のcheckerアクセス拒否を含む元記録。後続checker成功で上書きしていない |
| `public-batch-normalized.json` | 公開版のbatch記号を具体化したgraphのhash、checker成功 |
| `public-tract-*.json` | 公開版のdynamic batch衝突、batch=1後のSlice衝突、sequence変換後も同じ失敗 |
| `public-slice-metadata-repro.onnx` | 公開graphから抽出した14ノード・重みなしの再現例（Apache-2.0、toolingのNOTICEを参照） |
| `public-slice-repro-tract.json` / `public-slice-repro-oracle.json` | 同再現例のTract失敗、ONNX full checkerとCPU oracleの成功 |
| `tract-dependencies.json` | 固定TractのWindows依存103 package、license宣言・本文hash・build script・PE imports。配布承認ではない |
| `tool-tests.log` | sequence／batch変換と小型Tract forwardの追加10試験成功 |
| `file-index.json` | このディレクトリの証跡hashとサイズ |

公開モデル（step960）と現行モデル（step1113）は比較系列を分離した。現行モデルから再exportできたため、モデル差を混ぜない数値照合が可能になった。Tract全体forward、変換後Jeff全体のoracle一致、速度、Peak Working Set、品質・配布受入はまだ確認していない。

Tract実行ファイルは実験中のCLI追加により複数のhashがある。各記録は実際に使ったexeとharnessのhashを保持する。rawのCLI経過時間は中央値・p95・反復数を伴う測定ではない。
