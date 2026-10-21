# Native：gemmのCACHE_INFOとkernel parameter（#18）

2026-10-20。CACHE_INFOの違いで行列積のbitが変わる仕組みを、gemm 0.19のsourceと実測で特定した。libraryは変えていない。

## 結論

- **原因はkcだけである**。kcは、kの方向（和の方向）の区切りの大きさである。CACHE_INFOから決まるparameterのうち、mc・nc・thread数ではbitが変わらなかった。
- kcは`max(512, 64 × L1 associativityを2の累乗に切り上げた値)`を基に決まる（AVX2／FMAとNEONのkernel）。kは、その大きさを超えない範囲で均等に区切る。
  - kが512以下なら、kc＝kとなり、hostに依存しない。
  - モデルのlinearはすべてk≧1024なので、すべてhostに依存する。
- **k方向を自前で「512以下の均等な区切り」（gemmの下限512と同じ規則）に分けて順に足すと、hostによらず同じbitになる**。
  - i7-1360PのP-core／E-core、Cobalt 100のLinux／Windows、x86_64のrunner 2台で確認した。
- ただし、この方法では、**kc＞512のhostの結果が変わる**。記録機（Ryzen AI MAX+ 395）も、そのhostに含まれる。採否は判断が必要である（最後の節）。

## gemm 0.19の仕組み（source）

- **kernelの選択**：
  - x86_64：AVX-512のkernelは、cargo feature `x86-v4`がある時だけ使う。pure-jeffとCandleはこのfeatureを有効にしていない。
    - そのため、x86_64ではAVX-512のあるCPUでも、**FMA kernel（MR＝16、NR＝6）**を使う。
    - CIのEPYC 9V45（AVX-512あり）が、AVX2だけのEPYC 7763と、分割した全31積でbit一致したことでも確かめた（下記）。
  - aarch64：NEON kernel（MR＝16、NR＝4）。
- **`kernel_params(m, n, k)`**（`gemm-common/src/cache.rs`）：
  - **kc**：L1の大きさ・line・associativityとMR・NRから、基準値を求める。それを512以上に切り上げ、k以下に収める。そのうえで、kを`ceil(k / kc)`個に均等に分ける。
    - FMA・NEONでは、基準値は64×（associativityを2の累乗に切り上げた値）となる（L1が32 KiB以上の場合）。
  - **mc**：L2とkcから決まる。上限はMRの8倍である。
  - **nc**：L3とkcから決まる。L3が0の場合は別の既定値になる。
  - mとnがともに64以下の場合は、別の規則（kc＝min(k, 512)）を使う。
- 1行の積（m＝1）は、gemvで計算する。gemvはCACHE_INFOを使わない。
- 再実装：[kernel_params.py](research/native-gemm-kernel-params-2026-10-20/kernel_params.py)。実測した全31積で、bitの一致・不一致を説明できた。

## 実測

### 方法

- [`gemm_probe`](../runtime/rust/examples/gemm_probe.rs)は、forwardの行列積を、forwardと同じ形状・layoutで、固定のデータに対して計算する。
  - 形状：linear 8種、attentionの2つの積、readout。seqは128、513、874。
  - 各積の出力bitのSHA-256を出す。
  - 各積について、次の2通りを計算する。
    - そのまま計算したもの。
    - kを「`ceil(k / 512)`個の均等な区切り」に分け、順に足したもの（以下、分割）。
- **i7-1360P**：processを起動時からP-core（CPU 0〜7）またはE-core（CPU 8〜15）に固定した。1 threadと4 threadで計算した（[probe_pe.py](research/native-gemm-kernel-params-2026-10-20/probe_pe.py)）。
- **CI**：4つのrunnerで、1 threadと4 threadで計算した（一時的なworkflow、run 39386179020）。

### i7-1360P（P-core 48 KiB 12-way、E-core 32 KiB 8-way）

| 区分 | 積の数 |
| --- | ---: |
| kcがP／Eで違い、bitも違う | 26 |
| kcがP／Eで違うのに、bitが同じ | 0 |
| kcが同じなのに、bitが違う | 0 |
| kcが同じで、bitも同じ | 5 |

- **kcが違ったもの**：
  - linearはすべて（k＝1024、2048、3584）。kcはP-coreで1024（down_projは896）、E-coreで512だった。
  - attentionのvalue積（k＝513、874）。kcはP-coreでkそのもの、E-coreで257／437だった。
- **kcが同じだったもの**：attentionのscores（k＝256）、value積（k＝128）、readout（m＝1、gemv）。
- mcは、すべての積でP／E共通だった。ncは、kcが違う積でだけ違った。
- 1 threadと4 threadは、全積でbit一致した。
- **分割**：
  - P／Eの間で、全31積がbit一致した。
  - E-coreでは、そのまま計算したものと30積で一致した。一致しなかったのはreadoutだけである（m＝1のgemvは、もともとhostに依存しないので、分割の対象外にすべきもの）。
  - P-coreでは、k≦512の4積だけが一致した。

### CI runner（gemm_probe）

| runner | CPU | gemmのL1 | 分割＝そのまま（m＞1、30積） |
| --- | --- | --- | ---: |
| ubuntu-24.04 | EPYC 7763 | 16 KiB 8-way（SMTで半分） | 30 |
| windows-2022 | EPYC 9V45 | 48 KiB 12-way | 4 |
| ubuntu-24.04-arm | Cobalt 100（Neoverse N2） | 64 KiB 4-way | 4 |
| windows-11-arm | Cobalt 100 | 16 KiB 8-way（gemmの既定値） | 30 |

- **同じCobalt 100で、LinuxとWindowsの比較**：そのまま計算すると、31積中5積しか一致しない。分割すると、**31積すべてが一致**する。
- **x86_64のrunner 2台（EPYC 7763のLinuxとEPYC 9V45のWindows）**：そのままでは5積、分割すると31積すべてが一致した。
- host matrixの記録とも合う。PR #39のCI（`69eca65`）では、ARMのLinuxとWindowsで、39件中37件の確率が違った（同じCPU）。
- 1 threadと4 threadは、全runnerでbit一致した。

## hostごとのkc（再実装による。kは1024、2048、3584、513、874）

| host | gemmのL1 | kc | 512を基準にした規則との一致 |
| --- | --- | --- | --- |
| （512を基準にした規則） | — | 512、512、512、257、437 | — |
| Ryzen AI MAX+ 395（記録機） | 48 KiB 12-way | 1024、1024、896、513、874 | 不一致 |
| i7-1360P、P-core | 48 KiB 12-way | 1024、1024、896、513、874 | 不一致 |
| i7-1360P、E-core | 32 KiB 8-way | 512、512、512、257、437 | 一致 |
| EPYC 9V45／9V74、Windows | 48 KiB 12-way | 1024、1024、896、513、874 | 不一致 |
| EPYC 7763、Windows／Linux | 32／16 KiB 8-way | 512、512、512、257、437 | 一致 |
| EPYC 9V45、Xeon 6973P-C、Linux | 24 KiB 12-way | 512、512、598、513、437 | 不一致 |
| Cobalt 100、Linux | 64 KiB 4-way | 1024、1024、896、513、874 | 不一致 |
| Cobalt 100、Windows（既定値） | 16 KiB 8-way | 512、512、512、257、437 | 一致 |

- 記録機のkcは、CACHE_INFOの記録（[native-threads-diagnosis-2026-10-17.md](native-threads-diagnosis-2026-10-17.md)）と、x86_64がFMA kernelを使うことから求めた。記録機での直接の実測ではない。
- i7-1360PのP／E-core起動の差（3.55e-6、39件中36件）、ARMのLinux／Windowsの差は、どちらもこの表のkcの違いで説明できる。

## 固定方式の候補

| 案 | 内容 | hostによらない一致 | 既存の結果 | 速度・メモリ | 実現性 |
| --- | --- | --- | --- | --- | --- |
| A. kを自前で分割 | k＞512でm＞1の積は、kを「512以下の均等な区切り」に分け、gemmを区切りごとに呼んで出力に足し込む（gemmの`read_dst`で加算すると、一時領域は不要） | 同じkernel ISAの間で一致（x86_64はすべてFMA、aarch64はすべてNEON）。CPU・OS・起動coreによらない | **kc＞512のhost（記録機を含む）で変わる**。kc＝512のhost（8-way L1）では変わらない見込み | 実装後に計測が必要。Candle上での試作は、一時tensorと加算のため最大約2倍かかる。gemmへの直接の呼び出しで、どこまで縮むか未確認。kc＝512は、12-wayのhostでは本来の最適値より小さい | pure-jeffの中だけで完結。crates.ioの利用者にも効く |
| B. 上流にCACHE_INFOの設定APIを提案 | gemm-commonに「最初の利用の前に、CACHE_INFO（またはkc）を指定する」APIを足し、pure-jeffは記録機の値を指定する | 同じkernel ISAの間で一致 | 記録機の結果を保てる見込み | 変わらない（記録機と同じ区切り） | 上流のmergeとreleaseが必要（gemmは修正の取り込みが遅い。#31は1年以上Open）。repository buildだけなら、forkの`[patch]`で先行できるが、crates.ioの利用者には効かない |
| C. 文書化のみ | 再現性は「同じhost・OS・起動coreの種類」の範囲と明記する | なし | 変わらない | 変わらない | すぐできる |

- CPU0やP-coreへのaffinity固定は、既定の解決策にしない（#18の方針）。
- どの案でも、異なるkernel ISAの間（x86_64とARM64）のbit一致は得られない。これは要求していない。

## 判断が必要な事項

1. **案A**を採る場合：
   - 記録機の結果が変わるので、bit基準を新しく取り直す。0.2.0の「0.1.1とbit一致」の連続性は、そこで切れる。
   - 公式refとのgateと、記録機での速度同等性（0.2.0のrelease gate）を、記録機で再確認する必要がある。
2. **案B**を採る場合：上流へのissue・PRの提出（外部への公開）と、待つ期間の扱いを決める。
3. **案AとBの組み合わせ**：上流を待つ間は案Cとし、上流の対応が見込めなければ案Aにする、なども考えられる。

## その後の経過（2026-10-21）

- **案A**（kを自前で分割、PR #41）：実装と受入試験の結果、**不採用**とした。
  - 起動CPU・CACHE_INFOによらない再現性は得られた。
  - 記録機では、kc 1024／896を512以下に区切ることと、出力への加算そのものの費用が残った。1 threadの分割した積で約2〜4.5%遅い。
  - 並列実行を改良した追加実験でも、事前登録したwarm性能基準を満たさなかった（[記録](native-fixed-k-chunks-2026-10-20.md)）。
- **案B**（gemm上流にCACHE_INFO／kcを指定するAPIを提案）：**将来の検討候補として残す**。上流への投稿（issue・PR）は、まだ行っていない。
  - 記録機のkcのまま固定できれば、案Aの性能コストなしに、同じkernel ISAのhost間で一致させられる見込みである。
  - 投稿するかどうかと、上流の対応を待つ期間の扱いは、別途判断する。
- **案C**（文書化のみ）：現状の扱いである。mainの再現性は「同じhost・OS・起動coreの種類」の範囲で主張する。
