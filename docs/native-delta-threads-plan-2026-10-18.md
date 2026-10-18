# Native：DeltaNet逐次更新の複数thread化 — 事前登録（#18）

2026-10-18。[処理別時間とhead並列化の実験](native-threads-breakdown-2026-10-18.md)の続き。計測の前にこの計画を記録し、結果は別の文書（[native-delta-threads-2026-10-18.md](native-delta-threads-2026-10-18.md)）に書く。ここに書いた判定条件は、計測後に変えない。

## 出発点

- 16 threadでは、並列化されない処理がforwardの約60%を占める。DeltaNet逐次更新は、そのうち全体の17〜20%を占める。
- 前回のhead並列化（`--parallel-heads`）では、逐次更新が2〜2.7倍速くなり、全体は9〜13%短くなった。bit一致は保たれ、peakも変わらなかった。
- 前回の実装：
  - 推論ごと（DeltaNetの18層それぞれ）に`std::thread::scope`でthreadを新しく作る。
  - 入力の取り出し（`to_vec1`で5回copy）、qのscaling、decayの`exp`、headごとのbufferからの書き戻しは、逐次のまま。

## 仮説（どれも未確定）

- **H1**：逐次の準備（取り出し・scaling・`exp`）と書き戻しが残っている。
- **H2**：threadの生成・join、またはgemm直後にrayonのworkerがspinしている間に別threadを起動することが、時間を食っている。
- **H3**：共有資源の競合で、1 headあたりの計算が遅くなる。候補は、メモリ帯域、L3、全コア負荷時のclock、SMTで同じコアに2 threadが載ることの4つ。

### 事前登録の前に見たもの

計測器の動作確認として、次の3回を実行して結果を見た。どれも本計測には含めない。

1. 4 thread・128 tokens・2 reps。
2. 16 thread・874 tokens・1 rep。
3. 同じ条件でのprobe。

見えた傾向：

- `pool`／`fused`では、逐次更新の本体が4 threadで約3.7倍速くなった。
- 前回の方式では、threadの生成に1 forwardあたり約5 msかかった。
- 16 threadで同時に動かすと、1 headの時間が約2.5倍に延びた。L2に収まる入力でも同じだった。
- 16 threadのとき、終了時点で16 threadのうち14がSMTで同じコアに載っていた。

## 計測器（診断用example、ライブラリは変更しない）

`runtime/rust/examples/forward_breakdown.rs`に、次の`--delta`方式を追加した。

| 方式 | 内容 |
| --- | --- |
| `serial` | ライブラリの逐次loop（コピー）。工程別に計時する |
| `scoped` | 前回の実験の再現。headを`std::thread::scope`で新しいthreadに分ける |
| `pool` | `scoped`と同じ処理を、Candle／gemmがすでに使っているrayonのglobal poolで行う |
| `fused` | rayon poolの各head taskが、q／k／v／beta／gをtensorから直接読む。qのscalingと`exp`はtask内で行う。書き戻しは、token範囲ごとにpoolで並列に行う |

どの方式も、各head・各列blockの演算と順序は、ライブラリのloop本体と同じ（`head_columns`）。違うのは、計算するthreadと書込み先だけである。

- `fused`のscalingと`exp`は、要素ごとに準備passと同じ演算（`x / sqrt(K)`、`g.exp()`）を使う。
- 毎forwardで、最終hiddenがライブラリのforwardとbit一致することを確かめ、一致しなければ失敗とする。

工程は次のように分ける。

| 工程 | 内容 |
| --- | --- |
| `delta_extract` | tensorからの取り出し（`fused`は`contiguous()`の確認だけ） |
| `delta_prep` | qのscaling、decayの`exp` |
| `delta_core` | 最も忙しいthreadの計算時間 |
| `delta_sync` | 並列区間のwallから`delta_core`を引いた残り（起動・wake・待ち・join） |
| `delta_writeback` | 元の配置への書き戻しと、tensorの生成 |
| `delta_recurrence` | 残り（未分類） |

- **補足（`delta_notes`）**：並列区間のwall、各threadの忙しさの合計・最大・平均との差（偏り）、最初と最後のthreadの開始時刻、使われたthread数。
- **計時のコスト**：`--no-stage-timers`の別processで工程timerを外し、`delta_recurrence`の合計と比べる。
- **`--probe-scaling`**：第1層の実入力を使い、新しいn thread（1／2／4／8／16）で別々のheadを同時に計算する（weak scaling）。比べるのは次の3つ。
  - 全token版。
  - 先頭64 tokensの繰返し版（1 headの行がL2に収まる）。
  - 単純なcopyの帯域。

  各threadが終了時に動いていた論理CPUを記録し、SMTで同じコアに載ったthread数を数える。

## 診断計測（D1）

- **測定機**：AMD Ryzen AI MAX+ 395（16コア32 thread）、Windows、電源プランは既存のまま（バランス）。
- **driver**：`bench/delta_stage_profile.py`。exe、driverのhash、環境は`preregistration.json`に記録する。
- **計測の構成**：

  | 計測 | thread数 | 入力 | 方式 | reps |
  | --- | --- | --- | --- | --- |
  | 工程別（2 session） | 1／2／4／8／16。session 0は昇順、session 1は降順 | 128／512／874 tokens（`candidate-request`、`synthetic-ocr-ascii-8-512`、`long-text`） | 4方式。repごとに先頭を入れ替える | 3 |
  | 工程別（2 session） | 同上 | 8192 tokens | `serial`、`fused` | 1 |
  | 計時のコスト | 各thread数で1 process | 128／874 tokens | `serial`、`fused`（工程timerなし） | 3 |
  | probe | 16 threadのprocess | 874／8192 tokens | — | — |

- **記録**：process単位のpeak Working Set／Private。
- **集計**：
  - 各工程の中央値。
  - forward全体に占める割合。
  - Amdahl則による上限（その工程が0になった場合、またはthread数で割れた場合のforward短縮率）。
  - 方式間の比：同じprocess・同じrepの対で、`fused`÷`serial`などを求め、その中央値をとる。
  - hidden SHA-256が、thread数・方式・process間で一致するか。

## 判定条件

### E1：ライブラリ組み込み案を設計する条件（D1で判定）

1. **bit一致**：すべてのforwardが、ライブラリのforwardとbit一致すること。あわせて、各入力のhidden SHA-256が、全thread数・全方式・両sessionで1種類であること。
2. **4 thread以上の効果**：512／874 tokensで、採用候補÷`serial`の対ごとの比の中央値が0.95以下であること。
3. **退行がないこと**：2 thread（全入力）と128 tokens（全thread数）で、比の中央値が1.01以下であること。
4. **8192 tokens**：4 thread以上で、2 sessionとも比が1.0以下であること。
5. **候補の選び方**：2〜4を満たす方式のうち、16 thread・874 tokensで中央値が最も小さいものを採用候補とする。差が1%未満なら、passの少ない`fused`を優先する。
6. **1 thread**：ライブラリは今の逐次loopのままにする。1 threadの各方式の値は、記述として報告するだけにする。

満たさない場合は組み込まず、結果と原因を記録して終える。

### E2：ライブラリへの採用条件（組み込み版の公開API E2E。別PRで、計測前にこの条件を写して使う）

- **比較の方法**：main（`973bbb1`）と組み込み版を、同じ測定機・同じbundle設定で、processごとに交互に実行する。
- **測る内容**：
  - thread数：1／2／4／8／16。
  - 入力：128／512／874／8192 tokens。
  - warm（resident）。
  - one-shot（初回推論を含む）。
  - peak Working Set／Private。
- **数値**：
  - 全判断が既存の数値gateに合格すること（公式との最大絶対差≤1e-4、確率和の誤差≤1e-6、非有限値なし、選択／保留と候補順の一致）。
  - 確率が、mainの1 threadとbit一致すること。thread数・同一process内の反復・独立process間・候補順の変更・入力長の境界（127／128／129、511／512／513）・8192 tokensで確かめる。
  - timeoutの後に同じ`Model`で次の判断が正常に動き、結果がbit一致すること。
- **速度**：
  - 1 thread：コードの経路が変わらないので、bit一致し、warmの中央値の比が0.97〜1.03に収まること。
  - 2 thread以上：warmの中央値の比が、全条件で1.02以下であること。さらに、4 thread以上の512／874／8192 tokensでは0.95以下であること。
  - one-shot：中央値の比が、全thread数で1.05以下であること。
- **メモリ**：peak Working SetとPrivateが、全条件でmainの1.03倍以下であること。
- **統計**：
  - 2 session（thread数の順を逆にする）。
  - 入力ごとに、各sessionで3回以上のwarmを測る。
  - 比は、同じsession・同じ入力の中央値どうしで求める。
  - 判定は、2 sessionの両方で条件を満たすこととする。

## 想定される改善の上限

前回の処理別時間（中央値）から、次の上限を見込む。

| thread数 | 128 tokens | 512 tokens | 874 tokens |
| ---: | ---: | ---: | ---: |
| 4 | 11％ | 12％ | 13％ |
| 16 | 16％ | 17％ | 18％ |

- これは、逐次更新が理想的にthread数で割れる場合の、forward全体の短縮率である。逐次更新が0になった場合の上限は、4 threadで14〜17%、16 threadで17〜20%。
- 前回の実績（4 threadで7〜9%、16 threadで9〜13%）との差、つまり今回の上積みの上限は、16 threadで5〜7 point程度である。
- DeltaNetだけでは、16 threadでの公式Jeffとの差（約2倍）は埋まらない。

## リスク

- **bit一致**：head内の順序を変えればbit一致は崩れる。そのため、`head_columns`は1つの実装を全方式で共有する。
- **gemmとの入れ子**：rayon poolで、gemmとの入れ子やworkerの待ちが起きうる。逐次更新はgemmの外で呼ぶので入れ子にはならないが、wakeのコストは`delta_sync`として測る。
- **メモリ**：headごとのbuffer（出力と同じ大きさ。8192 tokensで64 MiB）が増える。
- **依存の追加**：ライブラリに組み込む場合は、`rayon`の直接依存が1つ増える（Cargo.lockにはすでにある）。Wasmにはcfgで入れない。
