# Windows環境継続記録と次の測定条件

2026-10-11。[固定cache長さ別pilot](onnx-tract-cache-fixed-lengths.md)では512 tokensのp95がNative20.906秒／Tract19.241秒となった。以前の約7秒台のpilotとの差は、温度・背景負荷・周波数・実行coreの記録不足により原因未確定である。今回、環境記録を追加し、正式測定へ進む前の結合検証を行った。

## 実装と測定範囲

`runtime/onnx/observe_windows_host.py`は開発用のWindows read-onlyツール。1秒間隔でAC／省電力flag、電源scheme GUID、system CPU累積時間、CPUセットのtopology／efficiency class／park状態、observerのprocess affinity mask、CPUごとのOS報告power情報をJSONLへ保存する。既存`benchmark_pilot.invoke`を変更せず、`invoke_observed`から呼び出す。公開runtime・API・Decision Report、固定exe・modelは変更しない。Pythonは開発時のみ使用する。

受入条件はAC=1、省電力flag=0、scheme／observer mask／topologyが標本間で不変、2標本以上、最大間隔≤設定間隔の2.5倍、記録エラーなし。観測条件の不合格はchild終了後に例外として伝播し、記録とsummaryを残す。child本来の失敗は上書きしない。既存の期限・Peak Working Set監視を維持する。

CPUセットは可変サイズのレコードとして解析し、未知typeはskip、破損・重複・空レコードは拒否する。今回のpower情報との対応は単一processor groupだけをサポートし、複数groupでは明示失敗する。[MicrosoftのCPUセット構造](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-system_cpu_set_information)に従う。

`CurrentMhz`と`MhzLimit`はOSが報告する値として保存する。hardware effective clockの直接測定、温度、throttlingの因果証明には使用しない。[MicrosoftのPROCESSOR_POWER_INFORMATION仕様](https://learn.microsoft.com/en-us/windows/win32/power/processor-power-information-str)も参照する。電源schemeは[PowerGetActiveScheme](https://learn.microsoft.com/en-us/windows/win32/api/powersetting/nf-powersetting-powergetactivescheme)で読み取り、取得したGUID領域を解放する。

## 検証

- 30秒・1秒間隔の実機smoke：31標本、最大間隔1.017秒、1標本の収集時間最大5.500 ms。観測条件に合格。収集時間は推論への影響量ではなく、observer有無の性能差は未測定。
- 正常終了、exit7、期限超過の3 childケースで、既存process監視と継続記録を併用できた。失敗2件は期待した失敗として保存し、成功runへ読み替えない。
- 7 unit testsで、AC不明／切断、省電力flag、scheme／affinity／topology変化、標本不足・間隔欠落・CPU counter不正、破損CPUセット、初回センサー失敗、child本来の例外保持を確認した。
- 固定済みNative4／Tract4で、既存人工512-token入力を各3反復。全6 forwardがONNX1e-4・確率和1e-6・判断／tokens一致、Native旧参照／全観測ペア1e-6、Tract raw完全一致と継続記録条件に合格した。最大ONNX確率差2.5033950805664062e-6、Native3反復は完全一致。生記録からの独立監査も合格し、証跡56ファイルと`validation.json`へ保存した。warmupなし・各1 sessionの結合検証であり、性能受入ではない。

| 推論中の環境記録 | 標本数 | 最大記録間隔（秒） | 収集時間最大（ms） |
| --- | ---: | ---: | ---: |
| Native4 | 67 | 1.035 | 14.614 |
| Tract4 | 134 | 1.041 | 32.524 |

この収集時間の最大値からも推論への影響は未確定であり、次の比較でobserverの負荷を測定する。

初回unit testの一部はsandboxの既定temporary directoryへのアクセスで失敗した。workspace内の`.venv`へtest用temporary directoryを変更して全7件合格。結合検証では参照を単一chunkから検索する誤りを推論開始前に修正した。数値閾値・参照値は変更していない。

今回のhostではlogical CPU0〜7がefficiency class1、8〜15がclass0として報告された。CPU0〜7は同一core indexを共有する2論理CPUずつの4組で、8〜15は別々のcore indexだった。park状態は標本ごとに保存する。これは実際にどのcoreでforwardを実行したかの記録ではない。observerのmask65535もchild workerの配置保証ではない。

ACPI thermal zone queryはaccess deniedだった。温度は取得不可として保持し、0℃や推定温度で埋めない。system busyは全processを含み、背景負荷と推論CPU時間を分離できない。1秒間隔の記録では標本間の変化を完全には捉えられず、電源scheme GUID不変でもscheme内部設定やOS電源modeの不変を保証しない。

## 次の実行順と判定

1. 固定exe・同じcacheB初期化条件のまま、継続記録あり／なしを独立したAB／BA組で比較し、observer overheadを評価する。性能条件・標本数・停止条件は新規事前登録し、旧pilotへ標本を足さない。記録ありrunでは全期間のJSONLを保存する。
2. 実行core配置を変える場合は新しい条件として扱う。候補は全CPU、class1の各physical coreから1 logical CPU、class0のCPU群。maskを番号だけで決めず、今回取得したtopologyと許可maskから導出する。cache初期化条件とcompute affinityを区別し、全28-case数値gateとresident反復gateに合格するまで性能比較へ進めない。
3. 未使用の人工OCR／ASR本文を長さ別に追加し、同一checkpointのONNX oracle・tokenizer／prompt／温度・判断を固定する。確認済み実データがないため、これをPhase 5品質評価や実運用hold-outとは呼ばない。
4. 事前の非推論観測、電源設定の読取結果、他の実験processの有無を記録する。ユーザーのprocessを終了したりglobal電源設定を自動変更したりせず、条件を満たさないrunは除外理由ごと保存する。system busyだけから背景負荷なしとは判定しない。
5. 正式warm campaignは5 warmup・n≥300と別日または3回以上の独立blockを含む。長時間residentの数値安定性・記録coverageを先に確認する。観測不能な温度／hardware clockは制約として明示し、条件付きSLOを提案する。API E2E、storage-cold、量子化、batchは別campaignとする。

暫定8秒SLOは未達成のまま。今回の作業は観測機能の受入であり、遅延原因の確定、高速化、正式SLO、TractBackend採用、Phase 5品質改善の受入ではない。

[生記録・事前登録・独立監査](research/jeff-onnx-tract/host-observer-2026-10-11/README.md)。
