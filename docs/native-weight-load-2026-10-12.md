# 重みをbytesから直接FP32へ変換する（2026-10-12）

[issue #8](https://github.com/siska-tech/pure-jeff/issues/8)。[要素ごとの演算の融合](native-elementwise-2026-10-12.md)（#2）の後の内訳では、短い入力で重みのアクセスが大きかった。128 tokensのforward 2.26秒のうち、重みの読込とBF16→FP32変換が0.49秒、embeddingが0.10秒を使っていた。これを**出力をbit単位で変えずに**減らした。

## 変更

変更前は、forwardのたびに重みを次の手順で用意していた。

1. `WeightSource::load`（Candleの`MmapedSafetensors::load`）で、mmapしたBF16のbytesを新しい配列へcopyする。
2. `to_dtype(F32)`で、もう1つ配列を確保して変換する。

embeddingは、表全体（248320×1024、BF16で485 MiB）をcopyしてから、必要な行を選んでいた。

変更後：

- **`WeightSource`に、既定の実装を持つメソッドを2つ追加した。** 既存の利用者の実装は、そのままbuildできる。
  - `load_f32(name)`：既定の実装は`load`のあと`to_dtype(F32)`。
  - `load_f32_rows(name, ids)`：既定の実装は`load`、`index_select`、`to_dtype(F32)`の順。
- **`MmapedSafetensors`と`SliceSafetensors`（ブラウザ）では、BF16のtensorをsafetensorsのbytesから直接FP32へ変換する。** embeddingは、必要な行だけを変換する。BF16以外のdtypeは、既定の実装（Candle）に任せる。
- **変換には`half::bf16::to_f32`を使う。** Candleの`to_dtype`が使うのと同じ関数で、signaling NaNを静かなNaNにする処理も同じになる。`half`はすでに依存ツリーにあった（2.7.1）ので、直接の依存に加えた。各`Cargo.lock`の変更は、`pure-jeff`の依存の1行だけである。
- backboneとreadoutは、重みを`load_f32`で、embeddingを`load_f32_rows`で読む。

FP32の重みを保持はしない（[#4](https://github.com/siska-tech/pure-jeff/issues/4)とは別）。

## 数値の確認

| 確認 | 結果 |
| --- | --- |
| 単体試験`direct_conversion_is_bitwise_equal_to_candle` | 直接の変換と、既定の実装（Candleの読込と変換）で、全要素のbitが一致した。入力は、正規化数、±0、±無限大、非正規化数、静かなNaN、signaling NaN、最大・最小のBF16値。行の選択（重複・逆順・空）と、F32のtensor（既定の実装に任せる経路）も含む。x86-64と、wasm32-wasip1＋simd128で合格した。変換を単純なbit shift（NaNを静かにしない）に変えると失敗することも確かめた |
| 公式参照7件（128〜8192 tokens） | 最終hidden stateのSHA-256が、全件で0.1.0の基準値と一致した。各2回の反復も一致した |
| `forward_breakdown` | 変更前・変更後とも、計時つきcopyの出力は全24回で本物のforwardとbit単位で一致した |
| crates.io用package（`tools/check_package.py --manifest`） | crates.ioのCandle 0.11.0で、公式参照7件に合格した。ケースごとの確率差は#1・#2の検証時と同じ値だった |
| ライセンス監査（`tools/audit_licenses.py --strict`） | 合格した |
| Webデモengine | `tools/build_wasm.py engine`でbuildでき、host pathを含まない |

## 時間

変更前（#2の後のmain）と変更後を交互に（前・後・後・前）実行し、1 thread、各caseで変更前・変更後それぞれ4回測った。forwardだけの時間の中央値（最小〜最大）。

| case | tokens | 変更前（秒） | 変更後（秒） | 後／前 |
| --- | ---: | --- | --- | ---: |
| candidate-request | 128 | 2.51（2.32〜2.64） | 2.09（1.99〜2.21） | 0.83 |
| asr-unicode | 206 | 3.20（3.17〜3.23） | 2.89（2.89〜2.92） | 0.90 |
| long-text | 874 | 11.45（11.10〜11.63） | 11.19（11.17〜11.33） | 0.98 |
| maximum-candidates | 3206 | 46.80（46.30〜47.20） | 46.45（46.26〜46.58） | 0.99 |

内訳（`forward_breakdown`、各3回の中央値）：

| tokens | 重みの読込＋変換 | embedding | 両者の割合（変更後） |
| ---: | --- | --- | ---: |
| 128 | 0.493 → 0.352秒 | 0.101 → 0.000秒 | 17.5% |
| 206 | 0.492 → 0.358秒 | 0.094 → 0.000秒 | 12.3% |
| 874 | 0.529 → 0.360秒 | 0.098 → 0.001秒 | 3.2% |
| 3206 | 0.520 → 0.352秒 | 0.105 → 0.002秒 | 0.8% |

残りの約0.35秒は、forwardごとに約5億パラメータ（FP32で約2.0 GB）を変換して書き出す時間である。別の小さな計測（1億要素、単発の観測値）では、次のことが分かった。

- **変換の式を変えても速くならない。** 分岐のない変換を作った。BF16の全65536値で`half`とbitが一致することを確かめたが、速度は同じだった（約1.5 G要素/秒）。
- **書き出し先の配列を使い回すと、約2倍速くなる（約3 G要素/秒）。** 残りの時間の約半分は、毎回新しく確保したメモリへの最初の書き込み（page fault）である。

配列を使い回すには、forwardをまたいで変換先の配列を再利用する仕組みが要る。重み自体をFP32で保持する（#4）と、変換はなくなるがメモリが増える。

## メモリ

forward_check（1 case、forward 1回、readoutを含む）を、変更前・変更後を交互に各2回実行した。peakの値は、OSが記録するprocessのpeakを、終了直前まで50 msごとに読んだもの（`peak.py.txt`）。各組の2回の差は1 MiB以内だった。

| case | private commitのpeak | Working Setのpeak |
| --- | --- | --- |
| candidate-request（128 tokens） | 553 → 203 MiB | 1,530 → 1,037 MiB |
| long-text（874 tokens） | 556 → 203 MiB | 1,610 → 1,126 MiB |

embedding表全体のcopyがなくなった分が減った。Working Setにはmmapした重みのpageも含まれる。

条件：Core i7-1360P、Windows 11 Home、Rust 1.99.0、AC電源。背景負荷は制御していない。この機械での記述的な観測値である。

実行ファイルのSHA-256：forward_check 変更前`6b7fa455…2a383ed`／変更後`1be93181…d53afb`、forward_breakdown 変更前`60609203…8477cbe7`／変更後`817d4951…02ebad8b`。

## 利用者への影響

- 出力は変わらない。
- `WeightSource`に、既定の実装を持つメソッドが2つ増えた。独自に`WeightSource`を実装している場合も、変更せずにbuildできる。直接の変換を使いたい場合は、2つのメソッドを実装する（既定の実装とbit単位で同じ値を返すこと）。
- runtimeのsourceが変わるので、build hashが変わる。CLIで使うbundle manifestは`jeff lock`で作り直す。

## 証跡

[research/native-weight-load-2026-10-12/](research/native-weight-load-2026-10-12)：

- `breakdown-before.jsonl`、`breakdown-after.jsonl`：内訳
- `golden.jsonl`：公式参照7件、変更後
- `interleaved.jsonl`：交互計測
- `memory.jsonl`：メモリのpeak
- `peak.py.txt`：メモリ計測に使ったscript
