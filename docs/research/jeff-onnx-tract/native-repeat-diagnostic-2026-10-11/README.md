# Native numerical repeat diagnosis, not performance reacceptance

Frozen text320/head1 FP32 exe, step1113, batch1, native effective length.
Four failed cases128/384/511 plus one unicode512 control. Threads1/4,
two sessions each, AB/BA order, three repeats/case/session = four processes/
60 forwards. No warmup or latency acceptance; raw times are diagnostics only.
ONNX probability1e-4/sum1e-6/judgment/token/resource gates stop on failure;
registered fixed60 collected regardless of repeat1e-6 exceedances, which
remain recorded, never relabeled as a successful performance comparison.
Within-process span, cross-process first delta, six-observation span and
old failed-run Native4 gate differences independently recomputed. JSON keys
ending within_1e6 mean within registered1e-6, as comparison code/preregistration
specify. Native raw/hidden logits not instrumented; causal source unknown.
Power raw and system CPU cumulative snapshots before/after each child;
average busy percent includes unrelated processes, not child utilization or
contention proof. No affinity/frequency/temperature/active worker telemetry.
Same artificial inputs, two sessions, no 28-case reacceptance, formal SLO,
backend adoption or recognition-quality claim. Previous failed run and
frozen assets, Native/API and sibling preserved. Distribution NOTICE open.
