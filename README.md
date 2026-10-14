# pure-jeff

Python・PyTorchを使わず、Rustだけで[Jeff](https://github.com/firelex/jeff)の候補判断（decision model）を実行する実装。Rustから直接呼べるライブラリ（crate `pure-jeff`）、CPUのNative実行（CLI `jeff`）、ブラウザ内のWebAssembly実行がある。ONNX＋Tractによる実行も実験として含む。

*Pure-Rust (Candle) inference for the Jeff-Qwen3.5-0.8B decision model, as a Rust library, a native CPU worker and in the browser via WebAssembly, verified against the official Python implementation. Not affiliated with the Jeff authors.*

> 本プロジェクトは本家Jeff・Qwenとは無関係の非公式実装です。

## 何ができるか

原文と候補（2〜255件）を渡すと、候補内の分布と、選択（selected）または保留（abstained）を返す。分布は渡した候補の中での比較であり、認識の正解率ではない。

| 系統 | 内容 | 検証 |
| --- | --- | --- |
| ライブラリ（`pure-jeff`、`src/`） | `Model::load`でbundleを照合してモデルを常駐させ、`Model::decide`で判断する。[crates.io](https://crates.io/crates/pure-jeff)で公開（[API文書](https://docs.rs/pure-jeff)、[README.crate.md](README.crate.md)、変更履歴は[CHANGELOG.md](CHANGELOG.md)） | crates.ioの依存だけでbuildした利用者projectで、公式参照7件の判断・tokens数が一致。確率差は最大3.457e-6 |
| Native CLI（`runtime/rust`） | `jeff.exe`。1要求ごとの子processとして動き、期限を超えると親がkillする。bundleのhashを照合してから実行する | 公式参照7件（最大8192 tokens、255候補）で判断が一致。確率差は最大5.066e-6 |
| ブラウザWasm（`runtime/wasm`） | Web Worker内の推論。single-thread、SIMD128 | Chrome／Edgeで128〜512 tokens、2〜8候補の12件が一致。最大2.38e-6 |
| ONNX／Tract（`runtime/onnx`、`runtime/tract`）**実験** | 512 tokens固定のONNXへexportし、局所修正したTractで実行する開発用CLI。公開API・デモには組み込んでいない（[手順と判断](docs/tract-development.md)） | 公式参照のうち512 tokens以下の4件で判断が一致。最大4.917e-6 |
| Webデモ（`apps/web-demo`） | ブラウザだけで、モデルの取得・保存・削除、判断、取消、JSON保存。画面は日本語・英語・ベトナム語。**https://pure-jeff.siska-tech.workers.dev** | 公開サイトに対するChrome／EdgeのE2Eに合格（[公開の記録](docs/web-demo-deployment-2026-10-12.md)）。モデルはHugging Faceから直接取得する。公開中のサイトは0.2.0（commit `4572a8d`）からbuildしたもの。推論速度は[0.2.0の最終受入](docs/release-0.2.0-verification-2026-10-14.md)で記録した（128 tokensで約3.3秒、512 tokensで約12.6秒、基準機での値） |

対象は固定checkpoint（`jeff-legacy/Jeff-Qwen3.5-0.8B` revision `51552f39…`）、text-only、batch 1。検証は人工データで行い、日本語OCR／ASRの認識品質は評価していない。

公式Jeffとの1 threadの比較（[結果](docs/benchmark-results-2026-10-12.md)、[前回](docs/benchmark-results-2026-10-11.md)）：

- 1要求ごとに起動する場合、Nativeは公式Jeffの1.97〜3.02倍速く、メモリは3分の1以下（1.03 GiB対3.84 GiB）。
- モデルを常駐させると、公式Jeff（PyTorch）の方がまだ速く、Nativeの0.74〜0.94倍の時間で判断する（前回は0.51〜0.66倍）。Nativeのresidentのメモリは1.07 GiB、公式Jeffは3.82 GiB。
- 前回からの改善は、DeltaNetの逐次更新（[記録](docs/native-delta-recurrence-2026-10-12.md)）、要素ごとの演算（[記録](docs/native-elementwise-2026-10-12.md)）、重みの読込（[記録](docs/native-weight-load-2026-10-12.md)）の書き換えによる。どれも出力をbit単位で変えていない。Nativeのforwardは、今は行列積が6〜7割を占める。

## 必要なもの

- Rust 1.99.0（`rust-toolchain`は固定していない。CIは1.99.0を使う）。Wasmには`wasm32-unknown-unknown` target
- Windows x86_64で検証している。ほかのOSは未検証
- モデル（約1.73 GB）：`tools/fetch_model.py`で取得する
- 公式Jeffとの照合やbenchmarkをする場合だけ：固定commitのJeff sourceとPython環境（[手順](docs/jeff-runtime.md)）

## 使い方

```powershell
# 1. モデルを取得し、11ファイルのSHA-256を照合する（Python 3.12以上、標準ライブラリのみ）
python tools/fetch_model.py

# 2. CLIをbuildし、このbuildに対応するbundle manifestを作る
cargo build --locked --release --manifest-path runtime/rust/Cargo.toml
runtime/rust/target/release/jeff.exe lock models/jeff-checkpoint models/jeff-rust-bundle.json 51552f39a943d62e8387c4ea5e17026a1408729f 0.7 0.1 1

# 3. 公式参照（golden）6件と照合する
python runtime/validate_migration_cases.py --executable runtime/rust/target/release/jeff.exe --manifest models/jeff-rust-bundle.json --output experiments/runs/golden.json
```

bundle manifest（`pure_jeff.bundle.v1`）は、checkpoint 11ファイルのSHA-256、policy、promptの契約と、lockしたbuildのhashを記録する。CLIはbuild hashの一致も要求するので、ライブラリやCLIを変えたら`jeff lock`で作り直す。ライブラリはbuild hashの一致を既定では要求しない（`LoadOptions::require_runtime_build`）。0.7／0.1は選択・保留の閾値の例で、推奨値ではない。1要求の実行やprocess境界は[Rust実行手順](runtime/rust/README.md)、Wasmは[runtime/wasm](runtime/wasm/README.md)、デモは[apps/web-demo](apps/web-demo/README.md)を参照。

Rustから使う場合：

```rust
pure_jeff::configure_threads(1)?;  // bundleのpolicyと同じthread数。推論より前に1回
let model = pure_jeff::Model::load("models/jeff-rust-bundle.json", &Default::default())?;
let observation = model.decide(&request, limits)?;  // 候補内の分布と、選択／保留
```

詳しくは[README.crate.md](README.crate.md)とAPI文書（`cargo doc --open`）。リポジトリ内のbuildは、`[patch.crates-io]`で検証済みのCandle revisionを使う。公開crateはcrates.ioのCandle 0.11.0を使い、こちらも公式参照7件で照合した（[結果](docs/crate-release-results-2026-10-12.md)）。

## 試験

```powershell
cargo test --locked --all-features                   # ライブラリ（process試験はPURE_JEFF_PYTHONが必要）
cargo test --locked --manifest-path runtime/rust/Cargo.toml
cargo test --locked --manifest-path runtime/wasm/Cargo.toml
cargo test --locked --manifest-path apps/web-demo/engine/Cargo.toml
python -m unittest discover -s runtime -p "test_*.py"
python tools/check_package.py --work <新しいdirectory>   # crates.io用package、利用者projectからのbuild
```

CI（`.github/workflows/ci.yml`、WindowsとLinux）は、これらに加えてclippy・fmt、Native release build、Wasm build（host pathを含まないことも検査）、ライセンス監査、crates.io用packageの検査（`cargo publish --dry-run`と利用者projectのbuild）を行う。モデルの配信元（Hugging Face）は週1回、`model-availability.yml`で照合する。モデルを使う照合は、ダウンロード量が大きいためCIに含めない。clone・build・モデル取得・goldenの照合を一度に行うには`bash tools/clean_check.sh <repository> <workdir>`を使う（[記録](docs/clean-environment-check.md)）。

## 構成

```
Cargo.toml, src/, tests/   ライブラリ（pure-jeff）：判断契約、bundle照合、tokenizer、backbone、readout、policy、Model、memory::Session、worker
runtime/rust/              CLI（pure-jeff-cli）：jeff lock／prepare／decide／worker、開発用example
runtime/wasm/              W0〜W2の研究用probe。当時のNative sourceをfrozen/にbytesのまま置き、hashで固定する
apps/web-demo/             Webデモ（Wasm engine、静的ページ、build・配信・E2E script）
runtime/*.py               公式Jeffの参照worker、参照出力の採取、照合、package用の開発tool
tools/                     モデル取得、ライセンス監査、Wasm build、package検査（tools/consumer）
tests/fixtures/            公式参照（golden）と要求
bench/                     公式Jeff・Native・Wasmの比較benchmark、Tractの常駐benchmark
runtime/onnx/, runtime/tract/   ONNX export・数値gate・Tract probe（実験。docs/tract-development.md）
runtime/tract-driver-profile/, runtime/bench-native/, runtime/native-retained/
                           Tract最適化実験の生成元、Nativeの計測wrapper・FP32保持実験
docs/                      計画、結果、検証記録と証跡（docs/README.md）
```

crate名・schema名は2026-10-12に`kaze_judge`（切り出し元KazeJudgeの名前）から`pure-jeff`／`pure_jeff.*`へ改めた（[対応表](docs/naming-map.md)）。公式golden（`kaze_judge.jeff_golden.v1`）、`docs/`の記録と証跡、ONNX／Tractの研究資産は、hashが記録されているため当時の名前のまま残している。

## 出典

- 本家Jeff（MIT）、Jeffの重み（Apache-2.0）、Qwen3.5-0.8B（Apache-2.0）、依存crate：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 切り出し元：KazeJudge commit `885e7ff`。複製したファイルとhashは[PROVENANCE.json](PROVENANCE.json)
- ONNX／Tract資産：KazeJudge commit `ad59b25`から履歴ごと移管。ファイルとhashは[docs/tract-migration-provenance.json](docs/tract-migration-provenance.json)、再検証は[docs/tract-migration-results-2026-10-12.md](docs/tract-migration-results-2026-10-12.md)

## ライセンス

[Apache License 2.0](LICENSE)。帰属表示は[NOTICE](NOTICE)と[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)にある。モデルの重みは含まず、重み自身のLICENSE（Apache-2.0）とNOTICEに従う。ライセンス監査の記録は[docs/licensing.md](docs/licensing.md)。
