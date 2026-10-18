# Native：DeltaNet headの複数thread化 — 公開API E2E（E2／E2b）の結果（#18）

2026-10-18。計画と判定条件は[E2の事前登録](native-delta-heads-e2e-plan-2026-10-18.md)にある。E2bの節は、E2の結果を見た後に追加した。組み込みの根拠は[工程別の診断](native-delta-threads-2026-10-18.md)（#36）にある。

## 結論

**採否：採用（例外承認）。** 2026-10-19、利用者（リポジトリ管理者）が#37の採用を承認した。

- **E2の判定**：事前登録した条件では**不合格**だった。これを正式な記録として維持し、事後に合格へ変えない。
  - 数値、bit一致、timeout、速度、peak Working Setは、全条件で合格した。
  - one-shotのPrivate（0.1秒ごとのsampling）が、6条件で1.03を超えた（最大1.147）。うち1条件は、両armが同じ逐次loopを使う1 threadだった。
- **追加証拠として認めたもの**：
  1. **E2b**：E2の結果を見た後に追加した計測である。同じ1.03の条件を、OSの生涯peak（終了後に読んだ`PeakPagefileUsage`／`PeakWorkingSetSize`）で測り直し、全条件で合格した。
     - private commitのpeakの比：0.998〜1.003。
     - Working Setのpeakの比：0.999〜1.001。
  2. **[最終commitでの代表ケース検証](native-delta-heads-final-check-2026-10-18.md)**：数値とメモリの両方で合格した。
     - 数値：1〜16 threadの260判断が、mainの1 threadとbit一致した。gate違反は0で、timeout後の再利用も確認した。
     - メモリ：生涯peakの比は最大1.0017だった。
- **例外承認の根拠**：
  - E2の不合格は、sampling計器が短いpeakを取りこぼしたためと判断した。実際のメモリ増加ではない。
  - 生涯peakでは、E2bと最終検証の両方で、事前登録と同じ閾値（1.03）を満たした。
  - 数値、bit一致、速度の条件は、すべて満たしている。
- **この承認の範囲**：今回の採用に限る。E2の判定条件や、今後の計測の受入条件は変えない。

## E2：公開API E2E

- **規模**：230 process、全てrc=0。
- **構成**：2 session × 5 thread数 × 2 arm。種類は次の3つ。
  - warm：各processで28判断。
  - one-shot：入力ごとに3回（8192 tokensは1回）。
  - timeout→再利用（session 0のみ）。
- **build**：
  - baseline：main（`973bbb1`）。
  - candidate：`e979904`（ライブラリは`4a0d392`と同じ）。
  - armごとに、そのbuildで作ったbundleを使った。違いは`runtime_build_sha256`だけである。

### 数値

| 項目 | 結果 |
| --- | --- |
| 数値gate違反 | 0 |
| mainの1 threadとのbit不一致 | 20入力の全判断で0 |
| timeout→同じ`Model`での再利用 | 全thread数・両armでbit一致 |

bit一致の範囲は次のとおり。

- 両arm、1〜16 thread。
- 同じprocess内の反復、独立process間。
- 候補順の変更（`reversed`）。
- 長さの境界：127／128／129、511／512／513。
- policyの境界、3206／8192 tokens。
- 8193 tokensでは、期待どおり`budget_exceeded`の失敗になった。

timeoutの停止時刻（期限3秒）は3.1〜4.9秒で、どちらのarmにも系統的な差はなかった。停止の判定は、層の間とattentionのblockの間で行われる。この契約は変えていない。

### 速度（warm、`decide`の中央値の比 candidate÷main。各セルは「session 0／session 1」）

| threads | 128 | 512 | 874 | 8192 |
| ---: | --- | --- | --- | --- |
| 1 | 1.010／1.007 | 1.009／1.003 | 1.003／1.009 | 1.018／1.022 |
| 2 | 0.947／0.955 | 0.935／0.948 | 0.939／0.944 | 0.954／0.957 |
| 4 | 0.897／0.911 | 0.861／0.865 | 0.888／0.883 | 0.921／0.912 |
| 8 | 0.895／0.894 | 0.880／0.874 | 0.866／0.869 | 0.907／0.890 |
| 16 | 0.892／0.942 | 0.867／0.863 | 0.848／0.847 | 0.870／0.887 |

- 1 threadの比は、条件（0.97〜1.03）を満たした。ただし、8192 tokensでは両sessionとも約2%遅かった。
  - 1 threadのcandidateは逐次loopの本体を変えていない。違いは、`recurrence`経由の呼び出しとbuildの違いだけである。
  - 原因は特定していない。codegenや配置の差の可能性がある。
- one-shot（process全体、load＋初回判断）の比は0.864〜1.044で、全条件で1.05以下だった。

### 絶対値（warm中央値、秒、両sessionの範囲）

| thread数 | candidate（128／512／874 tokens） | 公式Jeff（[診断](native-threads-diagnosis-2026-10-17.md)、参考） |
| ---: | --- | --- |
| 4 | 0.68〜0.69／2.36／3.99 | 0.74／2.46／4.32 |
| 16 | 0.65〜0.68／2.05〜2.07／3.36 | 0.41／1.21／2.13 |

- 4 threadでは、公式より4〜8%短い。
- 16 threadでは、公式の1.6〜1.7倍かかる。

日の違う単発の比較で、事前登録の判定ではない。

### メモリ

| 計器 | 結果 |
| --- | --- |
| warm processのpeak Working Set | 0.998〜1.004 |
| warm processのPrivate（sampling） | 0.996〜1.008 |
| one-shotのpeak Working Set | 1.000〜1.001 |
| one-shotのPrivate（sampling） | 0.864〜1.147。6条件で1.03を超え、うち1条件は1 thread（両armで同じloop）の1.078 |

## E2b：生涯peakでのメモリ再計測

- **規模**：240 process（one-shotのみ、2 session）。全てrc=0、gate違反0。
- **計器**：各processの終了後に`GetProcessMemoryInfo`で読んだ値。

| 指標 | 比の範囲 | 例：8192 tokens・16 thread |
| --- | --- | --- |
| `PeakPagefileUsage`（private commitのpeak） | 0.998〜1.003 | 1197.2 MiB→1197.2 MiB |
| `PeakWorkingSetSize` | 0.999〜1.001 | — |

headごとのbuffer（8192 tokensで出力と同じ64 MiB）は、forward全体のpeakを決める時点（attentionのblock）とは重ならない。そのため、peakは増えない。

## affinityを変えたときの再現性（記述、hybrid CPUの代わりではない）

- **方法**：candidate（4／16 thread）を、起動直後にprocess affinityを次の5通りに制限して実行した。
  - 全CPU。
  - CPU 0〜15。
  - CPU 16〜31。
  - 各コア1 thread（偶数CPU）。
  - CPU 8〜11。
- **入力**：128 tokens、874 tokens、policyの境界1件。
- **結果**：10条件すべてで、mainの1 thread（affinityなし）とbit一致し、gate違反はなかった。16 threadを4 CPUに詰めた場合も同じである。
- **参考（単発）**：「各コア1 thread」は、16 thread・874 tokensで3.63秒だった。全CPU（3.37秒）より速くはならなかった。
  - 診断の文書（#36）は、16 threadで伸びない主因をSMTでの同居と全コアclockとしていた。このうちどちらがどれだけ効いているかは、未解決として扱う。

## E2の後のコード変更

- **変更**：CI（Rust 1.99.0）のclippyが、定数幅の`chunks_exact_mut`をerrorにした。そのため、`delta_recurrence_heads`の2か所を`as_chunks_mut::<V>()`に置き換えた（`chunks_exact_mut(V)`→`as_chunks_mut::<V>().0.iter_mut()`）。
  - 分割は同じで、演算は変わらない。
  - E2とE2bで測ったbuildは、この変更の前のものである。
- **変更後の確認**：再buildしてbundleを再lockし、affinityの試験を1／2／4／16 threadで行った。
  - 20条件すべてで、mainの1 threadとbit一致し、gate違反はなかった（`affinity-after-lint-fix/`）。
  - 時間はE2と同じ水準だった（874 tokensで、16 thread 3.35秒、4 thread 3.95秒）。
  - E2・E2bそのものの再実行はしていない。

## 組み込みの設計（このPR）

| 項目 | 内容 |
| --- | --- |
| 有効になる条件 | `native` featureのbuildで、compute threadが2以上（`candle_core::utils::get_num_threads() > 1`）のとき |
| 有効になる経路 | `Model`、`ColdProvider`、worker、`backbone::forward`のすべて。どれも`linear_attention`を通る |
| 1 thread | 今の`delta_recurrence`をそのまま呼ぶ |
| 利用者の設定 | 新しい設定はない。bundle policyの`cpu_threads`（`configure_threads`）で決まる。既定の1 threadでは何も変わらない |
| 公開API | 変更なし |
| thread | rayonのglobal pool（Candleの行列積と同じ）を使う。推論ごとにOS threadを作らない |
| 小さな入力 | 閾値を設けない。2 thread・128 tokensでも短縮した（E2で0.947／0.955） |
| Wasm | `recurrence`は`delta_recurrence`の別名になり、並列のコードと`rayon`はcompileされない。Web demo engineとWasm probeはmainとbyte単位で同じである（engine `a25d75fc…`、probe `04a4de25…`） |
| 依存 | `rayon`（1.7、`native`の任意依存）。Cargo.lockに新しいcrateは増えない。unsafeの追加はない |
| 移植性 | rayonはWindows／Linux／ARM64で動く。Linuxはこのbranchのcheck（CI）で確かめる。ARM64は、build・実機とも未確認 |

## #18の受入条件に対する状況

| 受入条件 | 状況 |
| --- | --- |
| 実kernel parameterとCPU／cache条件 | AMDの1台のみ記録済み（10-17）。hybrid CPUは未確認 |
| 28件と長文・判断境界を含む数値gate | 現行集合では、全thread数・両armで合格（E2）。旧28件そのものの再実行はしていない |
| 反復差≤1e-6、既定経路のbit互換 | 1〜16 threadで、mainの1 threadとbit一致（E2、affinity） |
| thread設定・初期化・affinity復元・異常経路、CPU0固定なし | affinityの制限下でbit一致。timeout後の再利用も確認。初期化順とaffinityの「復元」は未試験 |
| 未計装のAPI E2E（速度・起動・peak）とhost別の成立範囲 | この1台（AMD Ryzen AI MAX+ 395、Windows）でE2を実施した。Linuxの実機、ARM64、Intel hybridは未確認 |

**Intel hybrid CPUは、この作業では利用できなかった。** 実機での確認はしておらず、確認したことにもしない。上のaffinityの試験は、CPUの一部に制限してもbit一致することを示すだけである。P／Eコアで`CACHE_INFO`が異なる場合のgemmの分割は確かめていない。

### 残課題（未確認。確認済みとして扱わない）

- **Intel hybrid CPU（P／Eコア混在）**：次のいずれも未確認。
  - CPU topologyとcache情報。
  - gemmのkernel選択。
  - thread数ごとの数値の再現性。
  - 初期化順の影響。
  - affinityへの依存。
- **Linuxの実機**：CIでbuild・test・clippyが通ることだけを確かめた。実機での速度、メモリ、bit一致の計測はしていない。
- **ARM64**：build・実機とも未確認。
- **Windows／Linux間の差**：未確認。
- **旧28件のgate**：そのものの再実行はしていない。
- **初期化順とaffinityの復元の試験**：未実施。
- **1 threadの8192 tokens**：E2で約2%遅かった（基準内）。原因は特定していない。

#18は、残りの受入条件を満たすまで閉じない。

## 16 threadで残る差（次の候補）

[診断](native-delta-threads-2026-10-18.md)の内訳によると、この変更の後も、16 thread・874 tokensで公式の約1.6倍かかる。次に取り組む候補の優先度は次のとおり。

1. **畳み込み＋SiLU**：見込みは最大約8%。channel方向に分ければ、要素ごとの演算順序は変わらない。
2. **計時の外にある約10%**：中身を特定する。
3. **RMSNorm／L2**：Candleの総和順序を再現できなければ、bit一致しない。
4. **行列積**：#15の範囲。

## 証跡

[research/native-delta-heads-2026-10-18/](research/native-delta-heads-2026-10-18)：

- `e2/`：事前登録、全process、集計、log。
- `e2b/`：同上。
- `affinity/`：結果。
- `affinity-after-lint-fix/`：コード変更後の再確認。
