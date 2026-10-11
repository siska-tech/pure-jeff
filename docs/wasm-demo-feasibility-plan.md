# Wasm優先の単体デモ計画

2026-10-11。ユーザーの「可能ならWasmで動くデモ」という希望により、初回デモの第一候補をブラウザ内推論へ変更する。[単体デモ計画](standalone-demo-release-plan.md)のWindowsコンソール案は代替案として保持する。**現時点ではJeffのWasmビルド・実forward・数値一致・ブラウザ性能は未検証。** 今回は成立性調査と計画更新まで。

## 目指す体験

静的Webページを開き、モデル取得量を確認して読み込み、文章と候補を入力して実行する。RustをWasmへコンパイルした推論をWeb Worker内で行い、候補分布と選択／保留を表示する。推論サーバー、ローカルのNative実行ファイル、Pythonは不要。UIとブラウザAPI接続にはJavaScript／TypeScriptを使い、モデル演算と判断処理をRustに置く。

初期検証対象はWindows上のデスクトップChrome／Edgeの固定version。Firefox、Safari、モバイルは後続で別検証する。CPU Wasmを基本とし、WebGPUを成立の前提にしない。HTTPSでの静的配信を想定し、`file://`での起動を保証しない。静的なファイル配信と推論サーバーは区別する。

モデル読込・検証・推論の状態、経過時間、取消、エラー、JSON保存を用意する。入力文章は推論のためにサーバーへ送信しない。モデルの初回取得は通信を伴う。キャッシュ後の完全オフライン動作は、アプリ資産とモデルの保存・更新・削除・容量不足を検証してから対応を表明する。

## 成立性の根拠と未解決点

[Candle公式のquant-qwen3例](https://github.com/huggingface/candle/blob/main/candle-wasm-examples/quant-qwen3/README.md)にはQwen3-0.6BをRust/Wasm/SIMDでブラウザ実行する実装がある。これはWasm経路の参考であり、別モデルであるJeff-Qwen3.5-0.8Bの互換性・速度・量子化品質を保証しない。現在固定しているCandle revisionで利用できる機能は、W0で個別確認する。参考例の速度をJeffへ転用しない。

| 現行資産 | ブラウザ向けの作業 |
| --- | --- |
| `runtime/rust/src/backbone.rs` のGated DeltaNet等 | 数式を維持し、tensor演算のWasm対応・精度を確認 |
| `MmapedSafetensors`依存のbackbone／readout | byte buffer／必要tensor読込を使う重みアクセス境界を追加 |
| bundleのファイル・path・hash検証 | 固定manifestと取得済みbytesのhash・shape・dtype検証へ適応 |
| tokenizerのファイル読込 | bytesから初期化。tokenizers／fancy-regex等の依存をWasm buildで検証 |
| process／環境変数／thread pool | Web WorkerとWasm用設定に分離。まずsingle-threadで実証 |
| `std::time::Instant`を使うLimits／deadline | 対象上の利用可否を確認。互換clock境界またはWasm adapterを設計し、Native APIを保全 |
| NativeProcessProviderによるkill/wait | UI側の取消／期限監視からWorkerを破棄し、遅延応答をrequest IDで破棄 |

現在の環境には`wasm32-unknown-unknown` targetがあるが、targetの存在は依存やruntimeのビルド成功を意味しない。WASIで動くこともブラウザで動くことの代用にしない。

## 最大のリスク：メモリと配信量

固定checkpointの`model.safetensors`は1,706,027,688 bytes。Nativeの常駐実験ではtext重みだけでFP32 payloadが3,009,572,096 bytesだった。元ファイルと全FP32重みを同じlinear memoryに同時保持する単純な設計では、これだけで4 GiBを超える。これは設計上の容量計算であり、Wasmの実測peakではない。逐次読込方式の現在のNative peakとも区別する。

通常のwasm32 linear memoryの上限は4 GiBで、実際の確保はブラウザ・端末にも制約される。[MDN Memory constructor](https://developer.mozilla.org/en-US/docs/WebAssembly/Reference/JavaScript_interface/Memory/Memory)。JS側の取得buffer、Wasmへの転送・コピー、一時tensor、tokenizerも含めて観測する。linear memoryの確保量を使用中heapやブラウザ全体のpeakと呼ばない。Memory64は初回の前提にしない。

まず元checkpointのままFP32演算を実証する。全FP32常駐を必須にせず、必要なtensorだけを展開し、コピーと寿命を管理する。収まらない場合は同一重みのtext-only抽出／shard化を検討し、tensor名・値・dtypeの一致と元checkpointへの来歴を検証する。それでも成立しなければ量子化を別の判断事項にする。量子化は容量や誤差の別gateが必要で、既存数値閾値を黙って緩めない。

## 実装順とGo／No-go

| 段階 | 実施内容 | 次へ進む条件 |
| --- | --- | --- |
| W0 コンパイルと小型演算 | 別crate `runtime/wasm/` 案。固定Candle・tokenizer・core依存をauditし、tokenize、GEMM、norm、Gated DeltaNetの小型fixtureをブラウザで動かす | 正式ブラウザtargetでbuild成功。prompt/token IDsが一致し、小型演算が既存許容誤差内。失敗箇所と修正範囲を保存 |
| W1 実モデル1件 | Web Workerで固定資産を検証し、短い人工2候補を全層forward、Decision Head、temperature、policyまで実行 | 同一checkpoint・prompt・tokens・候補順・判断一致、確率差≤1e-4。メモリ不足・tab crashなし。取消後に再実行できる |
| W2 入力範囲と動作安定性 | 初期128／256 tokensから512まで段階的に拡張。2～8候補、反復、順序変更、破損、失敗、取消、再読込 | 対応範囲の全数値gate合格、反復でメモリが増え続けない。対象browserごとに確認 |
| W3 Webデモ | `apps/web-demo/` 案。入力、人工sample、進捗、取消、結果、JSON保存、明示的モデル取得とcache管理 | 利用者が開発環境なしで操作可能。UIが推論で停止せず、保存・通信の説明と実挙動が一致 |
| W4 公開候補 | 静的配信設定、モデル／依存の配布条件、browser別計測、数値回帰、README、version/hash、release notes | 新規browser profileで読込から実推論まで成功。最終配信物のhashと検証対象が一致 |

**W0〜W3は2026-10-11に通過した（[W0結果](wasm-w0-results.md)、[W1結果](wasm-w1-results.md)、[W2結果](wasm-w2-results.md)、[W3結果](web-demo-w3-results.md)）。対応範囲は512 tokensまで。次の作業はW4（公開候補）で、配布条件の確認を伴う。W1の成功前にWeb UI全体や大規模な最適化を作り込まない。** W0/W1で失敗したら、compile、未対応演算、メモリ、実行時間、数値不一致を分けて報告する。対応範囲を絞った再試作の条件を決め、同じ原因の測定を繰り返さない。

FP32・同一checkpointで成立すればCPU Wasm版を初回リリースへ進める。成立しない場合は、容量対策・量子化の別計画、または既存Native版への切替を比較して決める。WebページがNativeサーバーを呼ぶ構成を「Wasm推論が成立した」とは扱わない。

## Worker、SIMD、thread、契約

UIのmain threadは入力・進捗・取消を受け付ける。推論は専用Worker内に置く。[Worker.terminate()](https://developer.mozilla.org/en-US/docs/Web/API/Worker/terminate)による取消はWorker内の後処理完了を待たないため、途中cacheを確定済みとして保存しない。取消後はWorkerと推論状態を作り直す。メモリの即時OS返却は保証せず、反復時の挙動を観測する。

最初はsingle-threadとし、SIMDの有無をfeature検出する。multithreadはsingle-threadの成立後に評価する。SharedArrayBufferを使う場合はcross-origin isolationと適切なCOOP／COEP等の配信設定が必要になる。[MDN crossOriginIsolated](https://developer.mozilla.org/en-US/docs/Web/API/Window/crossOriginIsolated)。モデル配信元のCORS／埋込方針も含めて実際のhostで検証する。

ブラウザでは非同期実行になる。公開Rust APIをブラウザ都合で破壊せず、共有できるrequest検証・prompt・policy・結果型を再利用し、非同期bridgeを分離する。既存Attemptのschemaと意味、候補順、保留と失敗の区別を維持する。Worker間の追加metadataは別wrapperに置く。Nativeの既存7件回帰は保全し、Wasmは初回の対応範囲内のfixtureを受入対象にする。8192 tokens等を試していない状態で全runtime互換を宣言しない。

## 評価と配布

- 初回download、cache読込、Wasm初期化、tokenize、forward、結果表示を区別する。全体E2Eと取得bytes、linear memory確保量、観測可能ならbrowser processメモリを記録する。
- W1の単発値は成立性確認。正式な性能判断はW2以降、最終構成で128／256／512など受け入れる長さ・候補数ごとに3 session×10回、中央値・p95・n・失敗を保存する。対応できない長さを成功cellに含めない。
- browser/version、OS、CPU/RAM、SIMD/thread設定、cache状態、電源、DevToolsの状態を固定・記録する。NativeのWindows Peak Working Setとの比較は測定scopeを明記する。
- 同じWorker内でモデルを再利用する反復と、Worker再作成・ページ再読込・初回取得を分ける。Native旧案の120秒期限や8秒候補をWasmの達成値にしない。pilotから実用範囲と期限を提案し、別runで確認する。
- 初回取得前に容量と配布元を表示し、利用者の操作で取得する。hash失敗・中断・容量不足・cache消去・version更新を扱う。streamingによるhash検証を含め、全bufferの不要な複製を避ける設計を実証する。
- 公開には自プロジェクトのlicense確定、モデル／派生資産／依存NOTICE、配信容量と費用、必要headerのhost対応を確認する。公開先へのuploadは完成した候補と配布条件を確認してから行う。

TractはWasmデモの前提にしない。まず現在のNative/Candle実装から演算を再利用する。これが難しい場合だけTractの対象graphとWasm対応を別候補として比較する。実OCRのN-best待ちは従来どおり品質評価側の課題とし、人工・手入力候補のWebデモとは独立して進める。
