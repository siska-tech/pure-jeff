# Native fixed-cache full28 numerical gate

Frozen instrumented cache diagnostic exe, cacheB init on verified logical CPU0,
main thread mask restored before pool/model/forward. Same step1113 FP32
text320/head1,4 compute threads,batch1. No runtime/API/source/exe changes.
Two passes over28 cases,7 per child, chunk order0/1/2/3 then3/2/1/0,
fixed shuffled input order =8 children/56 forwards. Each case observed in
two independent processes. No all-case within-process repeats or long
resident history. Existing ONNX1e-4,sum1e-6,judgment/tokens,input IDs,
finite hidden1024/raw255,pool/cache/affinity/resource gates enforced. Old
28-case Native gate and cross-process differences<=1e-6; frozen Native
references<=1e-4 where available. Thresholds and old failed evidence unchanged.
Independent raw validation includes chunk/order/coverage, CPU deltas, all
probability/hidden/raw differences and summary. Timing is diagnostic only.
Prior source/features/Rust checks and generated source are frozen in the
previous cache diagnostic archive, referenced by SHA256. This run accepts
only this instrumented condition/fixture set, not production backend,
uninstrumented performance build, long resident stability, formal SLO or
held-out recognition quality. Core placement/temperature/frequency/background
uncontrolled. CPU0 is host-specific, not a portable selection policy.
Native/API/sibling and all prior evidence unchanged. Python is dev-only.
License/NOTICE snapshot inherited; distribution acceptance remains open.
