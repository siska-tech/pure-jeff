# ONNX＋Tract計画の調査証跡

2026-10-10。[計画本文](../../onnx-tract-plan.md)、[互換性](../../onnx-tract-compatibility.md)、[ベンチマーク仕様](../../onnx-tract-benchmark-plan.md)。

| ファイル | 内容 |
| --- | --- |
| `native-baseline.json` | 既存128ファイルのbytes/SHA-256。source/tests/CI/既存docs/モデル/参照exeを含む。実装版のバックアップではない |
| `hf-metadata.json` | Hugging Face公開APIの取得結果。repo revision、サイズ、LFS SHAを含む |
| `checkpoint-comparison.json` | 現行と公開ONNXのconfig/provenance/hash比較、exporterの固定revision/hash |
| `onnx-static-inventory.json` | 実ONNXのopset、I/O、48 op件数、attributes、外部tensor宣言、sequence定数・到達性、Tract登録先 |
| `operators.md` | 全48演算子の可読一覧 |
| `inspect_assets.py` | 上記の静的解析を再生成する開発用stdlib helper。モデル推論は行わない |
| `validation.json` | 文書の相対リンク、JSON内部集計、baseline不変性の最終確認結果 |

## 入力と再確認

取得した入力はgitignore対象の `experiments/runs/onnx-tract-analysis/` に置いた。`model.onnx`は239,145,817 bytes。graphのhashはAPIのLFS SHAと一致。`model.onnx.data`の3,010,658,304 bytesは取得していない。

取得先は以下の固定資産。helperはこれらを読むだけで、外部コードをimport/実行しない。

- [ONNXモデルの固定版](https://huggingface.co/Zatsepin/jeff-qwen3.5-0.8b-onnx/tree/e42ca8299574aed4981d711d1c29ad66674ff4b1)：`model.onnx`、`decision_config.json`、`chat_template.jinja`、`processor_config.json`、`tokenizer_config.json`、`LICENSE`、`README.md`。
- [exporter固定source](https://github.com/Partysun/jigor/blob/cbd9a629f1a3d9b6829399f6f88bd3363693f9bb/scripts/jeff/export_onnx.py)：読むために取得したPythonファイル。実行していない。
- [Tract 0.23.8固定source](https://github.com/sonos/tract/tree/9e0cfaa9b3a9251f41f74101801dc2c937b1660a)：helperは隣接`../tract`のGit objectを`git show`で読む。作業ツリーやglobal Git設定は変更しない。
- 現行`models/jeff-checkpoint/`のconfig/tokenizer類。Nativeの固定hashはbaseline索引と既存`docs/jeff-reference.json`を参照。

同じ入力を配置し、Tractの該当commit objectが読める環境で、rootから次を実行する。

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B docs/research/jeff-onnx-tract/inspect_assets.py
```

stdlibのみで動く別のPythonでもよい。これは開発時の調査helperであり、KazeJudgeの通常実行や配布へのPython依存を追加していない。公開runtime・Cargo dependencies・lockは未変更。

helperは解析JSON/演算子一覧を再生成する。新しいモデル版を調べる場合は過去の証跡を上書きせず、別ディレクトリへ結果を保存する。実装試作では正式なONNX checkerとTractでのload/type/optimize/runを追加し、この限定protobuf readerの結果だけで合格判定しない。

## 今回実行していないもの

TractBackend実装、ONNX再export、ONNX/Tractのモデルforward、性能benchmark、実OCR/ASR品質評価、Gitコミット、upstream投稿・公開。既存の52試験成功とportable smokeは同日の先行監査の記録であり、今回の静的調査で再実行した結果ではない。
