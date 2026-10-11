# pure-jeffで加えたTractの変更

ここのTractは**upstreamそのままではない**。基準はsonos/tract commit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a`（0.23.8）。結果を引用するときは、どの変更を含む版かを明記し、upstream版の性能・互換性として扱わない。いずれもupstreamへは投稿していない。

各patchは、upstreamとの差分を読むための記録（改行をLFにそろえたunified diff）。正本は、変更を生成する`runtime/onnx/prepare_*.py`と、vendorした`runtime/tract/vendor/data`である。`python tools/check_tract_experiments.py --upstream <checkout> --work <dir> --patches`で、生成した木が当時の証跡（`generation.json`）とbyte単位で一致し、patchとも一致することを確かめる。

| patch | 使う場所 | 内容 | 判定 |
| --- | --- | --- | --- |
| [data-i64-tdim.patch](data-i64-tdim.patch) | `runtime/tract`（probe・bench・pack）と下記すべて | I64→TDimのcastでi32を経由せず64bitのまま変換（ONNX Sliceの`INT64_MAX`が-1になる不具合）。9行 | Jeff全体の型推論・forwardに必要。数値gate合格 |
| [duplicate-search-removal.patch](duplicate-search-removal.patch) | 生成実験（`prepare_duplicate_experiment.py --remove-duplicate-search`）以降の受入系列 | `ModelPatch::apply`の重複node探索を削除。最適化の起動時間を短縮 | 局所受入（起動49.7→19.3秒、数値一致） |
| [trilu-rows.patch](trilu-rows.patch) | `prepare_trilu_experiment.py` | 上記＋Triluを行単位の連続書き込みに（条件外は元の処理） | 局所受入（4 thread） |
| [scatter-rows.patch](scatter-rows.patch) | `prepare_scatter_experiment.py`（受入済みの最終版） | 上記＋ScatterElements（reduction=None）の行単位copy（条件外は元の処理） | 局所受入（4 thread） |
| [name-index.patch](name-index.patch) | `prepare_name_experiment.py` | node名のsuffix探索を索引化 | **不採用**（遅くなった） |
| [driver-timers.patch](driver-timers.patch) | `prepare_driver_profile.py` | 計時点の追加のみ（algorithmは変えない） | 診断用 |

このほか生成実験は、`tract-linalg/multithread-mm` featureと1／2／4／8 threadのexecutorを使う（`prepare_forward_experiment.py`、lockは`runtime/tract-driver-profile/forward.Cargo.lock`）。`runtime/tract`のprobe自体は`data`の修正だけを含み、最適化は既定の経路から`ChangeAxes`を1つ除く`run-no-change-axes`を明示したときだけ変わる（標準の最適化はCumSumのScan bodyで失敗する）。

結果の数値と判定は[docs/onnx-tract-progress.md](../../../docs/onnx-tract-progress.md)と各実験の文書にある。
