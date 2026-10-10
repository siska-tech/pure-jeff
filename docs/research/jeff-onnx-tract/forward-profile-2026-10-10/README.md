# Forward profile / thread pilot evidence

Continuous experiment from the 2026-10-10 work session; actual UTC start is in
preregistration.json (local date crossed to 2026-10-11). Fixed step1113, batch1,
physical512, decluttered NNEF. Accepted duplicate-removal base, no suffix change.
Frozen feature-off control and feature-on 1/2/4/8 pools each pass four goldens.
Eight independent resident sessions in ascending/reversed order, each one warmup
and three samples of candidate-request. Six measured forwards per thread; nearest
rank p95 is max. Separate one-thread profile session: one warmup, three samples.
Top-level wall time includes child plans; no nested-op CPU attribution. 14
processes and 56 forwards including gates/warmups. Prepared tensors exclude
tokenizer and API E2E. Startup n=2 per thread is incidental, not a cold campaign.
No formal SLO or recognition-quality acceptance. Host power policy was Balanced;
thermals, affinity and background load uncontrolled. Source hashes, incremental
diff, lockfiles, new dependency license texts and raw/validated records retained.
Model weights, generated full trees and binaries remain ignored.
