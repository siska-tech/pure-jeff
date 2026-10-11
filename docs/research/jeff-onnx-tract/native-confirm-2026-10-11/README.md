# Independent Native2/4 confirmation and Tract4 comparison

Frozen Native thread wrapper and accepted Scatter Tract exe, no rebuild/source
change. Native text320/head1 FP32, Tract FP32 packed plan, common512 text-only.
Three configurations in all six permutations; each position occurs twice.
One warmup + four measured/session, n=24/configuration and n=6/input. Twenty-one
processes/114 forwards = gate24 + warmup18 + measured72. New independent
sessions/seed after exploratory matrix, SAME artificial inputs, no held-out
input corpus or recognition quality labels. Nearest-rank p95=second-largest.
Native frozen probabilities tolerance1e-4, setting repeat1e-6; Tract raw exact
to frozen four-thread gate; all ONNX probability/judgment/tokens gates pass.
Global Native Rayon pool/Candle settings and Tract executor4 verified.
Raw/schedule/cache/pool/resource validation and all statistics independently
recomputed. Native4 warm confirmation only if all six block medians and pooled
median/p95 below Native2; no optional stopping or post-hoc threshold change.
Native4/Tract4 is descriptive operating-configuration comparison; no runtime-only
effect, adoption, API E2E or formal SLO. Algorithms/layout/kernel boundaries and
startup verification/request scopes differ. Lifetime peak includes startup/
mapped/shared memory, n=6 incidental; not warm private memory/cold campaign.
Thermals/affinity/background/storage cache uncontrolled; one warmup/six blocks.
No concurrent builds/tests/hash audits during timings. Nine Rust tests and
clippy/fmt/source reproduction inherited from hash-frozen previous archive.
Previous executables/source/archives, Native/API and sibling KazeNhanh preserved.
No new runtime dependency or distribution approval; NOTICE audit still open.
