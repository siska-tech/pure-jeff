# Native：DeltaNet headの複数thread化（ライブラリ組み込み）— E2の事前登録（#18）

2026-10-18。[工程別の診断](native-delta-threads-2026-10-18.md)は、E1（組み込み案を設計する条件）を満たした。候補は`fused`である（どちらの文書も#36）。この文書は、ライブラリに組み込んだ版を公開APIで測り、採否を判定する計画である。計測の前にcommitする。判定条件は[事前登録](native-delta-threads-plan-2026-10-18.md)のE2をそのまま写し、計測後に変えない。

## 組み込みの内容（このbranch）

- **2 thread以上（`candle_core::utils::get_num_threads() > 1`）**：
  - `linear_attention`は、DeltaNet逐次更新の16 headをrayonのglobal poolで計算する（`delta_recurrence_heads`）。これは、Candleの行列積がすでに使っているpoolである。
  - 各headは、入力をtensorから直接読む。qのscalingと`exp`は、使う場所で要素ごとに行う。各headは自分の(seq, V) bufferに書き、最後にtoken範囲ごとに並列で(seq, H, V)へ並べ直す。
  - head内の演算と順序は、逐次loopと同じである。testで、1／2／3／16 threadのpoolと、seq 1／2／37／130を使い、逐次loopとreferenceの両方とのbit一致を確かめる。
- **1 thread**：今の`delta_recurrence`（逐次loop）をそのまま呼ぶ。この関数の本体は変えていない。
- **thread数の解釈**：変えていない。並列化の有無は、bundle policyの`cpu_threads`、すなわち`configure_threads`で決まる。新しい設定項目、公開APIの変更、既定値の変更はない。
- **Native以外**：
  - `native` featureのないbuild（Wasm）では、`recurrence`は`delta_recurrence`の別名である。並列のコードと`rayon`はcompileされない。
  - Web demo engineとWasm probeを`tools/build_wasm.py`でbuildし、mainと同じSHA-256を確かめた。
    - engine：`a25d75fc…`
    - probe：`04a4de25…`
- **依存**：`rayon`（`version = "1.7"`、Candleと同じ指定）を、`native` featureの任意依存として加える。Cargo.lockにはすでにあり、新しいcrateは増えない。unsafeは加えない。

## 比較の方法

- **driver**：`bench/delta_heads_e2e.py`。plan、job、seed、exe・bundle・catalog・driverのhash、開始時の環境は、`preregistration.json`に計測前に書く。
- **比べるbuild**：
  - baseline：main（`973bbb1`）。
  - candidate：このbranch。
  - どちらも`runtime/rust`の`resident_bench`と`timeout_reuse`を`--release --locked`でbuildし、同じtoolchainを使う。
- **bundle**：bundleのruntime build hashはlibraryのsourceも含むので、armごとに、そのbuildの`jeff lock`で作ったbundleを使う。
  - baseline：`models/pure-jeff-bundle-tN-diag.json`（N＝1／2／4／8／16）。
  - candidate：`models/pure-jeff-bundle-tN-delta-heads.json`。
  - 両者の違いが`runtime_build_sha256`だけであることを、driverが計測前に確かめる。
- **session**：2回。session 0はthread数の昇順、session 1は降順で実行する。各thread数で、2つのarmのどちらを先にするかを交互に入れ替える。
- **計測の種類**：

  | 種類 | 内容 | 回数 |
  | --- | --- | --- |
  | warm | resident processを1つ立てる。warm-up（256 tokens）の後、測る入力（128／512／874／8192 tokens）を各3回、固定のshuffle順（seed 20261018）で判断する。続いてgate入力を各1回判断する | armとthread数ごと、各sessionで1回 |
  | one-shot | 入力1件ごとに新しいprocessを立てる（load＋初回判断） | 128／512／874 tokensは3回、8192 tokensは1回。armは入力ごとに交互 |
  | timeout | `timeout_reuse`を使う。8192 tokensの判断の途中で期限（3秒）を切り、同じ`Model`で128 tokensを再び判断する | 各thread数でarmごとに1回（session 0のみ） |

- **gate入力**：
  - 境界：127／128／129、511／512／513 tokens。
  - 候補順を変えたもの：`reversed`。
  - policyの境界：4件。
  - special token、ASR Unicode。
  - 3206 tokens（`maximum-candidates`）。
  - 8193 tokens：`budget_exceeded`の失敗が期待どおりに出ること。
- **記録**：全判断の`wall_s`（`decide`の前後だけを測り、内部に計時はない）、process単位のpeak Working SetとPrivate、processのwall。

## 判定条件（E2、事前登録から転記）

- **数値**：
  - 全判断が既存の数値gateに合格すること（公式との最大絶対差≤1e-4、確率和の誤差≤1e-6、非有限値なし、選択／保留と候補順の一致）。
  - 確率が、mainの1 threadとbit一致すること。thread数・同一process内の反復・独立process間・候補順の変更・入力長の境界・8192 tokensで確かめる。
  - timeoutの後に同じ`Model`で次の判断が正常に動き、結果がbit一致すること。
- **速度**：
  - 1 thread：コードの経路が変わらないので、bit一致し、warmの中央値の比が0.97〜1.03に収まること。
  - 2 thread以上：warmの中央値の比が、全条件で1.02以下であること。さらに、4 thread以上の512／874／8192 tokensでは0.95以下であること。
  - one-shot：中央値の比が、全thread数で1.05以下であること。
- **メモリ**：peak Working SetとPrivateが、全条件でmainの1.03倍以下であること。
- **統計**：
  - 比は、同じsession・同じ入力の中央値どうしで求める（candidate÷baseline）。
  - 判定は、2 sessionの両方で条件を満たすこととする。
  - one-shotの中央値は、入力ごとに3回（8192 tokensは1回）の値から求める。
  - メモリの「条件」は、(session, thread数, 種類, 入力)ごとのprocess peakの最大値どうしで比べる。

全条件を満たした場合に限り、既定経路（2 thread以上）への採用を提案する。満たさない条件があれば採用せず、結果と原因を記録する。

## E2b：メモリの再計測（E2の結果を見た後に追加した計画）

**E2の判定は変えない。** E2は、事前登録した条件では「不合格」である。

- **不合格の理由**：one-shotのPrivate（sampling）比が、6条件で1.03を超えた（最大1.147）。
- **合格した項目**：
  - 数値：gate違反0、bit不一致0、timeout後の再利用。
  - 速度：全条件。
  - peak Working Set：全条件。
- **原因の推定**：
  - E2のPrivateは、`bench/procmem.py`がprocess treeのPrivate bytesを0.1秒ごとに読んだ最大値である。sampleの間にある短いpeakは取りこぼす。
  - 1 threadでは両armが同じ逐次loopを使う。それでも1.078になった条件があり、逆に0.864〜0.885になった条件もある。
  - これは推定であり、確認はしていない。

E2bでは、条件をそのままに、計測器だけを替えて測り直す。採否は、E2とE2bの結果を並べて示したうえで、利用者が判断する。

- **計器**：各one-shot processを起動時にopenし、終了後に`GetProcessMemoryInfo`でOSの生涯peakを読む。読むのは`PeakPagefileUsage`（private commitのpeak）と`PeakWorkingSetSize`である。終了後の読み取りでpeakが取れることは、300 MiBの一時確保で確かめた。
- **driver**：`bench/delta_heads_memory.py`。
- **計測の構成**：
  - thread数：1／2／4／8／16。
  - 入力：128／512／874 tokensは各3回、8192 tokensは1回。
  - one-shotのみ。
  - 2 sessionで、thread数の昇順と降順。
  - 2つのarmのどちらを先にするかを毎回入れ替える。
  - 全判断に数値gateをかける。
- **判定**：
  - (session, thread数, 入力)ごとに、各armのpeakの最大値を求め、candidate÷baselineの比をとる。
  - 2 sessionの全条件で、比が1.03以下であること。
  - processの失敗やgate違反がないこと。
