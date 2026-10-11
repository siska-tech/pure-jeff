"""Benchmark-only resident official Jeff session (Python/PyTorch, CPU).
Verifies the bundle once with the reference worker's checks, constructs DecisionModel once and
decides each job request with the same official calls as runtime/jeff_worker.py. Emits JSON lines."""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
import jeff_worker as worker  # noqa: E402


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    manifest_path, job_path = map(Path, sys.argv[1:3])
    started = time.perf_counter()
    manifest = worker.verify_bundle(manifest_path)
    source, checkpoint = Path(manifest["source"]), Path(manifest["checkpoint"])
    versions = worker.check_dependencies(source)
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
    emit({"event": "init", "verify_s": verify_s, "import_s": import_s, "model_load_s": load_s,
          "startup_s": time.perf_counter() - started, "torch_threads": torch.get_num_threads(),
          "torch_interop_threads": torch.get_num_interop_threads(), "versions": versions,
          "parallel_info": torch.__config__.parallel_info()})
    for case in json.loads(job_path.read_text(encoding="utf-8")):
        request = case["request"]
        begin = time.perf_counter()
        row = worker.make_row(request)
        batch = model.prepare([row], max_length=8192)
        prepared = time.perf_counter()
        with torch.inference_mode():
            logits = model(batch)  # backbone, Decision Head and option mask
        forwarded = time.perf_counter()
        probabilities = (logits / model.temperature).softmax(-1).cpu().tolist()[0][:len(request["candidates"])]
        observation = worker.pack_observation(request, probabilities, model.temperature, batch.input_tokens,
                                              manifest["policy"], [])
        done = time.perf_counter()
        emit({"event": "decision", "name": case["name"], "prompt_tokenize_s": prepared - begin,
              "forward_s": forwarded - prepared, "readout_policy_s": done - forwarded, "total_s": done - begin,
              "input_tokens": batch.input_tokens, "probabilities": probabilities,
              "judgment": observation["judgment"]})


if __name__ == "__main__":
    main()
