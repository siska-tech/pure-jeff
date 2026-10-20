# Native：行列積のk分割をcrate側で固定する（#18、案A）

2026-10-20。[gemmのkernel parameterの調査](native-gemm-kernel-params-2026-10-20.md)で選んだ案Aを実装した。

## 変更

- **`backbone::matmul`**：kが512を超え、かつ2行以上の行列積が対象である。
  - 対象：forwardのlinearすべてと、attentionのvalue積（attentionのscoresはk＝256なので対象外）。
  - kを`ceil(k / 512)`個の均等な区切りに分け、gemmに区切りごとに直接渡す。
    - 1つ目の区切りで出力を書く。2つ目以降は出力に足し込む（`read_dst`）。
    - 区切りの決め方は、gemm自身がkc＝512の時に使う規則と同じである。
  - 区切りは512以下なので、gemmがさらに区切ることはない。和の順序はhostのcacheに依存しない。
  - gemmの呼び方（行優先の出力、`alpha`／`beta`、Candleと同じthread数）は、CandleのCPU matmulに合わせた。
  - 結果は、「Candleのmatmulで区切りごとに計算し、`+`で順に足したもの」とbit一致する（試験で確認）。
- **対象外**：1行の積（readout、m＝1のgemv）。cacheに依存しないので、Candleに任せる。
- **依存関係**：`gemm = "=0.19.0"`を直接の依存に加えた。Candleが既に使っている版・featureと同じで、新しいcrateは増えない。ライセンス監査は合格した。
- **`unsafe`**：`gemm::gemm`の呼び出し1か所である。
  - 呼ぶ前に、両operandのlayout（offset・stride・行数・列数）から最大のindexを求め、bufferの長さ未満であることを確かめる。満たさなければErrorを返す。
  - 書き込み先は、関数内で確保したbufferだけである。
- **試験**：
  - `matmul_splits_k_into_equal_chunks_of_at_most_512`：区切りの大きさ（513→257＋256、874→437＋437、1024→512×2、2048→512×4、3584→512×7）を確かめる。
  - あわせて、linearの形（(n, k)の転置）とattentionの形（8 head、連続とstrided）で、`matmul`がCandleでの分割計算とbit一致することを確かめる。
- 公開API、数値gate、timeout・killの契約は変えていない。`src`と`Cargo.toml`の変更なので、runtime build hashが変わる。bundleは再lockが必要である。

## 経緯：Candle上で分割した版（`19b0c85`）

最初の実装は、`unsafe`を使わず、Candleのmatmulを区切りごとに呼んで`+`で足すものだった。

- **bit**：直接呼び出しの版と同じ。i7-1360PのP-core／E-core起動で、39件すべてがbit一致した。
- **速度**：P-coreに固定したi7-1360Pで、mainに比べて1 threadで約9%、4 threadで14〜17%遅かった（下の表）。
- **原因の切り分け**（`gemm_chunk_bench`、linearの4形状、P-core）：

| 計算 | mainの計算に対する時間比 |
| --- | --- |
| Candle上で分割 | 1 thread：1.06〜1.19、4 thread：1.16〜1.69 |
| gemmの直接呼び出し（足し込み） | 1 thread：0.96〜1.05、4 thread：0.96〜1.12 |

  - 遅れの大部分は、区切りごとに新しい出力tensorを作ることと、それを足すことだった。kc＝512にしたこと自体による遅れは小さい。
  - そのため、gemmを直接呼び出す方式に替えた。

## 検証（i7-1360P、Windows）

### bit（catalogの全39件、4 thread、各processを起動時からP-coreまたはE-coreに固定）

| 比較 | 不一致の件数 |
| --- | ---: |
| branch（P-core起動）とbranch（E-core起動） | **0**（main同士では36） |
| main（E-core起動）とbranch（E-core起動） | 0（kc＝512のhostでは結果が変わらない） |
| main（P-core起動）とbranch（P-core起動） | 36（最大差3.55e-6、判定はすべて一致） |
| 直接呼び出しの版とCandle上で分割した版（P-core起動、E-core起動とも） | 0 |

- 4つのprocessとも、全39件で数値gateに合格した。

### 速度・peak（P-coreに固定、mainとの比（branch÷main）、各3回の中央値）

| 計算 | threads | 128 | 874 | 3206 | 8192 tokens | peak（private／Working Set） |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 直接呼び出し（採用） | 1 | 1.032 | 1.008 | 0.996 | 1.008 | 1.000／1.000 |
| 直接呼び出し（採用） | 4 | 0.967 | 1.012 | 1.009 | 1.009 | 1.002／1.001 |
| Candle上で分割（参考） | 1 | 1.106 | 1.092 | 1.091 | 1.090 | 1.000／1.000 |
| Candle上で分割（参考） | 4 | 1.170 | 1.154 | 1.165 | 1.136 | 1.000／0.999 |

- ノート機（電源・温度は未制御）での記述である。記録機（Ryzen AI MAX+ 395）での速度同等性（0.2.0のrelease gate）は、まだ確認していない。

### 試験

library・CLIの試験、clippy、fmt、doc（警告をErrorとして扱う）、ライセンス監査は、すべて合格した。

## 影響を受けるhost

[調査](native-gemm-kernel-params-2026-10-20.md)の表で、kcが「512を基準にした規則」と違うhostだけ、結果が変わる（最大で数e-6、判定は不変の見込み）。

- 記録機。
- i7-1360PのP-core。
- Windowsの12-way L1（EPYC 9V45など）。
- Linuxの12-way L1（down_projのみ）。
- Linux上のCobalt 100。

8-way L1のhost（i7-1360PのE-core、EPYC 7763、Windows on ARM）では、結果は変わらない。

## 4環境CI（`native-hosts.yml`を手動実行、`f517597`、run 39418570792）

| runner | CPU | gemmのL1 | 試験（debug） | golden 7件の最大差 | host matrix | 公式refとの最大差 |
| --- | --- | --- | --- | ---: | --- | ---: |
| ubuntu-24.04 | AMD EPYC 9V45 | 24 KiB 12-way | 46件合格 | 4.13e-6 | 合格 | 3.58e-6 |
| windows-2022 | AMD EPYC 9V74 | 32 KiB 8-way | 46件合格 | 3.99e-6 | 合格 | 3.52e-6 |
| ubuntu-24.04-arm | Cobalt 100 | 64 KiB 4-way | 46件合格 | 3.76e-6 | 合格 | 3.31e-6 |
| windows-11-arm | Cobalt 100 | 16 KiB 8-way | 46件合格 | 4.26e-6 | 合格 | 3.78e-6 |

host matrixは、各runner内で、1／2／4 thread、独立process、固定process、timeout→再利用がすべてbit一致した。

### hostの間の比較（期待どおりにならなかった点）

- **期待**：同じkernel ISAのrunnerどうしで、host matrixの確率がbit一致すること。
- **結果**：一致しなかった。
  - ARM64のLinuxとWindows（同じCobalt 100）で、39件中37件が不一致だった。
  - x86_64のLinuxとWindowsで、39件中35件が不一致だった。
- **原因**：要素ごとの関数の結果が、OSの数学libraryによって違う。行列積（gemm）ではない。
  - 調べ方：[`math_probe`](../runtime/rust/examples/math_probe.rs)で、forwardが使う要素ごとの関数を固定の入力（2^20個、−20〜20）で計算し、出力bitのdigestを4つのrunnerと手元で比べた（一時的なworkflow、run 39434906095）。

| 関数 | ubuntu x86_64 | windows x86_64（i7-1360Pも同じ） | ubuntu ARM64 | windows ARM64 |
| --- | --- | --- | --- | --- |
| `f32::exp`、SiLU、Candleのexp・sigmoid | A | **B** | A | A |
| `ln_1p`（DeltaNetのsoftplus） | 1 | 2 | 3 | 4 |
| `sqrt`、`powf`（RoPE） | 同じ | 同じ | 同じ | 同じ |
| Candleのsoftmax | P | Q | R | R |
| Candleのsum | S | S | T | T |
| gemm（k分割、31積） | X | X | Y | Y |

- **関数ごとの違い**：
  - Rustの`f32::exp`と`ln_1p`は、OSの数学library（glibc、MSVCのCRTなど）を呼ぶ。
  - `exp`は、Windowsのx86_64だけが違うbitを返す。
  - `ln_1p`は、4つのrunnerすべてで違った。
  - softmaxは、expと、ISAごとのvector和の両方の影響を受ける。
  - `sqrt`は、IEEEで正しく丸めるため、どこでも同じだった。
- **この変更の効果**：k分割したgemmの全31積は、x86_64のLinuxとWindowsの間で一致し、ARM64のLinuxとWindowsの間でも一致した。
  - 変更前は、ARM64で31積中5積しか一致しなかった（[調査](native-gemm-kernel-params-2026-10-20.md)）。
  - **この変更で、行列積はOSによらなくなった。ただし、forward全体は、数学libraryの違いでOSごとに違う**。
- 異なるOS・CPUの間でbit一致することは、#18では要求していない。この変更で得たのは、次の2点である。
  1. 同じhost（同じOS・ISA）で、起動したcoreやCACHE_INFOによらず、bitが同じになること（i7-1360PのP／E起動で、全39件一致）。
  2. 行列積については、同じISAのhostの間で同じbitになること。
- OSの間でもforward全体を一致させるには、`exp`・`ln_1p`を、OSによらない実装（例：pure Rustの`libm` crate）に替える必要がある。
  - Candleの内部（softmax・sigmoid・exp）も対象になるので、大きな変更である。
  - 全hostで結果も変わる。#18の範囲外として扱う。
- **未確認**：同じOS・ISAで、cacheの違うhostどうし（例：LinuxのEPYC 7763とXeon）が、forward全体で一致すること。予測では一致するが、同じrunでそのような組を得られていない。

## 残っていること

- **記録機での確認**：
  - 0.2.0のrelease gateの手順で、公式refとのgate、速度同等性、peakを確認する。
  - 新しいbit基準を取る。

証跡：[research/native-fixed-k-chunks-2026-10-20/](research/native-fixed-k-chunks-2026-10-20)（`ci-f517597`、`math-probe`を含む）
