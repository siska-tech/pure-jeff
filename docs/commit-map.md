# commit hashの対応表

2026-10-11。公開前に、commit messageからツールの帰属表示（trailer）を除くため履歴を書き換えた。書き換えたのはmessageだけで、各commitのfile tree、author、日時は変わっていない（commitごとに照合済み）。

証跡のJSON（事前登録、`build-info.json`）と、ローカルの出力directory名（例：`experiments/runs/bench-80e0cec`）には、記録したときの旧hashが残っている。証跡なので変更していない。文書中のcommit参照は新しいhashへ更新した。

| 旧hash | 新hash | commit |
| --- | --- | --- |
| `80e0cec` | `13a35d0` | Extract Pure Rust Jeff runtime, browser Wasm and web demo from KazeJudge |
| `ed7f964` | `76ab958` | Record one-thread benchmark: official Jeff, Rust Native, browser Wasm |
| `172d0ec` | `d59163e` | Document how to run the benchmark harness |
| `8d26e83` | `f3f6b49` | Plan OSS release and add pinned model fetch with hash verification |
| `055e65c` | `bac04cf` | Let model-free test runs pass in a fresh clone |
| `a863642` | `5e7feb0` | Audit dependency licenses and record attributions and open decisions |
| `a22be0a` | `a10368c` | Add a wasm export filter for the demo engine |
| `a5c27c0` | `dbc0400` | Replace inherited CI with a full model-free GitHub Actions workflow |
| `19dedf2` | `080eb3a` | Record the clean-environment check and add a reusable script |
| `d4380ce` | `d1b928e` | Prepare the web demo for hosting (W4) |
| `0d2f875` | `c54fc00` | Record W4 E2E results and the Cloudflare Pages + R2 hosting study |
| `d3fbf07` | `02ebd9c` | Plan optional FP32 weight retention for the Native runtime |
| `482106d` | `a2c5b88` | Rewrite the README and docs for an independent project |
