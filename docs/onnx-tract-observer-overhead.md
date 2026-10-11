# 環境記録あり／なしの負荷比較pilot

2026-10-11。[環境記録の結合検証](onnx-tract-host-observer.md)後に新規事前登録した比較。固定cacheB Native4と受入済みTract4のexe／資産を変更せず、各backendの記録あり／なしを2組・順序反転して比較した。既存runtime・公開API・Decision Reportは不変。

## 条件

同じ既存人工OCR入力（3候補、有効128 tokens）、同一step1113／FP32常駐／batch1／4 threads。Nativeは物理128、Tractは左paddingした物理512で演算するため、backend間の大小ではなく、同じbackend内の記録有無を評価する。各sessionは5 warmup＋3測定、8 child・64 forward、各backend・記録条件n=6、各session n=3。順序はblock0 Native off→on／Tract on→off、block1 Tract off→on／Native on→off。

記録ありは1秒間隔のWindows read-only observerを既存invokeの外側へ追加した。記録なしも、計時の前後に同じreaderで電源・CPU情報を取得する。offにはsession内部の継続記録がない。AC1／省電力flag0、電源scheme・observer mask・CPU topologyが初期値と一致することを境界で確認した。onでは記録エラーなし・2標本以上・最大間隔2.5秒以内も必須とした。

ONNX確率差1e-4、確率和誤差1e-6、判断／tokens一致、Native旧参照・全観測ペア差1e-6、Tract raw完全一致を維持。各child期限600秒・Peak Working Set上限min(8 GiB,物理RAMの50%)。入力・順序・閾値を測定前に固定し、途中の標本追加・差し替えを行わない。

## 数値・実行条件

全64 forward・8 childが数値／resource／host条件に合格。最大ONNX確率差2.4139881134033203e-06、Native全32 forwardの反復完全一致=True。全raw／入力順／pool／cache／全観測ペア・電源条件と統計を独立再計算した。baseline127ファイルと隣接KazeNhanh21ファイル、固定資産・前回証跡は不変。

## Warm prepared-compute（秒）

nearest-rank中央値／p95。各cell n=6でp95は最大値。5%差は事前登録した記述用screenに過ぎず、信頼区間や性能同等性の受入ではない。

| backend | off中央値 | on中央値 | 中央値差 (on−off) | 相対差 | off p95 | on p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native4 | 2.091780 | 2.023722 | -0.068059 | -3.254% | 2.295627 | 2.336423 |
| tract4 | 7.431042 | 7.761498 | +0.330456 | +4.447% | 8.339369 | 8.211336 |

## 順序反転した各組

| backend | block | off中央値 (s) | on中央値 (s) | 差 (s) | 相対差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| native4 | 0 | 1.914463 | 1.918330 | +0.003866 | +0.202% |
| native4 | 1 | 2.181357 | 2.215028 | +0.033671 | +1.544% |
| tract4 | 0 | 7.356490 | 7.761498 | +0.405008 | +5.505% |
| tract4 | 1 | 8.193637 | 7.773428 | -0.420209 | -5.128% |

Nativeは各組の中央値差がどちらも正だったが、pooled中央値差は負になった。n=6のnearest-rank中央値と組間の分布差により集計の方向が異なるため、pooled値だけで高速化・負荷低下を判断しない。Tractは2組で差の符号が反転し、両組とも絶対相対差が5%を超えた。observer負荷が小さい／安定しているという受入は行わず、独立組の追加と環境条件の改善を先に行う。

## 親processと初期化の付随観測

各条件session n=2。parent CPUはobserverと既存10ms間隔のメモリ／期限監視などを含む親process全threadのCPU時間で、child CPU時間を含まない。wrapper wallはobserver開始・終了を含み、既存invokeのparent_process時間より外側の区間。性能への因果効果を分離した値ではない。

| backend | mode | parent CPU合計 (s) | wrapper wall中央値 (s) | startup中央値 (s) | lifetime peak最大 (GiB) |
| --- | --- | ---: | ---: | ---: | ---: |
| native4 | off | 0.718750 | 21.722530 | 3.781564 | 4.276 |
| native4 | on | 0.609375 | 19.473272 | 3.510159 | 4.276 |
| tract4 | off | 1.578125 | 78.462572 | 19.488007 | 3.051 |
| tract4 | on | 1.421875 | 83.698327 | 20.816904 | 3.051 |

request・startup・wrapper wall・parent CPU・lifetime peakの中央値／p95／nはsummary.jsonに保存。n=2のnearest-rank中央値は小さい方の値であり、推定の安定性はない。lifetime peakは初期化・mapped／shared pagesを含み、warm private memoryではない。

## 観測coverageと判定

| on run | 標本数 | 最大間隔 (s) | 収集時間最大 (ms) |
| --- | ---: | ---: | ---: |
| block0-native4-on | 21 | 1.015805 | 1.308600 |
| block0-tract4-on | 85 | 1.020157 | 2.893200 |
| block1-tract4-on | 84 | 1.016730 | 5.092300 |
| block1-native4-on | 24 | 1.016477 | 2.973700 |

native4のpooled中央値相対差は-3.254%、p95相対差は+1.777%。2組の中央値相対差も含め、全て±5%の記述範囲内だった。

tract4のpooled中央値相対差は+4.447%、p95相対差は-1.535%。2組の中央値相対差も含め、一部が外れているため全ては±5%の記述範囲内ではなかった。

各条件n=6・同じ既存入力・各2 sessionのpilotであり、変化がobserver由来か、背景負荷・熱・core配置・順序などの変動かは分離できない。負の差をobserverによる高速化と解釈せず、±5%以内でも同等性能や「影響なし」と判定しない。温度・hardware effective clockは取得不可、OS報告MHzとsystem busyは代理記録に留まる。scheme内部設定・OS電源modeや標本間変化は保証しない。

記録あり条件の数値・動作は局所確認できたが、正式性能・SLO・backend採用・認識品質は未受入。次はobserver有無の独立組と未使用本文を増やし、背景負荷／CPU配置の条件を記録・制御する。配置を変更する場合はcache初期化条件とcompute maskを分け、全28-case数値gateとresident反復gateを先に行う。正式warm campaignの5 warmup・n≥300、API E2E、cold／warm、Phase 5実データ品質評価は別作業として残る。

[事前登録・生記録・独立validator](research/jeff-onnx-tract/observer-overhead-2026-10-11/README.md)。[比較ハーネス](../runtime/onnx/benchmark_observer_overhead.py)。
