# Native：thread数ごとの処理別時間と、DeltaNetのhead並列化の実験（#18）

2026-10-18。[複数threadの診断](native-threads-diagnosis-2026-10-17.md)では、Nativeは1〜16 threadで1 threadとbit単位で一致する一方、4 thread以上では速度が伸びず、公式Jeffに及ばなかった。今回は2つのことを行った。

1. forwardの処理別時間をthread数ごとに測った。
2. 効果が見込めるDeltaNet逐次更新のhead並列化を、診断用のexampleの中だけで実験した。

**ライブラリと既定経路（1 thread）は変えていない。** 数値gateとbit一致の条件は、そのまま適用した。

## 方法

- **測定機**：AMD Ryzen AI MAX+ 395、Windows。
- **thread数**：bundleの`cpu_threads`で、1／2／4／8／16を指定した。
- **計時**：`runtime/rust/examples/forward_breakdown.rs`の計時版backboneを使った。
  - 0.2.0の既定経路（重みの共有buffer、512行ずつのattention）に合わせて更新した（`3d32892`）。
  - 計時版の最終hiddenが、ライブラリのforwardとbit単位で一致することを毎回確かめる。
  - 表の「既定経路のforward」は計時版の合計である。同じprocessで交互に測ったライブラリ側（`backbone::forward`、共有bufferなし）は、比較対象ではない。
- **入力**：128（candidate-request）、512（synthetic-ocr-ascii-8-512）、874（long-text）tokens。各3回。
- **実験**：`--parallel-heads`（`e831aa4`）を付けると、16個の独立なDeltaNet headを、compute threadで分担して計算する。
  - 各headは自分のbufferに、逐次版と同じ演算・同じ順序で計算し、最後に元の配置へcopyする。
  - `bench/parallel_heads_check.py`で、逐次と並列を別processで交互に測り、process単位のpeakも記録した。
  - 8192 tokensは、16 threadで1回だけ測った。

## 処理別時間（中央値、秒）

128 tokens：

| 処理 | 1 | 2 | 4 | 8 | 16 | 並列化 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 線形層の行列積 | 1.176 | 0.607 | 0.391 | 0.306 | 0.264 | される（Candle） |
| DeltaNet逐次更新 | 0.108 | 0.111 | 0.113 | 0.115 | 0.120 | されない |
| 重みの変換 | 0.077 | 0.075 | 0.078 | 0.084 | 0.084 | されない |
| 畳み込み＋SiLU | 0.041 | 0.041 | 0.043 | 0.043 | 0.044 | されない |
| 要素ごとの演算など（RMSNorm、L2、gate、layoutほか） | 0.15 | 0.15 | 0.15 | 0.17 | 0.20 | 一部はCandle |
| attention（scores、softmax、確率×V） | 0.014 | 0.011 | 0.011 | 0.011 | 0.013 | される |
| **合計** | **1.552** | **0.984** | **0.777** | **0.713** | **0.712** | |

512／874 tokensも同じ傾向だった（[生データ](research/native-threads-2026-10-18/breakdown)）。

- **16 threadでの内訳**：並列化されない処理が合計の約60%を占める。
- **DeltaNet逐次更新の割合**：全体の17〜20%（128／512／874 tokensで0.12／0.44／0.79秒）で、thread数によらず一定だった。
- **thread数とともに増える処理**：要素ごとの演算の一部（RMSNorm、L2など）は、thread数とともにわずかに増えた。

## DeltaNetのhead並列化の評価

### 事前の見積もり

- **全体の短縮率**：逐次更新がthread数で割れると仮定すると、4 threadで11〜13%、16 threadで16〜18%の短縮を見込んだ。4 threadでは公式Jeff並み、16 threadでも公式の約1.5倍の時間が残る見込みだった。
- **threadの競合**：各headの状態（16 KiB）はそれぞれのL1に収まり、入力は読むだけで共有する。書込み先はheadごとに別の領域なので、false sharingは小さいと見込んだ。
- **メモリの増加**：headごとの出力buffer（出力と同じ大きさ）。874 tokensで約7 MB、8192 tokensで約64 MB。
- **数値の再現性**：各headの演算と順序は変わらないので、bit一致を見込んだ。

### 実験の結果

| threads | 逐次更新：逐次→並列（128 tokens） | 全体の短縮（128／512／874 tokens） | bit一致 |
| ---: | --- | --- | --- |
| 2 | 0.109→0.073秒 | 3.1％／3.1％／3.5％ | すべて一致 |
| 4 | 0.114→0.054秒 | 7.4％／8.4％／8.8％ | すべて一致 |
| 8 | 0.114→0.051秒 | 7.5％／8.8％／9.0％ | すべて一致 |
| 16 | 0.116→0.050秒 | 9.0％／11.7％／13.0％ | すべて一致 |
| 16（8192 tokens） | 7.22→2.64秒 | 9.7％ | 一致 |

- **数値**：全runで、最終hiddenがライブラリのforwardとbit単位で一致した。
- **メモリ**：process単位のpeakは変わらなかった（1.14〜1.15 GiB、8192 tokensで2.16 GiB）。headごとのbufferは、forward全体のpeakを決める時点（attentionのblockなど）とは重ならない。
- **速度**：逐次更新は約2〜2.7倍にしか速くならず、見積もりに届かなかった。headの分担は16 threadまで分かれるが、次の2つが逐次のまま残るためと考えている。
  - 前処理：qのscaling、k／v／betaの取り出し、decayの`exp`。
  - 後処理：headごとのbufferを元の配置へ戻すcopy。
- **公式Jeffとの比較**：[前回の診断](native-threads-diagnosis-2026-10-17.md)で測った公式Jeff（4 threadで0.74／2.46／4.32秒）と比べる。並列化したNative（4 threadで0.714／2.524／4.176秒）は、4 threadで公式並み（Native／公式で0.96／1.03／0.97）になった。8 threadと16 threadでは、まだ公式の1.3〜1.6倍の時間がかかる。これは日の違う単発の比較で、事前登録の判定ではない。

## 結論と次の段階

- **head並列化の効果**：数値（bit一致）とメモリの面で問題はない。4 threadで約8〜9%短くなり、公式並みになった。採用する価値はある。ただし既定経路に入れる前に、次の2つが要る。
  - 前処理と後処理も並列にするか、copyをなくして、逐次更新そのものの並列効率を上げる。
  - ライブラリへの組み込み方を決める。1 threadでは今のloopをそのまま使い、2 thread以上だけ並列にする。
- **16 threadで公式並みにするには**：逐次更新だけでは足りない。次の処理の並列化も必要である。
  - 畳み込み＋SiLU（channel方向に独立）。
  - 要素ごとの演算（RMSNorm、L2、gate）。
  - 重みの変換（tensorの中で分割できる）。

  どれも、要素ごとの演算順序を変えずに分ければbit一致を保てる見込みだが、試していない。
- **#18の残り**：
  - hybrid CPUでの再現性の確認。
  - 事前登録した速度の測定。
  - thread設定と異常経路の試験。
  - ライブラリへの組み込み。

## 証跡

[research/native-threads-2026-10-18/](research/native-threads-2026-10-18)：

- thread数ごとの処理別時間（`breakdown/t{1,2,4,8,16}.jsonl`）。
- 並列化実験の事前登録・全run・log。
