# Wasm W2：入力範囲と動作安定性の結果

2026-10-11。[Wasm成立性計画](wasm-demo-feasibility-plan.md)のW2。**Chrome 153とEdge 153の両方で、W2の通過条件を満たした。** 128〜512 tokens・2〜8候補の12件で、ブラウザ内Rust/Wasmの判断が公式Jeffと一致した。同じsessionでの反復、不正な要求、資産の破損、取消、ページ再読込も事前登録した条件どおりに動いた。対応範囲は**512 tokensまで**で、それを超える入力（874〜8192 tokensのgolden）はWasmで試していない。headless・single-threadでの確認であり、デモ公開や性能の判定ではない。既存Native source・凍結exe・公開API・Decision Reportは変更していない。

## 判定

| W2条件 | 結果（Chrome／Edge共通） |
| --- | --- |
| 対応範囲の全数値gate | 12件×2回（順方向と逆順）の全判断で、prompt SHA-256・input_ids・候補順・判断が公式参照と一致。確率差は最大2.38e-6（基準1e-4） |
| 反復でメモリが増え続けない | linear memoryはsession open後から2回目の終わりまで2,416 MiBで一定 |
| 反復 | 2回目（逆順）の確率と最終hidden stateは、1回目とbit単位で一致 |
| 不正な要求 | 6種すべてが、panicやtrapを起こさず通常のエラーで返った。その後のsessionも正常に判断した |
| 資産の破損 | tokenizerとmodelで1 byteを反転すると、`<資産> hash mismatch`でopenを拒否した。戻すとopenに成功した |
| 取消 | 512 tokensのforward中にWorkerを破棄し、新しいWorkerで再実行した。結果は1回目とbit一致 |
| 再読込 | 実際に`location.reload()`した後の新しいWorkerでも、1回目とbit一致 |
| browserごとの確認 | Chrome・Edgeとも合格。12件の確率とhidden stateは、両browserでbit単位に同一 |

## 入力

| 由来 | 件数 | tokens | 候補数 | 判断 |
| --- | ---: | --- | --- | --- |
| 既存golden（`candidate-request`、`reversed`、`special-token-text`、`asr-unicode`） | 4 | 128〜206 | 2〜3 | 選択2、保留2 |
| 長さfixture（既存の24件から8件を選択） | 8 | 128／256／384／511／512 | 2／3／8 | 選択4、保留4 |

長さfixtureの公式参照は、今回あらためて公式Jeff（Python、CPU FP32、1 thread、固定bundle）で採取した。各exporterの独立worker照合は差0で、promptのSHA-256とtoken数はfixtureの記録と一致した。`reversed`で候補順の変更を、8候補の2件で多候補を確認した。Native4の反復違反が出た2件（`ocr-ascii-3-128`、`ocr-ascii-3-511`）も含めた。

不正な要求は6種：JSON構文エラー、候補1件、候補IDの重複、未対応のquestion_id、routing理由なし、token予算超過（128 tokensの要求を上限64で実行）。いずれも人工の入力で、日本語OCR／ASRの品質評価ではない。

## 構成の変更：session

W1の1回きりの`decide`を、`Session::open`（資産hash、decision config、tokenizerと回答語彙の検査）と`Session::decide`（prompt、forward、readout、policy）に分けた。資産のbytesはページ側が確保して保持し、sessionはそれを参照するだけである。W1の`decide`はopenとdecideを続けて呼ぶ形になり、出力は変わらない。最終binaryでW1を再実行し、確率がW1の最終runと同一であることを確認した（`w1-regression`）。

Wasmの公開関数は`kj_session_open`／`kj_session_decide`／`kj_session_close`。Workerは命令（init、load、corrupt、open、decide）を受け取る形式にし、ページ側が手順を制御する。

## 時間とメモリ（単発の観測値）

性能の判定ではない。同じrun内のnative参照（同じsource、1 thread）との比で示す。

| tokens | Wasmのforward（Chrome／Edge、1・2回目） | native（Chrome run） | 比（Chrome 1回目） |
| ---: | --- | ---: | ---: |
| 128 | 5.3〜6.3秒 | 2.8秒 | 1.9〜2.3 |
| 256 | 9.8〜10.6秒 | 4.8秒 | 2.1 |
| 384 | 14.7〜15.3秒 | 7.2秒 | 2.1 |
| 511／512 | 19.2〜20.8秒 | 9.3〜9.4秒 | 2.0〜2.2 |

session openは4.7〜4.8秒（1.7 GBのSHA-256を含む）、資産の読込は1.6〜2.9秒（127.0.0.1から）。W1では同じ128 tokensのforwardが約18秒、hashが約15秒だった。今回はnative側も約3倍速く、マシンの負荷状態の差と考える。絶対時間は日や状態で大きく変わるため、同じrun内のnativeとの比（約2倍）の方が安定した指標である。

linear memoryは2,416 MiBで一定（768 MiBのheap予約を含む）。browserのprocess lifetime peakは、最大のprocessでWorking Set 4.13 GiB（Chrome）／4.35 GiB（Edge）、Pagefile（commit）4.61 GiB（Chrome）／6.86 GiB（Edge）。この実行ではWorkerを順に4つ作り直したので、破棄したWorkerのメモリが回収されるまでの重なりを含む可能性がある。shared pageを含むため、private RSSとは扱わない。

## W3へ持ち越す事項

- **対応範囲の表示**：今回確認したのは512 tokensまで。デモでは512を超える入力を拒否するか、別途確認してから広げる。
- **hashの費用**：open時のSHA-256は数秒〜15秒かかる。読込のstreamと同時に計算するなど、検証を省略せずに待ち時間を減らす方法をW3で設計する。
- **メモリの目安**：一度に1つのWorkerなら、linear memory約2.4 GiBとbrowser全体で4 GiB超のWorking Setを見込む。メモリの少ない端末での挙動は未確認。
- **出力の型**：結果はまだprobe独自のJSON。デモでは`Attempt`／`Observation`の型と意味に合わせる。
- **環境**：headlessのみ。headed表示、他browser、モバイルは未確認。

## 証跡と再現

[証跡](research/wasm-demo/w2-2026-10-11/README.md)、[runtime/wasm/README.md](../runtime/wasm/README.md)。
