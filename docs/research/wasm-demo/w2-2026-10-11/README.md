# W2証跡（2026-10-11）

[W2結果](../../../wasm-w2-results.md)の証跡。browserの生出力（hidden stateを含む`browser.json`）は、ignoredな`experiments/runs/wasm-w2-*-20261011/`にある。

| dir | 内容 | 判定 |
| --- | --- | --- |
| `chrome/`, `edge/` | 事前登録、集計、browser process treeのpeak、同じsourceのnative参照（1 thread）、case一覧 | 合格 |
| `official-references/` | 長さfixture 8件について、公式Jeff（Python）で採取した参照。選定記録、要求JSON、採取script | 各exporterの独立照合は差0 |
| `w1-regression/` | W2の最終binaryでのW1再実行（Chrome） | 合格。確率はW1最終runと同一 |

長さfixtureの元データは`experiments/runs/length-inputs-20261011/inputs.json`（ignored）。選定した8件のpromptのSHA-256とtoken数は`official-references/selection.json`に記録し、採取した参照と一致することを確認した。入力は説明用の人工データで、日本語OCR／ASRの品質評価ではない。
