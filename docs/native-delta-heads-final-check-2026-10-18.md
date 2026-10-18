# Native：DeltaNet headの複数thread化 — 最終commitでの代表ケース検証（#18）

2026-10-18。#36をmergeした後、#37をmainへrebaseした。この文書は、rebase後の最終commitで、代表ケースの数値とメモリを確かめる計画である。計測の前にcommitし、結果はこの文書の末尾に追記する。合否の条件は、計測後に変えない。

## 対象

- **candidate**：#37の最終commit（`7649bc7`）でbuildしたもの。bundleは、そのbuildの`jeff lock`で作り直した。
  - libraryのruntime build hashは、rebase前（`ba19132`）と同じである。libraryのsourceは変わっていない。
- **baseline**：main（`973bbb1`）でbuildしたもの。
  - mainはその後#36をmergeして`f14d54d`になったが、library（`src`、`Cargo.toml`、`Cargo.lock`、`build.rs`、`spec`）に差分はない。
- **測定機**：E2と同じ（AMD Ryzen AI MAX+ 395、Windows）。

## 数値（`bench/delta_heads_final_check.py`）

- **reference**：mainの1 thread（resident、公開API）で、各入力を1回判断する。
- **candidate**：
  - thread数：1／2／4／8／16。
  - 各thread数で、独立したprocessを2つ立てる。
  - 各processは全入力を2回判断する。2回目は順序を逆にする。
- **入力**：
  - 127／128／129 tokens。
  - 候補順の変更（`reversed`）。
  - 511／512／513 tokens。
  - policyの境界2件。
  - 874、3206、8192 tokens。
  - 8193 tokens（`budget_exceeded`の失敗を期待）。
- **timeout**：candidateの1／4／16 threadで`timeout_reuse`を実行する。8192 tokensの判断の途中で3秒の期限を切り、同じ`Model`で128 tokensを再び判断する。
- **合格の条件（すべて満たすこと）**：
  - 全processが正常終了すること。
  - 判断の欠けがないこと。
  - 数値gateの違反が0であること。
  - candidateの全判断で、確率と判定がreferenceとbit一致すること。
  - timeoutが起き、その後の判断がtimeout前とbit一致すること。

## メモリ（`bench/delta_heads_memory.py`の縮小plan）

- **計器**：E2bと同じ。各one-shot processの終了後に読む`PeakPagefileUsage`（private commitのpeak）と`PeakWorkingSetSize`。
- **構成**：
  - thread数：1／4／16。
  - 入力：128、874 tokensは各2回、8192 tokensは1回。
  - 1 session。armは毎回、先にする方を入れ替える。
- **合格の条件**：
  - (thread数, 入力)ごとに、各armのpeakの最大値を求める。その比（candidate÷baseline）が、両指標とも1.03以下であること。
  - processの失敗やgate違反がないこと。

## 結果

**数値とメモリの両方で合格した。** sourceは`a91b5e4`（未commitの変更なし）。このcommitはbenchとdocsだけを加えたもので、libraryは`7649bc7`と同じである。

### 数値

| 項目 | 結果 |
| --- | --- |
| process | 11（reference 1、candidate 10）。全て正常終了 |
| 判断 | reference 13、candidate 260（各26） |
| 欠け | なし |
| 数値gate違反 | 0（8193 tokensは期待どおり`budget_exceeded`） |
| referenceとのbit不一致 | 0 |
| timeout→再利用 | 1／4／16 threadとも、timeoutが起き、その後の判断がbit一致 |

- bit一致は、確率と判定の両方で確かめた。範囲は次のとおり。
  - 1〜16 thread。
  - 同じprocess内の2回目（逆順）。
  - 独立process間。
  - 候補順の変更。
  - 長さの境界（127／128／129、511／512／513）。
  - 3206／8192 tokens。
- timeoutの停止時刻（期限3秒）：1 threadで3.78秒、4 threadで4.47秒、16 threadで3.12秒。

### メモリ（生涯peak、candidate÷baseline）

| threads | 入力 | private commitのpeak | Working Setのpeak |
| ---: | --- | --- | --- |
| 1 | 128 | 202.4→202.7 MiB（1.0017） | 1047.3→1047.7 MiB（1.0004） |
| 1 | 874 | 203.7→203.9 MiB（1.0006） | 1130.4→1130.5 MiB（1.0001） |
| 1 | 8192 | 1181.1→1181.1 MiB（1.0000） | 2105.6→2105.4 MiB（0.9999） |
| 4 | 128 | 202.6→202.9 MiB（1.0014） | 1050.3→1049.3 MiB（0.9990） |
| 4 | 874 | 207.1→207.1 MiB（0.9997） | 1132.2→1132.1 MiB（1.0000） |
| 4 | 8192 | 1183.8→1183.5 MiB（0.9997） | 2106.9→2106.8 MiB（0.9999） |
| 16 | 128 | 202.7→202.8 MiB（1.0002） | 1057.2→1056.8 MiB（0.9997） |
| 16 | 874 | 220.5→220.2 MiB（0.9989） | 1139.2→1139.2 MiB（1.0000） |
| 16 | 8192 | 1197.3→1197.2 MiB（0.9999） | 2113.9→2113.9 MiB（1.0000） |

- 全条件で比は1.03以下（最大1.0017）。processの失敗やgate違反はなかった。
- 証跡：[research/native-delta-heads-2026-10-18/final-check/](research/native-delta-heads-2026-10-18/final-check)
