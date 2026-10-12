# 名前とpathの対応表（2026-10-12の改名）

KazeJudge由来の名前（`kaze_judge`）を、crates.io公開に向けて`pure-jeff`の名前へ改めた（[計画](crate-release-plan.md)）。旧名で書かれた記録・証跡を読むときは、この表で今の名前に読み替える。KazeJudgeとの後方互換性は持たない。旧schemaのmanifestは受け付けないので、作り直す必要がある。

旧名が通用した最後のcommitは`6dd46bf`（Rustの改名は次の`076897b`から）。

## package

| 旧 | 新 | path |
| --- | --- | --- |
| `kaze_judge`（判断契約） | `pure-jeff`（lib `pure_jeff`）。公開crate | `/` |
| `kaze_judge_jeff`（Native実行） | ライブラリ`pure-jeff`へ統合。CLIは`pure-jeff-cli`（`publish = false`、実行ファイル`jeff`） | `runtime/rust` |
| `kaze_judge_wasm_probe` | `pure-jeff-wasm-probe` | `runtime/wasm` |
| `kaze_judge_web_demo` | `pure-jeff-web-demo` | `apps/web-demo/engine` |
| `kaze_judge_wasm_probe.wasm`、`kaze_judge_web_demo.wasm` | `pure_jeff_wasm_probe.wasm`、`pure_jeff_web_demo.wasm` | build出力 |

## schema・環境変数

| 旧 | 新 | 内容 |
| --- | --- | --- |
| `kaze_judge.attempt.v1` | `pure_jeff.attempt.v1` | `Attempt`（CLI、Webデモの出力） |
| `kaze_judge.worker.v1` | `pure_jeff.worker.v1` | worker要求・応答（Rust・Python） |
| `kaze_judge.rust_jeff_bundle.v1` | `pure_jeff.bundle.v1` | Native／Webデモのbundle manifest |
| `kaze_judge.jeff_bundle.v1` | `pure_jeff.reference_bundle.v1` | Python参照worker（`runtime/jeff_worker.py`）のbundle |
| `kaze_judge.rust_prepared.v1` | `pure_jeff.prepared.v1` | `jeff prepare`の出力 |
| `kaze_judge.web_demo_config.v1` | `pure_jeff.web_demo_config.v1` | Webデモの`demo-config.json` |
| `KAZE_JUDGE_PYTHON` | `PURE_JEFF_PYTHON` | process試験のPython |
| `KAZE_JEFF_BUILD_INFO` | `PURE_JEFF_BUILD_INFO` | build scriptが渡すcompiler等の情報 |
| `RustProvider` | `ColdProvider`（呼出ごとに照合・読込）、`Model`（常駐） | Rust API |

## 移動したsource

`runtime/rust/src`の推論moduleはライブラリの`src/`へ移した（git上は移動として記録）。演算は変えていない。bytesが変わったのはimportと型名（重みを`WeightSource`経由で読む）、コメント、エラー型である。旧hashは証跡に記録された値。

| 旧path | 新path | 旧SHA-256（先頭12桁） | 新SHA-256（先頭12桁、`b85016c`） |
| --- | --- | --- | --- |
| `runtime/rust/src/backbone.rs` | `src/backbone.rs` | `6e4f79c9e510` | `c9b9f19769ad` |
| `runtime/rust/src/prompt.rs` | `src/prompt.rs` | `d8139cd0cb1b` | `bfb23267c231` |
| `runtime/rust/src/readout.rs` | `src/readout.rs` | `90a2781c46f0` | `860e41b40365` |
| `runtime/rust/src/policy.rs` | `src/policy.rs` | `7adee7fb4a67` | `a3d8099fa8f8` |
| `runtime/rust/src/bundle.rs` | `src/bundle.rs`（manifest型は`src/manifest.rs`、決定設定は`src/config.rs`） | `714dfdcd136e` | `51bdf3439225` |
| `runtime/rust/src/tokenize.rs` | `src/tokenize.rs` | `abee532540c2` | `069c65d9362e` |
| `runtime/rust/src/worker.rs` | `src/worker.rs` | `6fffa975232d` | `4114cd3ab0dc` |
| `runtime/rust/src/json.rs` | `src/json.rs` | `6d87637006ba` | 同じ |
| `runtime/rust/src/lib.rs`（`RustProvider`） | `src/model.rs` | — | — |
| `src/lib.rs`（判断契約） | `src/contract.rs` | — | — |
| `runtime/rust/spec/`、`runtime/rust/build.rs` | `spec/`、`build.rs` | — | — |

W0〜W2の証跡が参照する`backbone.rs`、`prompt.rs`、`readout.rs`、`policy.rs`の旧bytesは、`runtime/wasm/frozen/`にそのまま残している。研究用probeのbuild.rsは、今もこの旧hashで照合する。

`prompt.rs`のbytesはbundleのprompt契約（`prompt_sha256`）でもある。改名でbytesが変わったので、旧manifestのprompt hashは新しいライブラリと一致しない。promptの文面は変わっていない。公式golden 7件のprompt bytesとの一致は、試験（`runtime/rust/tests/contracts.rs`）で確かめている。

## 変えなかったもの

| 名前 | 理由 |
| --- | --- |
| 公式golden（`tests/fixtures/jeff-golden`、schema `kaze_judge.jeff_golden.v1`） | 凍結した参照データ。bytesのhashが証跡とharnessに記録されている |
| `docs/`の記録、`docs/research/`の証跡 | 当時の記録 |
| ONNX／Tractの研究資産（`kaze_judge_tract_probe`、`kaze_judge_native_bench`、`runtime/onnx`の記録schema） | 証跡が自身のhashを記録している（[Tract移管](tract-migration-plan.md)）。`runtime/bench-native`は旧名のcrateに依存するので、CIでは`6dd46bf`から取り出してbuildする |
| 研究用harnessが書く記録のschema（`kaze_judge.wasm_w*`、`kaze_judge.web_demo_w3_*`、`kaze_judge.p4_*`、`kaze_judge.profile.v1`など） | 同じschemaの過去の記録と比べるため |
| Wasmとページの間のimport名（`env.kj_random_fill`、`env.kj_now_ms`、`env.kj_panic`） | 公開中のページと同じ内部ABI。外部に見えるAPIではない |
