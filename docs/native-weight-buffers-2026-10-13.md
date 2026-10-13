# Native：重み変換領域の再利用（#14）とFP32保持（#4）

2026-10-13。[性能同等の計画](benchmark-parity-plan.md)と[baseline](benchmark-parity-results-2026-10-13.md)の条件・seed・数値gateで、P1a（#4、FP32保持のopt-in）とP1b（#14、変換領域の再利用）を実装し、比較した。どちらも出力はbit単位で変わらない。

## 結論

- **P1b（変換先の共有buffer）を既定経路に採用した。** shortの4入力群がすべて同等になり、baselineで「遅い」だった128群は1.134→0.960になった。one-shotの中央値は2〜5%短く、peakの増加は1.6%以内、確率はbit一致した。
- **P1a（FP32保持）はopt-inとして採用した。** 128群はさらに0.899。一方で、loadが約0.6秒、メモリが約1.9 GiB増える。常駐して約6〜8回以上判断する用途で得になる。
- **全長の受入は、まだ確認していない。** shortは受入、longはbaselineで受入済みである。ただし、今回の変更後のlongは、request curveで8192 tokensを2回測っただけで、事前登録したlong runは行っていない。P6の最終受入で行う。
- **Wasm（`memory::Session`）とCLIには適用していない**（理由は下記）。

## 実装

- **P1b：共有buffer**（`src/backbone.rs`の`Weights`）
  - 各重みは、それを使う1つの演算（行列積、要素ごとの演算、copy）を行うclosureにだけ貸す。どれも新しいtensorを作るので、同時に使われる重みは常に1つである。
  - Nativeのforwardは、変換するすべての重みを1つのF32 bufferへ変換する。最大の重みより大きくはならず、`in_proj_qkv`の6144×1024（25 MB）が上限になる。
  - closureの結果がbufferとstorageを共有していたらerrorにする。これで、貸した重みがclosureの外へ残ることを実行時に検出する。
  - bufferはforwardごとに作って捨てる。要求の間で値が残ることはなく、Model全体のlockも要らない。
  - 最初の設計では、役割（`mlp.up_proj.weight`など）ごとにbufferを持っていた。速度は今回とほぼ同じだったが、全役割のbufferを同時に持つためone-shotのpeakが9%以上増え、既定経路の5%の退行条件に当たったので作り直した（下記）。
- **P1a：FP32保持**（`LoadOptions::retain_f32`、`src/weights.rs`の`Retained`）
  - loadの時点で、embeddingを除くtext tensor（319件、1,992,453,376 bytes）とreadout（1,044,480 bytes）をF32に変換して保持する。
  - 件数とbytesが固定仕様と違えばloadを失敗させる。embeddingは従来どおり、要求に必要な行だけを読む。
  - 保持したtensorは共有bufferを通らず、上書きされない。
  - 失敗したとき（deadlineを含む）は、それまでに変換した分を解放してerrorを返す。
- **`WeightSource`への追加**：`convertible_shape`と`load_f32_into`。どちらも既定実装を持つので、既存の実装はそのままbuildできる。
- **非互換**：`LoadOptions`にpublic fieldが増えた。struct literalで作っているcodeには`..LoadOptions::default()`が要る（CHANGELOGの「Breaking」）。

## bit一致と数値gate

| 検査 | 結果 |
| --- | --- |
| 最終hidden（`weights_check`）。7入力（128〜874 tokens）、4経路（変換のみ／共有buffer／保持／保持＋共有buffer）、正順と逆順 | 42回すべてbit一致 |
| CLI worker（既定経路）と公式golden 7件 | 判断・tokens数が一致。誤差は変更前と同じ（最大5.066e-6） |
| crates.io版Candleの利用者build（`tools/check_package.py`） | golden 7件が合格（最大3.457e-6、0.1.0／0.1.1と同じ）。保持あり・なしの確率がbit一致 |
| benchmarkの全判断（short 2 run、one-shot、request curve 2 run） | 数値gateの違反なし。同じ系統・同じ経路の反復はbit一致。request curveでは、main（0.1.1相当）／共有buffer／保持の確率が全件bit一致 |
| 単体試験 | 共有bufferの値・再利用・別shape・拡張、結果がbufferを共有したときの拒否、保持tensorの非上書き、保持失敗時のerror |

## short（6 block、各case・系統24観測、API境界）

| 構成 | 128 | 256 | 384 | 512 | 受入 |
| --- | ---: | ---: | ---: | ---: | --- |
| baseline（0.1.1相当） | 1.134（遅い） | 0.981 | 0.907 | 0.860 | 不受入 |
| 役割別buffer（`edded27`、不採用） | 0.960 | 0.881 | 0.839 | 0.819 | 受入 |
| **共有buffer（`a91706d`、既定）** | **0.960**（0.943〜0.976） | 0.907 | 0.847 | 0.832 | **受入** |
| FP32保持（`edded27`、opt-in） | 0.899（0.890〜0.908） | 0.839 | 0.809 | 0.796 | 受入 |

値はNative／公式Jeffの点推定（片側95%区間）。128 tokensのNativeの中央値は、1.685秒（baseline）→1.427秒（共有buffer）→1.359秒（保持）。保持のrunは`edded27`のbuildで測った。保持したtensorは役割別bufferも共有bufferも通らないので、保持経路の動作は`a91706d`でも同じである。`a91706d`のrequest curveでも、warmは1.355秒と一致した。

## one-shot（既定のCLI worker、10 block、baselineとの比較）

| 構成 | 128：時間／peak | 512：時間／peak | 確率 | 判定 |
| --- | --- | --- | --- | --- |
| 役割別buffer | 0.959／**1.093** | 0.983／**1.098** | bit一致 | peakが5%超の退行（不採用） |
| **共有buffer** | 0.947／1.010 | 0.979／1.016 | bit一致 | 退行なし |

## 要求数別の総時間とメモリ（`bench/request_curve.py`、`a91706d`）

1つのprocessでloadし、同じ要求をN回判断した。総時間は、process起動からN回目の判断が終わるまで。

| 128 tokens | 起動 | 初回 | warm | 1回 | 10回 | 100回 | peak WS | Private | page fault |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main（0.1.1相当） | 1.86 | 2.04 | 1.697 | 3.9 | 19.3 | 171.8 | 1.02 GiB | 0.14 GiB | 66.8M |
| 共有buffer | 1.88 | 1.79 | 1.422 | 3.7 | 16.6 | 144.5 | 1.03 GiB | 0.17 GiB | 18.8M |
| FP32保持 | 2.45 | 1.37 | 1.355 | 3.8 | 16.0 | 137.8 | 2.87 GiB | 1.94 GiB | 18.7M |

| 512 tokens | 起動 | warm | 100回 | peak WS | page fault |
| --- | ---: | ---: | ---: | ---: | ---: |
| main | 1.89 | 5.537 | 555.9 | 1.06 GiB | 137.6M |
| 共有buffer | 1.85 | 5.259 | 527.2 | 1.08 GiB | 89.5M |
| FP32保持 | 2.46 | 5.151 | 517.4 | 2.92 GiB | 89.3M |

| 8192 tokens（各2回） | warm | peak WS | Private |
| --- | ---: | ---: | ---: |
| main | 124.25 | 7.79 GiB | 6.88 GiB |
| 共有buffer | 124.30 | 7.82 GiB | 6.90 GiB |
| FP32保持 | 125.15 | 9.65 GiB | 8.74 GiB |

- **損益分岐**：FP32保持のload増分を、1要求あたりの短縮で割ると、共有bufferに対して128 tokensで8.4要求、512 tokensで5.7要求、mainに対して1.5〜1.7要求になる。
- **page fault**：共有bufferで128 tokensは3.6分の1に減った。変換時間のうち、新しく確保したmemoryへの最初の書込みにかかっていた分がなくなった。
- **長い入力**：8192 tokensでは時間がattentionなどに支配され、どの構成もほぼ同じ。保持は1.9 GiB多く、公式Jeff（5.2 GiB）との差が広がる（#17）。
- **pagingの確認**：上のpage fault数はsoft fault（新しいpageへの最初の書込みなど）を含み、diskからの読込みとは区別していない。最大のPrivate bytes（保持、8192 tokensで8.74 GiB）は、この機械のOSから見える物理メモリ31.6 GiBの範囲に収まる。

## 適用しないもの

- **Wasm**：browserのlinear memoryは縮まないので、同じ設計でpeakがどうなるかは別に確かめる必要がある。`memory::Session`は従来の経路のまま（`reuse_buffers: false`）にした。Webデモengineの出力も変わらない。
- **CLI**：`jeff worker`／`decide-process`は1要求1 processなので、保持すると増分のloadとメモリだけが残る。そのためCLIからは選べないようにした。常駐で使う場合は、ライブラリの`LoadOptions::retain_f32`を使う。共有bufferはCLIの既定経路でも有効である（one-shotの結果を参照）。

## 条件

測定機、OS、公式Jeff、Candleは[baseline](benchmark-parity-results-2026-10-13.md)と同じ。各runの`preregistration.json`に、commit（`edded27`／`a91706d`）、exeとbundleのhash、環境を記録した。旧runの合否と閾値は変更していない。

## 証跡

[research/native-weight-buffers-2026-10-13/](research/native-weight-buffers-2026-10-13)：

- short（共有buffer、役割別buffer、保持）
- one-shot（共有buffer、役割別buffer）と、baselineとの比較
- request curve（`a91706d`と`edded27`）
- `weights_check`の結果
- golden照合
- driverのlog
