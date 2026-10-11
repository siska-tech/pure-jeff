# 移行照合用の公式参照

この集合は説明用の人工入力であり、日本語OCR/ASR品質の評価データではありません。固定source、checkpoint、CPU FP32・1 threadの公式predictとPython workerを比較し、prompt、token IDs、最終hidden state、logits、候補分布、判断を記録しています。資産・source・環境の固定情報は各JSONと `docs/jeff-reference.json` を参照してください。

追加3入力は `runtime/create_migration_requests.py` で生成した `tests/fixtures/jeff-requests/` にあります。長文は繰り返しの日本語、最大候補数は255候補、特殊文字はchat delimiterの文字列、全角英数字、結合文字、絵文字を含みます。delimiterの無害化を保証する試験ではなく、公式実装とのtokenize・推論の一致を検査します。

参照の再採取例（既存出力の上書きは禁止）:

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/export_jeff_reference.py --manifest models/jeff-bundle.json --request tests/fixtures/jeff-requests/maximum-candidates.json --output experiments/runs/maximum-reference-repeat.json --max-input-tokens 8192 --timeout-ms 600000
```

Rust workerとの全件照合:

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/validate_migration_cases.py --executable runtime/rust/target/release/jeff.exe --manifest models/jeff-rust-bundle-p3.json --output experiments/runs/extended-validation-repeat.json
```

harnessは子のPATHからPythonを除き、独立prompt/token IDs、候補順、分布誤差1e-4以内、判断、1 forward、token予算ちょうどの成功と1 token不足の拒否を検査します。Python未導入ホストでの配布検証や性能SLOの受入とは区別します。

## 8192 token上限

`runtime/create_token_limit_requests.py` は固定公式processorを使い、原文とoriginal候補の末尾へ ` x` を4032回追加し、全promptが8192 tokensになる入力を生成します。alternative候補に ` y` を1回追加した8193 tokensの入力も生成します。どちらも反復文字を用いた人工的な上限試験です。生成済みファイルの上書きは禁止です。

8192 tokensの公式参照の再採取は、上記exporterのrequestを `tests/fixtures/jeff-requests/token-limit-8192.json` に変更します。8193 tokensの入力は拒否用で、成功goldenは作成しません。

```powershell
& vendor/jeff/.venv/Scripts/python.exe -B runtime/validate_migration_cases.py --executable runtime/rust/target/release/jeff.exe --manifest models/jeff-rust-bundle-p3.json --cases token-limit-8192 --output experiments/runs/token-limit-forward-repeat.json
& vendor/jeff/.venv/Scripts/python.exe -B runtime/validate_token_limit_boundaries.py --executable runtime/rust/target/release/jeff.exe --manifest models/jeff-rust-bundle-p3.json --python-manifest models/jeff-bundle.json --output experiments/runs/token-limit-boundaries-repeat.json
```

境界harnessは公式モデルをロードし、workerと同じ `min(budget, 8192)` をprepareに渡して切り捨てなしの成功/拒否を検査します。公式prepareのforward hookは0回であることを確認します。Rustではprepareと拒否入力のnative process結果を検査し、上限内の実forward照合は別harnessで行います。全参照を一括照合する場合は `--cases candidate-request reversed asr-unicode long-text special-token-text maximum-candidates token-limit-8192` を明示します。
