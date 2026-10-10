# Native text320 FP32 thread matrix

Isolated generated wrapper, same equations/cache, threads1/2/4/8 per process.
Both environment variables set before tokenizer/tensor initialization; global
Rayon pool explicitly built and actual size checked. GEMM setting and pool
size emitted; barrier auxiliary count is a derived expectation, not telemetry.
Manifest policy remains1; experimental job overrides compute only. DeltaNet
recurrence unchanged/serial. Existing runtime/API/executables are preserved.
Thirteen generated files reproduced, nine Rust tests, release clippy/fmt pass.
Existing locked Rayon made explicit; no dependency package version change.
Four goldens + four common512 artificial requests gate each setting. Balanced
four-block Williams order; one warmup + four measured/session, n=16/setting,
per-input n=4. Twenty processes, 112 forwards = gate32 + warmup16 + measured64.
ONNX and frozen Native tolerance1e-4; one-thread frozen probabilities exact;
within-setting repeat tolerance1e-6. Judgment/tokens gates pass throughout.
Raw/schedule/cache/pool/resource records and statistics independently checked.
Next pilot candidate only: all block medians and pooled median/p95 below1,
then lowest eligible pooled median. No formal SLO/backend/API/Tract adoption.
Nearest-rank p95 at n=16 is max. Four blocks/one warmup/synthetic content,
uncontrolled thermals/affinity/background/storage cache, no quality labels.
Lifetime peak/startup n=4 incidental, not cold/private warm/API E2E evidence.
Pool size does not imply all workers active or cap total process OS threads.
No concurrent builds/tests/hash audits during timing. Previous Native/Tract
and sibling KazeNhanh remain unchanged. Distribution/NOTICE audit still open.
