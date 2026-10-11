# ONNX／Tract資産の移管計画

2026-10-12。KazeJudgeに残っているJeff向けのONNX export・Tract推論実験・性能最適化・benchmark・数値検証と研究証跡を、pure-jeffへ移す。pure-jeffを、Native（Candle）・ONNX／Tract・ブラウザWasmの3系統の推論基盤として整理する。

## 前提と制約

- 移管元はKazeJudge commit `ad59b25`（`main`）。KazeJudge・KazeNhanhのコード、API、データ、Git履歴は変更しない。読み取りは別のcloneで行う。KazeJudgeの作業ツリーにある他セッションの未コミットファイル（`runtime/onnx/prepare_unseen_oracle.py`など3件）は移管しない。
- 現行のNative（`runtime/rust`）、Wasm、公開Webデモの動作は変えない。既存のCIの検査も弱めない。
- モデル（ONNX 3.2 GB）、build生成物、新しく取るbenchmarkの一時ログはGitに入れない。
- 過去の性能値は当時のhostでの参考証跡であり、新しい環境での性能保証には使わない。
- 数値gateを満たさないTract経路は実験扱いのままにする。
- commitは論理単位で分け、AI署名は付けない。push・公開デプロイは行わない。

## 監査結果

### 移管対象（KazeJudge `ad59b25`、2,299ファイル）

| 移管元 | 内容 | 依存 |
| --- | --- | --- |
| `runtime/onnx/` | ONNX export・正規化・ORT参照（oracle）・Tract数値gate・benchmark harness（Python、開発専用）。74ファイル | 固定Jeff source＋Python環境、ONNX tools lock、`models/jeff-bundle.json`、golden |
| `runtime/tract/` | 隔離したTract probe／bench／pack（Rust）。Tract 0.23.8を固定し、`data` crateだけ局所修正版をvendor | sonos/tract `9e0cfaa`（git依存） |
| `runtime/tract-driver-profile/` | Tract最適化実験（重複探索削除、名前索引、Trilu・ScatterElementsの行単位処理、forward profile）の生成用source | 上記upstream checkout |
| `runtime/bench-native/` | Native計測wrapperと長さfixture生成 | pure-jeffの`kaze_judge`・`runtime/rust`（同名・同じ相対path） |
| `runtime/native-retained/` | Native FP32重み保持実験のsource | 同上 |
| `docs/onnx-tract-*.md`（kzn取込を除く30件） | 計画・互換性・各実験の結果 | — |
| `docs/research/jeff-onnx-tract/`（kzn取込を除く） | 実験ごとの証跡（job・raw出力・検証・host情報） | — |
| `.github/workflows/tract-probe.yml` | 小型graphのTract CI（GitHub上では未実行） | — |

履歴：上記pathに触れるKazeJudgeのcommitは33件。authorはpure-jeffと同じ。messageにツールの帰属表示はない。

### 移管しないもの

- kzn-datasetの実OCR取込とKazeNhanh単独確認（`docs/onnx-tract-kzn-ocr-intake.md`、`runtime/onnx/*kzn_ocr_intake.py`、証跡`kzn-ocr-intake-2026-10-11/`）：KazeNhanhと隣接データセットの監査であり、推論基盤ではない。KazeJudgeに残す。
- KazeJudgeの`.venv/`にある未追跡の補助script・凍結した実行ファイル・生成source（`archive_*.py`など）：Git管理外で、証跡の再現に使ったローカル資産。KazeJudge側に残し、必要な場合はhashで照合する。
- `experiments/runs/onnx-current-step1113-v2/`（ONNX 3.2 GB）：Gitに入れない。pure-jeffで再exportし、記録済みhashと照合する。

### 個人情報

証跡591ファイルとscript 1件に、利用者名を含むローカルの絶対path（`C:\Users\<名前>\...`）がある（host名・所有者名などは含まない）。pure-jeffは2026-10-12に同じ理由で履歴を書き換えている（[commit-map.md](commit-map.md)）。そのため取り込む全履歴で利用者名の部分だけを`<user>`に置き換える。置き換えたファイルの原本hash（KazeJudge）と取込後のhashの対応表を残し、KazeJudgeの原本に同じ置換を施すと取込後のbytesと一致することをscriptで検証できるようにする。

## 手順

1. **履歴を保った取込**：KazeJudgeを一時directoryへcloneし、`git filter-repo`で移管対象pathだけを残し（kzn取込は除外）、利用者名を置換する。pathは移管元と同じにする（scriptと証跡が相互にpathで参照しているため）。pure-jeffへ`--allow-unrelated-histories`でmergeする。
2. **hashの照合**：移管元`ad59b25`の全対象ファイルについて、置換なしのファイルはbytesが同一、置換したファイルは置換後が一致することを確認し、`docs/tract-migration-provenance.json`に記録する。
3. **pure-jeffでの単独build**：`.gitignore`、Tract用の隔離Cargo home、`runtime/tract`と`runtime/bench-native`のbuild・clippy・fmt・試験を確認する。
4. **upstreamとの差分の明示**：vendorした`data` crateの差分をupstream `9e0cfaa`と照合してpatchとして保存し、生成型の最適化実験（Trilu・ScatterElementsなど）と合わせて「upstream版ではない」ことを文書化する。
5. **モデル生成と数値検証**：pure-jeffの環境だけでONNXを再exportし、KazeJudgeで記録したhash・ORT oracle・Tract数値gate（goldenとの確率差1e-4以内、判断一致）と照合する。Nativeの公式golden照合も再実行し、既存結果と比べる。
6. **benchmark**：harnessの起動確認に限る。新しい環境の性能値は参考値として扱い、過去値と混ぜない。
7. **統合判断**：Tractを既存APIと互換のoptional backendにできるかを、数値gate（公式golden全件、8192 tokensを含む）・入力長・upstreamとの差分・配布条件で判断する。満たさない場合は実験のまま残し、条件を記録する。
8. **文書・CI・ライセンス**：README、docs索引、Tract用CI（既存CIと分離）、NOTICE／THIRD_PARTY_NOTICES（Tract MIT/Apache-2.0、jigor exporter Apache-2.0）を更新する。

## 受入条件

- 既存のCI相当の検査（contract、Native、Wasm、Webデモengine、Python）が移管前と同じく通る。
- 移管したファイルのhashが移管元と一致する（置換分は対応表で説明できる）。
- KazeJudge・KazeNhanhの`git status`とHEADが作業前と同じ。
- Tractの扱い（実験／optional backend）と根拠が文書にある。
