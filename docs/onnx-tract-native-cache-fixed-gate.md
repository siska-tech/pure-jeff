# Native cache条件固定：全28ケースの数値再検証

2026-10-11。[cache初期化診断](onnx-tract-native-cache-diagnostic.md)で旧gateを再現したcacheB条件を固定し、既存28ケースを独立process間で検証した。既存Native・公開API・Decision Report・判定閾値は不変。停止した性能runを合格へ変更する実験ではない。

## 固定条件と受入範囲

前回のfrozen診断exeを再利用し、再ビルド・演算変更は行っていない。step1113、text320＋head1 FP32保持、4 compute threads、batch1。jobのcache_init_cpuをこのhostで確認済みのlogical CPU0に固定し、main threadだけを初期化中にpinする。CACHE_INFO取得後に元のmask65535へ復元してからpool・model・forwardを作る。実推論中のcore配置は固定しない。

cacheBはL1 49,152 bytes／12-way、L2 1,310,720 bytes／10-way、L3 18,874,368 bytes／12-way。probeで前回のcache情報・CPU番号・affinity復元に完全一致することを確認した。CPU0を別hostへ一般化する選択方針は未実装である。仮定kernel_paramsは実GEMM呼び出し値の取得ではない。

全28ケースを7件ずつ4 chunkへ分け、chunk順0→1→2→3、次に3→2→1→0の2巡を事前登録した。各chunkの入力順は固定seed5781113＋10×巡＋chunkでshuffleする。全8 child・56 forward、各ケース2独立processの観測。childの既存600秒期限とpeak上限min(8 GiB,物理RAMの50%)を維持する。

ONNX確率差≤1e-4・確率和誤差≤1e-6・判断／tokens一致、旧28-case Native4 gateとの差≤1e-6、今回の独立process間差≤1e-6、既存Native参照との差≤1e-4（存在するケースのみ）を必須とした。入力ID一致、有限hidden1024／raw logits255、pool／保持cache／affinity復元も検査した。旧gateを新しい参照で置換せず、許容差も緩和していない。

同process内で全ケースを反復する試験や長時間resident履歴は今回に含まれない。前回の2ケース反復診断とは範囲を分ける。今回の局所再受入は、この診断exe・固定初期化条件・既存人工fixtureに限定する。未計装の性能用exeや本番backendの受入ではない。

## 結果

全56 forwardが数値・判断・tokens・resource条件を通過し、全8 child exit0、guardなし。最大ONNX確率差3.7550926208496094e-06、旧gateとの差最大0、独立process間の確率差最大0だった。生ログから入力・順序・全差分・coverage・pool・cache・resourceとsummaryを独立再計算した。

全28ケース中、独立process間で確率が完全一致したものは28件、hiddenは28件、raw logitsは28件。hidden／rawの差はJSON値をbinary f32へ正規化して計算した。

| case | tokens | 旧gate比最大確率差 | process間最大確率差 | 最大ONNX確率差 | hidden／raw完全一致 |
| --- | ---: | ---: | ---: | ---: | --- |
| candidate-request | 128 | 0 | 0 | 5.96046448e-08 | True／True |
| reversed | 128 | 0 | 0 | 1.82539225e-07 | True／True |
| asr-unicode | 206 | 0 | 0 | 3.75509262e-06 | True／True |
| special-token-text | 182 | 0 | 0 | 2.14576721e-06 | True／True |
| synthetic-ocr-ja-2-128 | 128 | 0 | 0 | 4.17232513e-07 | True／True |
| synthetic-ocr-ja-2-256 | 256 | 0 | 0 | 1.1920929e-07 | True／True |
| synthetic-ocr-ja-2-384 | 384 | 0 | 0 | 3.57627869e-07 | True／True |
| synthetic-ocr-ja-2-511 | 511 | 0 | 0 | 7.4505806e-09 | True／True |
| synthetic-ocr-ja-2-512 | 512 | 0 | 0 | 2.60770321e-07 | True／True |
| synthetic-asr-unicode-2-128 | 128 | 0 | 0 | 1.60932541e-06 | True／True |
| synthetic-asr-unicode-2-256 | 256 | 0 | 0 | 1.54972076e-06 | True／True |
| synthetic-asr-unicode-2-384 | 384 | 0 | 0 | 4.76837158e-07 | True／True |
| synthetic-asr-unicode-2-511 | 511 | 0 | 0 | 1.60932541e-06 | True／True |
| synthetic-asr-unicode-2-512 | 512 | 0 | 0 | 0 | True／True |
| synthetic-ocr-ascii-3-128 | 128 | 0 | 0 | 2.41398811e-06 | True／True |
| synthetic-ocr-ascii-3-256 | 256 | 0 | 0 | 1.32620335e-06 | True／True |
| synthetic-ocr-ascii-3-384 | 384 | 0 | 0 | 6.03497028e-07 | True／True |
| synthetic-ocr-ascii-3-511 | 511 | 0 | 0 | 2.98023224e-07 | True／True |
| synthetic-ocr-ascii-3-512 | 512 | 0 | 0 | 3.57627869e-07 | True／True |
| synthetic-asr-mixed-2-128 | 128 | 0 | 0 | 5.36441803e-07 | True／True |
| synthetic-asr-mixed-2-256 | 256 | 0 | 0 | 1.1920929e-07 | True／True |
| synthetic-asr-mixed-2-384 | 384 | 0 | 0 | 5.36441803e-07 | True／True |
| synthetic-asr-mixed-2-511 | 511 | 0 | 0 | 1.78813934e-07 | True／True |
| synthetic-asr-mixed-2-512 | 512 | 0 | 0 | 1.1920929e-07 | True／True |
| synthetic-ocr-ascii-8-256 | 256 | 0 | 0 | 3.94880772e-07 | True／True |
| synthetic-ocr-ascii-8-384 | 384 | 0 | 0 | 2.14576721e-06 | True／True |
| synthetic-ocr-ascii-8-511 | 511 | 0 | 0 | 2.83122063e-07 | True／True |
| synthetic-ocr-ascii-8-512 | 512 | 0 | 0 | 7.15255737e-07 | True／True |

電源・system CPUの前後snapshot：

| run | AC前→後 | 省電力flag前→後 | system平均busy (%) |
| --- | --- | --- | ---: |
| gate-0-chunk0 | 1→1 | 0→0 | 57.026 |
| gate-0-chunk1 | 1→1 | 0→0 | 56.946 |
| gate-0-chunk2 | 1→1 | 0→0 | 56.915 |
| gate-0-chunk3 | 1→1 | 0→0 | 56.371 |
| gate-1-chunk3 | 1→1 | 0→0 | 34.991 |
| gate-1-chunk2 | 1→1 | 0→0 | 31.018 |
| gate-1-chunk1 | 1→1 | 0→0 | 30.945 |
| gate-1-chunk0 | 1→1 | 0→0 | 31.581 |

system平均busyは他processを含む全体の累積時間差から計算したもので、child稼働率や競合原因の証明ではない。温度・周波数・背景負荷は未制御。診断時間にはwarmupがなくhidden／raw出力もあるため、性能中央値／p95・高速化倍率・正式SLOへ換算しない。

## 判定と残作業

全28ケースについて、この固定cache条件・診断exeの独立process間数値gateを局所再受入する。既存の反復上限1e-6を満たしたが、2観測／ケースから一般的な決定性や未使用入力への成立を保証しない。過去runのCACHE_INFOは取得されておらず、旧不合格の原因を直接証明したとも扱わない。元の停止runは不合格のまま保存する。

次は同じ初期化操作だけを通常の計測wrapperへ追加し、hidden／rawの診断出力を持たない性能用exeを別crate／targetで作る。その新exeで全28ケースと反復gateを再確認してから、新規事前登録のNative／Tract長さ別pilotへ進む。性能用exeと今回の診断exeの数値同等性を検証せず、既存gateを流用しない。CPU選択の可搬性、長いresident履歴、入力hold-out、AC／電源・背景負荷・CPU配置／温度等の記録／制御方針も残る。

今回の結果は性能改善・backend採用・API E2E・cold campaign・正式SLOの受入ではない。既存のp95≤8秒候補は、過去の時間変動も踏まえ安定性未確認の計画値として維持する。配布NOTICE・clean host受入は未完了、Phase 5はユーザー確認済みの実OCR／ASR正解付きN-best準備待ち。

Native baseline127ファイル（既知.gitignore差のみ）、隣接KazeNhanh21ファイル、過去のcache診断／停止runとfrozen assetsのhash不変を確認した。既存Rust9試験・clippy／fmt・156 package feature一致の証跡に対応する同一exeを使い、今回のPython harness／独立validatorは構文検査済み。検証器の7確認では既存cacheB出力の受入に加え、旧gate差2e-6、旧gate内でもprocess間差1.6e-6、入力ID変更、非有限raw、affinity記録変更、イベント欠落の拒否を確認した。実行時Python依存と公開APIの変更はない。第三者ライセンス／NOTICE snapshotは前回から引き継いだ。

[事前登録・生ログ・独立validator・検証証跡](research/jeff-onnx-tract/native-cache-fixed-gate-2026-10-11/README.md)。[検証ハーネス](../runtime/onnx/validate_native_cache_fixed.py)。
