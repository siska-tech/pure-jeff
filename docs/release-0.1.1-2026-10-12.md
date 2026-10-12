# pure-jeff 0.1.1の公開（2026-10-12）

Native推論の高速化とメモリ削減（#6、#7、#9）を含む0.1.1を公開した。出力は0.1.0とbit単位で同じ。変更点は[CHANGELOG](../CHANGELOG.md)、利用者向けの説明は[Release notes](release-notes-v0.1.1.md)（[GitHub Release](https://github.com/siska-tech/pure-jeff/releases/tag/v0.1.1)）にある。

## 公開したもの

| 対象 | 内容 |
| --- | --- |
| crates.io | `pure-jeff` 0.1.1。commit `12a8f15`（PR #11のmerge）のclean treeから`cargo publish --locked`。29ファイル、230.7 KiB（圧縮50.2 KiB）。0.1.0はyankしていない |
| docs.rs | 0.1.1の文書のbuildに成功した |
| tag | `v0.1.1`（注釈付き、`12a8f15`） |
| GitHub Release | `pure-jeff 0.1.1`（Latest）。本文は`release-notes-v0.1.1.md`から見出しを除いたもの |
| Webデモ | `12a8f15`からbuildして再deployした（Version `f3375f3e…`）。詳細は[公開の記録](web-demo-deployment-2026-10-12.md#再deployv0112026-10-12) |

## 公開前の確認（PR #11）

- 出力が0.1.0と同じか
  - リポジトリ内のbuild：公式参照7件で、最終hidden stateのSHA-256が0.1.0と一致した。
  - crates.ioの依存だけでbuild：crates.ioの0.1.0と0.1.1のpackageで、確率（全268個）がbitまで一致し、判断も一致した。
- clean consumer：`tools/check_package.py --manifest`で、公式参照7件に合格した。
- MSRV：Rust 1.88.0で`cargo check`できた。
- Windows・Linux CI：8件すべて合格した。
- Wasm：probeとengineのbuild、host pathの検査、wasm32＋SIMD128での一致試験に合格した。

詳細はPR #11の本文とCHANGELOGの「Verification」にある。

## 公開後の確認

- crates.ioのAPIで、最新versionが0.1.1であり、yankされていないことを確かめた。
- 新しいprojectで`cargo add pure-jeff@0.1.1`し、crates.ioだけからbuildした（candle-core 0.11.0）。`tools/consumer`の検査で、公式参照7件に合格した。判断・tokens数は一致し、最大確率差は3.457e-6（公開前と同じ）。
- Webデモの公開サイトで、Chrome・EdgeのE2Eが全条件に合格した。確率は、前回の公開版とbit単位で一致した。

## 性能について

- 性能の数値は、[benchmark](benchmark-results-2026-10-12.md)（リポジトリ内のbuild、固定revisionのCandle、1 thread）による。
- crates.io版のCandleでの性能は測っていない。
- ブラウザでの推論速度も測っていない。

## 公開後に必要なこと

- CLI（`jeff`）で使うbundle manifestは、0.1.1でbuildしたCLIで`jeff lock`し直す。runtime build hashが変わったため。
- ライブラリでは、`LoadOptions::require_runtime_build`を使う場合だけ、manifestを作り直す。
