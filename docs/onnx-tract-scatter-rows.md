# Jeff ScatterElements行単位コピーの独立実験

2026-10-11。[Trilu実験](onnx-tract-trilu-rows.md)で局所受入したexeを固定対照とし、ScatterElementsの上書き処理を単一変更として比較する。Native・通常Tract probe・公開API・Decision Reportは変更しない。

## 監査と変更条件

固定step1113の正規化ONNXにはScatterElementsが148個あり、axis=2が144個、axis=0が4個。148個すべてのindexがscalar Constant→Expandで生成され、値は0〜7だった。これは保存されたONNXの由来・shape metadataの監査であり、最適化後の実行回数やlayoutの証明ではない。外部重みはロードしていない。

固定Tract 0.23.8 commit `9e0cfaa9b3a9251f41f74101801dc2c937b1660a`のNone reductionは、更新値ごとにindexed_iterで座標を作り、index取得・負index補正・代入を行う。候補はcontiguous sliceが得られ、dataとupdatesの非axis次元が一致し、indicesとupdatesの形状も一致する場合に限り、axisより内側の行をコピーする。全行のindexが行内で一定かつ有効範囲内であることを、書込み前に確認する。

各行は元のC-order順で書き込むため、重複targetは後の更新で上書きされる。負indexをaxis長で補正し、値はclone_from_sliceでコピーするためNaN payload・負zeroを保持する。空更新は書き込まない。条件外・不正index・非標準layoutは従来loopへ戻す。既存の不正indexの失敗動作を維持し、今回の変更でエラー契約を修正しない。Add／Mul／Min／Max reductionは変更しない。helperはsafe Rustで、早期returnのtensor型復元には従来と同じunsafe set_datum_type呼出を使う。新たなruntime依存・専用DeltaNet kernelはない。

## 回帰と既存制約

helperの独立Rust 2試験は、prefix数・axis長・更新数・suffix長・負indexの6,336組と、重複index、辞退前の非変更、空更新、shape拒否、String、浮動小数点bitsを確認する。実対照・候補のrlibへ別々にリンクした各2試験は、共有入力、重複順序、bits、空更新、不正indexの失敗を確認する。

小型ONNXは4 shape／axis条件×4 index pattern×dtype／reductionを検査する。192条件は双方で2 forwardずつ成功しscalar参照と一致、64条件は双方で同じ既存エラーを確認する。成功384 process・768 forward、拒否128 process。toyの出力比較は先頭255要素で、helper試験は全領域を照合する。非axis次元が小さい場合と非uniform indexは従来pathの検査となる。plain RAM viewはshapeからstandard layoutで構成されるため、非標準layout guardを直接通す試験とは扱わない。

最初の試験はI64 reductionの64条件を成功すると誤って期待し、固定対照が`TDim is not a number`で拒否した。Tract ONNX importerはI64 CastをTDimへ変換する。初回失敗ログを保存し、I32の成功条件を追加するとともに、I64 reductionは双方の拒否一致を確認する試験へ修正した。候補runtimeの修正や失敗記録の削除は行っていない。最終Python全29試験はskip 0で合格。

## 事前登録した比較

同一step1113 declutter済みNNEF・FP32・batch1・物理512・有効128 tokens・4 threads、prepared tensorsで比較する。全source・lock・exe・model・goldenのhashを確認し、4件gateのraw logitsが固定対照と完全一致してから計測する。

AB／BA／ABの独立3組、各processでwarmup1＋測定3、各版n=9。全3組のsession中央値・pooled中央値・p95が短縮し、数値gate成功・guard失敗0なら局所受入とする。別profile session各1（warmup1＋測定3）は性能集計へ混ぜない。全10 process・40 forwardを予定する。

process期限600秒、Peak Working Set上限min(8 GiB,物理RAMの50%)、開始前の空きRAM4 GiB。Peakにはmapped/shared pagesを含む。温度・affinity・背景負荷・storage cacheは未制御。ビルド・試験は計測と並行させない。n=9のnearest-rank p95は観測最大であり、正式SLOの根拠にはしない。起動・peakは各n=3の付随観測で、cold campaignではない。

## 実測結果と局所判定

Windows CPU（Core i7-1360P、Balanced電源設定）で全10 process・40 forwardが成功した。全255 raw logitsは固定対照と完全一致し、golden確率との差は最大4.9173831939697266e-6、判断・tokensも一致した。guard発動は0件。保存したraw JSONLから数値gate、session対応、集計、受入判定を独立再検証した。

| 観測対象 | Trilu版対照 | Scatter候補 | 標本数 |
| --- | ---: | ---: | --- |
| warm forward中央値 | 8.284212秒 | 6.884419秒 | 各9、独立3 session |
| warm forward p95 | 8.466597秒 | 7.341230秒 | 各9、p95は最大値 |
| 起動中央値 | 20.310169秒 | 20.420487秒 | 各3、付随観測 |
| 起動p95 | 20.625239秒 | 20.574967秒 | 各3、p95は最大値 |
| Peak Working Set最大 | 3,277,160,448 bytes | 3,276,709,888 bytes | 各3、process lifetime |
| 別sessionのScatterElements計測中央値 | 2.057294秒 | 0.308645秒 | 各3、性能集計から除外 |

対応するsession中央値の差（候補−対照）は−1.138753／−1.370705／−1.549715秒。pooled中央値は1.399793秒短縮し、全3組・中央値・p95・数値gate・guardの事前条件を満たしたため、**この実験経路では局所受入**とする。起動短縮は確認していない。演算診断の差を通常forwardの短縮量へそのまま換算しない。前回測定のTrilu版中央値8.361秒ではなく、今回同時期に測った対照8.284秒を比較基準にする。

別directoryへ再生成した全174ファイルのhashが測定時と一致し、固定対照との差分はScatterElements本体と新規helperだけだった。依存lockは同一。Native baselineは128中127ファイル不変、既知の差は`.gitignore`のみ、隣接KazeNhanhの21ファイル・通常probe・固定対照exe・upstream core/data/linalg/Cargo.tomlも不変。release clippyとRust書式検査に合格し、追加CIのYAMLもローカル解析した。GitHub CIは未実行。

別profileの候補側で残った主な演算はOptMatMul中央値3.549984秒、MoveAxis 1.408766秒、OptMatMulPack 0.521682秒（各n=3）。これはinclusiveなtop-level wall timeであり、CPU時間やそのまま除去可能な時間ではない。8-threadの内訳も推定しない。

raw測定、初回回帰の失敗と修正理由、最終回帰、profile、source／依存lock／license、再現性・保全は[証跡](research/jeff-onnx-tract/scatter-rows-2026-10-11/README.md)へ保存した。次は受入候補を固定して4／8-threadと入力長matrixを再評価し、残余のMoveAxisは別の意味監査・単一変更として扱う。

## 再現と未受入

[生成script](../runtime/onnx/prepare_scatter_experiment.py)、[測定script](../runtime/onnx/benchmark_scatter.py)、[index監査](../runtime/onnx/audit_scatter_indices.py)、[実ONNX回帰](../runtime/onnx/test_tract_scatter.py)を保存する。Tractのlicense／NOTICEと依存lockを維持する。Pythonは開発側の検査・監視だけに使用する。

8-thread・入力長matrix・Nativeとの同形状／保持dtype／thread比較・Tract API E2E・実OCR/ASR品質・正式SLOは未受入。今回の局所実験を製品採用や認識品質改善へ換算しない。
