# 公式Jeff／Native：全長の受入（main `4e1794d`）

2026-10-14。#4／#14（共有bufferを既定、FP32保持をopt-in）をmergeした後のmain `4e1794d`で、[計画](benchmark-parity-plan.md)に事前登録したlong stage（874／3206／8192 tokens）を測り直した。shortは[共有bufferの記録](native-weight-buffers-2026-10-13.md)のrun（`a91706d`）で受入済みである。`a91706d`とmainの差は、doc commentの1件（`a89b6ff`）だけである。

## 結論

**short・longとも受入になり、全長の受入（short かつ long）が成立した。** 128〜8192 tokensのすべての入力群で、Native（既定経路、1 thread、公開API）は公式Jeff以上の速さである。ただし8192 tokensでは、Nativeのメモリがまだ公式を上回る（#17）。

| 段階 | 入力群 | Native／公式Jeff | 片側95%区間 | 判定 | run |
| --- | --- | ---: | --- | --- | --- |
| short | 128 | 0.960 | 0.943〜0.976 | 同等 | `a91706d` |
| | 256 | 0.907 | 0.886〜0.929 | 同等 | |
| | 384 | 0.847 | 0.832〜0.863 | 同等 | |
| | 512 | 0.832 | 0.807〜0.857 | 同等 | |
| long | 874 | 0.853 | 0.824〜0.883 | 同等 | `4e1794d` |
| | 3206 | 0.881 | 0.877〜0.886 | 同等 | |
| | 8192 | 0.869 | 0.861〜0.877 | 同等 | |

## long（6 block、各case・系統24観測、API境界、warm）

| case | 公式Jeff（秒） | Native（秒） |
| --- | ---: | ---: |
| long-text（874） | 10.75 | 9.15 |
| maximum-candidates（3206、255候補） | 42.77 | 37.60 |
| token-limit-8192 | 142.44 | 124.10 |

- **load**：公式10.51秒、Native 1.87秒。
- **初回の判断**（8192 tokens）：公式142.38秒、Native 125.09秒。
- **数値gate**：全判断で違反なし（gateには、8193 tokensの拒否を含む全入力の判断を含む）。
- **公式参照との最大差**：Native 4.74e-6。
- **反復**：bit単位で一致した。
- **前回との比較**：baseline（2026-10-13、0.1.1相当）のlongは0.885／0.876／0.858だった。共有bufferの効果は短い入力ほど大きく、長い入力ではattentionなどが時間を占めるので、longの比はほとんど変わらない。

## メモリ（longのrun、process単位の最大）

| | 公式Jeff | Native |
| --- | ---: | ---: |
| peak Working Set | 5.19 GiB | **7.83 GiB** |
| Private bytes（process tree） | 8.43 GiB | 6.91 GiB |

8192 tokensで、Nativeのpeak Working Setは公式Jeffより2.6 GiB大きい。主な原因は、full attentionで全位置のscore・mask・確率を同時に持つことと、K/Vの複製だと考えているが、内訳はまだ測っていない。#17（attentionのquery-block化）で扱う。Private bytesは公式の方が大きいが、Working Setと同じ時点の値ではない（process単位の最大）。

## 条件と証跡

- 測定機、OS、公式Jeff、Candle、計画、seed、数値gateは[baseline](benchmark-parity-results-2026-10-13.md)と同じ。
- source：`4e1794d`（clean）。bundle：`jeff lock`でmainのbuildに合わせて作り直した。
- 生データ：[research/benchmark-parity-2026-10-14-long/](research/benchmark-parity-2026-10-14-long)（事前登録、集計、session別の全判断、終了時の環境、driverのlog）。
