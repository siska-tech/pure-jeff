# Wasm W0：コンパイルと小型演算の結果

2026-10-11。[Wasm成立性計画](wasm-demo-feasibility-plan.md)のW0。**W0の通過条件を満たした。実モデルforward・メモリ・ブラウザ性能は未検証で、Wasm推論の成立やデモ公開を意味しない。** 既存Native source・凍結exe・公開API・Decision Reportは変更していない。

## 判定

| W0条件 | 結果 |
| --- | --- |
| 正式ブラウザtargetでbuild | `wasm32-unknown-unknown`で成功。固定Candle `c68b249`・tokenizers 0.23.2・core crateを含め、Native版lockと同一versionで新規依存なし |
| prompt／token IDs一致 | Chrome・Edgeの両variantで、公式golden 7件のprompt文字列と公式input_idsが完全一致（128〜8192 tokens）。tokenizer hash、255回答code／ID、chat prefix後の単一token性も一致 |
| 小型演算が許容誤差内 | 両browser・両variantで10演算すべて合格（事前登録v2）。v1基準では不合格の記録あり（下記） |
| 失敗箇所と修正範囲の保存 | 本書と[証跡](research/wasm-demo/w0-2026-10-11/README.md) |

## 構成

新規crate [runtime/wasm](../runtime/wasm/README.md)。凍結Nativeの`backbone.rs`と`prompt.rs`をbuild時にSHA-256照合し、byte単位でそのままincludeする。不一致ならbuildが失敗する。backboneの非公開演算は、probe用の薄い入口からだけ呼ぶ。演算式の複製・改変はしていない。ただしGEMMは凍結`linear`と同じ`x.matmul(&w.t())`を直接呼ぶ。重みstoreを経由する`linear`／`norm`／`mlp`／attention層全体はW0の対象外。

`wasm-bindgen`は使わず、生のC ABIで公開する。ページが渡すimportは3つだけ（`crypto.getRandomValues`による乱数、`performance.now`、panic文字列の受け取り）。依存の`getrandom` 0.3は`--cfg getrandom_backend="custom"`でページの乱数を使う。乱数はhash map seed用で、推論はサンプリングしない。Moduleのimportがこの3つだけであることをNodeで確認した。

| 成果物 | bytes | SHA-256 |
| --- | ---: | --- |
| baseline wasm | 3,933,525 | `2aa89061189f…` |
| simd128 wasm（`+simd128`） | 4,012,073 | `a9ce3db6b508…` |
| native参照exe（同一source、x86_64） | — | `9719e3ef1364…` |

完全なhashは各runの`preregistration.json`に記録。

## 方法

`runtime/wasm/run_w0.py`が許可したファイルだけを127.0.0.1で配信し、新規profileのheadlessブラウザを起動する。Web Worker内でvariantごとに演算を2回実行し、tokenizer（19,989,492 bytes）を取得してhash検証とtokenizeを行い、結果をPOSTで回収する。比較対象は同じsource・同じjobのnative実行（1 thread、凍結policyと同じ）。入力は整数生成器から作るため、両targetで同じf32値から始まる。

対象：Chrome 153.0.8010.48、Edge 153.0.4234.48（Windows 11、Core i7-1360P）。single-thread、cross-origin isolationなし、headless。headed表示・他browser・モバイルは未確認。

## 数値結果（最終run）

事前登録v2の基準：各tensorで max|wasm−native| ≤ 1e-5×max(1, max|native|)。入力だけで決まるGEMMは、float64の正確な積に対して max|out−exact| / (|x|·|w|ᵀ) ≤ 4·eps32（4.77e-7）を、nativeとwasmの両方に課す。同一Worker内の2回は値が完全一致すること。

| 演算 | 最大誤差 / tensor規模（baseline / simd128） | 備考 |
| --- | ---: | --- |
| GEMM 17×1024 · (3584×1024)ᵀ | 1.33e-6 / 1.33e-6 | backward誤差 native 2.55e-7、wasm 1.43e-7 |
| SiLU→GEMM 17×3584 · (1024×3584)ᵀ | 8.69e-7 / 8.69e-7 | |
| GEMM 5×64 · (33×64)ᵀ | 1.33e-7 / 1.33e-7 | backward誤差 native 3.6e-8、wasm 6.0e-8 |
| attention score＋因果mask softmax | 8.94e-8 / 8.94e-8 | |
| RMS正規化（凍結`normalized`） | 5.44e-7 / 1.36e-7 | |
| L2正規化（凍結`l2`） | 4.47e-8 / 1.49e-8 | |
| RoPE（凍結`rotary`） | 4.46e-8 / 4.46e-8 | 14,336要素中14,335がbit一致 |
| SiLU／sigmoid | 1.59e-7 / 1.59e-7 | |
| Gated DeltaNet再帰（凍結`delta_recurrence`、H16・K/V128・9 step） | 6.52e-9 / 5.59e-9 | |
| 最終次元の総和 | 4.47e-8 / 2.79e-8 | |

ChromeとEdgeの数値は、同じvariant同士で完全に同一。simd128版は総和を含む演算（RMS、L2、DeltaNet、総和）だけ結果が変わり、GEMMの結果は変わらない。同じWorker内の反復は、全組で値がbit一致した。

## v1の不合格と基準の変更

最初のrun（`wasm-w0-chrome-20261011`）はv1基準（要素ごとに |wasm−native| ≤ 1e-5＋1e-5·|native|）で**不合格**だった。2つの大きいGEMMが、0に近い出力で基準を超えた（最大絶対誤差5.72e-5、出力規模は約43）。他の8演算とtokenizeは合格。また、反復一致の判定が経過時間まで比較していたため不合格になった。これはdriverの不具合で、保存済みの値だけを比べると完全一致していた。

同じ入力を固定生成器からfloat64で再計算すると、wasmの誤差（1.43e-7×Σ|x||w|）はnative（2.55e-7×Σ|x||w|）以下だった。どちらもfloat32の加算順の差の範囲にある。v1不合格の原因は、相殺で0に近づいた和を要素ごとの相対誤差で判定したことにあり、wasmの欠陥ではないと判断した。このrunは不合格のまま記録し、閾値を後から緩めて合格扱いにはしていない。v2の基準とnative参照の1 thread固定を事前登録し、新しい出力先で再測定した（v1のnative参照は12 threadsだった）。

v2のChrome／Edge runも合格した。その後`cargo fmt`でsourceの行番号が変わり、panic位置の文字列を通してwasmのbytesが変わった。そのため、最終成果物で両browserを再測定したものを最終証跡とする。

## W1へ持ち越す事項

単発の観測値であり、性能の判定ではない。

- **重みアクセスの境界**：凍結backboneは`&MmapedSafetensors`を受け取る。ブラウザではfileのmmapができない。W1では、Candleのbyte buffer版safetensors読込などへ型だけを差し替えた**独立した生成コピー**を作る。凍結sourceは書き換えない。
- **メモリ**：`model.safetensors`は1,706,027,688 bytes。今回のlinear memoryは最大132 MiB（tokenizer込み）。W1では、JS側で全体の複製を持たずにlinear memoryへ流し込む方式と、埋め込み行列（BF16で約508 MB）を読む際の一時コピーを含むpeakを実測する。4 GiB上限内に収まることは未確認。
- **時計**：core crateの`Limits`と期限判定は`std::time::Instant`を使う。`wasm32-unknown-unknown`では、`Instant::now()`は呼んだ時点でpanicする（W0の経路では呼んでいない）。Native APIを保ったまま、Wasm用の時計adapterを設計する。
- **SIMD**：simd128版では総和系の演算の結果が変わるので、Candle自身の総和処理はSIMD128を使っている。一方GEMMは、baselineと結果がbit一致し、時間もほぼ同じだった。固定Candleのgemmは、Wasm上でSIMD128経路を使っていない可能性が高い。最終runの単発値で、17×1024×3584のGEMMは1 threadのnative 2.2〜2.6 ms、wasm 8.0〜9.0 ms。この比を全体forwardへ外挿しない。W1の全層forwardで実時間を測る。
- **tokenizer**：最終runの単発値で、hash検証0.32〜0.35秒、読込0.58〜0.98秒、8192 tokensのencode 6 ms。

## 再現

[runtime/wasm/README.md](../runtime/wasm/README.md)を参照。
