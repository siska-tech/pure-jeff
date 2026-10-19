# Native：Intel hybrid CPUでの複数thread検証と、Linux／ARM64のCI（#18）

2026-10-19。main（`95e122d`、#37のDeltaNet head並列化を含む）を、これまでの測定機（AMD Ryzen AI MAX+ 395）と別のCPUで検証した。あわせて、Linux・ARM64をGitHub-hosted runnerで試験するworkflowを加えた。

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
- **内容**：モデルの取得とhash照合（cacheあり）、release build、libraryとCLIの試験、one-shot CLIと公式golden 6件の照合（`runtime/validate_migration_cases.py`）、`bench/host_matrix.py`（既定は1／2／4 thread×2 process）。結果は要約をjobのsummaryに、証跡をartifactに残す。
- **起動**：手動（thread数・process数を指定できる）、週1回、この2ファイルを変えるPR。
- **範囲**：runnerは共有の仮想機なので、速度は判定しない。数値・起動・peakだけを見る。Intel hybrid CPUのrunnerはないため、P／E-coreの問題はCIでは再現できない。

## #18の受入条件への対応

- **実kernel parameterとCPU／cache条件**：i7-1360Pで、CACHE_INFOが起動CPUの種類で2通りになることを実測した。gemmの実際のkernel分割（CACHE_INFOから決まるblock size）は未記録である。
- **旧28件と現行集合の数値gate**：旧28件を含む全39件で、1〜16 threadとも合格した。旧28件の固定cache gate値とはbit一致した。
- **反復差≤1e-6、既定経路のbit互換**：P-coreから起動した場合は満たす。**E-coreから起動した場合は最大3.55e-6で満たさない。** 起動CPUに依存しないCACHE_INFOの決め方が必要である。
- **CPU0固定なし**：CPU0を除いた固定で動き、bit一致した。初期化順・affinityの復元・thread設定の異常経路は未試験のままである。
- **host別の成立範囲**：Windows・Intel hybridを加えた。Linux・ARM64はCIの結果を待つ。

証跡：[research/native-host-matrix-2026-10-19/](research/native-host-matrix-2026-10-19)
