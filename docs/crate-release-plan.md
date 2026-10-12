# crates.io v0.1.0 公開に向けた設計・移行計画

2026-10-12。pure-jeffを、Rustから直接呼べるNative推論ライブラリ`pure-jeff`としてcrates.ioへ出せる状態にする。公開（`cargo publish`）・push・Webデモの再デプロイは行わず、`cargo publish --dry-run`までを対象とする。

## 現状（commit `471dc5d`）

| package（path） | 役割 | 依存 | 公開 |
| --- | --- | --- | --- |
| `kaze_judge`（`/`） | 判断契約：要求・結果の型、検証、`evaluate`。feature `process`でprocess境界（`NativeProcessProvider`、Python用`LocalProcessProvider`） | serde、serde_json、tempfile | 未設定 |
| `kaze_judge_jeff`（`runtime/rust`） | Native推論：bundle（manifest・hash照合・lock）、tokenizer、prompt、backbone、readout、policy、`RustProvider`、worker、CLI `jeff` | `kaze_judge`、candle（git rev `c68b249`）、tokenizers =0.23.2 | `publish = false` |
| `kaze_judge_wasm_probe`（`runtime/wasm`） | W0〜W2の研究用probe。Nativeの`backbone/prompt/readout/policy.rs`をhashで固定して`include!`し、build.rsで重みの読み方だけを置換したcopyを作る | `kaze_judge`、candle（git） | `publish = false` |
| `kaze_judge_web_demo`（`apps/web-demo/engine`） | 公開Webデモのengine。probeのtokenize／slice／prompt／policyを使い、manifest・DecisionConfig・判断の手順をNativeから複製している | `kaze_judge`、probe、candle（git） | `publish = false` |
| `kaze_judge_tract_probe`、`kaze_judge_native_bench`（`runtime/tract`、`runtime/bench-native`） | ONNX／Tractの研究資産（凍結） | bench-nativeは`kaze_judge`・`kaze_judge_jeff`にpath依存 | `publish = false` |

- 公開API：Rustから直接推論する入口は`RustProvider`（呼出ごとにbundle照合・tokenizer構築・mmapを行うcold実行）だけ。常駐して使う型はなく、内部module（`bundle`、`backbone`など）がすべて`pub`のまま。
- bundle契約：manifest（`kaze_judge.rust_jeff_bundle.v1`）に、checkpoint 11ファイルのSHA-256、revision、policy（閾値・thread数）、`prompt.rs`のhash、runtime build hashを記録する。照合時は、ファイル集合とhash、tensorのshape／dtype、tokenizerの回答語彙、build hashの一致を要求する。build hashには`runtime/rust`のsourceに加えて、`../../../src/lib.rs`などpackageの外のfileとCargo.lockが含まれる。
- golden：`tests/fixtures/jeff-golden`の9件（schema `kaze_judge.jeff_golden.v1`）。hashはONNX／Tractの証跡やharnessにも記録されている。
- 依存：candleはgit revで、crates.ioはgit依存を許さない。crates.ioの`candle-core 0.11.0`はpin済みrevより65 commit古い。CPU kernelのsourceが異なり、`tokenizers 0.22`（onig、C build）を無条件に引く。pin済みrevにはSIMD128の半精度kernelの修正（#3904）とonig除去（#3952）がある。
- Tract：研究資産。Native・Wasmのcodeには依存しない（bench-nativeだけがNativeへpath依存）。

## 方針

### 1. 名前の整理

| 旧 | 新 |
| --- | --- |
| crate `kaze_judge` + `kaze_judge_jeff` | 公開crate **`pure-jeff`**（lib `pure_jeff`）に統合 |
| `runtime/rust`（`kaze_judge_jeff`） | `pure-jeff-cli`（`publish = false`）。実行ファイル名`jeff`、path、examplesは維持 |
| `kaze_judge_wasm_probe` | `pure-jeff-wasm-probe`（研究用、`publish = false`） |
| `kaze_judge_web_demo` | `pure-jeff-web-demo`（`publish = false`） |
| `kaze_judge.attempt.v1` | `pure_jeff.attempt.v1` |
| `kaze_judge.worker.v1` | `pure_jeff.worker.v1`（Rust・Pythonのworkerとも） |
| `kaze_judge.rust_jeff_bundle.v1` | `pure_jeff.bundle.v1` |
| `kaze_judge.rust_prepared.v1` | `pure_jeff.prepared.v1` |
| `kaze_judge.jeff_bundle.v1`（Python参照worker） | `pure_jeff.reference_bundle.v1` |
| `kaze_judge.web_demo_config.v1` | `pure_jeff.web_demo_config.v1` |
| 環境変数`KAZE_JUDGE_PYTHON`、build env `KAZE_JEFF_BUILD_INFO` | `PURE_JEFF_PYTHON`、`PURE_JEFF_BUILD_INFO` |

変えないもの（[対応表](naming-map.md)に記録する）：
- 公式golden（`kaze_judge.jeff_golden.v1`）。凍結した参照データで、bytesのhashが証跡に記録されているため。
- `docs/`の記録・`docs/research/`の証跡、ONNX／Tractの研究資産（`kaze_judge_tract_probe`、`kaze_judge_native_bench`）。
- 研究用harnessが書き出す記録のschema名（W0〜W3の事前登録・要約など）。
- Wasmとページの間の内部ABI名（`kj_*`）。

KazeJudgeとの後方互換性は持たない。旧schemaのmanifestは受け付けず、`jeff lock`で作り直す。公開中のWebデモは配信済みのbytesで動くので影響を受けない。次にデプロイするときは、新しいmanifestで作り直す。

### 2. 公開ライブラリAPI（`pure-jeff` 0.1.0）

```rust
use pure_jeff::{Model, LoadOptions, DecisionRequest, Limits};
pure_jeff::configure_threads(1)?;                  // 推論前に1回。bundleのpolicyと一致させる
let model = Model::load("models/bundle.json", &LoadOptions::default())?;  // hash照合・tokenizer・mmap
let observation = model.decide(&request, &limits)?;      // 候補内の分布と判断
let attempt = pure_jeff::evaluate(&mut &model, request, limits)?;    // 失敗を判断にしない包装
```

- `Model`：常駐型。読込時にmanifest・11ファイルのhash・tensor仕様・決定設定・tokenizerの回答語彙を照合し、tokenizerとmmapを保持する。`decide`は、budget・期限の確認、prompt、forward、readout、policy、artifactの記録を行う。`DecisionProvider`を実装する。
- 照合：checkpointのhash、prompt、決定設定、thread設定は常に照合する。runtime build hashの一致は`LoadOptions::require_runtime_build`で選ぶ。ライブラリでは既定で要求しない（利用者のbuildごとに値が変わるため）。CLIは従来どおり要求する。Observationのartifactには、実際に動いたbuildのhash（`runtime_build`）を記録する。
- エラー：読込は`pure_jeff::Error`（`ErrorKind`：`Bundle`、`Timeout`、`ThreadConfig`、`InvalidArgument`）、判断は従来の`Failure`。`anyhow`は公開型に出さない。
- `lock`：`pure_jeff::lock(checkpoint, manifest, revision, policy, deadline)`。
- `memory::Session`：ファイルを使わず、メモリ上のbytesで同じ照合と判断を行う（Webデモ用。時間制限は呼出側が持つ）。
- feature：`native`（既定。ファイル・mmap）、`process`（`NativeProcessProvider`、`LocalProcessProvider`、`worker::run`）。
- 内部module（backbone、readout、tokenize、json）は`#[doc(hidden)]`とし、semverの対象外にする。リポジトリ内のツールが使うためだけに残す。

### 3. 推論ロジックの共有

- backboneは重みの読み出しを`WeightSource` trait（mmap／byte slice）にし、NativeとWebデモengineで同じ式を使う。演算は変えない。
- 決定設定の検証、tokenizerの読込・回答語彙の確認、prompt、readout、policy、artifactの組立てはライブラリに一本化する。Webデモengineからは複製をなくし、`memory::Session`を使う。engineに残すのは、ページ用のABI、streaming hash、512 tokensの上限、`wasm_engine` artifact、段階時間だけ。
- 研究用のWasm probe（W0〜W2）は、当時の`backbone/prompt/readout/policy.rs`を`runtime/wasm/frozen/`にbytesのまま置き、build.rsのhash照合を続ける。frozen fileの`use kaze_judge::…`は、Cargoの依存名の付け替え（`kaze_judge = { package = "pure-jeff", … }`）で解決し、書き換えない。

### 4. 依存（candle）

- 公開crateは、crates.ioの`candle-core`／`candle-nn` `=0.11.0`と`tokenizers =0.23.2`に依存する。
- リポジトリ内の各root（ライブラリ、CLI、Wasm probe、Webデモengine）は、`[patch.crates-io]`で従来のgit rev `c68b249`に差し替える。これにより、CLI・Webデモの数値と生成物は従来と同じcandleのcodeから作られる。
- crates.io版candleで公式goldenが一致するかを実測で確かめる（下記）。一致しない場合は公開を見送り、理由を記録する。
- crates.io版candleではwasm32のbuildを保証しない（onigのC build、SIMD128半精度の修正なし）。v0.1.0の公開対象はNativeとし、wasm32はリポジトリ内（patch適用）だけで支える。

### 5. 検証

| 対象 | 方法 | 合格条件 |
| --- | --- | --- |
| Native CLI | 変更前の`jeff.exe`と変更後で、公式golden 7件（最大8192 tokens、255候補）のAttemptを比べる | 確率がbit単位で一致。判断・tokens一致。公式との差1e-4以内 |
| Webデモengine | 変更前後のengineをNative targetで同じgolden（512 tokens以下）に通し、Attemptを比べる。wasm32 build、host path検査、export検査も行う | 確率がbit単位で一致。schema名以外の出力が一致 |
| Webデモ（ブラウザ） | ローカル配信でChrome／EdgeのE2E（`run_w3.py`） | 既存のgate（公式との一致など）に合格 |
| Wasm probe | build、試験、frozen sourceのhash照合 | 従来どおり |
| 公開crate（crates.io版candle） | `cargo package`の内容を展開し、patchを使わない新規の利用者projectからbuildして、公式golden 7件を判定 | 公式との差1e-4以内、判断・tokens一致 |
| packaging | `cargo package --list`、`cargo publish --dry-run` | 成功。重み・証跡・fixtureの大きいfileを含まない |
| CI | Windows／Linuxで、ライブラリ・CLI・Wasm・engine・packaging・利用者projectのbuild（モデル不要） | workflowを更新。GitHub上の実行はpushしないため未実施 |

Linuxはこの環境（WSL・Dockerなし）では実行できないため、CIの定義だけを更新する。

### 6. commitの単位

1. 計画（この文書）
2. ライブラリの統合と改名（`pure-jeff`）、`Model` API、CLIの移行。Native goldenのbit一致を確認する
3. Webデモengineのライブラリ化、Wasm probeのfrozen source分離。engineのbit一致とE2Eを確認する
4. Python参照worker・script・CIの改名
5. crates.io向けmetadata・README・LICENSE／NOTICE、packaging、利用者projectの検証
6. 文書（README、対応表、結果）
