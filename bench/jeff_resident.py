"""Benchmark-only resident official Jeff session (Python/PyTorch, CPU).

    jeff_resident.py --mode api|internal manifest job.json

Verifies the bundle once with the reference worker's checks and constructs DecisionModel once.
`api`: per request, everything `runtime/jeff_worker.py` `infer` does after loading: request
checks, the decision config's option limit, `prepare` within the token budget, the deadline,
one forward and `pack_observation` (distribution, policy and artifact checks). `wall_s` is
measured around that sequence. `internal` (diagnostic): `make_row`, `prepare`, forward and
policy with a timer between stages, without the budget and deadline checks.
The job is `[{"name", "phase", "max_input_tokens", "request"}]`. Emits JSON lines."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
import jeff_worker as worker  # noqa: E402


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["api", "internal"], required=True)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("job", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    deadline = time.monotonic() + 4 * 3600
    manifest = worker.verify_bundle(args.manifest)
    source, checkpoint = Path(manifest["source"]), Path(manifest["checkpoint"])
    versions = worker.check_dependencies(source)
    config = worker.read_json(checkpoint / "decision_config.json")
    maximum = worker.validate_decision_config(config)
    verify_s = time.perf_counter() - started
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(source / "src"))
    step = time.perf_counter()
    import torch
    from jeff.model import DecisionModel
    import_s = time.perf_counter() - step
    step = time.perf_counter()
    model = DecisionModel(checkpoint=checkpoint, device="cpu", cpu_threads=manifest["policy"]["cpu_threads"])
    model.eval()
    load_s = time.perf_counter() - step
    artifacts = [{"component": key, "sha256": value} for key, value in {
        "checkpoint_bundle": worker.canonical_digest(manifest["checkpoint_files"]),
        "jeff_source": worker.canonical_digest(manifest["source_files"]),
        "bundle_manifest": worker.canonical_digest(manifest),
        "worker": manifest["worker_sha256"],
        "prompt": worker.canonical_digest({"id": worker.QUESTION_ID, "instructions": worker.INSTRUCTIONS}),
        "runtime_versions": worker.canonical_digest({"python": sys.version, **versions}),
    }.items()]
    emit({"event": "init", "mode": args.mode, "verify_s": verify_s, "import_s": import_s, "model_load_s": load_s,
          "startup_s": time.perf_counter() - started, "torch_threads": torch.get_num_threads(),
          "torch_interop_threads": torch.get_num_interop_threads(), "versions": versions,
          "kernel": {"cpu_capability": torch.backends.cpu.get_cpu_capability(),
                     "mkldnn": torch.backends.mkldnn.is_available(), "mkl": torch.backends.mkl.is_available(),
                     "parallel_info": torch.__config__.parallel_info()},
          "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})

    def check_time():
        if time.monotonic() >= deadline:
            raise worker.Rejected("timeout")

    for index, case in enumerate(json.loads(args.job.read_text(encoding="utf-8"))):
        request, budget = case["request"], case["max_input_tokens"]
        entry = {"event": "decision", "index": index, "name": case["name"], "phase": case["phase"]}
        begin = time.perf_counter()
        try:
            if args.mode == "api":
                # jeff_worker.infer after the bundle and model are loaded, in the same order.
                row = worker.make_row(request)
                if len(row["question"]["criteria"]) > maximum:
                    raise worker.Rejected("invalid_request")
                check_time()
                try:
                    batch = model.prepare([row], max_length=min(budget, 8192))
                except ValueError as error:
                    if "token limit" in str(error):
                        raise worker.Rejected("budget_exceeded") from error
                    raise
                if batch.input_tokens > budget:
                    raise worker.Rejected("budget_exceeded")
                check_time()
                with torch.inference_mode():
                    probabilities = (model(batch) / model.temperature).softmax(-1).cpu().tolist()[0][
                        :len(row["question"]["criteria"])]
                check_time()
                observation = worker.pack_observation(request, probabilities, model.temperature, batch.input_tokens,
                                                      manifest["policy"], artifacts)
                entry["wall_s"] = time.perf_counter() - begin
            else:
                row = worker.make_row(request)
                batch = model.prepare([row], max_length=8192)
                prepared = time.perf_counter()
                with torch.inference_mode():
                    logits = model(batch)
                forwarded = time.perf_counter()
                probabilities = (logits / model.temperature).softmax(-1).cpu().tolist()[0][:len(request["candidates"])]
                observation = worker.pack_observation(request, probabilities, model.temperature, batch.input_tokens,
                                                      manifest["policy"], [])
                done = time.perf_counter()
                entry["wall_s"] = done - begin
                entry["stages"] = {"prompt_tokenize_s": prepared - begin, "forward_s": forwarded - prepared,
                                   "readout_policy_s": done - forwarded}
        except worker.Rejected as error:
            entry.update(wall_s=time.perf_counter() - begin, outcome={"status": "failed", "failure": error.failure})
            emit(entry)
            continue
        ids = batch.inputs["input_ids"][0].tolist()
        entry["outcome"] = {
            "status": "completed",
            "candidate_ids": [s["candidate_id"] for s in observation["scores"]],
            "probabilities": [s["option_probability"] for s in observation["scores"]],
            "judgment": observation["judgment"], "input_tokens": observation["input_tokens"],
            "forwards": observation["forwards"],
            "input_ids_sha256": hashlib.sha256(b"".join(i.to_bytes(4, "little") for i in ids)).hexdigest()}
        emit(entry)


if __name__ == "__main__":
    main()
