# KazeJudge 単体デモ・初回リリース計画

> 2026-10-11方針更新：ユーザーの希望を受け、[Wasmデモ成立性計画](wasm-demo-feasibility-plan.md)を先行する。第一候補はブラウザ内のRust/Wasm推論とし、コンパイル・実モデル1件・数値とメモリのgateを通過してからWeb版を完成させる。本書のWindowsコンソール／portable案はWasmが成立しない場合の代替案として保持する。以下のUI方式・工程は旧第一案であり、Wasm計画と競合する場合は更新後の計画を優先する。

作成日：2026-10-11。対象：Windows x86_64 CPUで動く公開プレビュー版。計画時の基準commit：`a18a9ba`。本書は実装・公開の完了報告ではない。

## 1. リリースの目的と完成像

利用者がKazeNhanhや開発環境を用意せず、配布ZIPを展開してKazeJudgeを起動し、文章と候補を入力して、実モデルによる候補分布と選択／保留を確認できる状態を作る。

初回は**対話式コンソールとCLIを備えたNative Rustデモ**に集中する。Python、Cargo、GPU、OCRエンジンは通常実行に不要とする。モデルの配布条件を確認したうえでモデル同梱ZIPを第一案とし、準備後の推論はオフラインで完結させる。

初回の価値は「ローカル候補判断を実際に試せること」。日本語OCR/ASRの品質改善、校正済み正解確率、Tractの高速化を完成条件に含めない。プレビュー表記でも、数値整合・入力境界・停止・配布条件・clean host確認は必須とする。

利用の流れ：

1. ZIPを展開し、`KazeJudge.exe`を起動する。
2. 「サンプル」「自分の候補」「環境確認」から選ぶ。
3. 自分の候補ではOCR／ASRを選び、原文と代替候補を入力する。原文を候補の先頭に含め、実行前に一覧を確認できる。
4. 実行中は処理中の表示・経過時間・中止方法を示す。
5. 候補内の確率、選択または保留、入力tokens、所要時間を表示する。保存は明示操作で行う。
6. コンソールを閉じず、別の入力を試すか終了する。

単体デモで用いる候補は手入力または明示した人工サンプルでよい。実OCRのN-bestがないことは、このリリースの阻害要因にしない。

## 2. 現状と不足

| 項目 | 確認済みの資産 | デモに向けた不足 |
| --- | --- | --- |
| 契約 | coreのDecisionRequest／Attempt、候補順・分布・選択／保留検証 | 利用者向け入力と結果表示 |
| 実推論 | Rust Jeff worker、NativeProcessProvider、人工7件の数値照合 | デモからの接続、取消操作と終了処理 |
| CLI | `jeff prepare/decide-process` | manifestや予算を毎回指定しない入口、終了codeの整理 |
| ローカル配布 | p4c package、Rust verifier、再配置smoke・破損拒否 | 完成ZIP、外部DLL整理、clean host、正式な配布条件 |
| 性能 | P4の単発worker測定と別系統の常駐wrapper比較 | 最終デモbinaryでのE2E測定 |
| 実品質 | kzn-datasetの確認済みdevelopment 3件を取込済み | 実N-best・転記方針の整合・十分な評価集合 |

既存のroot `examples/jeff_decide.rs` はPython版であり、単体Rustデモの入口として案内しない。Rust workerを新しいデモから利用する。既存の実験用最適化wrapperも、そのまま製品binaryに置き換えない。

根拠：[Rust runtime](../runtime/rust/README.md)、[P4配布・性能記録](p4-acceptance.md)、[常駐wrapper比較](onnx-tract-cache-fixed-lengths.md)、[実OCR取込](onnx-tract-kzn-ocr-intake.md)。

## 3. 初回スコープ

| 採用する範囲 | 初回から外す範囲 |
| --- | --- |
| Windows x86_64、CPU、batch=1 | macOS／Linux／GPU |
| 固定Jeff checkpoint、Native Rust | Tract切替、量子化、独自カーネルの製品化 |
| 対話式コンソール、JSON入力CLI、JSON保存 | Web UI、GUI framework、HTTP server |
| 手入力候補、人工サンプル | 画像／音声読込、OCR／ASR実行、自動N-best生成 |
| 1要求ごとに監視付きworkerを起動 | モデル常駐、同時要求、queue、batch |
| 候補選択と保留の体験 | 自動訂正、recognition risk、品質改善の主張 |

モデル常駐は後続候補。初回は既存の期限監視境界を利用し、毎回の起動・モデル読込を含む待ち時間をそのまま示す。初回デモの標準backendという判断は、production推奨やTractとの性能優位の認定を意味しない。

## 4. 実装設計

### 配置と契約

独立crate `apps/demo/` を追加する案とする。coreの`process` featureとNativeProcessProviderを利用し、同梱したRust `jeff.exe` を呼ぶ。KazeNhanh adapterへの依存は追加しない。

公開API・Attempt schema・Decision Report契約は維持する。経過時間やデモversionなどの追加情報は表示用または別metadataに置き、既存Attemptへ独自fieldを挿入しない。JSON保存では完全なAttemptを保持する。表示時に候補順を並べ替えない。

モデル・worker・設定の基準pathは実行ファイル所在とし、cwdに依存しない。既存workerのsource/build fingerprintを維持できる構成を優先する。worker変更が必要になった場合は、新規binary・bundleとして全数値回帰を行い、旧資産を上書きしない。

### 利用者向けCLI案

以下は新設予定であり、現時点で実行可能なコマンドではない。

```text
KazeJudge.exe
KazeJudge.exe demo --sample ocr-basic
KazeJudge.exe decide --request request.json --output result.json
KazeJudge.exe doctor
KazeJudge.exe --help
KazeJudge.exe --version
```

`doctor`は同梱資産・hash・実行環境を検査し、修復手順を表示する。推論を伴う確認は別の明示操作とする。`--output`省略時は保存しない。既存ファイルの上書きは拒否し、対話モードでは別名を選べるようにする。

機械向けJSON出力と人向け進捗を混ぜない。CLIはstdoutを結果、stderrを進捗・診断に使う。選択・保留は正常終了。失敗・取消・入力拒否を非zero終了へ対応させ、具体的なcode表をD1で固定する。既存workerでexit0でもAttemptがfailedになり得るため、デモはAttemptの内容を判定する。

### デモ固有の入力・実行条件

- 候補数は2～8、原文を含める。候補IDはデモ側で一意に生成し、同一文字列の重複候補は入力時に知らせる。
- token上限はprompt・候補を含む512、入力JSONは64 KiB、1要求1 forward、同時実行は1件。超過は切り詰めず拒否する。coreの255候補／runtimeの8192 token対応は変更しない。
- 固定checkpointと既存promptを使用。デモの呼出しは利用者の明示操作とし、自動routingの実証として扱わない。
- 初期policyは既存のmin_probability=0.7／min_margin=0.1、1 threadを基準にする。未校正のデモ設定であることを表示する。temperatureは固定bundleの値を用いる。
- 1要求の期限は120秒を初期設定案とし、D3で利用者向け仕様として確定する。これは応答時間SLOではない。
- 取消・期限超過・親終了時にworkerを停止・回収する。NativeProcessProviderに利用者取消が不足する場合は、既存APIを壊さない追加インターフェースを最小限で設計する。強制終了時の残存child対策はWindows Job Object等を検討し、実証した範囲を記載する。
- 標準ログへ入力文章を永続保存しない。保存要求時のみ結果を書き出し、要求・応答の一時ファイルも終了時に片付ける。

「候補内の確率であり、認識の正解率ではない」を結果画面に短く明記する。保留と実行失敗は別の表示にする。自由文の質問や一般チャットは受け付けない。

## 5. 配布物

初回はインストーラ不要のportable ZIPを第一案とする。

```text
KazeJudge-demo-windows-x64/
  KazeJudge.exe
  runtime/jeff.exe
  verify.exe
  checkpoint/...
  bundle.json
  samples/...
  README-ja.md
  LICENSE
  THIRD_PARTY_NOTICES.txt
  licenses/...
  package.json
```

最終配置は既存verifierと相対bundleの契約に合わせてD2で固定する。package inventoryはimmutableな配布payloadを対象にし、利用者が保存した結果を改変検知対象に混ぜない。成果物にはversion・commit・toolchain・target・build fingerprint・モデルrevision・全payload hashを記録する。

既存p4cのpayloadは約1.74 GB（ZIP圧縮前）。これは容量の参考値であり、新デモの配布容量・必要RAMではない。最終ZIPの容量、展開容量、実測メモリと必要ディスク余裕をD3で記載する。

自プロジェクトのライセンス選択は権利者の決定が必要。未指定のまま公開しない。モデル・base model・依存・CRTの配布条件とNOTICEを最終確認する。モデル同梱が成立しない場合は、実行ファイルと固定モデル資産の導入手順を分離する案へ切り替える。その場合も、初回準備が完了して実モデルで動くことを受入条件にし、模型の出力で代用しない。

推論時の自動downloadは行わない。Windows DLL／CRT不足への対応は、許可された同梱または明示した前提条件で解決する。管理者権限や開発環境を暗黙に要求しない。署名を導入しない場合は未署名と明記し、配布元とSHA-256を提示する。OS警告が出ないことは約束せず、セキュリティ機能の無効化を起動手順にしない。

## 6. 段階別ロードマップ

| 段階 | 作業・成果物 | 完了条件 | 不合格時の扱い |
| --- | --- | --- | --- |
| D0 リリース仕様固定 | 対話flow、CLI仕様、対応環境、配布形態、既存資産index、license未決一覧 | 初回スコープと受入表を固定。権利者の決定事項を明確化 | UI方式を拡張せず、未決事項を残作業として管理 |
| D1 単体デモ実装 | apps/demo、対話入力、sample、Native接続、結果表示・保存、取消、doctor | KazeNhanh/Pythonなしで実モデルの選択／保留を表示。入力・失敗・取消を区別 | 数値不一致や残存workerは修正完了まで先へ進まない |
| D2 パッケージ化 | Rust release build、相対配置、verifier更新、ZIP、license/NOTICE | 別path・別cwdから起動。欠落／改変を拒否。配布条件を解消 | clean host向け候補にしない。必要ならモデル分離案へ |
| D3 リリース候補検証 | 数値回帰、製品E2E計測、clean host試験、README、既知制約 | 下記の必須gateが全て合格し、最終binary/hashで記録 | 入力範囲や環境条件の変更は別RCを作って再検証 |
| D4 公開準備・リリース | release notes、version/tag案、ZIP/checksum、検証報告 | 同じ成果物を第三者が手順だけで起動できる。公開内容と配布物が一致 | 公開を保留。修正後に新RCを作成 |

クリティカルパスは **D0 → D1 → D2 → D3 → D4**。license選定とclean host確保はD0から準備する。工数・日付はD1の停止制御方式と検証環境が確定してから見積もり、未測定のまま公開日を約束しない。

今回の依頼は計画立案まで。実装着手後も外部への公開・配布は、完成したZIPとrelease notesを確認できる段階で別途行う。

## 7. リリース判定基準

### 必須gate

| 分野 | 判定条件 |
| --- | --- |
| 単体性 | KazeNhanh checkout、Python、Rust toolchain、外部推論runtimeのないWindowsで実モデルsampleが成功。PATH隔離だけを代用にしない |
| 数値・契約 | 既存人工7件のprompt・token IDs・候補順・判断が一致、確率誤差≤既存1e-4。既存の厳しい個別条件も緩めない。デモの入力変換・JSON保存がAttempt契約を保持 |
| 表示 | 選択と保留の両方を実モデルで確認。人工例の出典を表示。確率の意味と未校正policyを明記 |
| 境界 | 不正JSON、2候補未満、重複ID、demo上限超過、モデル不足・破損・fingerprint不一致が明確に失敗。入力を黙って変更しない |
| 停止 | 初期化／forward中の取消・期限超過・親終了を検証し、残存workerと期限後結果の採用がない |
| 配布 | ZIPの新規展開、空白・日本語path、別cwd、標準ユーザー、オフライン推論を検証。必要DLL/CRTを記載 |
| 保全 | 既存core/API回帰とNative参照試験に合格。旧測定・旧bundleを保持。変更した資産の影響を追跡できる |
| 権利・来歴 | 自プロジェクトの配布ライセンス確定、モデル・依存NOTICE整備、配布対象とhash索引が一致 |
| 再現性 | 最終RCのversion/hash、clean host環境、実行手順、検証結果を保存。通常CIと実モデル試験を区別し、必要なCI成功を確認 |

数値回帰の7件はruntime回帰であり、demo CLIが8192 tokensや255候補を受け付けることを意味しない。上限外の既存能力はruntimeの回帰試験で保全する。

### 性能・体験の評価

最終デモの入力から結果表示／JSON書出し完了までを測る。過去のprepared-computeや異なるwrapperの値を製品E2Eに流用しない。

| 測定 | 計画 |
| --- | --- |
| 構成 | 最終RC Native、固定checkpoint/policy、1 thread。OS、CPU、RAM、電源、背景負荷を記録 |
| 入力 | token化済み総長128／256／512を目安に固定人工入力を作成し、2候補／8候補を別cellにする。元文章・候補・実tokensを保存 |
| 反復 | 各cell n=30、3 session×10回。各sessionで入力順を事前固定し、失敗・timeoutも残す |
| 起動条件 | デモ初回と2回目以降を区別。workerは毎回新規起動。再起動後の初回は別に5回記録し、厳密なdisk-coldとは呼ばない |
| 指標 | E2E、可能な計測区間、親／child別Peak Working Set、失敗率、timeout数、中央値・p95・n。計測できない内部区間を推定で埋めない |
| 統計 | nearest-rankを明示。n=30のp95は29番目。標本数が少ないcold 5回は全値も提示し、安定したtail保証としない |
| 体験 | 処理中表示の更新間隔、取消からchild回収までの時間。初期化／forward中を含めて検証 |

事前の体験予算案は「処理中表示を概ね1秒ごと」「取消から回収まで2秒以内」「120秒を越えた要求はtimeout扱い」。達成済みの値ではなく、D1/D3で検証する設計目標とする。推論速度については8秒などの既存候補を転用しない。まずpilotを行い、対象機・入力範囲ごとのデモ用E2E SLOを提案・固定してから、別runで確認する。正式計測後に閾値だけを引き上げて合格にしない。

公開プレビューは高速化倍率の達成を条件にしないが、対応すると表示した入力・環境で固定した期限と体験条件を満たし、実測の待ち時間を利用者へ示す。満たせなければ改善または対応範囲の再定義を行い、新しいRCで再検証する。

## 8. リスクと代替案

| リスク | 対応 |
| --- | --- |
| 長文で待ち時間が増える | 初回512 token上限。切捨てず拒否。改善が必要なら入力範囲の見直しを先に検証 |
| 毎回のモデルloadが体験を損なう | 初回は待ち時間を表示。常駐化は停止・状態管理・メモリを含む後続変更として別受入 |
| 高速化wrapperの数値・build条件を持ち込む | 初回は既存Native参照経路。最適化は新binaryと回帰証跡を揃えてから採用 |
| DLL／CRTやCPU命令条件で他PCで起動しない | clean hostと配布target/flagsの監査。測定したCPUだけを普遍的要件にしない |
| ライセンスまたはモデル再配布が未確定 | D0から解消。未解消なら公開停止または明示的なモデル別導入方式へ |
| 対話consoleの日本語入力が扱いにくい | UTF-8／日本語pathを試験し、JSONファイル入力を併設。GUI化は次版で判断 |
| 手入力デモを実OCR品質評価と誤解される | サンプルは人工と表示。kzn-datasetの正解を候補へ注入しない。品質評価は別報告 |

## 9. 既存計画との優先順位

最優先は単体デモのD0～D4とする。ONNX＋Tractの既存成果・失敗記録・数値基準は保持するが、追加の比較campaign、量子化、upstream提案はデモの必須作業から外す。今後の最適化はデモのE2E測定で確認した課題から選ぶ。

KazeNhanh接続と実OCR/ASR品質評価は後続。確認済みOCR development 3件の取込成果を維持し、実N-best・評価方針・独立評価集合が揃った時点で再開する。公開デモの完成と認識品質改善の判定を独立させる。

実装開始時の最初の作業は、D0のCLI／対話仕様と取消方式を固定し、D1の独立demo crateから既存Rust workerを1件呼んで実結果を表示する縦通しを作ること。
