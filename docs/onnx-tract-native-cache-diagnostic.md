# Native GEMM cache初期化条件の診断

2026-10-11。[停止した長さ別比較](onnx-tract-length-compare.md)と[反復診断](onnx-tract-native-repeat-diagnostic.md)で残った旧gateとの確率差を調べるため、独立crate／targetでcache初期化条件を操作した。既存Native・公開API・Decision Reportは不変。元runの不合格と反復閾値1e-6は維持する。

## 設計と事前検査

同一step1113・FP32 text320／head1保持・4 compute threads・batch1。差が最大だったOCR ASCII128とASR Unicode512 controlの2ケースを使用した。許可された全logical CPUについて、独立processのmain threadを一時的にそのCPUへ固定し、gemm-common 0.19.0のprocess内CACHE_INFOを明示初期化して記録した。元のthread maskへ復元し、その後にRayon pool・model・forwardを作る。推論中のcore配置は制御していない。

観測した2種類のcache情報から各1 CPUを選び、AB／BA順の各2 process、各ケース2反復、全4 process・16 forwardを事前登録した。入力ID、backboneのhidden 1024要素、headのraw logits 255要素、確率とforward前後のprocessor番号を記録する。JSONのhidden／raw値はbinary f32へ正規化して差を計算した。

依存追加の初版ではgemm-commonのdefault featureラベルが増えたため、モデル推論前に除外した。修正版はdefault-features=falseを指定し、対照と156 packageのversion／有効featureが一致、17生成ファイルの再生成がbyte一致した。backbone／weights sourceは対照とbyte同一。headの演算は同じで既存raw logitsを返す診断だけを追加した。初版のsource／exe hashと検出記録を保存し、推論には別名の修正版exeを用いた。Rust9試験、release clippy（警告拒否）、fmtを通した。

CPU番号はこのhost上のlogical indexであり、別hostへの移植値ではない。kernel_paramsの記録はm=128／512,n=k=1024,mr=nr=8,scalar=4の仮定計算で、実GEMM呼び出しの選択値を取得したものではない。

## 観測した初期化条件

process allowed maskは65535、全16 logical CPUを記録した。不正CPU index64はモデルロード前に拒否され、全probeと実推論processでmain thread mask復元を確認した。

| cache条件 | 同じcache情報のlogical CPU | 選択CPU | L1 bytes／ways | L2 bytes／ways | L3 bytes／ways | 仮定kc (m128／512) |
| --- | --- | ---: | --- | --- | --- | --- |
| cacheA | 8, 9, 10, 11, 12, 13, 14, 15 | 8 | 32768／8 | 2097152／16 | 18874368／12 | 512／512 |
| cacheB | 0, 1, 2, 3, 4, 5, 6, 7 | 0 | 49152／12 | 1310720／10 | 18874368／12 | 1024／1024 |

## 数値結果

全16 forwardがONNX確率差≤1e-4・確率和誤差≤1e-6・判断／tokens一致に合格した。最大ONNX確率差は2.4139881134033203e-06。全4 child exit0、resource guardなし。生ログのinput IDs・hidden／rawの有限性・cache／pool／順序／resource条件と以下の差分を独立に再計算した。

| case | cache条件 | 観測数 | 確率／hidden／raw反復完全一致 | 旧Native4 gate比最大差 | 停止session比最大差 |
| --- | --- | ---: | --- | ---: | ---: |
| synthetic-ocr-ascii-3-128 | cacheA | 4 | True/True/True | 3.5464763641357422e-06 | 0 |
| synthetic-ocr-ascii-3-128 | cacheB | 4 | True/True/True | 0 | 3.5464763641357422e-06 |
| synthetic-asr-unicode-2-512 | cacheA | 4 | True/True/True | 4.76837158203125e-07 | 0 |
| synthetic-asr-unicode-2-512 | cacheB | 4 | True/True/True | 0 | 4.76837158203125e-07 |

| case | cache条件間の候補確率最大差 | hidden最大差 | raw logits最大差 | 入力ID一致 |
| --- | ---: | ---: | ---: | --- |
| synthetic-ocr-ascii-3-128 | 3.5464763641357422e-06 | 1.430511474609375e-05 | 1.621246337890625e-05 | True |
| synthetic-asr-unicode-2-512 | 4.76837158203125e-07 | 1.71661376953125e-05 | 1.049041748046875e-05 | True |

## 判定と次の作業

今回の独立診断では、cache初期化条件を変えると旧gateと停止sessionの両方の確率を再現した。各条件内で繰り返し一致し、同じ入力ID・重み・thread設定でも初期cache条件で結果が変わることを確認できた。hiddenに差があるため、差はheadより前のbackbone出力にすでに存在する。ただし最初に差が出たlayer／GEMMは未特定である。

旧exeの過去runには実CACHE_INFOの記録がない。したがって過去の反復違反の原因がcache初期化だったという判断は、今回の再現に基づく推論であり、過去runの直接証明ではない。cache条件とGEMM分割の関係はsource監査に支えられるが、記録した仮定kcを実呼び出しのkcと同一視しない。温度・周波数・推論worker配置も未制御である。

次は診断用crateでcache情報／GEMM分割の再現条件を固定する単一候補を用意し、元の許容差を変えず全28ケースを独立process間で再受入する。短文2ケースの結果から全入力や判断境界へ一般化しない。受入後に電源・背景負荷・CPU配置等の記録／制御方針を固定して、新規の性能runへ戻る。API E2E・cold／warm・正式標本・未使用入力・配布NOTICEも残る。

今回の時間はwarmupなし・診断出力ありの観測であり、速度倍率・中央値／p95性能実績・8秒SLO達成には使用しない。認識品質と性能改善は別判定とし、Phase 5はユーザー確認済みの実OCR／ASRデータ準備待ち。

Native baseline127ファイル（既知.gitignore差のみ）、隣接KazeNhanh21ファイル、既存失敗／反復診断の証跡とfrozen assetsの不変を確認した。Pythonは開発用診断のみで、通常推論への実行時依存追加はない。ライセンス／NOTICE snapshotを引き継ぎ、配布受入の未完了事項は残す。

[事前登録・生ログ・独立validator・生成source・検証証跡](research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11/README.md)。[診断ハーネス](../runtime/onnx/diagnose_native_cache.py)。
