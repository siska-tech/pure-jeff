# commit hashの対応表

公開前に履歴を2回書き換えた。どちらもfileの内容（下記の1 fileを除く）、author、日時は変わっていない（commitごとに照合済み）。

1. 2026-10-11：commit messageからツールの帰属表示（trailer）を除いた。
2. 2026-10-12：証跡script `docs/research/wasm-demo/w2-2026-10-11/official-references/export_all.sh`の、利用者名を含むローカルの絶対pathを`${KAZEJUDGE}`に置き換えた（全commit）。commit messageが引用するhashも新しいhashに直した。

切り出し元のKazeJudgeも同じ理由でmessageを書き換えたため、切り出し元のcommitは`43f315b`から`885e7ff`（tree同一）になった。

証跡のJSON（事前登録、`build-info.json`）とローカルの出力directory名（例：`experiments/runs/bench-80e0cec`）には、記録したときのhashが残っている。証跡なので変更していない。文書中のcommit参照は現在のhashへ更新した。

| 現在 | 2026-10-11の書き換え後 | 当初 | commit |
| --- | --- | --- | --- |
| `23eed84` | `13a35d0` | `80e0cec` | Extract Pure Rust Jeff runtime, browser Wasm and web demo from KazeJudge |
| `03cdb71` | `76ab958` | `ed7f964` | Record one-thread benchmark: official Jeff, Rust Native, browser Wasm |
| `1e46f1e` | `d59163e` | `172d0ec` | Document how to run the benchmark harness |
| `2ced061` | `f3f6b49` | `8d26e83` | Plan OSS release and add pinned model fetch with hash verification |
| `02115b3` | `bac04cf` | `055e65c` | Let model-free test runs pass in a fresh clone |
| `00314a4` | `5e7feb0` | `a863642` | Audit dependency licenses and record attributions and open decisions |
| `c5ea383` | `a10368c` | `a22be0a` | Add a wasm export filter for the demo engine |
| `a6c2da3` | `dbc0400` | `a5c27c0` | Replace inherited CI with a full model-free GitHub Actions workflow |
| `4640b6f` | `080eb3a` | `19dedf2` | Record the clean-environment check and add a reusable script |
| `a496261` | `d1b928e` | `d4380ce` | Prepare the web demo for hosting (W4) |
| `90cb009` | `c54fc00` | `0d2f875` | Record W4 E2E results and the Cloudflare Pages + R2 hosting study |
| `8b2eb40` | `02ebd9c` | `d3fbf07` | Plan optional FP32 weight retention for the Native runtime |
| `385a723` | `a2c5b88` | `482106d` | Rewrite the README and docs for an independent project |
| `dc8b4b1` | `1f67bbe` | — | Update commit references after the message rewrite |
| `dcc7210` | `a1baf7e` | — | License pure-jeff under Apache-2.0 |
| `50d20bd` | `200df27` | — | Rename remaining KazeJudge-era names to pure-jeff ones |
| `a112b04` | `893a474` | — | Deploy the web demo as a Workers site fetching the model from Hugging Face |
| `fdf1c79` | `e26eb00` | — | Send a user agent when the E2E driver checks a deployed site |
| `1afb506` | `85a9711` | — | Record the public web demo deployment and its E2E results |
