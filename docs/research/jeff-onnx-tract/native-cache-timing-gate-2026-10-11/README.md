# Cache-fixed timing wrapper numerical acceptance

New separate crate/target, same explicit cache module as diagnostic, original
backbone/weights/readout/threads source and per-request output. No hidden/raw/
input-ID/processor request instrumentation. Init still records cache metadata
and hypothetical params, not actual GEMM-call telemetry. Main thread restored
before pool/model/forward. Host-specific cacheB/CPU0 verified by probe.
Step1113,text320/head1 FP32,4 threads,batch1. Gate28 in4 children7 each, then
resident4 children7 cases twice =8 children84 forwards,3 observations/case
in two processes.14 requests/resident is not long production history.
ONNX1e-4,sum1e-6,judgment/tokens; old gate/accepted diagnostic/within and cross
process probabilities1e-6, frozen Native1e-4 where available. Thresholds and
old failed evidence unchanged. Numeric acceptance only: no warmup, latency
comparison, performance/SLO/backend adoption/recognition-quality acceptance.
Rust9 checks/clippy/fmt,156 package feature sets,16 reproduced files, exact
compute source equality, independent raw audit and license/NOTICE snapshots.
Core placement/temperature/frequency/background uncontrolled. Native/API and
sibling unchanged; Python dev-only. Portable core selection, long history,
formal measurement, real labels and distribution NOTICE remain pending.
