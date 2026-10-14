# pure-jeff 0.2.0の公開（2026-10-14）

0.2.0を公開した。内容は次の3点で、出力は0.1.1とbit単位で同じ。

- Native推論の速度：128〜8192 tokensのすべての長さで、公式Jeff以上。
- メモリの削減。
- FP32保持のopt-in。

変更点は[CHANGELOG](../CHANGELOG.md)に、利用者向けの説明は[Release notes](release-notes-v0.2.0.md)（[GitHub Release](https://github.com/siska-tech/pure-jeff/releases/tag/v0.2.0)）にある。公開前の検証は[最終受入](release-0.2.0-verification-2026-10-14.md)（PR #24）。

## 公開したもの

| 対象 | 内容 |
| --- | --- |
| crates.io | `pure-jeff` 0.2.0。commit `4572a8d`（PR #24のmerge）のclean treeから`cargo publish --locked`した。29ファイル、253.1 KiB（圧縮55.9 KiB）、checksum `1559d0d0231c3801…`、MSRV 1.88。0.1.0と0.1.1はyankしていない |
| docs.rs | 0.2.0の文書のbuildに成功した |
| tag | `v0.2.0`（注釈付き、`4572a8d`） |
| GitHub Release | `pure-jeff 0.2.0`（Latest）。本文は`release-notes-v0.2.0.md`から見出しを除いたもの |
| Webデモ | `4572a8d`からbuildして再deployした（Version `37de8ccf-534b-4e46-ba45-bcfcb86fb300`）。詳細は[公開の記録](web-demo-deployment-2026-10-12.md#再deployv0202026-10-14) |

## 公開の途中の出来事

- **crates.ioの認証**：最初の`cargo publish`は、tokenの期限切れで認証に失敗した（403）。何も公開されていないことを確認し、tokenを作り直してから実行した。
- **Cloudflareのaccount**：`wrangler deploy`の時点で、loginしたaccountから2つのCloudflare accountが見えた。これまでと同じ`siska-tech`（`99360706…`）を`CLOUDFLARE_ACCOUNT_ID`で指定した。

## 公開後の確認

- **crates.ioのAPI**：最新versionが0.2.0で、yankされていないことを確かめた。
- **crates.ioだけからのbuild**：新しいprojectで`cargo add pure-jeff@0.2.0`し、crates.ioだけからbuildした（candle-core 0.11.0）。`tools/consumer`で次を確かめた。
  - golden 7件：最大差3.457e-6。保持あり・なしで確率がbit一致した。
  - catalog 39入力：数値gateに合格（最大差3.96e-6）。結果は、公開前のpackage検査とすべて一致した。
- **Webデモの公開サイト**：Chrome・EdgeのE2Eが全14条件に合格した。確率は、前回の公開版（0.1.1）とbit単位で一致した（[公開の記録](web-demo-deployment-2026-10-12.md#再deployv0202026-10-14)）。

## 公開後に必要なこと

- **CLI**（`jeff`）で使うbundle manifestは、0.2.0でbuildしたCLIで`jeff lock`し直す。runtime build hashが変わったため。
- **ライブラリ**：`LoadOptions::require_runtime_build`を使う場合だけ、manifestを作り直す。
- **`LoadOptions`をstruct literalで作っているcode**には、`..LoadOptions::default()`が要る。
