#!/bin/sh
# Official Jeff references for the W2 length cases (1 thread, CPU FP32, fixed bundle).
cd "${KAZEJUDGE:?set KAZEJUDGE to the KazeJudge checkout}"
R=experiments/runs/wasm-w2-references-20261011
for f in $R/requests/*.json; do
  n=$(basename $f .json)
  vendor/jeff/.venv/Scripts/python.exe -B runtime/export_jeff_reference.py --manifest models/jeff-bundle.json \
    --request $f --output $R/$n.json --max-input-tokens 512 --timeout-ms 600000 > $R/$n.log 2>&1
  echo "$n exit $?" >> $R/progress.log
done
echo done >> $R/progress.log
