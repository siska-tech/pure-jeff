# crates.io版Candleでの性能同等（#28）

2026-10-17。0.2.0の[最終受入](release-0.2.0-verification-2026-10-14.md)では、リポジトリ内のbuild（固定revisionのCandle）で速度を測った。crates.io版Candleでの速度は「証拠不足」として残していた。今回は、crates.ioの利用者と同じ依存で常駐の計測exeをbuildし、事前登録のshortとlongを、同じ[計画](benchmark-parity-plan.md)・seed・数値gateで測った。**short・longとも受入になり、すべての入力群で同等と判定された。**

過去の記録（最終受入、CHANGELOG、Release notes）は書き換えず、この文書から補う。

## build

`bench/build_cratesio_resident.py`で作った。

- **依存**：新しいprojectが`pure-jeff = "=0.2.0"`と`candle-core = "=0.11.0"`をcrates.ioから取る。`[patch]`もpath依存もない。
- **計測exe**：`runtime/rust/examples/resident_bench.rs`を変更せずにbuildした。
- **bundle**：同じbuildの`pure_jeff::lock`で作った。公開API経路は、同じbuildでlockしたbundleを要求する。
- **確認**：
  - `cargo tree`で、candle-core v0.11.0がcrates.ioから来ていること。
  - `Cargo.lock`で、`pure-jeff` 0.2.0がregistryから来ていること。
- **実kernel**：計測exeが報告したCandleの`with_avx`／`with_f16c`は**false**だった。リポジトリbuild（固定revision `c68b249`）ではtrueである。どちらも、実行時に検出したCPU機能（AVX2、FMA、AVX-512）は同じ。
  - 2つのCandleでは、CPU機能の判定に使える情報が違う。
  - 行列積（gemm crate）は、どちらも実行時に命令を選ぶ。

## 結果（6 block、各case・系統24観測、公開API、1 thread）

| 入力群 | crates.io build：Native／公式Jeff（片側95%区間） | 判定 | 参考：リポジトリbuild（2026-10-14） |
| --- | --- | --- | --- |
| 128 | 0.948（0.931〜0.964） | 同等 | 0.955（〜0.986） |
| 256 | 0.866（0.852〜0.879） | 同等 | 0.889 |
| 384 | 0.829（0.819〜0.839） | 同等 | 0.845 |
| 512 | 0.818（0.808〜0.829） | 同等 | 0.821 |
| 874 | 0.822（0.818〜0.826） | 同等 | 0.862 |
| 3206 | 0.877（0.873〜0.881） | 同等 | 0.882 |
| 8192 | 0.885（0.871〜0.899） | 同等 | 0.884 |

- **数値gate**：全判断で違反がなかった（公式参照との最大差3.96e-6。crates.io buildの値は公開前後の検査と同じ）。同じ系統・同じ経路の反復は、bit単位で一致した。
- **追加block**：証拠不足の群がなかったので、追加blockは実行していない。
- **メモリ**：Nativeのpeak Working Setは、shortで1.09 GiB、longで2.10 GiB。リポジトリbuildとほぼ同じだった。
- **load**：1.98〜1.99秒。

### 絶対時間について

この日は、公式Jeffの時間もリポジトリbuildの測定日（2026-10-14）より6〜8%長かった（128 tokensで1.48→1.60秒、8192 tokensで144.0→153.3秒）。各sessionの前後の背景負荷も4〜17%で、10-14の0〜8%より高かった。

- **判定への影響**：同等の判定は、同じblockで交互に測ったNativeと公式Jeffの比を使う。そのため、この日の環境の差は判定に影響しない。
- **リポジトリbuildとの比較**：Nativeの絶対時間（128 tokensで1.51秒、10-14のリポジトリbuildでは1.42秒）は、日をまたいで比べられない。crates.io版とリポジトリbuildの速度差は、今回は判断しない。比較するには、同じsessionで両方を交互に測る必要がある。

## 範囲

- 測定機は[baseline](benchmark-parity-results-2026-10-13.md)と同じ（Windows、AMD Ryzen AI MAX+ 395、1 thread）。
- 次は引き続き証拠不足：ほかのCPU、Linux、複数thread。

## 証跡

[research/benchmark-cratesio-2026-10-17/](research/benchmark-cratesio-2026-10-17)：

- short、longの事前登録・集計・session別の生データ・終了時の環境・driverのlog。
- buildの記録：生成した`Cargo.toml`、`Cargo.lock`、`lock.rs`、exeとbundleのhash。local pathは置き換えた。
