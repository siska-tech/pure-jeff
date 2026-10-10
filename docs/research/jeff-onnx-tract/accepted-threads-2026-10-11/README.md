# Accepted Scatter binary: four/eight-thread follow-up

Identical accepted binary, generated tree, NNEF model and dependency lock.
Four-golden gates at each thread count, then unprofiled AB/BA/AB three independent
pairs; warmup1 + samples3/session, n=9/thread. 8 processes / 32 forwards.
All raw logits exact, no guard failure. Statistics and preregistered selection
independently recomputed from raw records. No operator profiling in these runs.
Selection is a local pilot preference only, not product configuration or SLO.
n=9 nearest-rank p95 is max. Startup/peaks n=3 are incidental, not cold campaign.
Prepared effective128 physical512 inputs; thermals, affinity, background load,
storage cache uncontrolled. No Native/API/tokenizer E2E or recognition quality
acceptance. New length fixtures are preparation only: no numeric oracle, model
forward or input-length performance acceptance. The Rust generator uses frozen
Native prompt/tokenizer and does not initialize/run the model. Bundle verification hashes weights
and memory maps tensor shape/dtype metadata. Golden prompts/IDs and
exact/one-short/513 token budget boundaries are checked.
