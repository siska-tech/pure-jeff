# W4：Webデモの配信構成（Cloudflare Pages＋R2）

2026-10-11調査。Webデモ（`apps/web-demo`）を公開する場合の構成・料金・制約を整理した。**remote・Cloudflareのaccount・domain・有料設定はまだ何も作っていない。** 料金と制約は下の出典（Cloudflare公式文書）を2026-10-11に確認した値で、変わることがある。公開前に必ず再確認する。ローカルで模した検証の結果は[W4 E2E](web-demo-w4-results.md)にある。

## 構成

| 置き場所 | 中身 | 大きさ |
| --- | --- | --- |
| Cloudflare Pages（`https://<project>.pages.dev`または独自domain） | `index.html`、`app.js`、`engine-worker.js`、`style.css`、`engine.wasm`、`demo-config.json`、`samples.json`、`build-info.json`、`licenses/` | 約6 MB、13 file。最大は`engine.wasm`（4.7 MB）と`licenses/THIRD_PARTY_LICENSES.txt`（1.2 MB） |
| R2 bucket（独自domainで公開。例：`https://models.<domain>`） | `model/manifest.json`、`decision_config.json`、`tokenizer.json`、`readout.safetensors`、`model.safetensors`、`LICENSE`、`NOTICE` | 約1.73 GB。最大は`model.safetensors`（1.71 GB） |

```powershell
python apps/web-demo/build_demo.py --engine-wasm <engine.wasm> --manifest models/jeff-rust-bundle.json `
  --model-base-url https://models.<domain>/model/ --output dist
# dist/ を Pages へ。model/ の7 file（bundle manifest、checkpointの4資産、LICENSE、NOTICE）を R2 の model/ へ
```

ページは`demo-config.json`のSHA-256で各fileを照合するので、R2の中身がbuildと違えば読み込みは失敗する。重みを配る場合、Apache-2.0の条件としてcheckpointの`LICENSE`と`NOTICE`をR2にも置く（`build_demo.py --copy-model`の出力と同じ組み合わせ）。

### R2のCORS

別originのページから読むには、bucketにCORSが要る。ページのfetchは単純なGETなので、preflightは発生しない。

```json
[
  {
    "AllowedOrigins": ["https://<project>.pages.dev"],
    "AllowedMethods": ["GET", "HEAD"],
    "MaxAgeSeconds": 86400
  }
]
```

CORSの変更が独自domainのcacheに反映されるには、cacheのpurgeが要る場合がある。

### Pagesの`_headers`（案、未検証）

```
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Content-Security-Policy: default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self' https://models.<domain>; img-src 'self' data:; style-src 'self' 'unsafe-inline'
/engine.wasm
  Content-Type: application/wasm
```

`app.js`は分布barの幅をstyle属性で設定するため、`style-src`に`'unsafe-inline'`が要る（CSS classへ移せば不要になる）。CSPはまだ実ブラウザで検証していない。SharedArrayBufferを使わない（single-thread）ので、COOP／COEPは不要。

## 料金（2026-10-11時点の公式表）

- **R2 Standard**：保存 $0.015／GB-month、Class A $4.50／百万件、Class B $0.36／百万件、egressは無料。
- **R2の無料枠（毎月）**：保存10 GB-month、Class A 100万件、Class B 1,000万件。
- **Pages Free**：月500 build、1 siteあたり20,000 file、1 fileあたり25 MiB。

この構成での見積もり：

- 保存は1.73 GBで、無料枠に収まる。
- 1回のモデル取得で、ページはGETを5件（manifestと4資産、Class B）行う。無料枠のClass Bで、月に約200万回の取得に相当する。それを超えた分は、100万回の取得あたり約$1.8。egressは無料。
- 独自domainの費用は別にかかる。

R2を有効にするときに支払い方法の登録が必要かどうか、無料枠を超えたときに自動で課金されるかは、account側で確認する（未確認）。

## 制約と注意

- **CDNにcacheされない**：Free／Pro／Businessのcacheは1 fileあたり512 MBまで。`model.safetensors`（1.71 GB）はedgeにcacheされず、取得のたびにR2から読む。egressは無料だが、遠い地域では遅くなる可能性がある。対策として、512 MB以下に分割して配る案がある。その場合はWorkerが分割fileを順に同じbufferへ書き、hashを通しで計算すればよく、engineの変更は要らない（未実装）。
- **r2.devは使わない**：`r2.dev`のURLは開発用で、rate limitがある。公開には独自domainが要る。
- **利用者の負担**：初回に約1.73 GBを取得する。ブラウザには約2.4 GiBのWasmメモリと、4 GiB超のWorking Setが要る（W2／W3の観測）。メモリの少ない端末やモバイルは未検証。
- **誰でも取得できる**：公開bucketなので、モデルは誰でも直接取得できる。重みの再配布に当たる（[ライセンスの未決事項](licensing.md)の4）。

## 代替案：Hugging Faceから直接取得

固定revisionのresolve URL（`https://huggingface.co/jeff-legacy/Jeff-Qwen3.5-0.8B/resolve/51552f39…/<file>`）は、任意のOriginにCORSを許可する。redirect後のCDNの応答も`access-control-allow-origin: *`を返すことを確認した。

- 利点：自前で重みを再配布しない。保存・配信の費用がかからない。
- 欠点：第三者のrepo（名前が`jeff-legacy`）の存続とrate limitに依存する。bundle manifestはHugging Faceにないので、Pages側に置く必要がある。
- 未検証：ブラウザE2Eでの動作。`build_demo.py`は資産ごとに別のURLを指定できないので、manifestだけを別の場所に置くには変更が要る。

## 出典

- R2 pricing：https://developers.cloudflare.com/r2/pricing/
- R2 public buckets：https://developers.cloudflare.com/r2/buckets/public-buckets/
- R2 CORS：https://developers.cloudflare.com/r2/buckets/cors/
- Pages limits：https://developers.cloudflare.com/pages/platform/limits/
- Default cache behavior（cacheできるfileの大きさ）：https://developers.cloudflare.com/cache/concepts/default-cache-behavior/
