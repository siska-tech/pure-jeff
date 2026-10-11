# Common512 one-thread operating-configuration pilot

Same step1113, four full Rust requests at effective/physical512, no padding,
one requested/reported compute thread. Native BF16 mmap/per-forward FP32
conversion and Tract retained FP32 packed plan remain asymmetric. Algorithm
and stage boundaries differ. This is not isolation of runtime-only effects.
Four existing goldens plus four common512 inputs gate both engines first.
Three independent resident pairs AB/BA/AB, one warmup + four mixed measured
inputs per engine/session, n=12/backend, per-input n=3. Eight processes,
46 forwards = gate16 + warmup6 + measured24. Numeric gates pass, Native
probabilities exactly repeat gate, Tract raw logits exactly match prior
four-thread gate. Raw records and statistics independently revalidated.
Compute = Native backbone+head/softmax vs Tract forward+score. Request and
startup scopes differ; do not treat request as matched API E2E or startup
as cold adoption evidence. Peak is process lifetime including shared/mapped
pages, n=3 incidental, not per-request private memory. n=12 p95=max and only
three independent pairs. One warmup, synthetic content, no quality labels,
uncontrolled thermals/affinity/background/storage cache. No concurrent
builds/tests/hash audits during timing. No speedup/SLO/API/quality acceptance.
First sandbox attempt stopped before initialization: access denied, zero
forwards/samples. Same source/assets rerun under approved permission; initial
job/error/process/preregistration retained separately. Models/executables/
generated sources remain ignored, hash-frozen assets; no runtime API change.
