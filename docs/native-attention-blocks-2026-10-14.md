# Native：full attentionのquery-block化（#17）

2026-10-14。長文のfull attentionが、全位置のscore・mask・確率を同時に持たないようにした。[全長の受入](benchmark-parity-full-2026-10-14.md)で最後に残っていた不足は、8192 tokensのメモリ（Native 7.83 GiB、公式Jeff 5.19 GiB）だった。**変更後のpeakは2.10 GiBになり、最終hiddenはbit単位で変わらない。** 計画・seed・数値gateは[計画](benchmark-parity-plan.md)と同じ。

## 実装

`src/backbone.rs`の`full_attention`／`attention_rows`。

- **block単位で計算する。** query行を512行ずつに分ける。各blockについて、scores（`q_block · Kᵀ / 16`）、causal mask、softmax、`· V`を作り、終わったら捨てる。1つのtensorは(8, block, seq)で、8192 tokensでは2 GiBから128 MiBになる。
- **各行はすべてのkeyを見る。** 行ごとの積・和・softmaxの長さは、1 blockで計算した場合と同じである。maskされたkeyは、従来どおりexp(−inf)＝0として寄与する。keyを因果範囲に切り詰めると、総和の順序が変わる可能性があるので行わない。
- **512 tokens以下は1 blockで計算する。** 変更前と完全に同じ処理になる。Wasm engineは512 tokensまでなので、その出力も変わらない。
- **block境界**：各blockの前にもdeadlineを確かめる。mask行は、元の位置`start + i`で作る。
- **K/Vの8 headへの複製（各64 MiB）は残した。** 2 headのgroup共有にすると行列積の形が変わり、bit一致を確かめ直す必要がある。今回の目標（公式以下のpeak）はblock化だけで達成したので、別の作業とする。
- **online softmaxは採用しなかった。** 総和の順序が変わるので、既定経路の候補にしない。

## bit一致と数値gate

| 検査 | 結果 |
| --- | --- |
| 最終hiddenのSHA-256（`attention_blocks`）。1 block（変更前と同じ処理）とblock 512を、513（境界、2 block）、874、3206、8192 tokensで、別processで2回ずつ交互に | すべて一致 |
| 単体試験 | ランダム入力で、block 1／3／8と1 blockがbit一致（seq 1〜37）。各blockのcausal範囲が正しい |
| CLI workerと公式golden 7件 | 誤差が変更前と同じ |
| crates.io版Candleの利用者build | golden 7件が合格（最大3.457e-6、変更前と同じ） |
| benchmark（long、one-shot） | 数値gateの違反なし。反復はbit一致 |
| one-shot（≤512）とmainのrunの比較 | 時間0.994〜0.995倍、peak 1.000〜1.001倍、確率はbit一致。退行なし |

## メモリ（`attention_blocks`、process単位、2回の最大）

| tokens | peak WS：1 block → block 512 | Private：1 block → block 512 | forward（秒） |
| ---: | --- | --- | --- |
| 513 | 1.06 → 1.06 GiB | 0.15 → 0.15 GiB | 5.6 → 5.6 |
| 874 | 1.13 → 1.10 GiB | 0.22 → 0.20 GiB | 9.4 → 9.5 |
| 3206 | 2.19 → 1.41 GiB | 1.30 → 0.50 GiB | 37.7 → 37.8 |
| 8192 | **7.85 → 2.06 GiB** | 6.96 → 1.15 GiB | 124.4 → 124.9 |

## long（事前登録のlong stage、`aa157dd`、6 block、各case・系統24観測）

| 入力群 | 公式Jeff（秒） | Native（秒） | Native／公式（片側95%区間） | 判定 |
| --- | ---: | ---: | --- | --- |
| 874 | 10.84 | 9.18 | 0.856（0.837〜0.875） | 同等 |
| 3206 | 43.33 | 38.00 | 0.880（0.870〜0.890） | 同等 |
| 8192 | 144.67 | 126.19 | 0.890（0.855〜0.925） | 同等 |

| process単位の最大 | 公式Jeff | Native（main `4e1794d`） | Native（`aa157dd`） |
| --- | ---: | ---: | ---: |
| peak Working Set | 5.14 GiB | 7.83 GiB | **2.10 GiB** |
| Private bytes | 6.02 GiB | 6.91 GiB | 1.17 GiB |

- **速度とメモリ**：longは受入のままで、メモリでも8192 tokensまで公式Jeffを下回った。
- **8192 tokensの時間**：Nativeはmainのrun（124.10秒）より1.7%長かったが、同じrunで公式Jeffも1.6%長かった（142.44→144.67秒）。blockはNativeとJeffを対にして比べるので、判定はこのsession差の影響を受けない。
- **block化そのものの費用**：別processで交互に測った上の表では、forward 124.4→124.9秒（＋0.4%）だった。

## deadlineと再利用（`timeout_reuse`）

8192 tokensの要求にdeadline 3／30／60秒を与えた。どれも`Timeout`になり、停止したのは3.56／31.48／60.03秒だった。超過は最大で、block 1つまたはlinear attention層1つ分（約1.5秒）である。その後、同じ`Model`で別の要求を判断し、timeout前とbit一致した。

- **協調deadline**（同期演算の途中では止まらない）と、**`NativeProcessProvider`によるprocessのkill**の違いは変えていない。

## Wasm

現行のWeb engineは512 tokensまでなので、常に1 blockで計算する。処理もメモリも変更前と同じである。512 tokensを超える入力をbrowserで扱う場合は、linear memoryの上限との関係を別に評価する必要がある。

## 証跡

[research/native-attention-blocks-2026-10-14/](research/native-attention-blocks-2026-10-14)：

- block比較（digest、時間、peak）
- one-shotとlongのrun一式、mainのrunとの比較
- golden照合
- timeoutの記録
- driverのlog
