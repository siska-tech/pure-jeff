# Fixed512 effective-token length pilot

Development CPU ORT reference: 4 frozen goldens + 24 Rust-generated full requests.
Windows venv launcher first attempt was manually stopped because its process
counter did not cover the real child; initial source/partial outputs/process
identities retained. Accepted run uses direct base Python, actual ORT process
memory guarded. This changes no measured Native/Tract Rust executable.
First Tract gate stopped after four goldens because the harness omitted the
driver count field for new fixtures. Source/job/error retained; no performance
samples. Explicit count adapter fixed; runtime and fixtures unchanged.
Accepted Tract numerical gate 28 forwards precedes all timing. Same accepted
Scatter binary and NNEF, 4 threads, batch1 FP32 physical512. Three independent sessions,
5 model warmups + 20 mixed inputs/session; n=12/length across four inputs.
4 processes / 103 forwards = gate28 + warmup15 + measured60. Eight-candidate
extra cases gate-only; not included in primary timing. All repeated raw logits
exact to Tract gate, probability/judgment/token gates vs ORT pass. Raw records,
oracle probabilities/policy and all statistics independently revalidated.
n=12 nearest-rank p95 is max; only three independent sessions, content/length
confounded, no quality ground truth. Thermals/affinity/cache/background load
uncontrolled. No concurrent builds/tests/audits during timed runs. Startup and
lifetime peaks n=3 incidental, not a cold campaign; no per-length memory peak.
Prepared stages exclude tokenizer/API/IPC/parent policy. No Native comparison,
speedup, formal SLO, API integration or recognition-quality acceptance.
Source/lock/model/binary identities and preservation are hash recorded.
