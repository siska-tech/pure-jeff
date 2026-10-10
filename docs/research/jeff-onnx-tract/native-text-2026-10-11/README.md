# Native text320 FP32 retention pilot

Pinned full473 executable versus text320 candidate; same equations, wrapper,
Cargo manifest/lock and head1. Only retained model tensor selection changes.
Exact full473 inventory required; missing/duplicate/unexpected names rejected.
Eleven generated files independently reproduced; seven Rust tests, clippy, fmt.
Eight processes, 46 forwards: gate16, warmup6, measured24. Common512, one thread,
three AB/BA/AB pairs, one warmup plus four mixed measured requests/session.
All candidate probabilities exact to frozen Native; ONNX numeric gates pass.
Independent raw/schedule/cache/resource validation and statistics recomputation.
Local MEMORY-ONLY acceptance: all paired lifetime peaks and pooled maximum
decrease. Startup and warm latency are descriptive, no latency acceptance/SLO.
Lifetime peak includes startup mmap/conversion, not warm private memory.
n=12/mode, per-input n=3; nearest-rank p95=max; only three independent pairs.
Synthetic input, uncontrolled thermals/affinity/background/storage cache.
No concurrent builds/tests/hash audits during timings. Original Native/API,
previous full-cache candidate/evidence, Tract and sibling KazeNhanh preserved.
No new runtime dependency or distribution approval. Real quality remains open.
