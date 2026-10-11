# ONNX／Tract経路（実験）

pure-jeffの3つ目の推論系統。Jeffのcheckpointを固定形状（batch 1、512 tokens）のONNXへexportし、[Tract](https://github.com/sonos/tract)で実行する。**実験扱いで、公開API・Native worker・Webデモには組み込んでいない**（理由は[統合の判断](#統合の判断)）。KazeJudgeから2026-10-12に移した（[移管計画](tract-migration-plan.md)、[pure-jeffでの再検証](tract-migration-results-2026-10-12.md)）。

ここのTractはupstreamそのままではない。I64→TDim castの修正（`runtime/tract/vendor/data`）を常に含み、最適化は`ChangeAxes`を1つ除いた経路（`run-no-change-axes`）だけが全体forwardを通る。性能実験はさらにcoreを変更した生成版を使う。差分は[runtime/tract/patches/](../runtime/tract/patches/README.md)。

## 構成

| path | 内容 |
| --- | --- |
| `runtime/onnx/` | ONNX export、sequence正規化、ORT参照（oracle）、Tract数値gate、KazeJudgeで使ったbenchmark・診断harness（Python、開発専用） |
| `runtime/onnx/upstream/` | jigorのexporter（Apache-2.0、未変更の複製） |
| `runtime/tract/` | probe（`kaze_judge_tract_probe.exe`：import／type／optimize／run）、`bench.exe`（常駐計測）、`pack.exe`（NNEF保存） |
| `runtime/tract-driver-profile/`、`runtime/onnx/prepare_*_experiment.py` | Tract coreを変更した最適化実験の生成元 |
| `runtime/bench-native/`、`runtime/native-retained/` | Nativeの計測wrapperと長さfixture生成、FP32重み保持実験 |
| `bench/tract_resident.py` | pure-jeff用の常駐benchmark |
| `tools/verify_tract_migration.py`、`tools/check_tract_experiments.py` | 移管したファイルのhash照合、最適化実験の再生成と証跡の照合 |

crate名・schema名・実行ファイル名に残る`kaze_judge`は移管元の名前。移管したscript・lock・生成元は、証跡に記録された自分自身のhashを照合したり（`generator_sha256`など）、互いのbytesを複製したりするため、名前を置き換えずに当時のbytesのまま残している。

## 準備

Windows x86_64、Rust 1.99.0、Python 3.12。公式Jeffの参照環境（`vendor/jeff`、`.venv/jeff-ref`）と`models/jeff-bundle.json`は[clean環境の確認](clean-environment-check.md)と[Jeff参照backend](jeff-runtime.md)の手順で用意する。移管した文書が`vendor/jeff/.venv/Scripts/python.exe`と書いている箇所は、pure-jeffでは`.venv/jeff-ref/Scripts/python.exe`に読み替える。

```powershell
# Tractは隔離したCargo homeで取得する（ほかのcheckoutの変更を混ぜない）
$env:CARGO_HOME = Join-Path $PWD '.venv/tract-cargo-home'
cargo build --locked --release --manifest-path runtime/tract/Cargo.toml
cargo test --locked --manifest-path runtime/tract/Cargo.toml
Remove-Item Env:CARGO_HOME

# ONNX tools（hash固定）。公式Jeffの環境とは別のdirectoryへ入れる
uv --cache-dir .venv/onnx-cache pip install --python .venv/jeff-ref/Scripts/python.exe --target .venv/onnx-tools --require-hashes --only-binary :all: -r runtime/onnx/requirements.lock
$env:PYTHONPATH = (Resolve-Path .venv/onnx-tools).Path
$py = '.venv/jeff-ref/Scripts/python.exe'

# モデル不要の回帰試験（生成実験のexeがない8件はskip）
$env:TRACT_PROBE = (Resolve-Path runtime/tract/target/release/kaze_judge_tract_probe.exe).Path
$env:TRACT_BENCH = (Resolve-Path runtime/tract/target/release/bench.exe).Path
$env:TRACT_PACK = (Resolve-Path runtime/tract/target/release/pack.exe).Path
& $py -B -m unittest discover -s runtime/onnx -p 'test_*.py'
```

## モデル生成と数値gate

出力先はすべて新しいdirectoryにする（既存の結果を上書きしない）。ONNX（約3.2 GB）はGitに入れない。

```powershell
$o = 'experiments/runs/tract'
& $py -B runtime/onnx/check_padding.py --manifest models/jeff-bundle.json --output $o/padding.json
& $py -X utf8 -B runtime/onnx/export_current.py --manifest models/jeff-bundle.json --padding-gate $o/padding.json --output-dir $o/onnx --export
& $py -B runtime/onnx/check_oracle.py --model $o/onnx/model.onnx --manifest models/jeff-bundle.json --padding-gate $o/padding.json --output $o/oracle.json
& $py -B runtime/onnx/normalize_sequences.py $o/onnx/model.onnx $o/onnx/model.normalized.onnx --report $o/onnx/normalization.json
& $py -B runtime/onnx/check_oracle.py --model $o/onnx/model.onnx --normalized-model $o/onnx/model.normalized.onnx --baseline-oracle $o/oracle.json --manifest models/jeff-bundle.json --padding-gate $o/padding.json --output $o/oracle-normalized.json
& $py -B runtime/onnx/check_tract.py --model $o/onnx/model.normalized.onnx --oracle $o/oracle-normalized.json --manifest models/jeff-bundle.json --padding-gate $o/padding.json --executable runtime/tract/target/release/kaze_judge_tract_probe.exe --output-dir $o/gate --stage run-no-change-axes
```

1. 左512 paddingが公式出力を変えないこと（golden 4件）。
2. exportは、DeltaNetの置換が公式と一致することを確かめてからONNX（opset 18、batch 1、512、raw logits）を書く。
3. ORT（CPU、1 thread、最適化なし）でgoldenと照合する。
4. `SplitToSequence`／`SequenceAt`をTractが扱える形へ置き換え、置換前後のORT出力を照合する。
5. Tractで4件を実行し、golden・ORTとの確率差が1e-4以内、判断が一致することを確かめる（`parity.json`）。

数値gateは確率差1e-4以内・判断一致。満たさない経路（`run-typed`以外の標準`run`は最適化で失敗する）を結果として扱わない。

## 最適化実験とupstreamとの差分

```powershell
$meta = cargo metadata --locked --manifest-path runtime/tract/Cargo.toml --format-version 1 | ConvertFrom-Json
$upstream = Split-Path (Split-Path (($meta.packages | Where-Object name -eq 'tract-core').manifest_path) -Parent) -Parent
python -B tools/check_tract_experiments.py --upstream $upstream --work .venv/tract-generation-check --patches
```

7つの生成実験（diagnostic timer、重複探索削除とその対照、名前索引、thread executor、Trilu、ScatterElements）が、当時の証跡の`generation.json`とbyte単位で一致し、`runtime/tract/patches/`とも一致することを確かめる。各実験のbuildと試験はCI（`.github/workflows/tract-probe.yml`）の手順に従う。

## benchmark

```powershell
python -B bench/tract_resident.py --bench runtime/tract/target/release/bench.exe --model $o/onnx/model.normalized.onnx --gate $o/gate --output experiments/runs/tract-bench --warmup 1 --samples 3
```

毎回のraw logitsが数値gateと完全一致しなければ失敗する。値はそのhostの記述的な記録で、SLOやほかの環境との比較には使わない。`runtime/onnx/benchmark_*.py`はKazeJudgeでの実験そのもので、当時のローカル実行directoryと実行ファイルのhashを参照するため、pure-jeffではそのままでは動かない（記録として残している）。文書・証跡にある過去の性能値は、当時のhostでの参考証跡である。

## 統合の判断

2026-10-12時点では、Tractを既存APIのoptional backendとして提供**しない**。数値の再現は確認できた（[再検証](tract-migration-results-2026-10-12.md)）が、次の条件を満たしていない。

| 条件 | 現状 |
| --- | --- |
| 公式golden全件（7件、最大8192 tokens・255候補）で判断一致 | 物理512 tokens固定のgraphのため、512以下の4件だけ。874／3206／8192 tokensの3件は入力できない。既存APIの上限（8192）を満たせない |
| upstreamのTractで動く | `data`の修正が必須。標準の最適化はCumSumのScan bodyで失敗し、`ChangeAxes`を除いた非標準の経路だけが通る。修正はupstreamに投稿していない |
| 既存のDecisionProvider／worker契約（期限、kill、bundle hash照合、異常応答） | 未実装。probe・benchは開発用CLIで、トークナイズ済み入力を受け取る |
| モデルの入手と配布 | 3.2 GBのONNXを、公式Jeff（PyTorch）環境でexportして作る必要がある。配布物・hash固定のmanifestがない |
| 性能上の利点 | 起動はNativeより大幅に長い（最適化・planの構築）。warmは、短文1 threadではNativeより遅く、共通512形状では中央値がNativeより短い記録とFP32保持Nativeより長い記録がある。process peakはFP32保持Nativeより低い記録がある（いずれも当時のhostの参考値で、形状・algorithmの条件が揃っていない） |

統合を再検討するには、少なくとも(1)可変長または8192 tokensまでの形状で公式golden全件の数値gateに合格すること、(2)使用するTractの版と差分を固定・公開できること、(3)既存のprocess境界・bundle照合と同等の契約試験、が必要。それまでは`runtime/tract`は実験であり、Nativeと混同して結果を引用しない。
