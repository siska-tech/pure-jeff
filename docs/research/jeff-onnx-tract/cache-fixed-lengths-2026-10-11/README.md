# Cache-fixed Native4 / Tract4 length pilot

Frozen numerically accepted Native timing exe, cacheB CPU0 initialization only,
main mask restored before model/pool/forward. Frozen accepted Tract Scatter
exe/NNEF plan. Step1113, FP32 resident,batch1,4 threads. Native effective length,
Tract left-padded physical512: shape/layout/algorithm and startup/request
scopes unequal. Operational configuration comparison, no runtime-only claim.
Gate28/backend in4 children each, then3 AB/BA/AB resident pairs,5 mixed-length
warmups+20 measured/session =14 children206 forwards,103/backend. Each length
128/256/384/511/512 n12/backend, n3/input. Nearest-rank median,p95=max.
Existing ONNX1e-4,sum1e-6,judgment/tokens, Native references1e-4, old Native gate
and pairwise repeats1e-6, Tract raw exactly previous length gate. AC connected
and battery saver off required at each child boundary; system CPU snapshots
include other processes. Compute affinity/temperature/frequency/background
uncontrolled, same old artificial inputs, partially balanced order, no holdout.
Lifetime peak n3 includes startup/mapped/shared pages, not warm private memory
or storage-cold campaign. No backend adoption/API E2E/formal SLO/quality claim.
All raw/stats independently audited; original failed evidence/thresholds,
Native/API and sibling unchanged. Python dev-only, distribution NOTICE open.
The source diff is stored as JSON-escaped UTF-8 with its original byte hash;
decoding content.encode('utf-8') reconstructs the original patch bytes.
