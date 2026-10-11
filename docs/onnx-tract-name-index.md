# Tractのsuffix探索を1回の走査へまとめる実験

## 結果・2026-10-10

**命名と数値の回帰には合格したが、性能改善版としては不採用。** 以下は今回の交互比較、各版n=5、秒単位。対照は前回の重複探索削除版であり、元の約50秒のTractとは異なる。

| 区間 | 対照 中央値／p95 | suffix変更版 中央値／p95 |
| --- | ---: | ---: |
| NNEF load | 8.988／9.296 | 9.103／9.496 |
| codegen | 10.196／10.603 | 10.655／11.457 |
| plan構築 | 0.439／0.459 | 0.434／0.452 |
| cold起動全体 | 19.708／20.063 | 20.265／21.020 |
| cold process全体・1 forward込み | 31.746／31.994 | 32.576／32.879 |
| 常駐forward・candidate-request | 11.912／12.019 | 11.917／12.277 |

起動の候補−対照の5組差は+0.352、+0.882、+1.497、+0.077、+0.652秒で、全組で候補が遅かった。codegenの中央値・p95も増えた。HashSet構築と走査時の処理増加は原因候補だが、各処理の寄与は未計測なので断定しない。この限定変更が、今回のJeff・Windows CPU・1 thread条件で高速化する根拠は得られなかった。

cold Peak Working Set中央値／p95は対照3.052／3.052 GiB、候補3.051／3.052 GiB、常駐process peakは両版約3.051 GiBで、メモリ改善の根拠はない。全回帰gateも含む最大は約3.068 GiB。mapped/shared pages込みのOS process peakで、private memoryではない。

全14 process・30 forwardで4 goldenの確率差≤1e-4・判断・token数が一致し、同一入力のraw255 logitsは両版・全繰り返しで完全一致した。golden比最大確率差4.9173831939697266e-6。性能summaryの最大差6.556510925292969e-7はcandidate-requestのみの集計で、4件gateを含む検証とは範囲が異なる。推論失敗・期限・メモリguard発動は0件。

[保存証跡](research/jeff-onnx-tract/name-index-2026-10-10/README.md)に事前登録、全job／stdout／process／検証record、再集計、対照exeの参照、生成sourceのhash、実際のlock、core差分と追加module、licenseを保存した。Native保全対象128ファイルは既知の`.gitignore`差分だけである。小型Python回帰21試験はskipなしで合格し、単独Rustの命名集合試験も合格した。候補のrelease clippy、補助関数の単独clippy（いずれも警告をエラー化）、追加Rustコードのfmtも成功。追加CIは設定したがGitHub上では未実行。

この候補を通常probe・Native・公開APIへ適用しない。実験コードと証跡は再現用に残す。名前の永続indexを広げる前に、残る重複チェックと`unique_name`各分岐の回数・時間、名前変更／compactionに対する無効化を検証する必要がある。約12秒のforwardは別課題であり、次の性能評価ではoperator内訳とスレッド数比較を優先する。Phase 3全体・SLO・品質・API統合の受入は引き続き未完了。

## 変更範囲

前回受入した重複探索削除版を対照として固定し、`Graph::unique_name`のsuffix選択だけを変更する。prefix自体が未使用ならそのまま返す従来の処理は保つ。prefixが使用済みの場合は、全nodeから使用済みの正の整数suffixを1回で集め、最小の空き番号を返す。従来のsuffixごとの全node再走査を避ける。

`a.01`、`a.+1`、`a.0`などは従来のformatterが作る`a.1`を占有しない。重複名、空文字prefix、Unicode、番号の欠番も扱う。patch側の最初の`#`でprefixを分ける規則、garbage除去と改名、処理順は変更しない。Graphの名前を永続cacheへ入れる変更ではなく、各呼出時点の実際の名前から集める。

patch適用時の名前重複チェックとprefix未使用確認の走査は残る。したがって、前回診断の名前整理約9.8秒を丸ごと削減する変更ではない。`Graph::unique_name`を使う定数生成などにも作用するため、NNEF loadとcodegenは分けて測る。

元coreや通常probe、Native runtime、公開API、Decision Reportは変更しない。`prepare_name_experiment.py`で新規directoryへ生成し、別Cargo targetへビルドする。core差分は`graph.rs`の関数本体、`lib.rs`の非公開module宣言、新規の`name_index.rs`だけ。前回版とbench／patch source、Cargo.lockが同一であることを照合する。元のMIT OR Apache-2.0 licenseは保持する。

## 回帰と測定方法

単独Rust試験では13種類の名前から8,192集合を作り、各集合を正順／逆順・6 prefixで従来の選択処理と比較する。加えて重複名を検査する。実際のGraph 6件とModelPatch 5件で、欠番、非正規の番号表記、空prefix、Unicode、`#`の複数出現、garbage除去後の名前再利用と出力値を確認する。

既存の小型graphで共有定数、2出力TopK、node／edge／output slot／label／値を前回版と比較する。小型NNEFの繰り返しraw logitsも照合する。これらは有効graphの限定回帰で、Tract全体の互換性証明ではない。

実モデルは同じstep1113のdecluttered NNEF、物理512 tokens、SingleThread。両版の4 golden回帰を先に行い、確率差≤1e-4、判断・token数一致、同一入力のraw255 logits完全一致を要求する。回帰processは性能集計から除外する。

前回版とsuffix変更版を各5回、AB／BA交互でprocess-cold比較する。常駐は各1セッション、candidate-requestをwarm-up 1回＋測定5回。load、codegen、plan、起動全体、1 forward込みのprocess時間、warm forward、生涯Peak Working Setを記録する。内部timerなし、callback計測無効。モデルhash検証は親で行い、子の起動から除く。

中央値とnearest-rank p95を記録する。n=5のp95は観測最大で、storage cache・温度・背景負荷・電源／affinityの再snapshotは未制御。期限600秒、メモリguardは8 GiBと物理RAM半分の小さい方。1入力・1常駐セッションのpilotで、公開API end-to-end、正式SLO、実OCR／ASR品質を判定しない。

## 再現

```powershell
$env:CARGO_HOME = Join-Path $PWD '.venv/tract-cargo-home'
$upstream = (Get-Item .venv/tract-cargo-home/git/checkouts/tract-*/9e0cfaa).FullName
vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/prepare_name_experiment.py --upstream $upstream --output .venv/new-name-candidate
$env:CARGO_TARGET_DIR = Join-Path $PWD '.venv/new-name-candidate-target'
cargo build --offline --release --manifest-path .venv/new-name-candidate/Cargo.toml --bin bench --bin patch_semantics --bin name_semantics
vendor/jeff/.venv/Scripts/python.exe -B runtime/onnx/benchmark_duplicate.py --control .venv/tract-duplicate-candidate-target/release/bench.exe --control-reference docs/research/jeff-onnx-tract/duplicate-search-2026-10-10/preregistration.json --candidate .venv/new-name-candidate-target/release/bench.exe --generation .venv/new-name-candidate/generation.json --output experiments/runs/new-name-pilot
```

controlは前回の事前登録にあるexe hashと照合する。再ビルドでbytesが異なる場合は、同等だと仮定せず、新しい対照のsource／lock／回帰証跡を固定してから比較する。元のI64→TDim patchとChangeAxes除外の制約は残る。[前回の実験](onnx-tract-duplicate-search.md)、[開発用NOTICE](../runtime/tract-driver-profile/NOTICE.md)、[追加CI](../.github/workflows/tract-probe.yml)も参照。
