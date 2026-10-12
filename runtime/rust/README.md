# jeff CLI（pure-jeff-cli）

ライブラリ`pure-jeff`（リポジトリroot）の上の薄いCLI。推論の実装（prompt、tokenize、24層forward、readout、候補分布、選択／保留、bundle照合、worker）はすべてライブラリにある。固定Jeff-Qwen3.5-0.8B、Windows x86_64 CPU FP32、batch=1、text-only、cacheなし。Python/PyTorchは通常実行と資産固定には不要。開発用example（`probe`、`profile`、`resident_bench`、`verify_portable`、`forward_check`）もこのcrateにある。

Candle commit `c68b24997319b8d76e5a4e775dab197c7f26322a`のCPU演算を使用し（`Cargo.toml`の`[patch.crates-io]`）、Qwen3.5 text backboneとgated deltaの逐次式を実装した。tokenizersは0.23.2、default features無効、fancy-regexのみ有効。検証toolchainはrustc/cargo 1.99.0、x86_64-pc-windows-msvc。

## Rustだけで実行する

rootから取得済みの11資産を指定する。downloadは行わない。manifestはcheckpointの上位ディレクトリに置き、既存出力を上書きしない。0.7/0.1は移植比較用の未校正policy。

```powershell
cargo build --release --locked --offline --manifest-path runtime/rust/Cargo.toml --bin jeff
& runtime/rust/target/release/jeff.exe lock models/jeff-checkpoint models/jeff-rust-bundle.json 51552f39a943d62e8387c4ea5e17026a1408729f 0.7 0.1 1
& runtime/rust/target/release/jeff.exe prepare models/jeff-rust-bundle.json examples/candidate-request.json 120000 512
& runtime/rust/target/release/jeff.exe decide-process models/jeff-rust-bundle.json examples/candidate-request.json 120000 512
```

`prepare`はpromptとtoken IDsを返し、forwardしない。`decide-process`は同じexeをworkerとして起動し、Attempt JSON（`pure_jeff.attempt.v1`）を返す。親のdeadline超過時は直接の子をkill/waitし、期限後の結果を破棄する。終了codeだけでなく`outcome.status`も確認する。起動時の不正JSON/config等は非zero終了する。CLIは最大1 MiBのrequest、1 forward、8192 tokensまで。token予算超過は切り詰めず拒否し、単一sequenceなのでpaddingしない。

workerは`jeff worker --manifest path --request path --response path`で`pure_jeff.worker.v1`のファイル通信を行う（ライブラリの`pure_jeff::worker::run`）。応答は新規作成のみ、親の応答上限は1 MiB。親はschema、request ID、観測契約を検査し、異常終了・不正応答を成功にしない。workerは子孫プロセスを起動しない。OS sandbox、RSS上限、queue、累計予算はこの境界に含まない。

bundleは`pure_jeff.bundle.v1`。Python参照worker用のbundle（`pure_jeff.reference_bundle.v1`）とは別schema/別ファイルで、checkpointの相対path、revisionラベル、11資産のSHA-256、policy、prompt実装とruntime buildのfingerprintを保存する。build fingerprint（`pure_jeff::runtime_build_hash`）はライブラリのsource・tensor spec・toolchain/target/profile/Rust flagsから生成する。CLIはbuild fingerprintの一致を要求するので、build変更後は別名で再lockする。checkpoint revisionは呼出側が与えるラベルであり、Rust CLIがリモートrepository由来を証明するものではない。

使用時に全資産のhash・完全なファイル集合、固定config/template、tensor名/shape/dtype、回答code/token ID対応を再検証する。重複JSON key、未知manifest field、不正相対path、資産内のsymlink/Windows reparse pointを拒否する。信頼した不変ローカル資産向けで、hash確認からmmap終了までファイルが変更されないことを呼出側が保証する必要がある。

`decide`は同一process内で実行する診断経路として維持する（`pure_jeff::ColdProvider`：呼出ごとに照合・読込）。ライブラリを直接使う場合は、推論開始前に`pure_jeff::configure_threads`でprocess-wideのthread数をbundleの`policy.cpu_threads`へ設定し、`pure_jeff::Model`を常駐させる。CLI/workerは設定を行う。不一致は拒否し、要求間でglobal thread設定を変更しない。hashの各read、tokenize後、各層の前後、出力後にdeadlineを検査するが、同期演算の途中では即時停止できない。強制停止が必要な呼出ではライブラリの`process` featureと`NativeProcessProvider::new(executable, manifest)`を使う。

## 検証

```powershell
cargo test --locked --offline --manifest-path runtime/rust/Cargo.toml
cargo test --locked --offline --all-features   # ライブラリ（root）
cargo clippy --locked --offline --manifest-path runtime/rust/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path runtime/rust/Cargo.toml -- --check
```

（pure-jeff）KazeJudgeでは`models/jeff-rust-bundle-p3.json`（`kaze_judge.rust_jeff_bundle.v1`）を使っていた。2026-10-12の改名以降は旧schemaを受け付けないので、上の`jeff lock`で作り直す。KazeNhanh CLIとの接続を検証する`validate_rust_process.py`はKazeJudgeに残した。

開発用Python harnessはRust executableを起動して保存済み公式参照と比較する。Pythonでモデル推論は行わない。検証出力も上書きしない。

```powershell
python -B runtime/validate_migration_cases.py --executable runtime/rust/target/release/jeff.exe --manifest models/jeff-rust-bundle.json --output experiments/runs/golden-repeat.json
python -B runtime/check_rust_boundaries.py --executable runtime/rust/target/release/jeff.exe --manifest models/jeff-rust-bundle.json --output experiments/runs/boundaries-repeat.json
```

[6件の照合記録](../../docs/extended-migration-validation.json)、[8192 tokenの実forward](../../docs/token-limit-forward-validation.json)、[上限の拒否境界](../../docs/token-limit-boundaries.json)、[P3照合記録](../../docs/p3-validation.json)、[P3 buildの境界検証](../../docs/p3-boundaries.json)、[138依存の初期監査](../../docs/rust-dependency-audit-p3.json)、[移行進捗](../../docs/pure-rust-progress.md)を参照。長文874 tokens・特殊文字182 tokens・255候補3206 tokens・上限8192 tokensを含む人工7ケースでprompt/token IDs/候補順/選択・保留が完全一致し、分布の最大絶対誤差は5.066e-6（基準1e-4）。全件で実token数ちょうどの予算は成功、1 token不足は拒否した。8193 token入力は予算8193でも切り捨てず拒否した。検証では子のPATHをWindows System32だけに限定する。Python未導入ホストでの配布受入、日本語認識品質、性能SLOは未完了。追加入力の来歴と再実行手順は[fixture README](../../tests/fixtures/jeff-golden/README.md)を参照。

P1の`examples/probe.rs`はgolden prompt/hiddenを入力する診断用として残す。[P1記録](../../docs/p1-validation.json)、[P2記録](../../docs/p2-validation.json)、[P2境界検証](../../docs/p2-boundaries.json)と各監査は当時のbuildの証跡で、現在のbuild fingerprintとは異なる。既存P2 manifestは変更せず、P3用manifestを別名で固定した。

P4では診断用`profile` exampleとRust製package verifierを追加した。[性能測定・ローカルpackage・品質入力の受入記録](../../docs/p4-acceptance.md)を参照。推論用P3 executableとbundleのfingerprintは維持する。packageはローカル検証用で`release_ready=false`、Rust推奨経路への切替は未実施。
