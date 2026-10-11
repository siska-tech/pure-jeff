# Controlled Native cache initialization diagnosis

Pin only the diagnostic main thread during explicit process CACHE_INFO init;
restore original thread mask before pool/model/forward. Enumerate every allowed
logical CPU first; choose one CPU for each of two observed cache classes.
AB/BA, two sessions/class, two cases, two repeats =16 forwards. No warmup or
performance/SLO acceptance. Hypothetical kernel_params are not actual GEMM
call telemetry. Hidden/raw JSON values normalized to binary f32 for deltas.
Input IDs exact, ONNX probability1e-4/sum1e-6/judgment/token/resource gates;
original repeat threshold1e-6 unchanged, no global28 reacceptance. Generated
backbone/weights and156 dependency feature sets unchanged,17 files reproduced.
Feature-label change in unmeasured v1 was rejected before inference and fixed
in v2, using a distinct executable. Raw logs, preregistration, independent
validator, generated source, references and license/NOTICE snapshots retained.
No historical CACHE_INFO telemetry; historical failure cause remains inference.
Core placement after restoration, temperature and frequency uncontrolled.
No API/runtime Python dependency change, recognition quality or distribution
approval. Existing failed evidence and all frozen assets remain preserved.
