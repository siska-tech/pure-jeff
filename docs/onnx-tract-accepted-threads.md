# Jeff 最適化後の4／8-thread比較と入力長fixture

2026-10-11。[ScatterElements実験](onnx-tract-scatter-rows.md)で局所受入した同一exe・174生成source・依存lock・step1113 NNEFを固定し、4／8 threadsを比較した。新たなruntime最適化や再ビルドは行っていない。Native・通常probe・公開API・Decision Reportは維持する。

## 実測と選択

Core i7-1360P／Windows CPU／Balanced電源設定。batch1、FP32、candidate-request有効128・物理512 tokens、prepared tensors。両threadの4件gate後、AB／BA／ABの独立3組、各processでwarmup1＋測定3、各thread n=9。operator profileは無効。全8 process・32 forwardのraw logitsが固定対照と完全一致し、golden確率との差は最大4.9173831939697266e-6、判断・tokensも一致した。期限・メモリguard失敗は0件。

| 観測対象 | 4 threads | 8 threads | 標本数 |
| --- | ---: | ---: | --- |
| warm forward中央値 | 6.973198秒 | 6.517952秒 | 各9、独立3 session |
| warm forward p95 | 7.096843秒 | 7.167492秒 | 各9、p95は最大値 |
| 起動中央値 | 19.895878秒 | 20.078538秒 | 各3、付随観測 |
| 起動p95 | 20.146844秒 | 20.347804秒 | 各3、付随観測 |
| Peak Working Set最大 | 3,276,771,328 bytes | 3,276,795,904 bytes | 各3、process lifetime |

対応するsession中央値の差（8−4）は−0.032496／−0.349008／−0.650023秒。8 threadsは全3組とpooled中央値で短縮したが、p95は0.070648秒増えた。事前登録した「全3組の中央値、pooled中央値・p95がすべて改善した場合だけ8を選ぶ」という条件を満たさないため、**次のpilotは4 threadsを維持**する。これは8 threadsが一般に遅いことの証明ではなく、小規模pilotの保守的な選択である。製品のthread設定は変更していない。

raw記録からgate・executor・schedule・全統計・選択を独立再検証した。`stage-summary.json`にはtensor準備・forward・mask／temperature／softmax・prepared requestと、load／optimize／planを別集計した。request区間はtokenizer・serialization／IPC・親のpolicy検査を含まず、API E2Eではない。各段階のp95を加算しない。

process期限600秒、Peak Working Set上限min(8 GiB,物理RAMの50%)、開始前空きRAM4 GiB。peakはmapped/shared pagesを含む。温度・affinity・背景負荷・storage cacheは未制御、ビルド・試験・hash監査を計測と並行させていない。n=9のnearest-rank p95は観測最大であり、正式SLOや信頼区間の根拠にはしない。起動・peakの各n=3はcold campaignではない。過去の別runの値を差し引いて累積倍率を作らない。

## 次の入力長評価の準備

開発専用の[Rust生成器](../runtime/bench-native/src/bin/prepare_lengths.rs)を追加した。既存Nativeの`prompt::render`と`Tokenizer::prepare`を直接使い、bundleを検証してから人工requestを生成する。検証では重みのhashとmmapによるshape／dtypeを確認するが、モデルの常駐初期化・forwardは行わない。既存Native source・benchmark本体・公開API・依存lockは変更しない。

| 有効tokens | 主集合 | 追加8候補 | 合計 |
| ---: | ---: | ---: | ---: |
| 128 | 4 | 0 | 4 |
| 256 | 4 | 1 | 5 |
| 384 | 4 | 1 | 5 |
| 511 | 4 | 1 | 5 |
| 512 | 4 | 1 | 5 |

主集合はOCR日本語2候補・ASR Unicode 2候補・OCR ASCII 3候補・ASR混在2候補。元のstate末尾へ人工の` a`を追加して完全promptのencode長を合わせ、候補本文は固定する。8候補は256／384／511／512のみで、128の8候補cellを満たした扱いにはしない。内容差と長さ差が交絡し、実OCR/ASRの正解ラベルはない。

既存4 goldenのprompt bytes・token IDsと一致し、全24件でtoken予算ちょうどを許可、1不足を拒否した。別の513-token requestは512予算で`BudgetExceeded`になった。これはNative tokenizerの境界検査であり、TractBackend APIの境界受入ではない。padding後は物理512、pad ID248044、attention pad=0、mm=0。request／prompt／非padding IDsのhashとpaddingを独立照合した。

初回は`ocr-ja-2/128`が長いseed本文では到達できず生成を中止した。初回sourceと失敗ログを保存し、日本語・Unicode・ASCIIのseedを短縮し、混在集合を2候補に調整して成功した。prompt契約・tokenizer・token予算は変更していない。最終release build／clippy／fmtは合格。既存Native benchmark exeも不変。既存CIのnative wrapper build／lint／fmt対象へ新binが含まれるが、GitHub CIは未実行。

**24件は入力準備のみで、数値oracle・Tract forward・入力長別性能は未受入。** 次は同一checkpointの正規化ONNX oracleで確率・判断を固定し、Tractで全件gate後、4-thread固定の長さmatrixを事前登録して測定する。512固定graphのため有効長に比例する速度改善を予想せず、内容・候補数別の内訳も残す。

## 証跡と残作業

[証跡索引](research/jeff-onnx-tract/accepted-threads-2026-10-11/README.md)に事前登録、raw記録、独立再集計、stage内訳、24 fixture、初回失敗、最終生成、source／lock／license、保全結果を保存した。174生成source・受入exe・通常probe・隣接KazeNhanh 21ファイルは不変。Native baseline 128ファイルとの差は既知の`.gitignore`だけ。

正式SLO、同形状／保持dtype／thread条件でのNative比較、Tract API統合・E2E、実OCR/ASR品質、配布受入は未完了。
