# Native4 / Tract4 length comparison: stopped on registered repeat gate

Frozen step1113 FP32 batch1 four-thread Native effective-length vs Tract
left-padded physical512. Planned three AB/BA/AB pairs, five mixed warmups+
twenty measured/session, n=12/length/configuration. ACTUAL six processes,
156 forwards=gate56+warmup20+measured80; third pair (50 forwards) NOT RUN.
All156 ONNX probability<=1e-4/sum<=1e-6/judgment/token gates passed, and
all78 Tract raw logits exactly match the previous length gate. Native repeat
<=1e-6 FAILED for six observations/four cases in resident-1-native4 (two
warmup/four measured), maximum3.546476364135742e-6. Child completed25 with
exit0; parent post-child validation failed at iteration0 with exit1. Other
five processes have validated records; failed Native process has raw/job/
process records and independent audit, no fabricated validated record.
Thresholds unchanged, no replacement run, no successful pooled comparison,
backend adoption or formal SLO. Diagnostic session/length stats n=4 include
the failed session explicitly, p95=max, not acceptance performance results.
Substantial timing drift also observed in both backends; causes unknown.
Two lightweight process snapshots during timing, cumulative CPU not usage.
No concurrent builds/tests/hash audits; background/thermals/AC/cache not
controlled. Shapes differ below512, request/startup verification scopes
unequal, no API E2E/cold campaign, lifetime peaks include mapped/shared pages.
Same artificial inputs; no held-out corpus or recognition labels. Eight-
candidate extras gate-only and lack128 cell. Native raw logits unavailable.
Independent raw/pool/cache/schedule/resource/probability/statistics audit;
all frozen assets, old thread/length/confirmation archives, Native/API and
sibling preserved. Nine Rust tests/clippy/fmt/source reproduction inherited
from frozen previous archive; NOTICE/distribution review remains open.
