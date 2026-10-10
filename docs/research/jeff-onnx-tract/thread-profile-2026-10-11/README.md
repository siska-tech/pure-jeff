# 4/8-thread operator diagnosis

Frozen multithread binary from b41d19f; identical model and generated source
hashes to the preceding pilot. No runtime source, build, optimizer or dependency
change. Both executors pass four goldens before profiling. Two independent
profile sessions per executor, orders [4,8] then [8,4], each warmup1 + samples3.
6 processes / 24 forwards including gates and warmups. Six measured profiled
forwards per thread; nearest rank p95 is max. Operator wall time is top-level,
includes child plans, and is not CPU time. All raw logits equal frozen control.
No unprofiled latency comparison, speedup claim, API E2E or formal SLO acceptance.
ONNX provenance uses stored metadata and exact names only; unmatched optimizer
nodes are retained as unmatched, never guessed. No external weight tensor load.
Actual UTC start, guards and hashes are in preregistration.json. New development
scripts do not introduce runtime dependencies. Prior Tract license/NOTICE and
lock are retained; additional dependency licenses remain in the preceding pilot.
