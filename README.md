# pure-jeff

Jeff（Qwen3.5-0.8BベースのDecision Model）の候補判断を、Python・PyTorchなしでRustだけで実行する実装。CPUのNative実行と、ブラウザ内のWebAssembly実行の2系統がある。

固定checkpoint（step1113、revision `51552f39…`）・text-only・batch 1に対象を絞り、公式Jeff（Python）の出力を参照として数値一致を検証している。人工データでの検証であり、日本語OCR／ASRの認識品質は評価していない。

## 現状

| 系統 | 状態 | 記録 |
| --- | --- | --- |
| Native（`runtime/rust`） | 公式参照7件（最大8192 tokens・255候補）で判断一致、確率差は最大5.066e-6。1要求ごとに子processで実行し、期限超過時は親がkillする | [進捗](docs/pure-rust-progress.md)、[P4](docs/p4-acceptance.md) |
| ブラウザWasm（`runtime/wasm`） | Chrome／Edgeで128〜512 tokens・2〜8候補の12件が公式参照と一致（最大2.38e-6）。反復・不正入力・資産破損・取消・再読込を確認 | [W0](docs/wasm-w0-results.md)〜[W2](docs/wasm-w2-results.md) |
| Webデモ（`apps/web-demo`） | ブラウザだけで、モデルの取得・保存・削除、判断、取消、JSON保存ができる。Chrome／Edgeの自動E2Eに合格。未公開 | [W3](docs/web-demo-w3-results.md) |

公式Jeffとの1 thread横並びベンチマーク（[結果](docs/benchmark-results-2026-10-11.md)）では、1要求ごとに起動するone-shotでNativeが1.65〜2.78倍速く、メモリは半分以下だった。モデル常駐では公式Jeff（PyTorch）の方が速く、Nativeの0.51〜0.66倍の時間で判断した。性能の許容値（SLO）、配布用のライセンス確定、Python未導入の端末での検証、公開は未完了。

## 構成

```
Cargo.toml, src/, tests/   判断契約crate（kaze_judge）。KazeJudgeから複製した要求・結果の型と検証
runtime/rust/              Native実行（jeff.exe worker、bundle検証、tokenizer、backbone、readout、policy）
runtime/wasm/              ブラウザ用probe。凍結したNative sourceをhashで固定して再利用する
apps/web-demo/             Webデモ（Wasmエンジン、静的ページ、build・配信・E2E script）
runtime/*.py               公式Jeffの参照worker・参照出力の採取・照合・packageの開発用tool
tests/fixtures/            公式参照（golden）と要求
docs/                      計画・進捗・検証記録と証跡（docs/README.md）
```

`kaze_judge`は、KazeJudgeが定める判断契約（`DecisionRequest`、`Observation`、`Attempt`など）の複製である。crate名を変えていないのは、凍結sourceのhashとpath依存をそのまま保つためである。複製元との同期は手動で行う。

## 必要なもの

- Rust 1.99.0、`wasm32-unknown-unknown` target（Wasm／デモ）
- `models/`（git管理外）：`models/jeff-checkpoint/`に固定checkpointの11ファイル。bundle manifestは`jeff lock`で作る（runtimeのsourceのhashを固定するため、契約crateやruntimeを変えたら作り直す）。照合方法は[Rust実行手順](runtime/rust/README.md)を参照
- 公式Jeffとの照合やベンチマークだけ：固定commitのJeff sourceと依存環境（[手順](docs/jeff-runtime.md)）

## 検証

```powershell
cargo test --locked --offline              # 契約。--all-features の process試験は KAZE_JUDGE_PYTHON が必要
cargo test --locked --offline --manifest-path runtime/rust/Cargo.toml
cargo test --locked --offline --manifest-path runtime/wasm/Cargo.toml
cargo test --locked --offline --manifest-path apps/web-demo/engine/Cargo.toml
```

実モデルでの照合、Wasm、デモの手順は、[runtime/rust](runtime/rust/README.md)、[runtime/wasm](runtime/wasm/README.md)、[apps/web-demo](apps/web-demo/README.md)の各READMEを参照。

## 出典とライセンス

KazeJudge commit `43f315b33fcc401c4a677901bb92384d5f263820`から切り出した。複製したファイルとhashは[PROVENANCE.json](PROVENANCE.json)にある。履歴は引き継いでいない。

このリポジトリ自身のコードのライセンスは**未定**である。公式Jeffの参照実装（MIT）の本文は`runtime/licenses/jeff-source/LICENSE`にある。checkpointと依存crateにはそれぞれの条件がある。配布の前に、ライセンスとNOTICEを確定する必要がある。
