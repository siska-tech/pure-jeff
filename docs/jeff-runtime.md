# Jeffローカル実験backend

2026-10-08。接続コードとモデル不要の契約試験を追加。実重み推論・公式predictとの一致・日本語OCR/ASR品質・CPU SLOは未検証。

**2026-10-09更新:** [Pure Rust移行P0](pure-rust-progress.md)で資産・依存環境を導入し、人工候補1件の実重み推論と公式predictとの一致を確認した。以下の未導入・未検証の記述は初期作業時点の記録。日本語品質・CPU SLOとRust推論backendは引き続き未検証。

**2026-10-10更新:** [P1のRustプローブ](rust-backend-assessment.md)で実モデル3ケースのforward/readoutを確認した。Python版は参照実装として保持し、Rustの独立prompt/bundle/Provider実装へ進む。日本語品質・CPU SLOと配布受入は未検証。

## 実装

**現在の移行状況:** Rust worker/NativeProcessProviderとCLI接続は実装済み。公式参照を長文・特殊文字・255候補・8192 token上限を含む7件へ拡充した。[Rust実行手順](../runtime/rust/README.md)、[6件の照合記録](extended-migration-validation.json)、[8192 token照合](token-limit-forward-validation.json)、[P4受入記録](p4-acceptance.md)を参照。以下はPython参照backendの手順で、過去の更新記録は当時の進捗を示す。

Rustのoptional feature `process` に `LocalProcessProvider` を追加した。呼出ごとにPythonを直接起動し、専用temp directoryのJSONで1要求・1応答を交換する。shell、HTTP server、自動retryは使用しない。親プロセスがdeadlineを監視し、超過時は子をkill/waitしてから一時ファイルを破棄する。Windowsでは非表示起動。

既定featureは引き続きcoreのみ。KazeNhanhへの依存追加・本体変更はない。

`runtime/jeff_worker.py` はローカルの固定JeffソースからDecisionModelをimportする。text-only / CPU / 1 question / 1 forward / adapterなし。question_idは `transcription-candidate.v1` のみ。checkpointのtemperatureとprompt layoutを使用し、候補順序を維持する。tokenize後、入力上限を確認してforwardする。8192 tokensを超える入力は切り詰めず拒否する。

選択閾値はmanifest作成時に明示する。最大probabilityと1位・2位の差で選択/保留を決め、同点は必ず保留。これは選択policyであって、認識riskの校正ではない。modelが判断不能ラベルを選んだ結果とは別である。下記の0.7 / 0.1は手順例であり、推奨値・実測に基づく値ではない。

## ローカル資産の準備

必要なもの：Python 3.12以上、git、immutable commitのcleanなJeff checkout、checkpoint一式、対応するPython依存環境。コードと重みの利用条件をそれぞれ確認する。adapterなしの実験では公式が案内するv1.2が候補。v1.3 + adapter対応は未実装。

このセッションではPython 3.12のみ存在し、Jeff・torch・transformersは未導入。git ls-remoteによるgithub.comへの接続も失敗したため、実モデル取得と実ファイルhashの固定は未完了。2026-10-09にGitHub/Hugging Faceのmetadataからソースcommitとcheckpoint revision候補を特定した（下記参照）。重みLICENSE本文の取得・精査は残っている。Webで現行ソースを閲覧できたことは、ローカル実行互換性の証明ではない。

取得済みのJeffを `vendor/jeff`、取得済みcheckpointを `models/jeff-checkpoint` に置く例。取得元repository/revision/licenseは別途保存する。Jeff自身のuv.lockを使って独立環境へruntime依存を用意する。学習依存は不要で、インストールには公式の `uv sync --no-default-groups` を参照する。Windows向けwheelの利用可否は未検証。

```powershell
# 依存導入済みのPythonと、実際に取得したJeffのcommitを指定する。
$python = (Resolve-Path vendor/jeff/.venv/Scripts/python.exe).Path
$revision = git -C vendor/jeff rev-parse HEAD
& $python -B runtime/jeff_worker.py --lock --manifest models/jeff-bundle.json --checkpoint models/jeff-checkpoint --source vendor/jeff --source-revision $revision --min-probability 0.7 --min-margin 0.1 --cpu-threads 4
```

manifestはモデル/ソースdirectoryの外へ置く。作成時にgit HEAD一致とclean checkoutを確認し、checkpoint全ファイル、Jeff packageの全.py・pyproject.toml・uv.lock・LICENSE、worker自身のhashを記録する。既存manifestは上書きしない。実行時も全hashとファイル集合を再検証する。ソースのbytecode cache・symlinkを拒否する。モデルファイルは変更しないこと。検証とロードの間の他プロセスによる変更を防ぐOSレベルのロックはない。

依存versionは固定Jeffのpyproject.tomlのruntime一覧と一致する必要がある。未対応の依存指定形式やversion差は失敗として扱う。モデル・source・manifest・worker・prompt・runtime versionsのdigestをObservationへ記録する。モデルrevision/licenseは自動取得しないので、manifestのhashだけを配布条件の確認済み表示にはしない。

## 1件実行

```powershell
cargo run --locked --offline --features process --example jeff_decide -- $python models/jeff-bundle.json examples/candidate-request.json 120000 512
```

末尾はcold loadを含むtimeout-msとmax-input-tokens。stdoutはAttemptのJSON。失敗もJSONの `outcome.status=failed` として返るため、CLI exit codeだけで成功判定しない。

入力は説明用の人工候補。実OCR/ASRデータの精度評価ではない。原文の候補を含め、呼出側で明示routingした対象に限定する。成功しても元のRecognitionReportを更新しない。

## 制限

- 毎回hash検証・モデルloadするcold実行。常駐worker、queue、累計予算、複数pass、LoRA、fine-tuningは未実装。
- direct childの終了だけを管理する。workerは子孫プロセスを作らない前提で、OS sandbox・process tree制限ではない。
- 応答のRust読み込みは1 MiBまで。悪意あるworkerのdisk/RSS消費を制限する仕組みではない。指定するPythonとworkerは信頼したローカルファイルに限る。
- stdin/stdout/stderrは親側で破棄し、本文をログへ流さない。失敗理由は型付きcodeまで。必要時は同じwire入力をworkerへ直接渡してstderrの例外型を確認する。
- HF_HUB_OFFLINE / TRANSFORMERS_OFFLINEを有効にするが、OSネットワーク隔離ではない。
- missing dependency/hash不一致/ロードエラーはunavailable。成功で観測できなかったtoken/forward実消費は不明で、0と推定しない。

## 検証と残作業

### Pure Rust移行用の参照出力

`runtime/export_jeff_reference.py`を追加した。固定bundleと同じ依存環境で公式`DecisionModel.predict`を1 forward実行し、hookで実際の入力tensor、最終hidden state、mask前後logitsを採取する。その後モデルを解放し、既存workerで独立してcold推論し、分布・候補順・token数・temperature・選択/保留を照合する。prompt、回答code/token ID、runtime依存、exporter hashも保存する。

```powershell
& $python -B runtime/export_jeff_reference.py --manifest models/jeff-bundle.json --request examples/candidate-request.json --output tests/fixtures/jeff-golden/candidate-request.json --max-input-tokens 512 --timeout-ms 120000
```

出力は既存ファイルを上書きしない。確率差は既定で最大絶対誤差1e-6まで。JSON内の文字列はUTF-8で再符号化し、`prompt_utf8_sha256`と照合できる。tensorのshape/dtypeも記録する。公式forward内部で生成されるposition/attentionの中間tensorや各層の出力はまだ採取しないため、backbone差分の調査時に拡張する。exporter全体は開発用で、公式推論のhard timeoutは持たない。`--timeout-ms`は独立worker推論の協調deadlineであり、プロセス停止が必要ならRust CLIを使う。

採取データが実モデル由来でも、説明用の人工候補1件は日本語OCR/ASR品質や校正の評価ではない。参照集合の拡充とP1のRust実証は[移行計画](pure-rust-plan.md)に従う。

```powershell
$env:KAZE_JUDGE_PYTHON = (Get-Command python).Source
cargo test --locked --offline --all-features
python -B -m unittest discover -s runtime -p 'test_*.py' -v
cargo clippy --locked --offline --all-features --all-targets -- -D warnings
cargo fmt --check
```

Rust 11件、Python 10件成功。子プロセス停止・過大応答・ID不一致・失敗応答・hash変更・ファイル追加・bytecode cache・候補順序・保留・forward前のtoken予算を確認。Pythonのモデル呼出試験には明示fixtureを使っており、実Jeff推論の試験ではない。

次は資産取得可能な環境でcommit/checkpoint/licenseを固定し、同一promptと候補順序で公式predictと分布・token数を照合する。[KazeNhanh report adapter](kaze-nhanh-integration.md)は実装・契約検証済み。実モデル照合後に実データ比較へ進む。

## 参照

- [Jeff README](https://github.com/firelex/jeff)：モデル版と導入方針。
- [公式model.py](https://github.com/firelex/jeff/blob/main/src/jeff/model.py)：prepare、forward、temperature付き分布とprompt layout。
- [公式pyproject.toml](https://github.com/firelex/jeff/blob/main/pyproject.toml)：Pythonとruntime依存。

いずれも2026-10-08にmainを閲覧。固定commitの監査記録ではない。

## 2026-10-09: 固定参照候補

- Jeffコード：3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0。GitHub connectorでcommit情報を取得。[commit](https://github.com/firelex/jeff/commit/3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0)。
- 0.8B checkpoint候補：mstrasser/Jeff-Qwen3.5-0.8B、revision 51552f39a943d62e8387c4ea5e17026a1408729f。Hugging Face APIのmetadataでApache-2.0、言語en、base Qwen/Qwen3.5-0.8B、必要ファイル一覧を確認。[metadata](https://huggingface.co/api/models/mstrasser/Jeff-Qwen3.5-0.8B)。

これは参照候補の特定であり、実ファイル取得済みのasset lockではない。checkpointのdecision_configとLICENSE本文は取得できず、コードとの実行互換性も未検証。公開言語は英語であり、日本語OCR/ASRの有効性を仮定しない。
