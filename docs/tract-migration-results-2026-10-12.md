# ONNX／Tract移管後のpure-jeffでの再検証

2026-10-12。KazeJudge commit `ad59b25`から移したONNX／Tract資産を、pure-jeffの作業ツリーと環境だけでbuild・モデル生成・数値照合し、KazeJudgeの記録と比べた。[移管計画](tract-migration-plan.md)、[手順](tract-development.md)。

環境：Windows 11 Home x86_64、Rust 1.99.0、Python 3.12.14。公式Jeff参照環境は`.venv/jeff-ref`（torch 2.14.0+cpu、transformers 5.17.0、numpy 2.5.3）、ONNX tools はlockどおり（onnx 1.23.2、onnxruntime 1.31.0、onnxscript 0.7.2）。モデル・ONNX・実行ログは`experiments/runs/`（Git管理外）に置いた。

## 移管

| 項目 | 結果 |
| --- | --- |
| 履歴 | 対象pathに触れるKazeJudgeのcommit 33件を、`git filter-repo`で別cloneから抽出してmerge（`be56ecc`）。KazeJudgeのHEAD・作業ツリーは作業前と同じ |
| ファイル | 2,299件。うち584件は利用者名を含むローカルpathだけを`<user>`に置換。全履歴のblobに利用者名が残っていないことを確認 |
| hash | `tools/verify_tract_migration.py --source ../KazeJudge`：全件がKazeJudgeの原本（置換分は原本に同じ置換を施したbytes）と一致、失敗0 |
| 移管しないもの | kzn-datasetのOCR取込（KazeNhanhの監査）、KazeJudgeの`.venv`にある未追跡の補助scriptと凍結exe、他セッションの未コミットファイル、ONNX本体 |

## build・試験

| 対象 | 結果 |
| --- | --- |
| `runtime/tract`（新しい隔離Cargo homeでsonos/tract `9e0cfaa`を取得） | release build（2分51秒）、test 1件、clippy `-D warnings`、fmt：合格 |
| `runtime/bench-native`（pure-jeffの`kaze_judge`・`runtime/rust`にpath依存） | release build、clippy、fmt：合格。lockは変更なし |
| `runtime/onnx`のモデル不要試験 | 36件合格、8件skip（生成実験のexeを要する試験） |
| 最適化実験の再生成（`tools/check_tract_experiments.py --patches`） | 7件すべての`generation.json`がKazeJudgeの証跡とbyte単位で一致。upstreamとの差分patch 6件とも一致 |
| 既存CI相当（contract、Native、Wasm probe、Webデモengine、Python 33件、ライセンス監査`--strict`） | すべて合格。移管による変更なし |

## モデル生成と数値照合

| 段階 | pure-jeff | KazeJudgeの記録 |
| --- | --- | --- |
| 左512 padding（golden 4件） | 合格、最大確率差6.556510925292969e-7 | 同値 |
| DeltaNet置換（export前） | 合格、最大2.384185791015625e-7。`patch-gate.json`はmanifest・wrapperのhash以外同一 | 同値 |
| export（opset 18、batch 1、512） | 104秒、checker合格 | — |
| `model.onnx.data`（重み） | 3,010,658,304 bytes、`1b7c0e8a…a1afb1a5` | **同一hash** |
| `model.onnx`（graph） | 216,432,242 bytes、`7760b62b…5e064d` | 217,616,222 bytes、`6faa35aa…2d6725` |
| ORT oracle | golden比最大1.3113021850585938e-6、padded比最大1.7285346984863281e-6、判断一致 | 同値 |
| sequence正規化 | SplitToSequence 24／SequenceAt 66、checker合格、`e57de357…119eaa` | `4808e281…cd9b0c` |
| Tract `run-no-change-axes`（4件） | 合格。golden比最大4.9173831939697266e-6、oracle比最大4.649162292480469e-6、判断一致 | 同値。**raw logitsは4件ともKazeJudgeの証跡（`optimizer-2026-10-10/parity`）とbit単位で一致**（入力も同一） |

graphのhashが違うのは、ノードに付くexport時のmetadata（Python sourceの位置など、環境のpathに依存する情報）だけである。`doc_string`とmetadataを除いた2つのgraphはbyte単位で一致し、ノード数・演算・initializer・入出力・opsetも同じだった。

Nativeも公式goldenで再照合した（`runtime/validate_migration_cases.py`、6件）。実行ファイル・build hashは前回のpure-jeffでの照合と同一で、全項目が経過時間以外一致した（最大確率差5.066394805908203e-6、判断一致）。Native・Wasm・Webデモのsourceは今回変更していない。

## benchmark（参考）

`bench/tract_resident.py`、1 thread、warm-up 1巡＋計測2巡（各case n=2）。12回のforwardすべてでraw logitsが数値gateとbit単位で一致した。

| 項目 | 値 |
| --- | --- |
| 起動（load・type・最適化・plan） | 105.8秒 |
| warm forward中央値 | candidate-request 11.83秒、reversed 11.93秒、asr-unicode 12.02秒、special-token-text 11.97秒 |

このhostで1回測っただけの記述的な値である。直前に重い処理（build・試験）を走らせた後で、背景負荷・温度は制御していない。SLOや性能保証、KazeJudgeの記録との比較には使わない。

## 結論

- 移管した資産で、pure-jeffだけでbuild、モデル生成、数値gate、最適化実験の再生成、benchmarkができる。
- 数値はKazeJudgeの記録を再現した（Tractのraw logitsはbit単位で一致）。
- Tractは実験のままとし、既存APIのbackendには組み込まない（[統合の判断](tract-development.md#統合の判断)）。
