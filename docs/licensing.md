# ライセンスの監査と未決事項

2026-10-11。公開の前に権利者・利用者が判断すべき点を整理した。ここでは推測で決めない。上流の帰属は[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)、依存の一覧は[license-audit.json](license-audit.json)にある。

## 監査の結果

| 対象 | ライセンス | 確認方法 | 結果 |
| --- | --- | --- | --- |
| 本家Jeff（firelex/jeff `3720e7c`） | MIT | 固定commitのLICENSE本文（hash記録済み） | 帰属表示で足りる |
| Jeffの重み（`jeff-legacy/Jeff-Qwen3.5-0.8B` `51552f39`） | Apache-2.0とNOTICE | Hugging Faceの固定revisionのmetadata、checkpoint内のLICENSE・NOTICE | repoには含めない。再配布ではLICENSEとNOTICEを同梱する |
| Qwen3.5-0.8B | Apache-2.0 | Hugging Faceのmetadata | 重みのNOTICEで言及されている |
| Rust依存（138 package） | すべてpermissive | `tools/audit_licenses.py`（Cargo.lockから） | 未宣言なし、copyleftなし、本文の欠落なし |
| pure-jeff自身のコード | **未定** | — | 公開blocker |

## 公開blocker（判断が必要）

1. **pure-jeff自身のライセンス**：自作の4 crate（`kaze_judge`、`kaze_judge_jeff`、`kaze_judge_wasm_probe`、`kaze_judge_web_demo`）、Python・JSのtool、文書にライセンスがない。依存はすべてpermissiveなので、次のどれも技術的には両立する。選択は権利者が行う。
   - MIT OR Apache-2.0（Rustで一般的。依存と同じ形）
   - Apache-2.0（特許条項あり。重みやQwenと同じ）
   - MIT（本家Jeffのコードと同じ）
2. **著作権者の確認**：commitのauthorは組織のドメイン（`siska-tech.jp`）のメールアドレスである。コードの権利が個人と組織のどちらにあるか（業務で作成したか）を確認し、LICENSEの著作権表示を決める必要がある。
3. **`backbone.rs`とTransformersの関係**：commentは「Transformers 5.17.0のQwen3.5で式を照合した」と書く。実装がTransformers（Apache-2.0）のsourceを翻訳した派生物にあたるなら、そのファイルにApache-2.0の帰属と変更の表示が必要になる。作成の経緯（KazeJudge P1）を記録だけからは判定できないため、作成者の確認を要する。
4. **重みの再配布と学習データ**：重みの公開者はApache-2.0を宣言している。一方、model cardは学習データにshare-alike（CC BY-SA）のdatasetを含むと書く。Webデモで重みを自前のstorage（R2など）から配る場合、公開者の宣言に依拠して再配布してよいかを判断する必要がある。Hugging Faceの固定revisionからブラウザが直接取得する構成にすれば、自前の再配布は避けられる（[W4 hosting](w4-hosting.md)）。
5. **名称**：「pure-jeff」と「Jeff」は上流projectの名称を含む。上流と無関係である旨をREADMEに書いた。名称の使用について上流に確認するかは判断事項とする。

## 公開前に確認しておくとよい点（blockerではない）

- checkpointのrepoは`mstrasser/…`から`jeff-legacy/…`へ移っている。固定revisionのhashで内容を照合しているので、取得物の同一性は保証される。ただし、legacy repoが将来削除されると`tools/fetch_model.py`が使えなくなる。
- 証跡script `docs/research/wasm-demo/w2-2026-10-11/official-references/export_all.sh`は、利用者名を含むローカルの絶対pathを含む。証跡なので変更していない。公開してよいか確認する。
- git履歴のauthor名とメールアドレスが公開される。
- crate名、schema名（`kaze_judge.*`）は、KazeJudgeとの互換と既存の証跡を保つため残している。改名すると既存のAPI・hash固定・証跡が変わる。
