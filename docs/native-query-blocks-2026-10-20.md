# Native：1行のquery blockを作らない分け方（#18）

2026-10-20。full attentionのquery blockの分け方を変え、最後のblockが1行にならないようにした。

## 背景

- [ARM64の差異](native-arm64-2026-10-20.md)の調査で、1行だけのblockは、gemmがgemv経路で計算することが分かった。gemvは、kを区切らずに足す。
- 次のhostでは、gemvの和の順序が、複数行のkernelと違う。
  - aarch64。
  - host L1から決まるkcがkより小さいx86_64（8-way L1のEPYC runner、i7-1360PのE-core）。
- そのため、seq mod 512＝1の入力（513、1025、…、7681 tokens）では、block化した結果が1 blockの計算とbit一致しなかった。
  - 公式refとの数値gateと判定には影響しない。

## 変更

- **`query_blocks(seq, block)`**（`src/backbone.rs`）：block列を作る関数。
  - 512行ずつ分け、最後が1行になる場合だけ、最後の2つを511行と2行にする。
  - それ以外の入力では、従来と同じ分け方になる。
  - blockの最大は512行のままなので、scores・mask・probabilitiesのメモリの上限は変わらない。block数も変わらない。
- **`full_attention`**：この分け方を使う。期限の確認は、従来どおりblockの間にある。
- **試験**：
  - `query_blocks_cover_the_sequence_without_one_row_blocks`（新規）：block列が連続して全行を覆うこと、各blockが1〜block行であること、1行のblockがないこと（seq＝1を除く）、変わるのは1行の末尾がある場合だけであることを確かめる。block 3、8、512で、seq 1〜3×block＋2、8191、8192を調べる。
  - `attention_in_query_blocks_is_bitwise_equal_to_one_block`：`query_blocks`の分け方で、**すべてのtargetでbit一致**を要求する。PR #38で入れた1e-6の例外は削除した。
    - 対象：seq 1／7／8／9／37（block 3、8）と、513／1024／1025（block 512）。
    - 任意の分け方（1行のblockを含む）の試験はやめた。それは本番で使わない分け方である。

公開API、1 threadの既定経路のほかの部分、数値gate、timeout・killの契約は変えていない。`src`の変更なので、runtime build hashが変わる。bundleは再lockが必要である。

## 検証

### 手元（i7-1360P、Windows）

- library・CLIの試験は、すべて合格した。
- **試験を起動CPUに固定して実行**（`host_matrix.py`の方法）：P-core（CPU 0〜7）、E-core（CPU 8〜15）とも、新しい試験3件が合格した。
  - 変更前は、E-coreで「seq 513, block 512」が不一致だった。
- **モデル、main（`0b49f64`）とこのbranchの比較**（catalogの全39件、4 thread、`resident_bench --mode api`、各processを起動時からP-coreまたはE-coreに固定）：

| 比較 | bit不一致の件数 | 内容 |
| --- | ---: | --- |
| main（P-core起動）とbranch（P-core起動） | 0 | 全39件で確率・判定がbit一致。kc≧kのhostでは結果が変わらない |
| main（E-core起動）とbranch（E-core起動） | 1 | synthetic-ocr-ascii-3-513だけ（確率の最大差3.7e-7、判定は一致）。ほかの38件はbit一致 |
| P-core起動とE-core起動（main、branchとも） | 36 | CACHE_INFOによる既知の差（#18）。この変更の対象外 |

- 4つのprocessとも、全39件で数値gateに合格した。
- **513 tokensで、block化と1 blockの比較**（`attention_block_diff model`、4 thread）：

| build | 起動CPU | hidden（1024要素）の不一致 | 確率の不一致 | 判定 |
| --- | --- | ---: | ---: | --- |
| main | P-core | 0 | 0 | 一致 |
| main | E-core | 958 | 3 | 一致 |
| branch | P-core | 0 | 0 | 一致 |
| branch | E-core | **0** | **0** | 一致 |

- 証跡：[research/native-query-blocks-2026-10-20/](research/native-query-blocks-2026-10-20)
  - 判断ごとの確率（`decisions-*.jsonl`）。
  - 比較（`compare-39-cases.json`）。
  - 513 tokensの比較（`blockdiff-513-*.jsonl`）。

### 4環境CI

`native-hosts.yml`をこのbranchで手動実行し、結果をPRに記録する。
