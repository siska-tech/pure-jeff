# Pure Rust推論への移行計画

2026-10-10更新。P3のRust worker/NativeProcessProviderとKazeNhanh CLI backend選択を実装・ローカル検証済み。P4へ着手し、探索的性能測定、再配置可能なローカルpackage、license本文収集、品質入力監査、Python不要の通常CI定義を追加した。依存本文の不足を補完し、Jeff参照実装のMIT本文とNOTICE索引を追加した。性能SLO、日本語品質、プロジェクトlicense・配布NOTICEの最終レビューとPython未導入clean hostでの受入は未完了。P0の人工参照は長文・特殊文字・255候補・8192 token上限を含む7件へ拡充し、実forward照合に成功した。[追加6件の照合](extended-migration-validation.json)、[8192 token照合](token-limit-forward-validation.json)、[本文収集監査](p4-license-review.json)、[P4受入記録](p4-acceptance.md)、[進捗記録](pure-rust-progress.md)、[Rust実行手順](../runtime/rust/README.md)、現在の設計は[architecture.md](architecture.md)を参照。

## 目標と範囲

Windows x86_64 CPUで、資産検証、prompt構築、tokenize、モデルforward、Jeff readout、候補分布、選択/保留までRustで実行する。配布物はRust製実行ファイルと固定モデル資産で構成し、Python・PyTorch・libtorch・ONNX Runtime・llama.cpp等の外部推論実装を必要としない。OS API、標準のシステムライブラリ、Rust toolchainが使用するリンカは許容する。推論・tokenizerの推移的依存にC/C++実装が入らないことも監査する。

初期範囲はtext-only、CPU FP32、1要求・1質問・1 forward、adapterなし。既存のDecisionRequest / Observation / DecisionProviderとKazeNhanh adapterを利用する。学習、参照結果の生成、移行検証用のPython環境は開発側に残せるが、配布・通常実行・Rust版資産検証には不要とする。

GPU、量子化、LoRA、画像・音声の直接入力、常駐化、queue・累計予算は後続課題。それぞれ移植一致と品質評価を経て追加する。

## 技術方針

- 推論基盤の第一調査候補はCandleのCPU backend。採用はP1の実証後に決め、依存version/revisionとfeatureを固定する。MKL・Accelerate・CUDA等を使う構成は初期Pure Rust構成に含めない。
- tokenizerはHugging Face tokenizersのRust実装を第一候補とする。採用版のregex、正規化、build scriptを含む推移的依存を調べる。default feature無効化だけで純Rustを証明した扱いにしない。
- 重みは元checkpointのsafetensorsを直接読み込む方針。shard index、tensor名・shape・dtype、readoutを検証する。変換が必要なら入力/出力hashと変換仕様を残し、変換後の一致を別途検証する。
- Jeff固有の前後処理とbackbone実装を分ける。通常のLLM生成APIだけではJeffのreadout出力を再現できないため、必要なhidden stateへアクセスできることを採用条件とする。
- 最初の配布経路はRust製workerの子プロセス方式。親がdeadlineを監視してkill/waitする既存の停止能力を維持する。Pure Rust化に単一プロセス化は必須としない。
- in-processのRust Providerは後続で提供可能。ただし同期forwardを即時停止できない制約を明示し、停止保証が必要な呼出にはprocess方式を使う。

Candle公式READMEにはRust/CPU backendが記載されているが、確認したmainのmodel一覧に`qwen3_5`はない。これは「未対応」と断定する証拠ではなく、対応状況・別実装・必要演算を固定revisionで調べる必要があるという判断材料である。Qwen2/Qwen3の実装をそのまま使えるとは仮定しない。詳細な互換性と性能は未検証。

## 移行段階と完了条件

### P0: 参照実装と資産を確定する

1. Python 3.12以上の実行パスと独立依存環境を整備し、既存Rust/Python試験を再実行する。
2. `jeff-reference.json`のcommit/checkpoint候補を取得し、実config・LICENSE/NOTICE・tokenizer・readout・全重みを確認してhashを固定する。候補のコードとcheckpointが非互換なら組合せを再選定し、理由を記録する。
3. 現workerの`decision_config.max_options`要求を検証する。確認した固定版Jeffの設定型・保存処理にはこの項目がなく、`codes`/`token_ids`を持つ。実checkpointに基づき上限検証を整合させ、設定だけで推論前に失敗する問題を解消する。
4. 公式predictと現workerを同じprompt・候補順・CPU FP32条件で照合する。単一forwardに対応する条件を固定し、複数順序の平均化を混ぜない。
5. 合成入力による移植用fixtureを作成する。prompt bytes、token IDs、attention/position関連入力、最終hidden state、mask前後logits、temperature、分布、token数と選択結果を保存する。資産hashと依存versionを添付する。

**完了条件:** 実重みで公式とworkerの差分を説明でき、再生成可能な参照fixtureがある。現在の人工モデルfixtureだけではこの段階を完了にしない。

### P1: Rust backendの実現性を判定する

1. 固定checkpointのtext backboneが必要とする全演算、位置表現、mask、状態管理、tensor配置を一覧化する。Qwen3.5固有のattention/線形attention等は実configと固定ソースから特定する。
2. Candle候補版について、全演算のCPU FP32実行、重みロード、最終hidden state取得を小さな実証コードで確認する。不足箇所の実装範囲と保守コストを記録する。
3. tokenizer/chat templateの一致を実証する。tokenizer JSONの読み込みに加え、特殊token、正規化、generation prompt、thinking設定を確認する。
4. `cargo tree -e features`、build script、ネイティブリンク先を調べ、Windowsでのビルド結果を保存する。推論・tokenizerのC/C++依存が必要なら除去方法を検証する。

**完了条件:** 対応演算表、依存監査、実重み1件のforward結果、採用判断を保存する。Candleが要件を満たさない場合は、不足演算のRust実装と別のRust backendを比較して計画を再見積もりする。外部推論FFIへの置換をPure Rust達成として扱わない。別モデルへの変更は品質・校正をやり直す別判断とする。

### P2: Jeff互換処理をRustへ移す

- 提案package `runtime/rust`（`kaze_judge_jeff`）へ実装する。coreから重い推論依存を分離し、rootの既定依存を小さく保つ。
- `bundle`、`prompt`、`tokenize`、`backbone`、`readout`、`policy`を分け、段階ごとにP0のfixtureと比較する。
- 候補ID/順序、回答codeとtoken ID対応、prompt layout、chat template、左padding、入力上限での拒否を再現する。未対応template/configは明示的に拒否する。
- checkpoint固有readout、候補mask、temperature、softmaxを再現し、保留policyを同じ条件で適用する。近似実装や通常の語彙logitsへの置換を暗黙に行わない。
- Rust用bundle schemaを新設する。重み・tokenizer・readout・config・prompt・policy・runtime buildを識別し、SHA-256とファイル集合を検証する。旧Python manifestを同じschemaのまま別の意味に変えない。
- 資産を固定するRust CLIも提供する。重複JSON key、不正path、symlink、欠落/追加/変更ファイル、shape/dtype不一致を検査し、未知の構成を成功扱いにしない。

**完了条件:** P0の参照に対し、入力処理が完全一致し、非量子化実重みの分布が事前に定めた数値誤差基準を満たす。

### P3: 実行境界とKazeNhanhへ接続する

- Rust製worker executableと`NativeProcessProvider`（仮称）を追加する。既存Python用constructorは維持し、内部の起動・監視・wire処理を共通化する。
- 既存`kaze_judge.worker.v1`で表現できる範囲は再利用する。request ID照合、応答1 MiB上限、失敗code、期限超過後の結果破棄、直接子のkill/waitを維持する。
- モデルロード・hash検証を含めたdeadlineと、forward前token/forward予算を検査する。workerは子孫を起動しない。OS sandboxやRSS上限はこの境界の保証に含めない。
- KazeNhanhのCLIに明示backend選択を加え、同じreport/policyからRust版を呼べるようにする。失敗時の暗黙Python/cloud fallbackは設けない。

**完了条件:** Pythonが存在しない環境で、Rust CLIから実モデルのCompleted/Abstainedを得られる。適用外reportのskip、不正入力、期限超過、資産不一致、worker異常終了を確認し、元reportのevidence/risk/decisionを保持する。

### P4: 品質・性能と配布を受け入れる

- 移植評価用の固定集合と、対象ドメインのOCR/ASR評価集合を分ける。後者はdocument/origin/話者の分割を守り、参照未確認データを正解扱いにしない。
- 元Python、Rustの双方で、選択/保留一致、追加検出、追加誤警報を測る。候補順序の入替えによる影響も記録する。
- 同一Windows機、同一thread数・入力・重み・ビルド条件で、cold起動全体とload/hash/tokenize/forward別の時間、p50/p95、peak RSS、配布サイズを測る。warm値はモデル保持を実装した経路だけで測り、one-shot値と混同しない。
- 性能SLOはP0/P1の実測と呼出側予算から決め、最終評価前に固定する。Rust化だけで高速化を保証しない。
- Rust toolchain、Cargo.lock、依存feature、資産manifest、ライセンス一覧、配布・実行手順を固定する。通常CIはRustの契約/fixture試験、資産付き検証は明示ジョブ、Python参照再生成は開発用ジョブに分ける。

**完了条件:** 数値・品質・性能の受入記録と依存監査が揃い、Pythonも外部推論runtimeもないWindows環境で、ローカル資産だけによるend-to-end試験が通る。その後にRust backendを推奨経路にする。

### P5: 実測に基づく最適化

常駐Rust worker、queue・累計予算、量子化、追加evidence、LoRAを必要性の高い順に検討する。常駐化ではtimeout後のworker破棄/再起動、要求間の状態分離、再ロード時のhash検証を設計する。各最適化はP4の結果を基準に再評価する。

## 比較試験の受入ルール

| 対象 | 条件 |
| --- | --- |
| prompt bytes・token IDs・候補順・token数 | 全fixtureで完全一致 |
| FP32 hidden/logits | 層・段階ごとの最大絶対/相対誤差を記録し、差が最初に発生する箇所を特定 |
| 最終候補分布 | 仮目標は最大絶対誤差1e-4以下。P0/P1で妥当性を確認しP2の最終評価前に固定。変更理由は記録し、黙って緩和しない |
| 選択・保留 | 固定受入集合で完全一致。同点、min_probability/min_margin近傍の不一致は個別調査し、分布誤差だけで合格にしない |
| 入力境界 | 日本語、英語、結合文字、全半角、改行、特殊token相当文字列、2候補、上限候補数、token上限前後、候補順入替え |
| エラー・期限・予算 | 不正資産/出力を成功にしない。forward前の予算拒否、実行中timeout、kill/wait、後処理後の期限も確認 |
| 再現性 | 固定資産・versionで反復。fixture更新は自動上書きせず差分と原因を記録 |

確率分布の移植一致は日本語認識品質の証明とは別である。品質が不十分ならRust移植の完了と実運用採用を分けて判断する。

## 実装単位と着手順

1. P0: 参照資産/環境の整備、worker互換性修正、golden fixture exporter。
2. P1: 演算・依存監査と実重みのRust実証。ここで本移植の工数を再見積もりする。
3. P2a: Rust bundle検証・prompt/tokenize。
4. P2b: backbone/readout・数値比較。
5. P3: Rust worker・Provider・KazeNhanh CLI。
6. P4: 評価・配布検証・推奨経路切替。

P0の資産取得待ちでも依存監査やbundle設計は進められるが、モデル互換性の完了判定には実資産が必要。最大の工数変動要因はQwen3.5固有演算の不足と数値差の解消であり、現時点では日付付きの完了予定を確約しない。最初の到達点は「固定実資産から参照結果を保存し、Rustで同じ1件をforwardできること」とする。

## 調査根拠

2026-10-09に以下の一次資料を閲覧。main参照は選定の入口であり、実装開始時には採用revisionを固定する。

- [Jeff固定commitのmodel.py](https://raw.githubusercontent.com/firelex/jeff/3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0/src/jeff/model.py)：config、prompt、prepare、readout、predictを確認。実checkpointとの互換性は未確認。
- [Candle公式README](https://github.com/huggingface/candle)：Rust/CPU backendと任意のネイティブbackend。
- [Candleのmodel一覧](https://raw.githubusercontent.com/huggingface/candle/main/candle-transformers/src/models/mod.rs)：Qwen3.5対応調査の起点。
- [tokenizers公式repository](https://github.com/huggingface/tokenizers)と[Cargo.toml](https://raw.githubusercontent.com/huggingface/tokenizers/main/tokenizers/Cargo.toml)：Rust実装と依存・feature調査の起点。閲覧したmainは開発版であり、そのまま採用しない。
