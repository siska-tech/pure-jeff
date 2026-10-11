# P1: Rust backendの実現性と採用判断

2026-10-10。固定Jeff 0.8Bのtext-only実モデルで、Rustのtokenizeと24層forward/readoutを実証した。Candle CPUをP2実装の基盤として暫定採用する。これは開発用プロトタイプの判断であり、Provider・配布物の受入ではない。

## 固定した参照と依存

- Jeff source: `3720e7c66d73b79a6e90189f3d5b0d6ecf03ddc0`。
- checkpoint: `51552f39a943d62e8387c4ea5e17026a1408729f`。前日のbundleを変更せず使用。
- Candle core/nn: `c68b24997319b8d76e5a4e775dab197c7f26322a`、default featuresなし。
- tokenizers: 0.23.2、default featuresなし、`fancy-regex`のみ明示。
- `runtime/rust/Cargo.lock`を独立管理。root/coreへ推論依存を追加していない。

当該Candle revisionのモデル一覧にはQwen3.5がなく、gated deltaの実装も確認できなかった。Candleの既存Qwen3実装による代用は採用せず、CPU tensor/GEMM基盤として利用し、[backbone.rs](../runtime/rust/src/backbone.rs)に必要なtext経路を実装した。参照は固定依存のTransformers 5.17.0 `models/qwen3_5/modeling_qwen3_5.py`。同ファイルはApache-2.0として配布されている。

## 対応演算表

| 処理 | 参照の要点 | Rustプロトタイプ |
| --- | --- | --- |
| embedding | BF16資産をCPU FP32で使用 | token行を選択後FP32へ変換 |
| RMSNorm | zero-centered weight、eps=1e-6 | mean-squareと`1+weight`を再現 |
| MLP | SiLU(gate) × up → down | Candle GEMM/SiLU |
| full attention ×6層 | 8 Q heads、2 KV heads、head dim=256 | GQA展開、causal mask、softmax、出力gate |
| 位置表現 | theta=1e7、partial rotary=0.25、textの同一3軸位置 | 64次元を回転、残り192次元を保持。画像位置は非対応 |
| linear attention ×18層 | depthwise causal conv(kernel=4)、Q/K L2 norm | shifted tensorでconv、FP32でnorm |
| gated delta | decay、beta、状態更新、query scaling | Rustの逐次更新式。参照のchunk処理との数値差を計測 |
| gated RMSNorm | norm後にweightとSiLU(z) | 通常のzero-centered normとは別に実装 |
| 最終norm/hidden | 最終tokenのhidden state | 最終norm後の最終行を取得 |
| Jeff readout | checkpointの255×1024 weight | 独立safetensorsをFP32で乗算 |
| 候補mask/分布 | 非候補=-1e9、checkpoint temperature | 同じ処理順を使用 |
| 選択/保留 | min_probability/min_margin、同点保留 | manifest policyで結果を比較 |
| tokenize | 保存済みpromptをencode | tokenizers Rust版で公式token IDsと完全一致 |
| prompt/template | 公式prepareで作成 | 現在はgolden文字列を入力。P2で独立実装 |

configの主要次元、layer layout、activation、norm epsilon、rope条件をCLIで検査する。モデルの汎用対応、padding、batch>1、cache、画像、LoRA、量子化、別checkpointは未対応。

## 実モデル比較

CPU FP32、Python参照は1 thread、Rustは`RAYON_NUM_THREADS=1` / `CANDLE_NUM_THREADS=1`、release build。最終ソースで3ケースを実行し、各結果にソースhashを記録した。

| 人工ケース | tokens | hidden最大絶対誤差 | logits最大絶対誤差 | 候補分布最大絶対誤差 | 結果 |
| --- | --- | --- | --- | --- | --- |
| 元のOCR候補 | 128 | 2.480e-5 | 6.914e-6 | 2.384e-7 | original選択、一致 |
| 候補順の反転 | 128 | 2.050e-5 | 7.629e-6 | 6.333e-8 | original選択、一致 |
| ASR・Unicode・改行・3候補 | 206 | 1.955e-5 | 2.193e-5 | 5.066e-6 | 保留、一致 |

すべてtoken IDsは完全一致、分布はP1仮目標1e-4以内。公式とworker間の分布誤差は3件とも0.0。Rust readout単体の初回プローブでもlogits/分布誤差0.0を確認した。backbone全体は演算順や実装方式の差があるためbit一致ではない。各層の差分や相対誤差の監査はP2で拡充する。

結果の[機械可読記録](p1-validation.json)を保存。raw hidden/logits等はgitignore対象の`experiments/runs/p1-final-*.json`、比較元goldenは`tests/fixtures/jeff-golden`に保持する。観測された実行時間はhash検証・tokenize・weight読込込みの単発値で、OS cacheや同時処理の影響を除いていない。cold/warmのSLOや高速化を主張する指標にはしない。

## 依存とビルド監査

[監査JSON](rust-dependency-audit.json)はWindows targetの解決graph 137 package、各feature/license/build script hash、Cargo.lockと実行ファイルhash、PEの直接DLL importを記録する。[監査スクリプト](../runtime/audit_rust_dependencies.py)で再生成できる。

- CPU構成でMKL/Accelerate/CUDA/Metal、libtorch、ONNX Runtime、llama.cpp、Onigurumaは有効になっていない。
- `esaxx-rs`のbuild scriptにはC++分岐があるが、`cpp` featureは無効。`cc`/`cmake` packageは解決graphにない。default features無効化だけでなく、解決featureと当該build scriptを確認した。
- active build scriptsのnative compile/link分岐を確認した。Rust compilerのversion/feature probeと、無効なC++分岐を区別した。
- PEの直接importはWindows API/CRT系のみ。`VCRUNTIME140.dll`等の標準ランタイム依存はある。Python/PyTorch等の外部推論DLLはない。
- 実際のfull probeはRust executableがモデル資産を直接読み込んで実行する。Pythonはgolden生成・開発用検証と監査スクリプトに使う。

これは固定Windows buildの初期監査。既知crate名の除外や直接importだけで全推移的ソースのFFI不在を証明したとは扱わない。配布対象machineでの検証、依存/ソースのライセンス一覧とNOTICEの整備、再現buildはP4の残作業。

## 採用判断と次段階

固定0.8Bの初期text範囲ではCPU演算とhidden state取得に必要な処理を実装でき、実モデルの分布が仮目標内となった。P2はこのCandle CPU基盤と独立packageを継続する。別のFFI推論backendへ切り替える必要は現時点でない。

P2ではrequestからprompt/templateを独立生成し、Rust用bundleと厳格なloader、重複JSON key・必須component・ファイル集合検証、thread設定、token/forward予算を整備する。未知のconfigを拒否する境界と演算単位/各層の比較も強化する。その後P3でRust workerとProviderへ接続する。最大255候補や長文のfull Rust推論、汎用checkpoint対応、認識品質は今回の3ケースの成立から推定しない。
