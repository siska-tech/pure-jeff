# pure-jeff

Python・PyTorchを使わず、Rustだけで[Jeff](https://github.com/firelex/jeff)の候補判断（decision model）を実行する実装。CPUのNative実行と、ブラウザ内のWebAssembly実行がある。

*Pure-Rust (Candle) inference for the Jeff-Qwen3.5-0.8B decision model, as a native CPU worker and in the browser via WebAssembly, verified against the official Python implementation. Not affiliated with the Jeff authors.*

> 本プロジェクトは本家Jeff・Qwenとは無関係の非公式実装です。

## 何ができるか

原文と候補（2〜255件）を渡すと、候補内の分布と、選択（selected）または保留（abstained）を返す。分布は渡した候補の中での比較であり、認識の正解率ではない。

| 系統 | 内容 | 検証 |
| --- | --- | --- |
| Native（`runtime/rust`） | `jeff.exe`。1要求ごとの子processとして動き、期限を超えると親がkillする。bundleのhashを照合してから実行する | 公式参照7件（最大8192 tokens、255候補）で判断が一致。確率差は最大5.066e-6 |
| ブラウザWasm（`runtime/wasm`） | Web Worker内の推論。single-thread、SIMD128 | Chrome／Edgeで128〜512 tokens、2〜8候補の12件が一致。最大2.38e-6 |
| Webデモ（`apps/web-demo`） | ブラウザだけで、モデルの取得・保存・削除、判断、取消、JSON保存。**https://pure-jeff.siska-tech.workers.dev** | 公開サイトに対するChrome／EdgeのE2Eに合格（[公開の記録](docs/web-demo-deployment-2026-10-12.md)）。モデルはHugging Faceから直接取得する |

対象は固定checkpoint（`jeff-legacy/Jeff-Qwen3.5-0.8B` revision `51552f39…`）、text-only、batch 1。検証は人工データで行い、日本語OCR／ASRの認識品質は評価していない。

公式Jeffとの1 threadの比較（[結果](docs/benchmark-results-2026-10-11.md)）：

- 1要求ごとに起動する場合、Nativeは公式Jeffの1.65〜2.78倍速く、メモリは半分以下。
- モデルを常駐させると、公式Jeff（PyTorch）の方が速く、Nativeの0.51〜0.66倍の時間で判断する。Nativeの改善案は[計画](docs/native-fp32-retention-plan.md)にある。

## 必要なもの

- Rust 1.99.0（`rust-toolchain`は固定していない。CIは1.99.0を使う）。Wasmには`wasm32-unknown-unknown` target
- Windows x86_64で検証している。ほかのOSは未検証
- モデル（約1.73 GB）：`tools/fetch_model.py`で取得する
- 公式Jeffとの照合やbenchmarkをする場合だけ：固定commitのJeff sourceとPython環境（[手順](docs/jeff-runtime.md)）

## 使い方

```powershell
# 1. モデルを取得し、11ファイルのSHA-256を照合する（Python 3.12以上、標準ライブラリのみ）
python tools/fetch_model.py

# 2. Native workerをbuildし、このbuildに対応するbundle manifestを作る
cargo build --locked --release --manifest-path runtime/rust/Cargo.toml
runtime/rust/target/release/jeff.exe lock models/jeff-checkpoint models/jeff-rust-bundle.json 51552f39a943d62e8387c4ea5e17026a1408729f 0.7 0.1 1

# 3. 公式参照（golden）6件と照合する
python runtime/validate_migration_cases.py --executable runtime/rust/target/release/jeff.exe --manifest models/jeff-rust-bundle.json --output experiments/runs/golden.json
```

bundle manifestは、runtimeのsourceから計算したbuild hashを固定する。runtimeや契約crateを変えたら`jeff lock`で作り直す。0.7／0.1は選択・保留の閾値の例で、推奨値ではない。1要求の実行やprocess境界は[Rust実行手順](runtime/rust/README.md)、Wasmは[runtime/wasm](runtime/wasm/README.md)、デモは[apps/web-demo](apps/web-demo/README.md)を参照。

## 試験

```powershell
cargo test --locked                                  # 判断契約（process試験はKAZE_JUDGE_PYTHONが必要）
cargo test --locked --manifest-path runtime/rust/Cargo.toml
cargo test --locked --manifest-path runtime/wasm/Cargo.toml
cargo test --locked --manifest-path apps/web-demo/engine/Cargo.toml
python -m unittest discover -s runtime -p "test_*.py"
```

CI（`.github/workflows/ci.yml`）は、これらに加えてclippy・fmt、Native release build、Wasm build、ライセンス監査を行う。モデルを使う照合は、ダウンロード量が大きいためCIに含めない。clone・build・モデル取得・goldenの照合を一度に行うには`bash tools/clean_check.sh <repository> <workdir>`を使う（[記録](docs/clean-environment-check.md)）。

## 構成

```
Cargo.toml, src/, tests/   判断契約crate（kaze_judge）：要求・結果の型と検証
runtime/rust/              Native実行（worker、bundle検証、tokenizer、backbone、readout、policy）
runtime/wasm/              ブラウザ用probe。凍結したNative sourceをhashで固定して再利用する
apps/web-demo/             Webデモ（Wasm engine、静的ページ、build・配信・E2E script）
runtime/*.py               公式Jeffの参照worker、参照出力の採取、照合、package用の開発tool
tools/                     モデル取得、ライセンス監査
tests/fixtures/            公式参照（golden）と要求
bench/                     公式Jeff・Native・Wasmの比較benchmark
docs/                      計画、結果、検証記録と証跡（docs/README.md）
```

crate名とschema名に残る`kaze_judge`は、このコードがKazeJudge（判断契約を利用する側のproject）から切り出されたことによる。改名すると既存のAPI、hash固定、検証証跡が変わるため、そのままにしている。

## 出典

- 本家Jeff（MIT）、Jeffの重み（Apache-2.0）、Qwen3.5-0.8B（Apache-2.0）、依存crate：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 切り出し元：KazeJudge commit `885e7ff`。複製したファイルとhashは[PROVENANCE.json](PROVENANCE.json)

## ライセンス

[Apache License 2.0](LICENSE)。帰属表示は[NOTICE](NOTICE)と[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)にある。モデルの重みは含まず、重み自身のLICENSE（Apache-2.0）とNOTICEに従う。ライセンス監査の記録は[docs/licensing.md](docs/licensing.md)。
