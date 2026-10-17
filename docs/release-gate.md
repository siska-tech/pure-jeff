# リリース前のモデル付きgate（必須）

通常のCI（Windows、Linux、package）はモデルを使わない。crateの公開とWebデモの再deployの前には、リリース候補のcommitで以下をすべて実行し、合格した証跡を`docs/research/`に残す。1つでも不合格なら公開しない。閾値は[性能同等の計画](benchmark-parity-plan.md)で事前登録したものを使い、結果を見てから変えない。初回の実施記録は[0.2.0の最終受入](release-0.2.0-verification-2026-10-14.md)。

## 準備

- **checkpoint・公式Jeff・bundle**：[bench/README](../bench/README.md)の「Setup」のとおり用意する。
  - checkpoint revision `51552f39…`。
  - 公式Jeff `3720e7c…`の環境。
  - Native bundleは`jeff lock`で、候補commitのbuildに合わせて作り直す（runtime build hashが変わるため）。
- **source**：候補commitがcleanであること。各runの`preregistration.json`に、commit・dirty・exeとbundleのhashが残る。
- **他の作業**：測定中は、build・install・downloadをしない。driverが開始時と各sessionの前に確かめる。

## 1. 公開crate（crates.io版Candle）

```powershell
python -B tools/check_package.py --work <新しいdir> --manifest models/<bundle>.json --cases --msrv 1.88.0
```

- **package**：中身と大きさ、`cargo publish --dry-run`。
- **利用者build**：`[patch]`なしで、crates.io版Candle 0.11.0からbuildする。
- **golden 7件**：公式参照との差は≤1e-4、判断・token数は一致。`LoadOptions::retain_f32`の有無で、確率がbit一致すること。
- **catalogの全入力**（`bench/cases/catalog.json`）：共通の数値gate（`bench/validate.py`）に合格すること。
- **MSRV**：Rust 1.88.0で`cargo check`が通ること。

## 2. CLI（固定Candle版）

```powershell
python -B runtime/validate_migration_cases.py --executable runtime/rust/target/release/jeff.exe --manifest models/<bundle>.json --cases candidate-request reversed asr-unicode long-text special-token-text maximum-candidates token-limit-8192 --output <file>
python -B runtime/check_rust_boundaries.py --executable runtime/rust/target/release/jeff.exe --manifest models/<bundle>.json --output <file>
runtime/rust/target/release/examples/timeout_reuse.exe models/<bundle>.json tests/fixtures/jeff-golden/token-limit-8192.json tests/fixtures/jeff-golden/candidate-request.json 3
```

- **golden**：worker processで判定し、子processのPATHからPythonを除く。
- **境界**：token予算ちょうどは成功、1 token不足は拒否。255候補は成功、256候補は拒否。8193 tokensは拒否。
- **timeout**：常駐APIでtimeoutした後、同じModelを再利用できること。
- **契約試験**：process境界、timeoutとkill、異常応答、bundle照合は、CIの`cargo test`に含まれる。

## 3. 性能同等（事前登録のbenchmark）

```powershell
python -B bench/run_benchmark.py --stage short ...   # 128〜512、各群の同等判定
python -B bench/run_benchmark.py --stage long ...    # 874／3206／8192
python -B bench/run_benchmark.py --stage oneshot ... # 既定経路
python -B bench/compare_runs.py <前回のone-shot> <今回のone-shot>
python -B bench/request_curve.py ...                 # 1／10／100要求、FP32保持の損益分岐、メモリ
```

公開した版が出た後に、crates.io版の依存での速度も同じ計画で測る：`bench/build_cratesio_resident.py`で計測exeとbundleを作り、`--native-build crates-io --resident-exe … --rust-manifest …`でshortとlongを実行する（[0.2.0の例](benchmark-cratesio-2026-10-17.md)）。

- **数値gate**：全run・全系統の全判断で違反がないこと。反復はbit一致すること。
- **short・long**：各入力群が同等（点推定≤1.00、片側95%上限≤1.05）であること。
  - 「遅い」群や「証拠不足」の群があれば、その範囲の同等を主張しない。
- **one-shot**：前回の公開版との比較で、中央値・peakの5%を超える退行がないこと。
  - 出力を変えない変更なら、確率がbit一致すること。

## 4. Webデモ（現行engine）

```powershell
python tools/build_wasm.py engine --target-dir <dir>
python -B tools/check_no_host_paths.py <dir>/wasm32-unknown-unknown/release/pure_jeff_web_demo.wasm
python -B apps/web-demo/build_demo.py --engine-wasm ... --manifest models/<bundle>.json --output <dist>
python -B apps/web-demo/run_w3.py --browser <chrome> --dist <dist> --manifest models/<bundle>.json --output <dir>   # Chrome・Edge
python -B bench/run_benchmark.py --stage wasm ...
```

- **E2E**：download、samples、取消と復帰、reload、Cache、削除、公式参照との一致。
- **時間・メモリ**：現行engineの値を記録する。凍結した研究用probeの数字を、現行engineの値として引用しない。
- **deploy用のengine**：host pathの検査に合格したbuildを使う。
  - rustupで`rust-src`を入れた環境では、標準libraryのpathが埋め込まれて不合格になる。その場合はCIのbuildを使うか、rust-srcのない環境でbuildする。
- **Native専用の機能はWasmに適用しない**：FP32保持と共有bufferはWasmに適用しない（browserのメモリは別に評価する）。

## 5. 記録

- **結果文書**（`docs/`）：環境ごと（基準機のWindows、独立のCPU、Linux）に分けて、短文と全長それぞれの達成・未達・証拠不足を書く。
- **証跡**（`docs/research/`）：source、exe、入力のhash、生ログ、統計、NOTICE、既知の限界。
- **CHANGELOGとRelease notes**：「Verification」に要点を書く。
