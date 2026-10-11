# FP32 retained common512 Native/Tract pilot

Frozen text320 Native FP32/head1 versus accepted Scatter Tract FP32 packed plan.
Same step1113, common effective/physical512, one compute thread, no padding.
Source/configuration thread audit captures Candle commit, clean diff, feature
tree and exact source excerpts/hashes. This does not assert one OS process
thread or measure active worker telemetry. Native wrapper forces both env vars
to 1; GEMM Parallelism::None, barrier auxiliary workers zero; DeltaNet serial.
Tract explicitly uses SingleThread. No existing executable/source rebuild.
Four goldens + four artificial requests gate both engines. Three AB/BA/AB
pairs, warmup1 + measured4, n=12/backend and n=3/input. Eight processes/46
forwards = gate16 + warmup6 + measured24. Numeric gates pass; Native frozen
probabilities exact; Tract raw exact to previous four-thread gate.
Raw/schedule/cache/resource records and all statistics independently checked.
Descriptive operating-configuration comparison, no backend adoption/SLO/speedup
or runtime-only claim. FP32 retention equalizes dtype, not packed layout,
algorithm, kernel boundaries, startup validation or API E2E. Lifetime peaks
include startup/mapped/shared pages, not private warm memory; n=3 incidental.
Nearest-rank n=12 p95=max, three pairs, one warmup, artificial content, no labels,
uncontrolled thermals/affinity/background/storage cache. No concurrent
builds/tests/hash audits during timings. Native/API/previous evidence/Tract
and sibling KazeNhanh preserved. No new runtime dependency or distribution
approval. Future Native thread matrix needs an independent wrapper and gates.
