# crates.io v0.1.0に向けたライブラリ化の検証結果

2026-10-12。[計画](crate-release-plan.md)に沿って、判断契約とNative推論をライブラリ`pure-jeff`にまとめ、公開APIを加え、名前を改めた（[対応表](naming-map.md)）。crates.ioへの公開、push、Webデモの再デプロイは行っていない。

環境：Windows 11 Home x86_64、Rust 1.99.0（MSRVの確認に1.88.0）、Python 3.12.14、Chrome／Edge（headless）。モデルは`jeff-legacy/Jeff-Qwen3.5-0.8B` revision `51552f39…`。Linuxはこの環境で実行できない（WSL・Dockerなし）。

## 変更

| commit | 内容 |
| --- | --- |
| `6dd46bf` | 計画 |
| `076897b` | `kaze_judge`と`kaze_judge_jeff`をライブラリ`pure-jeff`に統合。公開API（`Model`、`LoadOptions`、`ColdProvider`、`memory::Session`、`Error`、`lock`、`configure_threads`、`runtime_build_hash`）。backboneとreadoutは`WeightSource`経由で重みを読み、Webデモengineは`memory::Session`を使う。研究用Wasm probeは凍結sourceを`runtime/wasm/frozen/`に置く。schema・package名を改名。candleはcrates.io版を宣言し、リポジトリ内では`[patch]`で`c68b249`に差し替える |
| `7a2dc99` | Python参照worker、benchmark script、build・監査tool、CIの改名。Tract用CIは`runtime/bench-native`を`6dd46bf`から取り出してbuildする |
| `b85016c` | crates.io向けREADME（`README.crate.md`）、package内容の限定、`tools/check_package.py`と利用者project（`tools/consumer`）、CIのpackage job |

## 検証

| 対象 | 方法 | 結果 |
| --- | --- | --- |
| Native CLI（`jeff decide`） | 変更前のbuild（`471dc5d`）と`b85016c`のbuildで、公式golden 7件（128〜8192 tokens、2〜255候補）のAttemptを比較 | **7件とも確率がbit単位で一致**。判断・tokens数・rendered promptも一致。公式との差は最大5.066e-6（従来と同じ）。artifactで違うのは、manifest・build・prompt sourceの3つのhashだけ（いずれも想定どおり） |
| Webデモengine（Native targetで実行） | 変更前後のengineを、それぞれ自身のlockfileでbuildし、同じgoldenを判定 | 512 tokens以内の4件で**確率がbit単位で一致**し、そのほかの出力もschema名とhash以外は同一。512超の3件はどちらも`budget_exceeded` |
| Webデモ（wasm32） | `tools/build_wasm.py`、host path検査、export検査 | build成功。host path 0件。exportは`memory`と`demo_*`のみ。importは従来と同じ`env.kj_now_ms`／`kj_panic`／`kj_random_fill`。同じsourceから2回buildしてbytesが同一 |
| Webデモ（ブラウザE2E） | `b85016c`からbuildしたsiteを`run_w3.py`でローカル配信し、Chrome・Edgeで実行 | 両方とも全gate合格（consent、single_download、private_inference、results、attempt、save、repeat、main_thread、delete）。公式との確率差は最大2.384e-6 |
| 研究用Wasm probe | 試験、clippy、fmt、wasm32 build、frozen sourceのhash照合 | 合格（試験8件） |
| Python参照worker | 新schemaでbundleを作り直し、`LocalProcessProvider`（`examples/jeff_decide`）でgolden 1件を判定 | 公式の確率と一致（差は約1e-16） |
| 公開crate（crates.io版candle） | `cargo package`の.crateを展開し、`[patch]`のない別projectからbuild（candle-core 0.11.0、tokenizers 0.23.2などはすべてcrates.io）。公式golden 7件を判定 | **7件とも判断・tokens数が一致**。公式との差は最大3.457e-6（`maximum-candidates`）。pin版candleとはbit単位では一致しない（差は最大4.2e-6） |
| packaging | `cargo package --list`、`cargo package`、`cargo publish --dry-run`（clean tree） | 成功。29ファイル、47,237 bytes。source 18件、tensor spec、build script、README、LICENSE、NOTICE、THIRD_PARTY_NOTICES、JeffのMIT本文のみ |
| MSRV | 利用者projectをRust 1.88.0で`cargo check` | 成功（`rust-version = "1.88"`） |
| 試験・lint | ライブラリ（`--all-features`、process試験にPython fixtureを使用）、CLI、engine、probe | 試験すべて合格。clippy `-D warnings`（ライブラリは既定featureあり・なしの両方）、rustdoc（警告なし）、fmt |
| ライセンス | `tools/audit_licenses.py --strict` | 137 packages、指摘なし |
| ONNX／Tract移管記録 | `tools/verify_tract_migration.py` | 失敗0（移管後に変わったのは`.github/workflows/tract-probe.yml`だけ） |

公開crateの依存（crates.ioのcandle 0.11.0）は、`tokenizers 0.22`をonig（Cライブラリ）付きで引き込む。そのためbuildにCコンパイラが要り、wasm32では使えない。README.crate.mdに明記した。

## 残っていること

- Linux：CIの定義（ライブラリ、CLI、Wasm、engine、package job）は更新したが、この環境では実行していない。pushしていないので、GitHub上でも未実行。
- crates.ioへの公開、Webデモの再デプロイは行っていない。次にデプロイするときは、新しいmanifest（`pure_jeff.bundle.v1`）でsiteを作り直す。Attempt・設定のschema名が変わり、キャッシュ名（manifestのhash由来）も変わるので、利用者のブラウザではモデルの再取得が起きる。
- 公開crateは、リポジトリ内のbuildと異なるcandleのcodeで計算する。公式参照との一致は確認したが、bit単位の再現性はリポジトリ内のbuild（CLI・デモ）でのみ保たれる。
- 既存のbundle manifest（旧schema）は作り直しが必要。ローカルでは`models/pure-jeff-bundle-b85016c.json`（CLI）と`models/pure-jeff-reference-bundle.json`（Python参照）を作った。
