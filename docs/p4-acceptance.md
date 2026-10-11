# P4受入の実施記録

2026-10-10。P4は実施中。Rust backendの推奨経路への切替と配布受入はまだ行わない。P3で検証した実行ファイルを維持し、診断用profiler・package verifier・開発harnessを追加した。

ユーザー確認済みの方針：許容時間・メモリ上限は未定なので、今回は実測のみで性能の合否を付けない。N-bestと確認済み転記が揃った品質データはまだなく、準備条件を記録する。

| 条件 | 現状 | 証跡・残作業 |
| --- | --- | --- |
| 数値互換 | 人工7件で一致 | [6件の追加照合](extended-migration-validation.json)、[8192 tokenの実forward](token-limit-forward-validation.json)、[上限の拒否境界](token-limit-boundaries.json)。上限ちょうどの成功、予算1不足と入力1超過の拒否を確認 |
| 性能 | 探索的測定 | [実測JSON](p4-benchmark.json)。各ケース・backend 5回、SLO未確定、正式受入なし |
| 持ち運び | ローカル再配置で成功 | [p4c package検証](p4c-portable-validation.json)。Python/Cargoを子のPATHから除き、checkout外のcwdから起動 |
| 依存/NOTICE | 138件の本文・索引を監査 | [依存監査](rust-dependency-audit-p3.json)、[収集監査](p4-license-review.json)。136件で本文あり、自プロジェクト2件は未指定。厳密な配布対象/base model/NOTICEの最終レビューは残る |
| 日本語品質 | 評価入力が不足 | [入力監査](p4-quality-input-audit.json)。OCR 15行に明示N-bestなし、8行の転記未確認、held-out splitなし |
| clean host | 未実施 | Python/外部推論runtime未導入Windowsホストで再検証する。PATH隔離とは区別 |
| 通常CI | 定義追加・ローカル同等試験成功 | [workflow](../.github/workflows/rust-contracts.yml)。GitHub上の実行は未確認。隣接KazeNhanh依存のadapter試験は別ローカル検証 |

## 性能の測定範囲

`runtime/benchmark_rust_runtime.py`は同一Windows機・CPU FP32・1 thread・同じ11資産・同じpolicyで、Rust/Python workerをケースごとに交互の順で起動する。毎回新規process・新規model loadで、OS file cacheは消去しない。モデルを保持したwarm性能や、ディスクcacheが空の起動時間ではない。初回の測定はpackage作成のI/Oが混ざったため中断し、成果の数値には使用しなかった。記録した測定中は追加のbuild/copy/モデル検証を並行実行しない。

worker全体の時間には起動、hash、load、推論、結果ファイル出力を含む。PythonではPython/PyTorch/transformersの起動とsource/dependency検証も含む。Rust/Pythonでforwardだけの速さを比較した値とは扱わない。native process CLIも別に1回測定し、parentの起動・監視込みの時間を記録する。

メモリはWindowsの`PeakWorkingSetSize`。mapped/shared pageを含み、private RSSではない。直接起動したprocessのOS peak counterを10 ms間隔で読む。終了後queryの成否も保存し、最後のsample以降のpeakを捕捉できない可能性も残す。native CLIのメモリ値はparentのみで、Rust child peakはworker測定を参照する。Python interpreterは下記のprocess-tree補足測定で確認する。backend同時実行時の合計メモリ上限やOSのRSS制限を実証したものではない。

診断用`profile` exampleはbundleのhash/metadata検証、tokenizer load/語彙検証、prompt/tokenize、model mmap、forward、readout/policyを計測する。BF16重みの読込・FP32変換はforward中に行うため、forwardに含む。mmap時間をモデルload全体と読み替えない。段階値は各ケース1回の診断値で、段階別p95ではない。

p50/p95はnearest-rank。5件でp95は最大値になるため、安定したtail latencyの推定ではない。許容時間・メモリ上限が未確定なので、この測定からSLOの合格やRust backendの採用を決めない。

| 人工参照ケース | tokens | Rust worker p50 / p95（秒） | Python worker p50 / p95（秒） |
| --- | --- | --- | --- |
| candidate-request | 128 | 5.52 / 6.28 | 18.53 / 92.34 |
| reversed | 128 | 6.67 / 7.83 | 21.70 / 26.66 |
| asr-unicode | 206 | 6.87 / 7.46 | 16.24 / 16.92 |

各cellは5回の実測。candidate-requestのPython 2回目に92.34秒の外れ値があり、除外していない。原因は特定しておらず、低い中央値だけで期限内完了を保証しない。別に計測したnative process CLIの単発値は5.55〜7.51秒。診断用のbundle hash/metadataは約1.13〜1.17秒、tokenizer load/語彙検証は約0.79〜0.88秒、重み変換を含むforwardは約3.36〜4.80秒だった。

メモリのscope確認で、Windows venvの`python.exe`が実interpreterを子として起動することを検出した。元benchmarkのPython約5 MiBはlauncherのみであり、実推論メモリとして比較しない。raw測定値を変更せずmetadataを訂正し、元harnessとraw recordを`experiments/runs/benchmark-harness-v1.py`、`p4-benchmark-raw.json`に保持した。

[process-tree補足測定](p4-worker-tree-memory.json)ではToolhelpで子を追跡し、Python interpreterのOS peak working setを約3799.66〜3812.95 MiB（3.71〜3.72 GiB）と確認した。Rust workerの5回測定内のpeak最大は約1526.97〜1529.34 MiB（約1.49 GiB）。Python側は各ケース1回の補足測定で、メモリのp50/p95比較ではない。process treeの同時working setのsample最大も保存するが、shared pageの重複計上とsample間の取りこぼしがあり、private RSSや厳密な合計peakではない。

```powershell
cargo build --release --locked --offline --manifest-path runtime/rust/Cargo.toml --example profile
& vendor/jeff/.venv/Scripts/python.exe -B runtime/benchmark_rust_runtime.py --executable runtime/rust/target/release/jeff.exe --profiler runtime/rust/target/release/examples/profile.exe --manifest models/jeff-rust-bundle-p3.json --python vendor/jeff/.venv/Scripts/python.exe --python-manifest models/jeff-bundle.json --repeats 5 --output experiments/runs/p4-benchmark-repeat.json
& vendor/jeff/.venv/Scripts/python.exe -B runtime/measure_worker_tree.py --python vendor/jeff/.venv/Scripts/python.exe --manifest models/jeff-bundle.json --output experiments/runs/p4-memory-repeat.json
```

## 現在のローカルpackage（p4c）

`experiments/runs/portable-p4c` は266 payload files、1,735,414,269 bytes。初回p4bの推論exe・11 checkpoint資産をそのまま維持し、依存の補足MIT本文、Jeff参照実装のMIT本文、出典索引、`THIRD_PARTY_NOTICES.txt` を追加した。[package検証](p4c-portable-validation.json)、[本文収集・索引監査](p4-license-review.json)を参照。Python/Cargoを子のPATHから除いた再配置smokeと4破損ケースの拒否に成功した。

`pulp-wasm-simd-flag` 0.1.1の欠落本文は、同じ固定VCS commitのrepository MIT本文とpackage宣言を確認し、同commitの取得済みpulp crateの本文から補完した。[固定出典・hash](../runtime/licenses/supplements.json)を保持し、builderは依存identity/source/commit/hashと本文hashの不一致を拒否する。補足の改変、別version、source改変、path逸脱に対する試験を追加し、Python計18試験が成功した。

Jeff参照実装のMIT本文は固定元manifestのhashと照合し、[出典索引](../runtime/licenses/reference-sources.json)と共に保存した。NOTICE索引は監査対象138依存すべてを列挙する。136件は本文あり、残る2件はプロジェクト自身のlicense未指定。本文収集・索引の検証は配布条件への最終適合判断ではなく、base modelと第三者NOTICEのレビュー、clean host、品質/SLO受入は未完了。

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/package_rust_runtime.py --executable runtime/rust/target/release/jeff.exe --verifier runtime/rust/target/release/examples/verify_portable.exe --manifest models/jeff-rust-bundle-p3.json --audit docs/rust-dependency-audit-p3.json --destination experiments/runs/portable-repeat
& vendor/jeff/.venv/Scripts/python.exe -B runtime/validate_portable.py --package experiments/runs/portable-repeat --output experiments/runs/portable-validation-repeat.json
& vendor/jeff/.venv/Scripts/python.exe -B runtime/audit_license_package.py --package experiments/runs/portable-repeat --previous-package experiments/runs/portable-p4b --output experiments/runs/license-review-repeat.json
```

builderは収集helperと入力索引のhashもpackageへ記録する。初回builderは `experiments/runs/package-builder-p4b.py` に保存し、以下の初回証跡を上書きしていない。

## 初回ローカルpackage（p4bの記録）

`experiments/runs/portable-p4b`に`jeff.exe`、Rust製`verify.exe`、11 checkpoint資産、相対bundle、smoke request/期待値、license本文と索引、依存監査、全payloadのbytes/SHA-256索引を作成した。261 payload files、1,735,391,870 bytes（package.json自身を除く）。モデル重みは複製した元safetensorsで、変換しない。KazeNhanh adapter executableはこの最小packageには含めない。

`verify.exe`は自身の所在を基準に全payloadの集合・hash・path・reparse pointを検査し、Rust workerで実モデルsmokeを行う。package.jsonは信頼するローカル索引であり、署名付きの配布元認証ではない。package.jsonのSHA-256は開発側の検証JSONにも保存する。通常実行・資産検証にPython/Cargo/PowerShell scriptは不要。Windows OS/CRT、VCRUNTIME140.dllは必要。

追加したprofiler/verifierの[直接PE import記録](p4-tool-imports.json)も保存した。直接importだけで、推移的依存や動的loadを含む配布監査の完了とは扱わない。

```powershell
cargo build --release --locked --offline --manifest-path runtime/rust/Cargo.toml --example verify_portable
& vendor/jeff/.venv/Scripts/python.exe -B runtime/package_rust_runtime.py --executable runtime/rust/target/release/jeff.exe --verifier runtime/rust/target/release/examples/verify_portable.exe --manifest models/jeff-rust-bundle-p3.json --audit docs/rust-dependency-audit-p3.json --destination experiments/runs/portable-repeat
& experiments/runs/portable-repeat/verify.exe
```

builder/腐敗検証harnessだけが開発用Pythonを使用する。builderは新規workspace内ディレクトリに限定し、既存packageを上書きしない。license本文は固定cargo metadataから得た保守的なbuild graphで収集し、build/dev依存も含む。Candle workspaceの共通licenseはrepository上位から収集した。以下の未達をpackageの`release_ready=false`へ記録した。

- `kaze_judge`と`kaze_judge_jeff`はlicense宣言と本文がない。勝手にライセンスを選定していない。
- `pulp-wasm-simd-flag`はMIT宣言だが、取得済みcrateに本文がない。Windows実行/配布対象かを厳密に整理し、必要な本文を確認する。
- base modelと第三者NOTICEの配布レビュー、署名、Python未導入clean hostでの実証が残る。

## 品質評価へ進む条件

既存KazeNhanhのOCR development observation 15行を監査した。7行はuser-confirmed、8行はimage transcription unconfirmedで、いずれにも明示N-bestがない。さらに先頭5行は行内document_idが欠測。これらをheld-out品質評価集合として扱わず、正解転記から候補を作ってモデルへ渡すこともしない。

recognizerが出した原文1-best/N-best、origin/document/speaker、確認済み転記と候補正誤、開発・校正・testの非重複splitを用意する。routingと確率/margin閾値を校正側で固定してから、追加検出と追加誤警報を別々に集計する。Jeffの候補確率を認識正解率へ読み替えない。実ASR品質の入力も未整備。
