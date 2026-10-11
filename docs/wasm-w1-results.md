# Wasm W1：実モデル1件の結果

2026-10-11。[Wasm成立性計画](wasm-demo-feasibility-plan.md)のW1。**W1の通過条件を満たした。ブラウザ内のRust/Wasmで、固定checkpointの全24層forwardから判断までが動き、公式参照と一致した。** ただし対象は短い人工2候補の1件（128 tokens）だけである。入力範囲・反復時のメモリ・他browser・性能の判断はW2以降で、デモ公開を意味しない。既存Native source・凍結exe・公開API・Decision Reportは変更していない。

## 判定

| W1条件 | 結果 |
| --- | --- |
| 同一checkpoint | Wasm内で、manifestにある4資産（`model.safetensors` 1,706,027,688 bytesを含む）のSHA-256を照合して合格 |
| prompt・tokens・候補順・判断が一致 | 生成promptのSHA-256、input_ids（128）、候補順、判断（original選択）が公式goldenと一致 |
| 確率差≤1e-4 | 最大5.36e-7（公式golden比）。同じsourceのnative実行比は2.98e-7 |
| メモリ不足・tab crashなし | 全runで期限内に完了。linear memoryは最大2,416 MiB（wasm32の上限4 GiBの内側） |
| 取消後に再実行できる | forward中にWorkerを`terminate()`し、新しいWorkerで再実行した。再実行の確率と最終hidden stateは、最初のrunとbit単位で一致 |

Chrome 153／Edge 153（Windows 11、Core i7-1360P）、headless、single-thread、simd128版で確認した。確率は全3 run・全6回の完走でbit単位で同一（0.9285955429077148 / 0.07140449434518814）。

## 構成

[runtime/wasm](../runtime/wasm/README.md)の`decide`は、Native `RustProvider`と同じ順に処理する：資産hash、decision configの検査、tokenizerと回答語彙の検査、prompt描画とtokenize、全層forward、readout、temperature、policy。

- **重みの読み方だけを変えた生成コピー**：`build.rs`が凍結`backbone.rs`／`readout.rs`をSHA-256で照合する。そのうえで、mmapをbyte slice読込（Candleの`SliceSafetensors`）へ置き換える文字列置換だけを適用する。backboneは1か所、readoutは4か所で、各置換が正確に1回だけ一致することをbuild時に検査する。凍結テストは生成コピー上でも合格した。`policy.rs`と`prompt.rs`は無変更でincludeする。
- **同一sourceのnative参照**：同じ`decide`をx86_64・1 threadで実行した結果は、凍結Nativeのprofilerとbit単位で同一の確率になった（0.928595244884491 / 0.07140474766492844。golden比2.38e-7は凍結`jeff.exe`の記録値と同じ）。WasmとNativeの差（2.98e-7）は、演算順による通常のfloat32差の範囲にある。
- **資産の読み込み**：Workerが各資産をfetchのstreamから直接linear memoryへ書き込む。JS側にモデル全体の複製を持たない。
- **Nativeとの違い**：call内に期限判定はなく、取消はWorkerの破棄で行う。`Attempt`／`Observation`形式の出力やartifact一覧はまだ作らない（W3で公開APIの型に合わせる）。

## 時間とメモリ（単発の観測値）

性能の判定ではない。最終run（Chrome／Edge、各2回完走）の範囲を示す。

| 段階 | Wasm | 備考 |
| --- | ---: | --- |
| モデルのstream読込（127.0.0.1） | 3.7〜4.4秒 | 実際の配信では回線速度に依存 |
| 4資産のSHA-256 | 15.0〜15.9秒 | Nativeは同じ処理で約0.85秒 |
| tokenizerと回答語彙 | 1.1〜1.4秒 | 下記のheap対策後 |
| 全層forward（128 tokens） | 18.1〜18.5秒 | 同日の1 thread native（同じsource）は8.5〜9.0秒 |

linear memoryは、モデル読込後1,648 MiB、heap予約後と完了時は2,416 MiB。browserの各process lifetime peakは、最大のprocessでWorking Set 3.70〜3.71 GiB、Pagefile（commit）4.89〜4.90 GiB。shared pageを含むため、private RSSやタブ単位の合計とは扱わない。

## 判明した問題と対策：heapの小刻みな拡張

最初のChrome run（予約なし）は、W1の全条件に合格した。ただしtokenizer段階が29.9〜32.6秒かかった（W0では1秒未満）。Nodeで同じwasmを使って切り分けた（[診断script](research/wasm-demo/w1-2026-10-11/tokenizer-heap-diagnosis.mjs)）。1.7 GBを確保した後のtokenizer読込は、0.9秒から20.7〜29.9秒に悪化した。一方、20 MBのSHA-256は遅くならなかった。

Rustのallocatorが、大きなlinear memory上で`memory.grow`を小刻みに繰り返すことが原因と判断した。資産の読込後に768 MiBを一度に確保して即解放すると、0.45秒に戻った。最終runではWorkerがこの予約を行い、tokenizer段階は1.1〜1.4秒になった。確率は予約なしのrunとbit単位で同一で、変わったのは時間とlinear memory（+176 MiB）だけである。予約量は今回の1件の観測（forward中の増加約590 MiB）から決めた暫定値で、長い入力への十分性は未確認。

## W2へ持ち越す事項

- **入力範囲**：128 tokensの1件のみ。256／512 tokens、2〜8候補、順序変更、破損・失敗系はW2で確認する。8192 tokensまでの互換は主張しない。
- **反復**：同じWorker内で複数回判断したときに、linear memoryが増え続けないかは未確認。今回はrunごとにWorkerを作り直した。
- **hashの費用**：1.7 GBのSHA-256にWasmで約15秒かかる。読込のstreamと同時に計算する方式、または取得済みcacheの検証方式を設計する。検証を省略はしない。
- **forwardの速度**：同じsourceのnativeの約2倍。GEMMがSIMD128を使っていない可能性（W0）を含め、W2以降の正式計測で扱う。
- **環境**：headlessのみ。headed表示、他browser、モバイル、メモリの少ない端末は未確認。

## 証跡と再現

[証跡](research/wasm-demo/w1-2026-10-11/README.md)、[runtime/wasm/README.md](../runtime/wasm/README.md)。W0の判定は最終binaryでも再度合格した（`w0-regression`）。
