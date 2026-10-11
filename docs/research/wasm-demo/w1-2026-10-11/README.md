# W1証跡（2026-10-11）

[W1結果](../../../wasm-w1-results.md)の証跡。browserの生出力（hidden stateを含む`browser.json`）は、ignoredな`experiments/runs/wasm-w1-*-20261011/`にある。

| dir | 内容 | 判定 |
| --- | --- | --- |
| `chrome/` | 最初のrun。heap予約なし。使用した`run_w1.py`と`w1-worker.js`を`.used`として同梱（事前登録のhashと一致を確認） | 合格（tokenizer段階が約30秒） |
| `final-chrome/`, `final-edge/` | 768 MiBのheap予約あり。最終source・最終成果物 | 合格（最終証跡） |
| `w0-regression/` | 最終binaryでのW0再実行（Chrome、baseline／simd128） | 合格 |
| `tokenizer-heap-diagnosis.mjs` | Nodeでtokenizer読込を、大きな確保の有無と予約の有無で比べたscript | 診断用 |

各runの`native-reference.json`は、同じ`decide`をx86_64・1 threadで実行した結果。`browser-processes.json`は、終了直前のbrowser process treeのlifetime peak。入力は説明用の人工goldenで、日本語OCR／ASRの品質評価ではない。
