# 独立OSS公開に向けた実行計画

2026-10-11作成。pure-jeffを独立したOSSとして公開できる状態にするための作業計画と、着手時点の調査結果。公開（remote作成、push、一般公開、有料サービスの設定）はこの計画の範囲外で、利用者の判断を待つ。

## 着手時点の調査結果

| 項目 | 状態 |
| --- | --- |
| Rustのbuild・試験 | 4 crateとも単独でbuild・試験に合格（`80e0cec`時点）。Cargo依存はcrates.ioとCandleのgit revisionのみ |
| KazeJudgeへの依存 | 公式JeffのPython環境（`../KazeJudge/vendor/jeff/.venv`）を借用している。ほかに、Webデモの表示名とcache名、W0／W1の画面title、`runtime/package_rust_runtime.py`の文言に「KazeJudge」が残る |
| モデルの入手 | `models/`はgit管理外。checkpointは公開repo `jeff-legacy/Jeff-Qwen3.5-0.8B`（旧`mstrasser/…`）の固定revision `51552f39…`から取得でき、gateなし、Apache-2.0。`main`は`d86f657`へ進んでいる |
| ライセンス | 本家Jeffのコード：MIT（Mathias Strasser、Denis Yarats）。重み：Apache-2.0とNOTICE（Qwen3.5-0.8Bの派生）。base model Qwen3.5-0.8B：Apache-2.0。**pure-jeff自身のライセンスは未定。** 重みのREADMEは、学習データに条件の異なるdataset（CC BY-SAを含む）を混ぜたと記載している |
| 秘密情報・個人情報 | 鍵・token等は検出なし。ローカルの絶対path（利用者名を含む）が証跡script 1件（`docs/research/wasm-demo/w2-2026-10-11/official-references/export_all.sh`）にある。commitのauthor情報は利用者のもの |
| 大容量file | 最大は453 KBのgolden。モデル・build成果物はignore済み |
| CI | `.github/workflows/rust-contracts.yml`はKazeJudge時代のもので、Wasm buildとdemo engineを含まない |
| Hugging Faceからの配信 | 固定revisionのresolve URLは、任意のOriginに対してCORSを許可する。デモがHFから直接取得する構成も技術的には可能 |

## 作業順と完了条件

### 1. 独立性とbuildの確認

1. 公式Jeffの参照環境を、pure-jeff自身の`.venv/jeff-ref`へ固定lockから作る（`uv sync --frozen --no-default-groups --no-install-project`）。Jeff sourceが要求するuvのversion（0.12.19以上）は、利用者のuvを更新せず`uvx`で使う。
2. `tools/fetch_model.py`：固定revisionの11ファイルをHugging Faceから取得し、commitしたSHA-256一覧と照合する。既存のファイルは上書きしない。
3. clean環境での確認：pure-jeffを一時directoryへcloneし、新しい`CARGO_HOME`と`CARGO_TARGET_DIR`で依存の取得から始める。モデルをHugging Faceから取得してbundleを`jeff lock`し、build・試験・公式golden 6件の照合を行う。

完了条件：KazeJudgeのfileを一切参照せず、golden 6件の判断が一致し、確率差が既存記録（最大5.066e-6）と同じであること。

### 2. ライセンス・配布準備

1. `tools/audit_licenses.py`：4つのCargo lockから、対象platform（Windows x86_64、wasm32）別に依存のlicense宣言とlicense本文の有無を一覧にし、未宣言やcopyleftを検出する。
2. `THIRD_PARTY_NOTICES.md`：本家Jeff（MIT）、重み（Apache-2.0とNOTICE）、Qwen3.5（Apache-2.0）、実装の参照元、依存crateの帰属をまとめる。
3. Webデモの配信物に、engineへ組み込まれる依存のlicense本文と、モデルのLICENSE／NOTICEを同梱する。
4. **pure-jeff自身のLICENSEは追加しない。** 選択肢と影響を`docs/licensing.md`に整理し、公開blockerとして報告する。

### 3. リポジトリ整理とCI

1. READMEを独立プロジェクト向けに書き直す（概要、対応範囲、入手・build・検証の手順、出典、未決事項）。
2. GitHub Actions（Windows）：4 crateのtest・clippy・fmt、Native release build、probeとdemo engineのWasm build、モデル不要のPython試験、JSの構文確認。workflowは利用者がremoteを作るまで実行されないため、同じcommandをclean cloneで実行して確認する。
3. 大容量・一時生成物・秘密情報がcommitされていないことを、上の走査で継続して確認する。

### 4. Webデモの公開準備（W4）

1. 配信物の`engine.wasm`から、probeの開発用export（`kj_*`）を除く（buildの後処理でexport sectionを絞る。probeのsourceと証跡は変えない）。
2. 表示：失敗・不評価のときに分布の注記を出さない。削除後の使用量表示の遅れを説明する。表示名をpure-jeffに改める。ライセンス表示へのリンクを置く。
3. HTTPS配信の検証：自己署名証明書で`https://demo.test`（サイト）と`https://models.test`（モデル、CORS付き）の別originを用意し、Pages＋R2の構成を模す。W3の判定に、ダウンロード途中の中止（部分保存なし）を加え、Chrome／Edgeで実施する。従来のW3構成（同一origin、HTTP）もChromeで回帰確認する。
4. `docs/w4-hosting.md`：Cloudflare Pages＋R2の構成、`_headers`とR2のCORS設定例、料金と制約（512 MBを超えるfileはCDNにcacheされない、r2.devは開発用、custom domainが必要）、代替案（Hugging Faceから直接取得、分割配信）。

### 5. Native推論の改善計画（実装はしない）

KazeJudgeの既存証跡（FP32保持、text320、thread matrix）と今回のbenchmarkを使い、BF16 mmapを既定のまま、FP32重み保持をoptionにする案の性能・メモリ・数値の論点を`docs/native-fp32-retention-plan.md`に整理する。

## 守ること

既存のAPI・推論結果・golden・検証証跡を変えない。KazeJudgeや他セッションのfileを変えない。変更ごとに必要な試験を行い、論理単位でcommitする。remote作成・push・公開・有料サービスの設定は行わない。ライセンスや公開条件の不確実な点は推測で解決せず、blockerとして報告する。

## 進捗（2026-10-11）

| 段階 | 状態 | 記録 |
| --- | --- | --- |
| 1. 独立性とbuild | 完了。KazeJudgeのfileとPython環境を使わずに、clean cloneでbuild・試験・golden 6件の完全再現を確認。公式Jeffの参照環境も`.venv/jeff-ref`へ作り直した | [clean環境での確認](clean-environment-check.md) |
| 2. ライセンス | 監査とNOTICEは完了。**自身のライセンスなど5件が公開blocker**（利用者の判断待ち） | [licensing.md](licensing.md)、[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) |
| 3. 整理とCI | README、docs索引、CI workflowを整備。CIはremoteがないため未実行で、同じcommandをclean cloneで確認する | [.github/workflows/ci.yml](../.github/workflows/ci.yml) |
| 4. W4 | 開発用exportの除去、ライセンスの同梱、表示の修正、HTTPS・別originでのE2E（Chrome／Edge）に合格。中止後に残る部分cacheを消せない点は未修正 | [W4結果](web-demo-w4-results.md)、[配信構成](w4-hosting.md) |
| 5. Native改善 | 計画のみ | [計画](native-fp32-retention-plan.md) |

KazeJudge時代の名称は、証跡に結び付いたfile（W0／W1のprobe画面のtitle、`runtime/wasm`の各driverの既定manifest名、`runtime/package_rust_runtime.py`の文言）に残っている。hashが証跡に記録されているため、変えていない。
