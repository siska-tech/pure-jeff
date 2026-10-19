# Native：Intel hybrid CPUでの複数thread検証と、Linux／ARM64のCI（#18）

2026-10-19。main（`95e122d`、#37のDeltaNet head並列化を含む）を、これまでの測定機（AMD Ryzen AI MAX+ 395）と別のCPUで検証した。Intel hybrid CPU（i7-1360P）の手元機と、GitHub-hosted runner（Linux・Windows、x86_64・ARM64）の4種である。

## 対象と方法

- **測定機**：13th Gen Intel Core i7-1360P（P-core 4〈SMT〉＋E-core 8、論理CPU 16）、Windows 11、メモリ32 GB。#18で未確認だったIntel hybrid CPUにあたる。
- **build**：main `95e122d`の`runtime/rust`（release）。bundleは同じbuildの`jeff lock`で、thread数ごとに作った。
- **driver**：[bench/host_matrix.py](../bench/host_matrix.py)（標準libraryのみ。Windows・Linux・macOS、x86_64・ARM64で動く）。
  - **CACHE_INFO**：`thread_probe`を、固定しない状態で3回、論理CPUごとに起動時から固定して1回ずつ実行した。
  - **matrix**：catalogの全39件（旧28件、長さの境界、policy境界、874／3206／8192 tokens、8193 tokensの`budget_exceeded`を含む）。1／2／4／8／16 threadで、独立したprocessを2つずつ立てる。各processは全件を2回判断し、2回目は逆順にする。referenceは1 threadの最初のprocessの1回目である。
  - **pinned**：起動時からCPU集合に固定したprocess。CACHE_INFOの群ごと（P-core群、E-core群）と、CPU0を除く全CPUについて、1／4／16 threadで600 tokens以下の35件を判断する。Windowsではprocessを停止状態で作り、affinityを設定してから再開する（最初の命令から固定される）。
  - **timeout**：`timeout_reuse`を1／4／16 threadで実行した。
- **合格の条件**：全processの正常終了、判断の欠けなし、共通数値gateの違反0、全判断がreferenceと確率・判定でbit一致、timeout後の再利用がbit一致。
- 計測時のdriverは、commitした版から要約表の列を足す前のものである（hashは`host.json`に記録）。判定とraw結果は同じである。

## 結果

**E-core群から起動したprocessだけがbit一致しなかった。** それ以外はすべて合格した。

### CACHE_INFO（gemmがprocessごとに一度、最初に呼ばれたCPUから読む値）

| 群 | 論理CPU | L1 | L2 | L3 | 固定なしの起動 |
| --- | --- | --- | --- | --- | ---: |
| P-core | 0〜7 | 48 KiB、12-way | 1.25 MiB、10-way | 18 MiB、12-way | 3／3 |
| E-core | 8〜15 | 32 KiB、8-way | 2 MiB、16-way | 18 MiB、12-way | 0／3 |

- CACHE_INFOは、processが最初にgemmを呼んだCPUの種類で変わる。libraryにはこれを固定する処理がない。

### 数値

| 項目 | 結果 |
| --- | --- |
| matrix（10 process、各78判断） | 全て正常終了、gate違反0、referenceとのbit不一致0 |
| 旧28件の固定cache gate値との差 | 28件すべて0（bit一致） |
| 公式referenceとの最大差 | 4.74e-6 |
| pinned：P-core群、CPU0を除く全CPU | bit一致 |
| **pinned：E-core群** | **1／4／16 threadとも35件中33件がbit不一致。最大差3.55e-6。判定の違いはなし。gateは合格** |
| timeout→再利用 | 1／4／16 threadとも、timeoutが起き、その後の判断がbit一致 |

- E-core群の3 processは、互いにbit一致した（1／4／16 thread）。差はthread数ではなく、起動したCPUのCACHE_INFOから来ている。
- E-core群の最大差3.55e-6は、旧実験の反復差の上限1e-6を超える。固定しないprocessがE-coreで起動すると（P-coreが混んでいる時など）、同じbuild・同じ入力でも、process間でこの差が出うる。
- CPU0を除いた固定ではbit一致した。CPU0固定には依存していない。

### 起動・peak・時間（記述のみ）

- load：1.91〜1.98秒（matrix）。E-core群に固定したprocessは約3.0秒。
- peak（matrix、8192 tokensを含む）：private 1,185.7〜1,217.3 MiB、Working Set 2,137.2〜2,156.5 MiB。
- 判断時間の中央値（秒）：

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.77 | 10.90 | 46.32 | 150.16 |
| 2 | 1.25 | 7.39 | 30.55 | 97.07 |
| 4 | 1.25 | 6.24 | 24.30 | 79.53 |
| 8 | 1.34 | 6.73 | 24.34 | 76.87 |
| 16 | 1.43 | 6.06 | 22.14 | 69.30 |

- 電源・温度・背景負荷は制御していない。速度の判定には使わない。

## CI（`.github/workflows/native-hosts.yml`）

- **runner**：ubuntu-24.04（x86_64）、ubuntu-24.04-arm（ARM64）、windows-2022（x86_64）、windows-11-arm（ARM64）。いずれも4 vCPU。
- **内容**：
  - モデルの取得とhash照合（cacheあり）。
  - release build。
  - libraryとCLIの試験。
  - one-shot CLIと公式golden 6件の照合（`runtime/validate_migration_cases.py`）。
  - `bench/host_matrix.py`（既定は1／2／4 thread×2 process）。
  - 試験が失敗しても、buildが通っていれば後の照合とmatrixは実行する。jobは失敗のまま残る。
  - 要約はjobのsummaryに、証跡はartifactに残す。
- **起動**：手動（thread数・process数を指定できる）、週1回、この2ファイルを変えるPR。
- **範囲**：runnerは共有の仮想機なので、速度は判定しない。数値・起動・peakだけを見る。Intel hybrid CPUのrunnerはないため、P／E-coreの問題はCIでは再現できない。

### 結果（変更前：PR #38、commit `5b729b9`、run 39233327905）

原因と対応は[native-arm64-2026-10-20.md](native-arm64-2026-10-20.md)にまとめた。この節は、対応前の記録として残す。

| runner | CPU | gemm CACHE_INFO（L1／L2／L3） | matrix | 公式refとの最大差 | golden 6件の最大差 | library試験 |
| --- | --- | --- | --- | ---: | ---: | --- |
| ubuntu-24.04 | Intel Xeon 6973P-C | 24 KiB／1 MiB／480 MiB | 合格 | 3.99e-6 | 4.38e-6 | 合格 |
| windows-2022 | AMD EPYC 9V74 | 32 KiB／1 MiB／**0** | 合格 | 3.52e-6 | 2.41e-6 | 合格 |
| ubuntu-24.04-arm | Neoverse N2（Cobalt 100） | 64 KiB／1 MiB／128 MiB | 合格 | 5.30e-6 | 5.72e-6 | **不合格（1件）** |
| windows-11-arm | Cobalt 100 | 16 KiB／512 KiB／1 MiB | 合格 | 3.78e-6 | 4.17e-6 | **不合格（1件）** |

- **matrix**：全runnerで、全39件×1／2／4 thread×2 processと、固定process（全CPU、CPU0を除く）でgate違反0、1 threadとのbit不一致0。timeout→再利用もbit一致した。
- **host間**：bit一致しない（旧28件のgate値との差は2.2e-6〜3.8e-6）。依存版やcache条件が違う環境どうしのbit一致は、もともと前提にしていない。
- **CACHE_INFOの実測値**：
  - OSの報告と一致しないことがある。ubuntu-24.04ではsysfsがL1d 48 KiB／L2 2 MiBなのに、gemmは24 KiB／1 MiBを使う。
  - windows-2022ではL3が0になった（仮想機がL3を報告しない）。
  - 同じCobalt 100でも、LinuxとWindowsで値が違う。Windowsの値は既定値への退避とみられるが、未確認。
- **ARM64のlibrary試験**：`backbone::tests::attention_in_query_blocks_is_bitwise_equal_to_one_block`が、Linux・Windowsとも失敗した（最初の不一致は`seq 7, block 1`）。
  - full attentionをquery blockに分けた結果が、1 blockの結果とbit一致しない。行数でgemmのkernelや和の順序が変わるためとみられる。
  - x86_64では成り立つ。ARM64では、8192 tokensなどblock化される入力で、block化前とbit一致しないことになる。
  - 公式refとの差・判定は、上の表のとおりgateに合格している。
  - cargoは最初に失敗した試験binaryで止まるため、ARM64ではそれ以降の統合試験・CLI試験は未実行である。
- **ARM64のdebug build**：`gemm-f16` 0.19がopt-level 0でcompileできない（`instruction requires: fullfp16`）。
  - 原因は、gemm-commonの`#[inline]`関数（`vmulq_f16`など）が、target featureなしでfp16のinline asmを持つことである。
  - release buildは通るので、CIはlibraryの試験もreleaseで実行する。利用者が既定の`cargo build`／`cargo test`をARM64で使うと失敗する。
- **起動・peak・時間**（記述のみ）：
  - load：x86_64で1.9〜2.9秒、ARM64で5.2〜5.3秒。
  - peak：2.1〜2.3 GiB（8192 tokensを含むprocess）。
  - 8192 tokensの中央値：1 threadで171〜296秒、4 threadで89〜106秒。
  - timeoutの停止（期限3秒）：ARM64の1 threadで8.5〜8.9秒かかった。forward内の確認点の間隔が長い。

## #18の受入条件への対応

- **実kernel parameterとCPU／cache条件**：5種のCPU（i7-1360P、Xeon 6973P-C、EPYC 9V74、Cobalt 100のLinux・Windows）でgemmのCACHE_INFOを実測した。
  - i7-1360Pでは、起動CPUの種類で2通りになる。
  - 仮想機では、OSの報告と違う値やL3＝0になる。
  - gemmの実際のkernel分割（CACHE_INFOから決まるblock size）は未記録である。
- **旧28件と現行集合の数値gate**：旧28件を含む全39件で、5つのhostの全thread数で合格した。i7-1360P（P-core起動）では、旧28件の固定cache gate値ともbit一致した。
- **反復差≤1e-6、既定経路のbit互換**：同じhost・同じ起動条件では、全hostで満たした。
  - **i7-1360PでE-coreから起動した場合は、最大3.55e-6で満たさない。** 起動CPUに依存しないCACHE_INFOの決め方が必要である。
  - ARM64では、attentionのblock化がbit互換でない（library試験の失敗）。
- **CPU0固定なし**：CPU0を除いた固定で動き、bit一致した。初期化順・affinityの復元・thread設定の異常経路は未試験のままである。
- **host別の成立範囲**：Windows（Intel hybrid、x86_64仮想機、ARM64仮想機）とLinux（x86_64、ARM64の仮想機）で、数値gateと複数threadのbit一致が成立した。
  - 速度は仮想機では判定していない。
  - Linuxの実機は未確認である。

証跡：[research/native-host-matrix-2026-10-19/](research/native-host-matrix-2026-10-19)
