# Jeff Trilu行単位処理の独立実験

2026-10-11。[4／8-thread診断](onnx-tract-thread-profile.md)で残ったTriluを対象に、contiguousな行の消去領域をまとめてfillする最小変更を試作した。Native・通常Tract probe・公開API・Decision Reportは変更しない。

## 変更範囲と意味の保全

固定Tract 0.23.8のcommit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a`、受入済みの重複探索削除＋多スレッド版を基準にする。新しい生成treeとCargo targetへコピーし、変更は`core/src/ops/array/trilu.rs`のguard付き呼出と、project作成の`trilu_rows.rs`だけに限定した。benchmark driver、optimizer、thread threshold、data crateの既存修正と依存lockは不変。

元の処理は各座標を列挙し、upperなら`col < row+k`、lowerなら`col > row+k`をdefault値へ置き換える。候補はstandard layoutを確認してから、upperの行頭区間またはlowerの行末区間へ`fill(T::default())`を適用する。書き換え対象外の値は触らず、浮動小数点の演算・順序も変更しない。

非標準layoutは元のindexed loopへ戻す。`row+k`のi64加算があふれる可能性がある場合も、変更前にfast pathを辞退する。元のrelease版はその境界でwrapするため、今回の性能変更で数学的な境界処理へ修正しない。境界の意味を修正するなら別issue・別回帰とする。lower側の消去開始位置はi128で計算し、`row+k+1`自身のoverflowを避ける。空形状では書込みを行わない。

独立Rust helper試験は長方形・batch・空形状・正負k・上下三角を32,800組で比較し、別試験で整数境界、変更前の辞退、NaN payload／負zeroの保持、String defaultも確認する。実Tractの小型ONNX試験は4形状／転置条件×3 dtype（FP32／I64／BOOL）×upper/lower×7 kの168条件を、固定対照とscalar参照へ比較する。各exeで2回forwardする。極端なkは元のrelease wrapを参照にする。

## 性能比較の設計

同一step1113のdeclutter済みNNEF、batch1、物理512、候補requestの有効128 tokens、4 threads。資産・source・goldenをhash確認し、両exeの4件gateが通ってから計測する。全raw logitsが前回の固定対照と完全一致することを条件にする。

常駐比較はAB／BA／ABの独立3組。各processで1 warmup＋3測定、各exeの計測なしforwardはn=9。nearest-rank p95は観測最大であり、信頼区間や正式SLOの根拠にはしない。起動・process Peak Working Setは各n=3の付随観測で、cold評価を完了した扱いにはしない。Peak Working Setはmapped/shared pagesを含む。

局所受入は、3組すべてのsession中央値差が改善方向、pooled中央値・p95も改善、全数値gate成功、guard失敗0と事前登録する。一組でも再現しなければ不採用とする。計測なし比較の後に別の計測ありセッションを各exeへ1回追加し、Trilu内訳を確認する。profileは1 warmup＋3測定で、性能比較へ混ぜない。

guardはprocess600秒とmin(8 GiB,物理RAMの50%)。実行前に空きRAM4 GiB以上を要求する。温度・affinity・背景負荷・storage cacheは制御せず、ビルド・試験を測定と並行させない。prepared tensorsの比較であり、Tokenizer／API E2EやNativeとの比較ではない。

## 実測結果と局所判定

Windows CPU（Core i7-1360P、Balanced電源設定）で実行し、全10 process・40 forwardが成功した。全255 raw logitsは4件とも固定対照と完全一致し、golden確率との差は最大4.9173831939697266e-6、判断・tokensも一致した。guard発動は0件。

| 観測対象 | 対照 | Trilu候補 | 標本数 |
| --- | ---: | ---: | --- |
| warm forward中央値 | 8.963430秒 | 8.361453秒 | 各9、独立3 session |
| warm forward p95 | 9.899806秒 | 8.666366秒 | 各9、p95は最大値 |
| 起動中央値 | 20.247582秒 | 20.385648秒 | 各3、付随観測 |
| 起動p95 | 21.502306秒 | 20.453793秒 | 各3、p95は最大値 |
| Peak Working Set最大 | 3,276,775,424 bytes | 3,276,881,920 bytes | 各3、process lifetime |
| 別sessionのTrilu計測中央値 | 0.792394秒 | 0.001648秒 | 各3、性能集計から除外 |

対応するsession中央値の差（候補−対照）は−0.776426／−0.738890／−1.131365秒。pooled中央値は0.601977秒短縮し、3組すべて・中央値・p95・数値gateの事前条件を満たしたため、**この実験経路では局所受入**とする。起動短縮は確認していない。operator診断の短縮時間と通常forwardの短縮時間は別の観測であり、そのまま対応づけない。

回帰はPython 28試験（skip 0）、独立helper Rust 2試験、実候補rlibへ直接リンクしたRust 2試験に合格。小型ONNXの168条件は両exeで各2 forward、計336 process・672 forwardを比較した。直接operator試験は共有入力のcopy-on-writeと空形状を確認する。plain RAMのArrayViewMutはshapeからstandard layoutで構築されるため、非標準layoutのfallback guardを直接通した試験ではない。この制限を証跡へ記録した。

release clippyとRust書式検査に合格。別directoryへの再生成で全173ファイルのhashを照合し、固定対照からの変更がTrilu本体と新規helperだけであることを確認する。追加CIは構文をローカル検査したもので、GitHub実行結果ではない。raw記録、事前登録、独立再集計、source／依存lock／licenseは[証跡](research/jeff-onnx-tract/trilu-rows-2026-10-11/README.md)へ保存する。

次の最適化候補は残余の大きいScatterElementsとする。index・axis・重複index・境界・dtype・共有入力の意味を先に監査し、変更を一つに限定して同じgateと独立対照比較を行う。Triluの結果をScatterElementsの期待倍率へ換算しない。8 threads・他の入力長については別実験が必要。

## 再現と未受入

[生成script](../runtime/onnx/prepare_trilu_experiment.py)、[測定script](../runtime/onnx/benchmark_trilu.py)、[helper](../runtime/tract-driver-profile/trilu_rows.rs)、[小型回帰](../runtime/onnx/test_tract_trilu.py)を保存する。追加runtime依存・専用DeltaNet kernelはなく、TractのlicenseとNOTICEを維持する。Pythonは開発側の検証・監視だけで、実行時依存には追加しない。

局所受入と正式なPhase 3／配布承認は分ける。入力長matrix、同形状・保持dtype・thread条件でのNative比較、Tract API E2E、実OCR/ASR品質、正式SLOは引き続き未受入。以前の4／8-thread向け実験予算12秒を製品SLOに変更しない。
