# Trilu row-fill experiment

Fixed step1113 NNEF and frozen multithread control. New isolated Cargo target,
identical lock/benchmark driver, only Trilu and row-fill helper changed. Both
four-golden gates precede timing. Four threads, three independent AB/BA/AB
resident pairs, each one warmup plus three samples (n=9/binary). Separate
profile sessions each warmup1 + samples3, excluded from latency aggregates.
10 processes / 40 forwards. All raw logits equal frozen control. Nearest-rank
p95 with n=9 is max; startup and lifetime peaks have n=3, not a cold campaign.
Local acceptance is preregistered and recomputed from raw records. No formal
SLO, Native comparison or recognition-quality acceptance. Prepared physical512
inputs; thermals, affinity, background load and storage cache uncontrolled.
Original fallback retained for nonstandard layout and legacy row+k overflow.
The existing release overflow behavior is preserved, not repaired. New helper
is project-authored; Tract licenses/NOTICE and unchanged lock are retained.
Model, binary and generated full tree remain ignored, with hashes archived.
