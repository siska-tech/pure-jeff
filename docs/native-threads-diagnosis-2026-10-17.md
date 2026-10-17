# Native：複数threadの診断（#18、診断のみ）

2026-10-17。#18の最初の段階として、次の2点を測った。

1. compute threadを増やしたとき、Nativeの判断がbit単位で再現するか、また1 threadとどれだけ違うか。
2. 速度がどう伸びるか。比較のため、公式Jeffも同じthread数で測った。

**既定経路は変えていない**（1 threadの主張と受入はそのまま）。これは事前登録の受入runではなく、記述的な診断である。

## 背景

KazeJudge時代の実験（[cache診断](onnx-tract-native-cache-diagnostic.md)ほか）では、4 threadで同じ入力を繰り返すと確率が1e-6を超えてずれた。原因の候補は、gemmがkernelの大きさを決めるcache情報（`CACHE_INFO`）である。この値はprocessごとに一度、最初に動いたCPUから読まれるので、P／Eコアが混在するIntelのCPUでは、processによって値が変わりうる。

## 方法

- **測定機**：AMD Ryzen AI MAX+ 395（16コア32 thread）、Windows、main `2221283`。
- **cache情報**（`thread_probe` example）：32個の論理CPUのそれぞれに固定して起動し、gemmの`CACHE_INFO`を記録した。
- **反復と速度**（`bench/thread_diagnosis.py`）：
  - thread数：1／2／4／8／16。
  - Native：各thread数で独立した2 processを、公開API経路で動かした。jobは、短い入力とpolicy境界の14入力を3回ずつ（固定した順序）、長い3入力（874／3206／8192 tokens）を1回ずつ。1回目はthread数の昇順、2回目は降順で実行した。
  - 公式Jeff：各thread数で1 process。128／512／874 tokensを3回ずつ判断した。
  - bundleは、thread数ごとに`jeff lock`と`jeff_worker.py --lock`で作った。
  - **数値gate**：全判断に、1 threadの公式参照に対する共通の数値gateをかけた。

## 結果

### cache情報

32個の論理CPUのすべてで、`CACHE_INFO`は同じだった。L1は48 KiB（12-way）、L2は1 MiB（16-way）、L3は0（検出されない）。この機械では、最初に動いたCPUによってkernelの大きさが変わることはない。

### 再現性と数値

| thread数 | 同じprocess内の反復 | 独立process間 | 1 threadとbit一致しない入力 | 公式との最大差 | 数値gate |
| ---: | --- | --- | ---: | ---: | --- |
| 1 | 一致 | 一致 | — | 4.74e-6 | 違反なし |
| 2 | 一致 | 一致 | 0 | 4.74e-6 | 違反なし |
| 4 | 一致 | 一致 | 0 | 4.74e-6 | 違反なし |
| 8 | 一致 | 一致 | 0 | 4.74e-6 | 違反なし |
| 16 | 一致 | 一致 | 0 | 4.74e-6 | 違反なし |

**この機械では、2〜16 threadの結果が、すべての入力で1 threadとbit単位で一致した。** gemmは、threadで分けた各要素の和を、thread数に関係なく同じ順序で計算していると考えられる。Native独自の処理（DeltaNetの逐次更新、畳み込み、要素ごとの演算）は1 threadのままなので、そもそも順序が変わらない。peak Working Setは、thread数に関係なく約2.1 GiBだった。

### 速度（判断1回の中央値、秒）

| thread数 | 128 tokens：Native／公式 | 512 tokens：Native／公式 | 874 tokens：Native／公式 | 3206：Native | 8192：Native |
| ---: | --- | --- | --- | ---: | ---: |
| 1 | 1.54／1.58 | 5.68／6.37 | 9.87／11.98 | 40.3 | 135.5 |
| 2 | 1.02／0.93 | 3.73／3.65 | 6.30／5.98 | 25.8 | 84.2 |
| 4 | 0.78／0.74 | 2.78／2.46 | 4.65／4.32 | 18.7 | 60.7 |
| 8 | 0.70／0.49 | 2.58／1.68 | 4.34／2.97 | 16.4 | 51.4 |
| 16 | 0.75／0.41 | 2.42／1.21 | 4.12／2.13 | 15.1 | 45.5 |

- **伸び方**：Nativeは4 threadまでで頭打ちになり、1 threadに対して128 tokensで約2倍、512 tokensで約2.3倍にとどまる。公式は16 threadまで伸び、約3.8〜5.6倍になる。
- **公式との比**：
  - 2 threadでは同等に近い（128 tokensで1.10、512 tokensで1.02）。
  - 4 threadで1.05〜1.13。
  - 8 threadで1.43〜1.54。
  - 16 threadで約2倍。
- **頭打ちの理由（推定）**：Candleの行列積だけがthreadで分かれ、Native独自の処理（DeltaNetの逐次更新、畳み込み、要素ごとの演算、重みの変換）は1 threadで動く。Amdahl則によって、行列積以外の部分が残っていると考えている。まだ段階ごとの内訳は測っていない。
- **測定の性格**：これは単発の記述的な測定で、事前登録したblock設計の判定ではない。

## 結論と次の段階

- **数値と再現性**：この機械では問題がない。複数threadを提供しても、出力は1 threadとbit単位で同じになる。ただし、これは「全コアが同じcache情報を持つCPU」での結果である。P／Eコアが混在するCPUでの再現性は、旧実験どおり別に確かめる必要がある（ここでは測っていない）。
- **速度**：4 thread以上では公式Jeffに及ばない。複数threadで同等を主張するには、行列積以外の処理を並列化する必要がある。次は、`forward_breakdown`をthread数ごとに測り、どの処理が頭打ちの原因かを特定する。改善の候補は、headごとに独立したDeltaNetの逐次更新（16 head）と、要素ごとの演算の並列化である。どちらも、各要素の計算順序を変えずに分ければ、bit一致を保てる見込みがある。
- **#18の受入条件のうち未達のもの**：
  - 別のCPU環境（特にhybrid CPU）。
  - 事前登録した速度の測定。
  - threadの設定・初期化・異常経路の試験。

## 証跡

[research/native-threads-2026-10-17/](research/native-threads-2026-10-17)：

- CPUごとのcache情報（`probe-per-cpu.jsonl`）
- 事前登録と集計
- session別の全判断
- log
