# clean環境での確認

2026-10-11。pure-jeffがKazeJudgeのファイルやPython環境に頼らずに、build・試験・数値再現できることを確認した。手順は`tools/clean_check.sh`にまとめた。

## 方法

- commit `8d26e83`を一時directoryへcloneした。空の`CARGO_HOME`を使い、crates.ioとCandleのgit依存を取得し直した。
- モデルは`tools/fetch_model.py`でHugging Faceの固定revision（`jeff-legacy/Jeff-Qwen3.5-0.8B` `51552f39…`）から取得した。11ファイルすべてのSHA-256が`tools/checkpoint.json`と一致した。
- Pythonはuvが管理するCPython 3.12.14（標準ライブラリのみ）。KazeJudgeのvenvは使っていない。
- Windows 11、Rust 1.99.0。

## 結果

| 確認 | 結果 |
| --- | --- |
| 契約crateの試験 | 11件合格。process試験4件は`KAZE_JUDGE_PYTHON`が未設定で失敗した。変数なしでもskipするよう試験を直した（`055e65c`）。`tools/clean_check.sh`は変数を設定して実行する |
| Native runtime | 試験12件合格、release build成功 |
| Wasm probe、デモengine | 試験合格。wasm32 buildはどちらも成功した（1回目は確認scriptが別名のtoolchainを指定したためtarget未導入で失敗し、既定のtoolchainで再実行した） |
| bundleのlock | manifestのSHA-256は`7de618cb…`。開発環境で作ったmanifestと同じで、runtimeのbuild hashはpathやmachineによらず再現した |
| 公式golden 6件 | 判断がすべて一致。確率差の最大は5.066e-6で、既存の記録（KazeJudge P3）と同じ。各caseの誤差も一致 |
| Python試験（標準ライブラリのみ） | 18件合格 |
| KazeJudgeへの参照 | 生成物にKazeJudgeのpathは現れなかった |

## 公式Jeff（Python）の参照環境

公式参照の再採取とbenchmarkには、公式JeffのPython環境が要る。pure-jeffでは、固定commitのJeff source（`vendor/jeff`、git管理外）の`uv.lock`から、`.venv/jeff-ref`へ作り直した。

```powershell
git clone https://github.com/firelex/jeff vendor/jeff
git -C vendor/jeff checkout 3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0
$env:UV_PROJECT_ENVIRONMENT = "$PWD/.venv/jeff-ref"
# Jeff sourceはuv 0.12.19以上を要求する。既存のuvを更新せずに、uvxで指定versionを使う
uvx --from "uv==0.12.19" uv sync --frozen --no-default-groups --no-install-project --python 3.12.14 --project vendor/jeff
```

この環境（torch 2.14.0+cpu、transformers 5.17.0）で`candidate-request`を公式workerで実行すると、goldenの確率と完全に一致した。Jeff sourceのcheckoutは変更されず、bundle検証のhashも保たれた。

## 残る差

- Wasmのbinaryは、build pathがpanic messageに入るため、cloneしたpathによってhashが変わる。数値と動作は試験で確認している。byte単位の再現が必要なら、`--remap-path-prefix`の導入を検討する。
- Windows以外のOSでは確認していない。
