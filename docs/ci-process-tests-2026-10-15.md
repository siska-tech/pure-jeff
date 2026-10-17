# CI：Python worker試験の不安定さ（#26）

2026-10-15。v0.2.0の公開の後、PR #25（文書だけの変更）のWindows CIで、`tests/process.rs`の3件が同時に失敗した。同じcommitのもう1本のrunと再実行では合格した。この文書は、原因の調査、修正、残るリスクの記録である。

**本番のcodeは変えていない。** `src/process.rs`のdeadline・kill・異常応答の契約、推論logic、公開APIはそのままで、変えたのは試験だけである。v0.2.0の証跡にも触れていない。

## 現象

直近100 runの全attemptを調べると、`tests/process.rs`の3件（`process_round_trip`、`process_failures_are_preserved`、`timeout_terminates_running_child`）は、いつも同時に失敗していた。

| run／attempt | 日時 | test binaryの開始から3件の失敗まで |
| --- | --- | --- |
| 38222048730 a1 | 2026-10-12 08:11 | 10.45秒 |
| 38224027079 a1 | 2026-10-12 08:30 | 10.39秒 |
| 38572031768 a1 | 2026-10-14 13:28 | 12.46秒 |

- **protocolの2件**：`Timeout`になった。期待値はCompletedと`InvalidOutput`。deadlineは10秒だった。
- **timeout試験**：deadline 5秒に対し、7秒以内に戻らなかった。
- **同時刻**：3件の`FAILED`は、logで同じ時刻に出力されていた。

ほかの失敗は別の原因である。

- 2026-10-11の`process.rs:119`：timeout試験の時間の上限を5秒／7秒にする前のもの。
- 2026-10-12／13の`native_process.rs`：killの所要時間。#22で修正済み。
- そのほか：文書やbuildの手順の失敗。

## 調査：各段階

`LocalProcessProvider`（`src/process.rs`）の流れは次のとおり。

1. **事前の判定**：request・予算・deadlineを確かめる（deadline切れなら`Timeout`）。
2. **workerの起動**：`Command::spawn`（WindowsではCreateProcess）でPythonを直接起動する。
3. **起動の完了**：providerは起動の完了を検出しない。子が動き出したかどうかに関係なく、5 ms以下の間隔で`try_wait`とdeadlineを交互に確かめる。
4. **deadline超過の判定**：deadlineを過ぎたら`Timeout`を返す。
5. **killと終了待ち**：戻る前に、`RunningChild`のdropで`kill`し、`wait`する。終了待ちが済むまで呼出は戻らないので、直接の子は戻った時点で終了している。

失敗したrunでは、deadline 5秒の試験も、deadline 10秒の試験も、同じ時刻（10.4〜12.5秒）に戻っていた。手順4の判定は5 msごとに行われるので、5秒の試験だけが先に戻るはずである。全試験が同時に戻ったということは、**3つのPythonの起動（手順2：spawnから子が動き出すまで）が、そろって10秒以上止まっていた**と考えられる。spawnは同期の呼出なので、その間は手順4の判定ができない。止まった原因（runnerのdisk、scan、同時起動の競合など）は、logからは特定できない。試験はdeadlineを`Instant::now()`から作るので、この起動の遅れがそのまま試験の結果を左右していた。

- **protocolの2件**：deadlineを検証する試験ではないのに、起動が10秒を超えると`Timeout`になった。
- **timeout試験**：
  - 起動の遅れとkillの遅れを区別できなかった。
  - 「fixtureが実際に起動したこと」を要求していたので、起動がdeadlineより遅いと必ず失敗した。
- **同時起動**：同じbinaryの試験は並行に走り、3つの冷えたinterpreterを同時に起動していた。

### 再現

起動をN ms遅らせてから本物のPythonを起動するwrapperを、localで作った（`PURE_JEFF_PYTHON`に指定する。repositoryには入れていない）。

| 起動の遅れ | 修正前の試験（main） | 修正後の試験 |
| --- | --- | --- |
| 12秒 | 3件が失敗（`process.rs:63`、`:79`、`:120`。CIと同じ行と同じ組合せ） | 4件とも合格 |

## 修正

1. **`tests/process_launch.rs`と`tests/fixtures/fake_python.rs`を追加した**：deadline契約を、Pythonの起動時間と切り離して検証する。
   - Pythonの代わりに、std だけでbuildする代役を`LocalProcessProvider`から起動する。代役は数msで起動し、launcherのcommand line（`-I -B`、各path）とoffline用の環境変数を確かめる。そのうえで、遅いinterpreterのように指定の時間だけ待ってから動く。
   - 検証する場合：
     - 起動がdeadline内に終わる → Completed。
     - 起動中にdeadlineを過ぎる → `Timeout`。
     - 実行中にdeadlineを過ぎる → `Timeout`。
     - 応答を書いた後も終了しない → `Timeout`。
   - `Timeout`の各場合に確かめること：
     - deadlineより前には戻らない。
     - hangの上限（20秒）以内に戻る。
     - 子は呼出の後に何も書かない（すでに終了している）。
   - Pythonが不要なので、Linux CIでも走る。
   - **検出力の確認**：`src/process.rs`をlocalで一時的に壊して試した。killと終了待ちをやめる場合と、待ちのloopでdeadlineを確かめない場合で、どちらも3件が失敗した。
2. **`tests/process.rs`（本物のPython）を、protocolとlauncherの検証に絞った**。
   - **protocolの2件のdeadline**：120秒にした。deadlineは検証していないので、起動時間より長ければよい。protocolの誤りは、deadlineに関係なくすぐに失敗する。
   - **同時起動の回避**：interpreterを1つずつ起動するようにした。
   - **timeout試験**：deadline 5秒のまま、次の2つの場合を両方受け入れる。どちらの場合も、子が呼出の後に残らないことを確かめる。時間の上限（60秒）は、hangを検出するためだけのものである。
     - interpreterの起動中にkillされた場合：fixtureは一度も動かない。
     - fixtureの実行中にkillされた場合：`.survived`は書かれない。

**単にtimeoutを延ばしたわけではない。**

- deadlineの検証は、起動時間が決まっている代役で行う。deadlineは0.5〜1.5秒と短い。
- 本物のPythonでのtimeout試験も、deadlineは5秒のままである。延ばしたのは、deadlineを検証していないprotocolの試験と、hangを検出するための上限だけである。

## 検証

| 検証 | 条件 | 結果 |
| --- | --- | --- |
| 修正前の試験の再現 | localで、Pythonの起動を12秒遅らせる | 3件が失敗（CIと同じ行） |
| 修正後の試験 | 同上 | 4件とも合格（起動を1つずつ行うので90.5秒かかる） |
| 代役の試験の検出力 | `src/process.rs`をlocalで一時的に壊す（killと終了待ちをやめる、待ちのloopでdeadlineを確かめない） | どちらも3件が失敗 |
| localの反復（Windows、本物のPython） | `process`／`process_launch`／`native_process`を各20回 | 60回すべて合格。中央値は10.51／5.81／4.94秒 |
| localの反復（全論理CPUに負荷） | 各10回 | 30回すべて合格。中央値は11.27／6.21／5.38秒 |
| PRのCI | Windows・Linux、2 run（push、pull_request）×5 attempt | 40 jobすべて合格。Windowsの`process`は10.5〜11.0秒、`process_launch`は5.8〜6.0秒 |

- **CIで起動の遅延は起きなかった**：PRのCIでは、元の失敗のような起動の遅延は起きなかった。そのため、起動が遅い場合の動作は、CIでは代役の試験で、localでは起動を遅らせるwrapperで確かめた。
- **時間の内訳**：`process`の約10秒は、timeout試験が子の終了を確かめるための待ち時間がほとんどである。
- **証跡**（[research/ci-process-tests-2026-10-15/](research/ci-process-tests-2026-10-15)）：
  - 修正前のCIの失敗の抽出（`ci-failures-before.jsonl`と、その抽出script）。
  - localの反復の結果と、反復script。
  - 起動を遅らせるwrapperのsource。
  - PRのCIの各attemptの所要時間。

## 残るリスク

- **spawn自体が止まる場合**：Windowsでspawnが止まると、deadlineを過ぎても、止まっている間は`Timeout`を返せない。これはproviderの既知の限界（同期の呼出の途中では止められない）で、今回は変えていない。本番で起動の遅れが問題になる場合は、deadlineに余裕を持たせるか、`NativeProcessProvider`を使う。
- **子processを起こすlauncher**：`PURE_JEFF_PYTHON`に、Pythonを子processとして起動するlauncher（Windowsのvenvの`python.exe`など）を指定すると、killはlauncherにしか届かない。本物のPythonが孫processとして残る。
  - これは「終了処理は直接の子だけを対象とする」という既知の制約である。
  - 上の再現用wrapperも、遅らせずに使うと、この理由でtimeout試験が失敗した。
  - CIはsetup-pythonの`python.exe`を直接使うので、影響しない。
  - **訂正（2026-10-17）**：「Windowsのvenvの`python.exe`など」という例は誤りだった。実機で確かめると、次の3つは、どれも本物のPythonを別processとして起動するが、launcherがkillされると本物のPythonも終了した。
    - uvが作ったvenv。
    - CPythonの`python -m venv`。
    - `py.exe`。

    `tests/process.rs`のtimeout試験も、uvのvenvの`python.exe`を指定して合格した。孫processが残るのは、子processを終了させる仕組みを持たないwrapper（上の再現用wrapperなど）を指定した場合と、workerが自分で子孫を起動した場合（workerの契約に反する）だけである。この確認を受けて、Job Objectでprocess treeを終了させる変更は見送った。確認の方法と結果は`research/ci-process-tests-2026-10-15/kill_launcher.py`と`launcher-kill-2026-10-17.jsonl`にある。
- **極端に遅いrunner**：上限を超えると失敗する。
  - Pythonの起動が120秒を超える場合（protocolの試験）。
  - killと終了待ちが、hangの上限（20秒・60秒）を超える場合。
- **本物のPythonでの検証範囲**：遅いrunnerでは、本物のPythonのtimeout試験が「起動中にkill」の側を通る。そのため「実行中にkill」をその回の本物のPythonでは検証しないが、代役の試験が毎回検証する。
