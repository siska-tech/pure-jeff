# Pure Rust移行の進捗

## 2026-10-10: 配布用ライセンス本文とNOTICE索引の補完

P4の本文収集不足を1件解消し、Jeff参照実装のMIT本文と第三者NOTICE索引を追加した新規package `experiments/runs/portable-p4c` を検証した。[ライセンス収集・索引監査](p4-license-review.json)、[package再配置・破損検証](p4c-portable-validation.json)、[受入条件](p4-acceptance.md)を参照。配布受入や法的レビューの完了とは扱わない。

- `pulp-wasm-simd-flag` 0.1.1はWindowsの通常依存グラフにも含まれる。実装本体にはwasm向けcfgがあるが、本文収集から除外しなかった。公開crateのVCS commitと同じ固定commit `5eb07fd7b68edf0a5e19f71737d315f72a510295` の[リポジトリMIT本文](https://raw.githubusercontent.com/sarah-quinones/pulp/5eb07fd7b68edf0a5e19f71737d315f72a510295/LICENSE)と[package宣言](https://raw.githubusercontent.com/sarah-quinones/pulp/5eb07fd7b68edf0a5e19f71737d315f72a510295/pulp-wasm-simd-flag/Cargo.toml)を確認。同じcommitを持つ取得済みpulp crateの本文を補足資料として保存した。
- 補足は依存name/version/source/宣言license、Cargo.toml・VCS情報・sourceのhash、commit、本文hashが一致する場合だけ同梱する。本文改変・別version・source改変・path逸脱の拒否を試験した。出典は[補足索引](../runtime/licenses/supplements.json)へ固定。
- 公式参照JeffのMIT本文は元Python manifestに固定されたhashと照合して同梱。`THIRD_PARTY_NOTICES.txt` でcheckpointのLICENSE/NOTICE、参照source、監査対象138依存と収集本文への経路を列挙した。Pythonのsource/runtimeはpackageへ追加していない。
- 保守的なbuild/dev込み138依存のうち136件で本文あり。未指定・本文なしの残件は自プロジェクトの `kaze_judge` と `kaze_judge_jeff`。配布ライセンスは未指定を維持し、第三者への適合判断やbase model/NOTICEの最終レビューは別の残作業とする。
- 新packageは266 payload files、1,735,414,269 bytes。旧p4bと比較し、11 checkpoint資産と推論exeが同一であることを照合。Python/CargoをPATHから除きcheckout外cwdから実モデルsmoke成功、追加・変更・欠落・不正pathの4ケース拒否と全ファイル復元を確認した。Python試験は補足検証4件を追加した計18件が成功。
- 旧p4b packageと検証JSONは維持し、当時のbuilderを `experiments/runs/package-builder-p4b.py` に保存した。新しいbuilder/helper/indexのhashはp4c package索引へ記録した。

次はプロジェクトlicenseの確定、base model/第三者NOTICEの配布レビュー、Python未導入Windows clean hostの検証。日本語品質入力と性能SLOは既存方針のまま未確定で、`release_ready=false` を維持する。

## 2026-10-10: 8192 token上限の実forwardと拒否境界

8192 tokensちょうどの公式参照を追加し、P3の同じRust executable/bundleで実forward照合に成功した。人工参照は計7件。[上限forward照合](token-limit-forward-validation.json)、[拒否境界4ケース](token-limit-boundaries.json)、[再実行手順](../tests/fixtures/jeff-golden/README.md)を参照。過去の進捗記録にある上限照合の残作業は今回実施した。

- 固定公式processorで、原文とoriginal候補の末尾に ` x` を4032回追加し、prompt全体が8192 tokensになる入力を生成。alternative候補への ` y` 1回追加で8193 tokensの拒否用入力も作成した。反復文字による上限検証であり、一般の長文全体に対する品質保証ではない。
- 8192 tokensの公式predict/Python workerの分布誤差は0.0（基準1e-6）。Rustの独立prompt bytes・token IDs・候補順・判断・1 forwardが一致し、分布誤差は4.679e-6（基準1e-4）。判断はalternative。全7件を通じた最大誤差は引き続き5.066e-6。
- 8192 tokens / 予算8192は成功し、予算8191は拒否。8193 tokensは予算8192でも8193でも拒否した。公式prepareはworker同様の `min(budget, 8192)` を使って切り捨てなしの成功/拒否を検査し、forward hookは0回。Rustもprepareで拒否し、native processのtyped outcomeはBudgetExceededだった。
- 検証時はRustの子PATHからPythonを除外。推論executable・bundle・公式source/workerは変更せず、新しい参照と診断harnessを追加した。以前の6件の照合記録を上書きしていない。
- モデル不要のprompt契約試験を7 fixtureへ拡大。runtime試験12件、Python試験14件、runtime all-targets clippy/fmt成功。上限forward中に契約試験のbuild/checkも実行したため、今回の経過時間は互換性検証の診断情報として扱い、性能benchmarkへ追加しない。

P4の残作業は品質入力の整備、license/NOTICE、Python未導入Windows clean hostでの配布受入。ユーザー方針に従い、性能は実測のみでSLOの合否を付けない。今回の上限照合をもって推奨backendへの切替や配布受入の完了とは扱わない。

## 2026-10-10: 長文・特殊文字・最大候補数の実モデル照合

P0の人工参照集合を3件から6件へ拡充し、P3の同じRust executable/bundleで全件の実forward照合に成功した。[照合JSON](extended-migration-validation.json)、[入力の来歴と再実行手順](../tests/fixtures/jeff-golden/README.md)を参照。以下の過去記録にある3件は各段階での検証範囲を示す。

| 追加入力 | token数 | 候補数 | Rust/公式の分布最大絶対誤差 | 判断 |
| --- | --- | --- | --- | --- |
| 長文（繰り返しの日本語） | 874 | 2 | 2.189e-8 | original |
| chat delimiter文字列・全角・結合文字・絵文字 | 182 | 2 | 8.345e-7 | 保留 |
| 最大候補数 | 3206 | 255 | 1.192e-6 | c0 |

- 追加3件の公式predictとPython workerの分布誤差は0.0（基準1e-6）。固定source/checkpoint、CPU FP32・1 threadで参照を取得した。
- Pythonを子のPATHから除いてRustの独立prompt bytes・token IDs・候補順・判断・各1 forwardを検証。全6件の分布誤差は最大5.066e-6で基準1e-4以内。全件で実token数ちょうどの予算は成功し、1 token不足はBudgetExceededになった。
- Rustのモデル不要prompt試験も6 fixtureへ拡大。runtime試験12件、Python試験14件、runtimeのall-targets clippy/fmtが成功。推論用executableのSHA-256はP3の`66aff281ba40d611758de1f9f45577465e8d0a88febfdf127743825197369bfd`を維持した。
- 新しいharnessの経過時間は互換性検証の診断情報であり、性能benchmarkの追加標本にはしない。途中でモデル不要のbuild/checkも実行した。

今回の入力は認識器の実N-bestではなく人工データ。品質改善・校正・SLOの受入は行っていない。残る検証は8192 token上限そのものの実forward照合と、P4の品質データ、license/NOTICE、Python未導入clean hostでの受入。性能はユーザー方針どおり実測のみを維持する。

## 2026-10-10: P4の性能測定とローカルpackage

P4へ着手。P3の推論用executable/bundleを維持し、diagnostic `profile`とRust製`verify_portable`、Windows one-shot benchmark、package作成と破損検証harness、品質入力監査、通常CI定義を追加した。[P4受入記録](p4-acceptance.md)、[性能JSON](p4-benchmark.json)、[process-treeメモリ補足](p4-worker-tree-memory.json)、[package検証JSON](p4-portable-validation.json)、[品質入力監査](p4-quality-input-audit.json)を参照。P4全体の受入と推奨backend切替は未完了。

- 同一Windows機・同じ資産/policy・CPU FP32・1 threadで、Rust/Python workerを人工3ケース×各5回、新規processで交互に測定した。中央値はRust 5.52〜6.87秒、Python 16.24〜21.70秒。Python 92.34秒の外れ値も除外せず保持。OS file cacheは消去せず、モデル保持のwarm性能とは区別する。最初のI/O混在測定は中断し、単独測定へ取り直した。
- Rust workerのOS peak working setは約1.49 GiB。元Python測定がvenv launcherのみを見ていたため、metadataを訂正し、子interpreterを追跡する補足測定を追加した。Python interpreterは各ケース1回で約3.71〜3.72 GiB。両者ともmapped/shared pageを含み、private RSSではない。Python memoryの反復p95は未測定。
- `experiments/runs/portable-p4b`へRust worker/検証exe、固定11資産、相対bundle、smoke input/期待値、license本文・索引・依存監査をまとめた。261 payload files、1,735,391,870 bytes。Python/Cargoを子のPATHから除き、checkout/package外のcwdからRust製verifierで実モデルsmoke成功。ファイル追加・変更・欠落、不正pathの4ケースを拒否し、検証後の全bytes/hash復元も確認した。
- 固定138依存の保守的なbuild graphからlocal license本文を収集。プロジェクト2 packageのlicense未指定と、MIT宣言の`pulp-wasm-simd-flag`の本文欠落を検出した。配布対象の厳密な整理とNOTICEレビューは残し、packageは`release_ready=false`。ライセンスを勝手に選定していない。
- 既存KazeNhanh OCR development observation 15行を監査。確認済み転記7行・未確認8行、明示N-bestは0行。gold転記から候補を生成せず、品質計測forwardは0回。ユーザーからも評価データは未整備と確認し、準備条件を記録した。
- Windowsの通常CI定義を追加。core契約7件、native process 3件、Rust runtime 12件の計22件をローカルで成功。新examplesを含むruntime clippy/fmt成功。通常CIではPython worker試験や実資産付き推論を走らせない。GitHub上のworkflow実行は未確認で、隣接KazeNhanh依存のadapter試験は別ローカル手順とする。

ユーザー方針により、許容時間・メモリ上限は未定のまま、今回は実測値の保存のみでSLOの合否を付けない。次の受入条件は、品質データの整備、SLOの固定と十分な反復、license/NOTICE整理、Python未導入Windows clean hostでの実証、長文/最大候補数の実forward参照拡充。

## 2026-10-10: P3のRust workerとKazeNhanh接続

P3の実装とローカル検証を完了。coreの`process` featureに`NativeProcessProvider`を追加し、Rust worker executableを呼ぶ。既存Python constructorを維持し、起動引数以外のpreflight、wire、応答上限、deadline監視、kill/wait、観測検証を共通化した。KazeNhanhの実験CLIに`--backend rust|python`を追加し、従来7引数のPython経路も維持した。[P3検証JSON](p3-validation.json)、[実行手順](../runtime/rust/README.md)、[KazeNhanh接続](kaze-nhanh-integration.md)、[依存監査](rust-dependency-audit-p3.json)を参照。

- `jeff worker`と`jeff decide-process`を追加。1要求につき1子process、既存`kaze_judge.worker.v1`を使用し、request IDと最大1 MiBの応答を検査する。Rust workerは子孫processを起動しない。
- 親はモデルロードとhash検証を含めてdeadlineを監視する。期限超過時に直接の子をkill/waitし、期限後の結果を破棄する。Rust製fixtureで実起動をmarker確認し、応答を書いてから終了が遅れた子も終了・回収され、後続markerを書けないことを検証した。
- Rust製fixtureで正常応答、ID/schema不一致、重複key、不正JSON、応答超過、異常終了、typed failure、実行前予算拒否とopt-outを確認。実workerでは不正wire、予算0、期限0、欠落bundle、出力上書き拒否を確認した。
- 子のPATHをWindows System32だけにし、python/python3/pyが解決できないことをharnessで検査。Rust process経由の人工3ケースで公式prompt/token IDs/候補順/選択・保留が一致。分布誤差は最大5.066e-6（基準1e-4）。各1 forward。
- KazeNhanhの人工OCR report（100円/700円）を実モデルで評価し、`nbest_1`を選択。元report全体、evidence/risk/decision、入力ファイルbytes、候補順を保持した。scope不一致は実行ファイル/manifestがなくてもskip。予算不足、timeout、bundle不一致、不正report、実行ファイル欠落時のfallbackなしも確認。harnessの失敗・skip検証は計10ケース。
- core/process 14件、Rust runtime 12件、KazeNhanh adapter 8件、計34試験が成功。各packageのclippy/fmtも成功。固定Rust executableの138依存を初期監査し、既知の禁止依存/featureとesaxx C++有効化なし。Windows OS/CRTへの直接importは引き続き存在する。

P3 build用のmanifestは`models/jeff-rust-bundle-p3.json`へ新規固定し、P1/P2の検証記録とmanifestは当時の証跡として保持した。runtime build fingerprintにworker、core process境界とCLI sourceも含める。

次はP4の品質・性能・配布受入と、P0の長文/最大候補数の実forward参照拡充。今回のPATH隔離はPythonをアンインストールしたclean host試験ではないため、計画の「Pythonが存在しない環境」での受入条件は未完了。OS sandbox/RSS上限、子孫processの終了、queue/累計予算、認識品質改善、校正は保証しない。KazeNhanh本体への変更は行っていない。

## 2026-10-10: P2の独立Rust実行と互換処理

固定0.8B・text-onlyのP2互換処理を実装し、保存済み公式参照3件に対する受入基準を満たした。requestからprompt/chat prefixを独立生成し、資産検証、tokenize、24層forward、readout、候補分布、選択/保留までRust CLIで完結する。coreの`DecisionProvider`を実装する`RustProvider`も追加した。Pythonは開発用の照合harnessのみで、CLIの資産固定・通常実行には不要。[実行手順](../runtime/rust/README.md)、[照合JSON](p2-validation.json)、[境界JSON](p2-boundaries.json)、[依存監査](rust-dependency-audit-p2.json)を参照。

- Rust用bundle `kaze_judge.rust_jeff_bundle.v1`と`jeff lock/prepare/decide`を追加。旧Python schemaとmanifestは維持した。
- 11資産の完全な集合とSHA-256、固定config/template、全tensor名/shape/dtype、255回答code/token ID対応、policy、prompt/runtime build fingerprintを検証する。重複JSON key、未知manifest field、不正path、資産のsymlink/reparse pointを拒否する。
- 人工3ケースでprompt bytes、token IDs、候補順、token数、選択/保留が一致。分布の最大絶対誤差は2.384e-7 / 6.333e-8 / 5.066e-6で、事前基準1e-4以下。128/128/206 tokens、各1 forward。
- 実CLIでtoken予算不足、1 ms timeout、適用外requestのProvider未起動、重複request key、bundleのbuild/hash/必須集合/path/未知field異常の9ケースを確認。
- forwardなしの実tokenizer境界検証で128ちょうどを許可、127を拒否。255候補は参照と同じ3206 tokens、3205上限と256候補を拒否。呼出側が大きな上限を渡してもruntimeの8192-token ceilingを維持する。
- Rust packageの9試験、既存core/processの11試験、KazeNhanh adapterの8試験が成功。Rust packageのclippyとfmtも成功。固定Windows executableの138依存を初期監査し、既知の禁止依存/feature、esaxx C++有効化なし。直接DLL importにはWindows OS/CRTとVCRUNTIME140.dllを含む。配布受入の包括監査はP4で継続する。

次はP3のRust worker、親によるkill/wait、KazeNhanh CLIのbackend選択。現native Providerはhash read・tokenize後・各層の前後・出力後の協調的deadline検査で、演算途中の即時停止を保証しない。検証済みローカル資産を実行中に変更しないことが前提。日本語認識品質、長文/255候補の実forward、性能SLO、Python未導入環境での配布受入は未評価。

## 2026-10-10: P0拡充とP1のRust実モデル実証

P0の参照を3ケースへ拡充し、P1の演算表・固定依存・実モデルforward・初期依存監査・採用判断を記録した。Candle CPUをP2の基盤として暫定採用する。詳細は[Rust backend評価](rust-backend-assessment.md)、[検証JSON](p1-validation.json)、[packageの実行手順](../runtime/rust/README.md)を参照。

- 候補順反転、ASR・全半角・結合文字・改行の2ケースを追加。公式predict/worker間の分布誤差は3ケースとも0.0。
- Rustのtoken IDsは3ケースとも完全一致。Rustの24層forward/readoutを実行し、候補分布の最大絶対誤差は2.384e-7 / 6.333e-8 / 5.066e-6。全ケースで選択/保留が一致し、仮目標1e-4を満たした。
- [実tokenizerの境界検証](../tests/fixtures/jeff-golden/boundaries.json)を追加。128 tokensちょうどは許可、127上限ではbudget_exceededでforward 0回。255候補は3206 tokensでprepare成功、256候補はinvalid_request。255候補の実forwardはしていない。
- 閾値ちょうどは選択、確率/margin閾値のnextafter直上では保留、同点も保留を確認。
- 固定Windows buildの137依存・feature/build script・直接DLL importを初期監査。esaxx C++機能と外部推論runtimeは非有効。配布受入の包括監査は残っている。
- Rust新packageの演算試験2件、core/process 11件、Python 14件が成功。新packageのclippy/fmt成功。

次はP2の独立prompt生成、Rust用bundle/loader、token予算と厳格な設定検証。現プローブはgolden promptを入力する開発ツールで、実運用Providerやdeadline保証はまだ持たない。P0は長文・最大候補数の実forward等の参照拡充を継続する。日本語認識品質と校正は未評価。

## 2026-10-09: P0の初回実モデル照合

P0着手。実モデル資産の取得・固定、参照環境の導入、人工候補1件の公式/worker照合、Rust process経由の実行まで成功した。RustでモデルforwardするP1/P2は未着手。

### 実施した作業

- `vendor/jeff`へ公式sourceを取得し、commit `3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0`で固定。clean checkoutを確認。
- 旧`mstrasser/Jeff-Qwen3.5-0.8B`の固定revisionは現在`jeff-legacy/Jeff-Qwen3.5-0.8B`へredirectされることを確認。revision `51552f39a943d62e8387c4ea5e17026a1408729f`から重み・readout・tokenizer・config・chat template・processor config・README・LICENSE・NOTICEを取得。
- モデル重み1,706,027,688 bytesのSHA-256をHugging Faceの固定revision metadataのLFS hashと照合。hashは`080ff4a5b419aaf59f5c5059c492de88a063f34087361fb3c3ff120d95d5396f`。
- 取得した11資産すべてについて、固定revision metadataのLFS SHA-256またはGit blob IDとの一致を確認。golden JSONとlocal manifestの記録済みhashも再照合した。
- sourceはMIT、checkpointのLICENSEはApache-2.0、NOTICEにはQwen3.5-0.8B由来と記載されていることを確認。ライセンスファイルはbundleへ含めた。配布時のbase modelと推移的依存を含むNOTICE整備は残作業。
- 同梱Python 3.12.14を使用。既存uv 0.12.17がupstream要求`>=0.12.19`に届かなかったため、プロジェクト専用`.venv/tools`へuv 0.12.19を導入。sourceやlockfileは変更せず、`uv sync --frozen --no-default-groups --no-install-project`で44 packageを`vendor/jeff/.venv`へ導入。学習groupは導入していない。
- upstreamのruntime依存9件のversion完全一致を検査。torch 2.14.0 CPU、transformers 5.17.0を使用。
- workerが要求していた非公式`decision_config.max_options`を廃止し、実形式の`format_version`、255個の`codes`/`token_ids`、revision、temperature、prompt layoutを検証するよう修正。不正な回答語彙・重複・非有限値等の回帰試験を追加。
- `runtime/export_jeff_reference.py`を追加。公式predictの実forwardをhookし、入力tensorとshape/dtype、最終hidden state、mask前後logits、prompt bytesのdigestを記録。その後workerを独立cold実行し、分布と契約を照合する。
- `models/jeff-bundle.json`を作成。資産集合、source、workerのhashを固定し、exporterとRust CLIで再検証した。manifest・モデル・仮想環境はgitignore対象。

### 観測結果

入力は`examples/candidate-request.json`の説明用人工候補「節約する」「節税する」。元の順序を保持した。CPU FP32、1 thread、1質問、1 forward。選択policyは手順例のmin_probability=0.7 / min_margin=0.1で、校正済み閾値ではない。

| 項目 | 結果 |
| --- | --- |
| 入力token数 | 128 |
| temperature | 1.0845714325759162 |
| hidden state幅 | 1024 |
| originalの候補確率 | 0.9285950064659119 |
| alternativeの候補確率 | 0.07140493392944336 |
| 公式predictとworkerの最大絶対誤差 | 0.0（許容値1e-6） |
| 選択結果 | original |
| Rust LocalProcessProvider経由 | Completed、128 tokens、1 forward、同じ分布 |

参照データは[人工候補1件のgolden JSON](../tests/fixtures/jeff-golden/candidate-request.json)。hash・参照先は[jeff-reference.json](jeff-reference.json)にも記録した。bundle manifestは絶対pathを含むため、別のcheckoutで再作成したmanifest digestは変わり得る。移植比較ではprompt/token IDs/分布と個々の資産digestを照合する。

### 検証

- Rust core/process: 11件成功。Pythonの絶対pathを`KAZE_JUDGE_PYTHON`へ指定して実行。
- KazeNhanh adapter: 8件成功。
- Python: 14件成功。fixtureによる試験は実モデル検証と区別する。
- rootのall-features/all-targets clippy、fmt check成功。
- 上記の実モデル照合とRust CLI smoke成功。CLIのexit codeだけでなく`outcome.status=completed`を確認。

### 再実行

rootから以下を実行する。資産取得済みのローカル環境を前提とし、推論時のdownloadは行わない。

```powershell
$python = (Resolve-Path vendor/jeff/.venv/Scripts/python.exe).Path
$env:KAZE_JUDGE_PYTHON = $python
cargo test --locked --offline --all-features
& $python -B -m unittest discover -s runtime -p 'test_*.py'
& $python -B runtime/export_jeff_reference.py --manifest models/jeff-bundle.json --request examples/candidate-request.json --output experiments/runs/reference-repeat.json --max-input-tokens 512 --timeout-ms 120000
cargo run --locked --offline --features process --example jeff_decide -- $python models/jeff-bundle.json examples/candidate-request.json 120000 512
```

exporterの既存出力は上書きできないので、反復時は別名を指定する。worker変更時は古いmanifestで実行せず、資産を確認して別名のmanifestを作成する。

### 残作業と次の到達点

1. P0参照集合を拡充する。OCR/ASR、候補順入替え、日本語の正規化・特殊文字、token上限、最大候補数と選択/保留境界を含める。現時点で確認できた一致は1件のみ。
2. P1でCandle等の固定revisionを選び、依存と対応演算を監査する。実checkpointは24層中18層がlinear attention、6層がfull attention。hidden_size=1024。Qwen3一般の対応だけで互換性を判断しない。
3. Rustで同じ実資産・入力を1 forwardし、今回採取したhidden/logits/分布と比較する。内部position/attentionや各層の中間出力は差分調査に応じてexporterを拡張する。

今回の成功は、Rust側からPythonのJeffを正しく呼べたことと、移植の比較基準を作れたことを示す。日本語認識品質、校正、CPU SLO、Rust推論backendの成立は未検証。P0全体の受入は参照集合を拡充してから行う。
