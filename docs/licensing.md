# ライセンスの監査と未決事項

2026-10-11。公開の前に権利者・利用者が判断すべき点を整理した。ここでは推測で決めない。上流の帰属は[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)、依存の一覧は[license-audit.json](license-audit.json)にある。

## 監査の結果

| 対象 | ライセンス | 確認方法 | 結果 |
| --- | --- | --- | --- |
| 本家Jeff（firelex/jeff `3720e7c`） | MIT | 固定commitのLICENSE本文（hash記録済み） | 帰属表示で足りる |
| Jeffの重み（`jeff-legacy/Jeff-Qwen3.5-0.8B` `51552f39`） | Apache-2.0とNOTICE | Hugging Faceの固定revisionのmetadata、checkpoint内のLICENSE・NOTICE | repoには含めない。再配布ではLICENSEとNOTICEを同梱する |
| Qwen3.5-0.8B | Apache-2.0 | Hugging Faceのmetadata | 重みのNOTICEで言及されている |
| Rust依存（138 package） | すべてpermissive | `tools/audit_licenses.py`（Cargo.lockから） | 未宣言なし、copyleftなし、本文の欠落なし |
| pure-jeff自身のコード | Apache-2.0 | 利用者の決定（2026-10-12） | `LICENSE`、`NOTICE` |

## 公開blockerの決定（2026-10-12）

1. **pure-jeff自身のライセンス**：利用者の決定により**Apache-2.0**とした（`LICENSE`、`NOTICE`、4 crateの`license`）。依存はすべてpermissiveで両立する。
2. **著作権表示**：`NOTICE`は「The pure-jeff authors」とした。特定の法人名・個人名は書いていない。権利者を明記する必要があれば、利用者が追記する。
3. **`backbone.rs`とTransformers**：pure-jeffもApache-2.0になったため、仮にTransformers（Apache-2.0）の派生物にあたる場合でも、ライセンスは両立する。帰属は[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)に記載済み。作成の経緯（翻訳か独自実装か）は未確認のまま残る。
4. **重みの再配布**：公開するWebデモ（`pure-jeff.siska-tech.workers.dev`）は、Hugging Faceの固定revisionからブラウザが直接取得する構成にした。pure-jeffは重みを再配布しない。checkpointのLICENSEとNOTICEは、配信物の`licenses/`にも置く。
5. **名称**：利用者の決定により、pure-jeffの名称で公開する。READMEとWebデモに非公式実装である旨を表示する。

## 公開前に確認しておくとよい点（blockerではない）

- checkpointのrepoは`mstrasser/…`から`jeff-legacy/…`へ移っている。固定revisionのhashで内容を照合しているので、取得物の同一性は保証される。ただし、legacy repoが将来削除されると`tools/fetch_model.py`が使えなくなる。
- 証跡script `docs/research/wasm-demo/w2-2026-10-11/official-references/export_all.sh`は、利用者名を含むローカルの絶対pathを含む。証跡なので変更していない。公開してよいか確認する。
- git履歴のauthor名とメールアドレスが公開される。
- crate名、schema名（`kaze_judge.*`）は、KazeJudgeとの互換と既存の証跡を保つため残している。改名すると既存のAPI・hash固定・証跡が変わる。
