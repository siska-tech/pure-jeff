# 固定cache性能用wrapperの数値受入

2026-10-11。[診断exeの全28件再検証](onnx-tract-native-cache-fixed-gate.md)を受け、requestごとの診断出力を持たない計測wrapperを別crate／targetで作成し、その数値同等性を検証した。既存Native・公開API・Decision Reportは不変。元の失敗runと数値閾値は維持する。

## 変更と検証設計

frozen Native thread wrapperを基に、診断版と同じcache初期化moduleとmainからの呼び出しだけを追加した。backbone／weights／readout／threadsの4 sourceは元wrapperとbyte同一で、requestの計測境界・出力形式も元wrapperのまま。hidden・raw logits・入力IDs・processor番号のrequest出力はない。初期化eventにはcache情報と仮定kernel_paramsを記録するが、実GEMM呼び出しの選択値ではない。

16生成ファイルを再生成してbyte一致、依存156 packageのversion／有効featureは受入済み診断版と一致した。新しいrelease exeを別targetへビルドし、Rust9試験・clippy（警告拒否）・fmtを通過した。cache moduleは診断版と同一で、probeでcacheB／logical CPU0・mask65535への復元を確認。不正CPU index64はモデルロード前に拒否した。

step1113、text320＋head1 FP32保持、4 compute threads、batch1。cache初期化中だけmain threadをCPU0へpinし、pool・model・forwardの前に元maskへ戻す。CPU0はこのhostで検証した条件であり、別hostへの可搬な選択方針ではない。

全28ケースを7件ずつ4 chunkに分けたgate 4 child（28 forward）の後、逆chunk順でresident 4 childを実行する。residentは7ケースを異なる固定shuffle順で2巡、14 requests／process（56 forward）。全8 child・84 forward、各ケースはgate 1回＋resident 2回、2独立processで3観測となる。seed6791113、chunkと巡による加算を事前登録した。child期限600秒とpeak上限min(8 GiB,物理RAMの50%)は不変。

ONNX確率差≤1e-4・確率和誤差≤1e-6・判断／tokens一致、旧gate・受入済み診断版との差≤1e-6、今回のgate比反復差≤1e-6、既存Native参照との差≤1e-4（存在するケースのみ）を必須とした。pool・保持payload・cache／affinity記録も照合し、request診断fieldsが残っていれば拒否する。入力IDsの直接出力は除き、tokenizer／compute source不変とtokens一致で検証範囲を明示した。

## 結果

全84 forwardが数値・判断・tokens・resource条件を通過し、8 childすべてexit0、guardなし。最大ONNX確率差3.7550926208496094e-06、診断版比最大差0、旧gate比最大差0、今回gate比反復差最大0、resident内最大差0。全28ケース中28ケースで3観測の確率が完全一致した。

| case | tokens | 診断版比最大差 | gate比反復最大差 | resident内最大差 | 最大ONNX差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| candidate-request | 128 | 0 | 0 | 0 | 5.96046448e-08 |
| reversed | 128 | 0 | 0 | 0 | 1.82539225e-07 |
| asr-unicode | 206 | 0 | 0 | 0 | 3.75509262e-06 |
| special-token-text | 182 | 0 | 0 | 0 | 2.14576721e-06 |
| synthetic-ocr-ja-2-128 | 128 | 0 | 0 | 0 | 4.17232513e-07 |
| synthetic-ocr-ja-2-256 | 256 | 0 | 0 | 0 | 1.1920929e-07 |
| synthetic-ocr-ja-2-384 | 384 | 0 | 0 | 0 | 3.57627869e-07 |
| synthetic-ocr-ja-2-511 | 511 | 0 | 0 | 0 | 7.4505806e-09 |
| synthetic-ocr-ja-2-512 | 512 | 0 | 0 | 0 | 2.60770321e-07 |
| synthetic-asr-unicode-2-128 | 128 | 0 | 0 | 0 | 1.60932541e-06 |
| synthetic-asr-unicode-2-256 | 256 | 0 | 0 | 0 | 1.54972076e-06 |
| synthetic-asr-unicode-2-384 | 384 | 0 | 0 | 0 | 4.76837158e-07 |
| synthetic-asr-unicode-2-511 | 511 | 0 | 0 | 0 | 1.60932541e-06 |
| synthetic-asr-unicode-2-512 | 512 | 0 | 0 | 0 | 0 |
| synthetic-ocr-ascii-3-128 | 128 | 0 | 0 | 0 | 2.41398811e-06 |
| synthetic-ocr-ascii-3-256 | 256 | 0 | 0 | 0 | 1.32620335e-06 |
| synthetic-ocr-ascii-3-384 | 384 | 0 | 0 | 0 | 6.03497028e-07 |
| synthetic-ocr-ascii-3-511 | 511 | 0 | 0 | 0 | 2.98023224e-07 |
| synthetic-ocr-ascii-3-512 | 512 | 0 | 0 | 0 | 3.57627869e-07 |
| synthetic-asr-mixed-2-128 | 128 | 0 | 0 | 0 | 5.36441803e-07 |
| synthetic-asr-mixed-2-256 | 256 | 0 | 0 | 0 | 1.1920929e-07 |
| synthetic-asr-mixed-2-384 | 384 | 0 | 0 | 0 | 5.36441803e-07 |
| synthetic-asr-mixed-2-511 | 511 | 0 | 0 | 0 | 1.78813934e-07 |
| synthetic-asr-mixed-2-512 | 512 | 0 | 0 | 0 | 1.1920929e-07 |
| synthetic-ocr-ascii-8-256 | 256 | 0 | 0 | 0 | 3.94880772e-07 |
| synthetic-ocr-ascii-8-384 | 384 | 0 | 0 | 0 | 2.14576721e-06 |
| synthetic-ocr-ascii-8-511 | 511 | 0 | 0 | 0 | 2.83122063e-07 |
| synthetic-ocr-ascii-8-512 | 512 | 0 | 0 | 0 | 7.15255737e-07 |

電源・system CPUの前後snapshot：

| run | AC前→後 | 省電力flag前→後 | system平均busy (%) |
| --- | --- | --- | ---: |
| gate-chunk0 | 1→1 | 0→0 | 31.014 |
| gate-chunk1 | 1→1 | 0→0 | 30.628 |
| gate-chunk2 | 1→1 | 0→0 | 30.515 |
| gate-chunk3 | 1→1 | 0→0 | 34.437 |
| resident-chunk3 | 1→1 | 0→0 | 34.080 |
| resident-chunk2 | 1→1 | 0→0 | 35.104 |
| resident-chunk1 | 1→1 | 0→0 | 32.151 |
| resident-chunk0 | 1→1 | 0→0 | 32.438 |

raw出力、入力順／coverage、診断版参照、全確率差・pool／cache／resourceとsummaryを独立に再計算した。初期化probe・不正番号拒否、source／feature／再生成とbuild検査ログもhash照合した。system平均busyは他processを含み、childのCPU利用率や競合の証明ではない。温度・周波数・背景負荷・推論core配置は未制御。

## 受入範囲と次の段階

この新しい計測exeを、固定cacheB・既存28人工fixtureに対する数値同等性と14-request resident内の反復について局所受入する。3観測／ケース・2 processだけで一般的な決定性や長期residentの安定性を保証しない。hidden／rawの同等性をこのexeで直接観測したという主張もしない。旧失敗runは不合格のままで、過去CACHE_INFOがないため原因の直接証明とは扱わない。

次はこのexeを固定して、受入Tract4との長さ別pilotを新規事前登録する。各childのAC／省電力・system負荷を記録し、電源・背景負荷・CPU配置／温度の制御できる項目とできない項目を区別する。数値gateを各backendで再実施し、Nativeの反復≤1e-6とTract raw一致を必須とする。Native有効長／Tract左padding物理512、packed layout／algorithmと初期化・request境界の非対称性は運用構成比較の制約として残す。

今回の時間は数値受入の診断値でwarmupやbackend比較がなく、速度倍率・性能中央値／p95・8秒SLOへ換算しない。正式SLO、API E2E、cold campaign、入力hold-out、長期resident、portable core選択、配布NOTICEは別受入で残る。Phase 5は確認済み実OCR／ASR N-bestデータ準備待ち。

Native baseline127ファイル（既知.gitignore差のみ）、隣接KazeNhanh21ファイル、旧診断／失敗証跡とfrozen assetsの不変を確認した。Pythonは開発用のみで推論実行時依存へ追加していない。ライセンス／NOTICE snapshotを引き継ぎ、配布承認とは扱わない。

[事前登録・生ログ・source・検査ログ・独立validator](research/jeff-onnx-tract/native-cache-timing-gate-2026-10-11/README.md)。[生成ハーネス](../runtime/onnx/prepare_native_cache_fixed.py)、[数値検証ハーネス](../runtime/onnx/validate_native_cache_timing.py)。


追加の[固定cache Native4／Tract4長さ別pilot](onnx-tract-cache-fixed-lengths.md)は、性能用exeの84 forward数値受入後に新規事前登録し、各backend28件gate＋3独立resident組、全14 child・206 forwardを完了した。旧gate／Native全観測ペア差≤1e-6とTract raw一致、power／resource条件を維持。各長さn=12の記述的比較で、正式SLO・API E2E・backend採用・入力hold-outは未受入。元の停止runは置換しない。
