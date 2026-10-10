# Native FP32 retention experiment

One isolated executable: original-equation mmap control vs owned CPU FP32
model/readout tensors. Native reference/API/existing exe unchanged.
All473 checkpoint model tensors were retained: static inventory identifies
320 text-used tensors and 153 unused visual tensors; text-only filtering is
future unmeasured work, not a change to this experiment.
Nine generated files exactly reproduced, four release tests plus clippy/fmt pass.
Backbone source text (LF-normalized) restores exactly after reversing type/
import/unused-entry annotation changes. Lock versions unchanged; candle-nn
only made explicit at root, already an existing dependency.
Four goldens + four common512 inputs gate both modes. All 46 forwards match
frozen Native probabilities exactly and ONNX probability/judgment/token gates.
Three independent AB/BA/AB pairs, one warmup + four mixed measured/session,
n=12/mode, per-input n=3. Process startup includes verification/tokenizer and
candidate FP32 retention cost; lifetime peak includes temporary mmap/conversion.
No concurrent builds/tests/audits during timing. Initial development build had
only an unused forward-entry warning; before measurement generated-v2 adds
annotation/format, release build/clippy have no warnings. No failed model run.
Local warm acceptance is preregistered all paired medians plus pooled median/
p95 improvement, gates/guards pass; not formal SLO/backend/product acceptance.
n=12 nearest-rank p95=max, only three pairs, one warmup, synthetic content,
uncontrolled thermals/affinity/background/storage cache. No Tract comparison,
API E2E, cold campaign, recognition quality or distribution acceptance.
Raw records/statistics/preservation independently revalidated, hashes indexed.
