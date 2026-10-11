# ScatterElements row-copy experiment

Frozen accepted Trilu binary as control, same step1113 NNEF and dependency lock.
Only overwrite ScatterElements and new safe row-copy helper differ. All row
indices are checked before mutation; fallback and reductions retain old paths.
4 threads, four-golden gates followed by three AB/BA/AB resident pairs, warmup1
+ samples3 (n=9/binary). Separate profiles excluded. 10 processes / 40 forwards,
all raw logits exact. Raw records independently revalidated and statistics and
local acceptance recomputed. n=9 nearest-rank p95 is max, startup/peaks n=3 are
incidental, not a cold campaign. No Native superiority, API E2E, quality or SLO
acceptance. Thermals/affinity/cache/background uncontrolled; no concurrent tests.
ONNX audit uses metadata and scalar Constant->Expand provenance, no weights.
Initial small-test failures are retained: I64 Cast -> TDim reductions rejected
by frozen control. Final regression verifies both paths reject these 64 cases;
192 other conditions succeed. These rejections are not successful forwards.
Plain RAM views are standard; nonstandard-layout guard is defensive, unexercised.
Source reproduction, preservation, original locks/licenses/NOTICE are retained.
Models/executables/generated trees remain ignored; identities are hash recorded.
