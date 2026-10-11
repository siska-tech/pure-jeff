"""Generate one real-model reference case for the Rust migration (development only).

Uses the official predict path with hooks, then independently runs jeff_worker.infer.
Requires a locked local bundle and its exact Python dependencies. No downloads.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import math
import os
from pathlib import Path
import sys
import json

import jeff_worker as worker

SCHEMA = "kaze_judge.jeff_golden.v1"


def compare_probabilities(official, observation, tolerance):
    actual = [score["option_probability"] for score in observation["scores"]]
    if (not math.isfinite(tolerance) or tolerance < 0
            or len(official) != len(actual) or not official
            or any(not math.isfinite(p) or not 0 <= p <= 1 for p in official + actual)
            or abs(sum(official) - 1) > 1e-6 or abs(sum(actual) - 1) > 1e-6):
        raise ValueError("invalid reference comparison")
    error = max(abs(a-b) for a, b in zip(official, actual))
    if not math.isfinite(error) or error > tolerance:
        raise ValueError(f"official/worker probability mismatch: {error}")
    return error


def export_reference(manifest_path, request_path, output_path, max_tokens, timeout_ms, tolerance):
    if output_path.exists():
        raise FileExistsError("reference output already exists")
    if not worker.positive_int(max_tokens) or not worker.positive_int(timeout_ms):
        raise ValueError("positive token budget and worker timeout required")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("finite, nonnegative tolerance required")
    request = worker.read_json(request_path)
    row = worker.make_row(request)
    manifest = worker.verify_bundle(manifest_path)
    checkpoint, source = Path(manifest["checkpoint"]), Path(manifest["source"])
    config = worker.read_json(checkpoint / "decision_config.json")
    worker.validate_decision_config(config)
    versions = worker.check_dependencies(source)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(source / "src"))
    import torch
    from jeff.model import DecisionModel, decision_messages

    model = DecisionModel(checkpoint=checkpoint, device="cpu",
                          cpu_threads=manifest["policy"]["cpu_threads"])
    model.eval()
    messages = decision_messages(row, model.codes, model.prompt_layout)
    prompt = model.processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    captured = {}

    def prepared_hook(module, args):
        batch = args[0]
        if batch.input_tokens > max_tokens:
            raise worker.Rejected("budget_exceeded")
        if "inputs" in captured:
            raise ValueError("reference must use exactly one official forward")
        captured["inputs"] = {key: tensor.detach().cpu().tolist()
                              for key, tensor in batch.inputs.items()}
        captured["input_tensor_specs"] = {key: {"dtype": str(tensor.dtype), "shape": list(tensor.shape)}
                                          for key, tensor in batch.inputs.items()}
        captured["input_tokens"] = batch.input_tokens
        captured["counts"] = list(batch.counts)

    def hidden_hook(module, args, result):
        captured["last_hidden_state"] = result.last_hidden_state[:, -1].detach().float().cpu().tolist()

    def readout_hook(module, args, result):
        captured["unmasked_logits"] = result.detach().float().cpu().tolist()

    def masked_hook(module, args, result):
        captured["masked_logits"] = result.detach().float().cpu().tolist()

    # Token preflight before official predict; hooks record its actual prepared inputs.
    model.prepare([row], max_length=min(max_tokens, 8192))
    handles = [model.register_forward_pre_hook(prepared_hook),
               model.backbone.register_forward_hook(hidden_hook),
               model.readout.register_forward_hook(readout_hook),
               model.register_forward_hook(masked_hook)]
    try:
        official = model.predict([row], batch_size=1)[0]
    finally:
        for handle in handles:
            handle.remove()
    temperature = model.temperature
    codes, token_ids = list(model.codes), list(model.token_ids)
    # Release the reference model before worker's independent cold load.
    del handles, model
    gc.collect()
    wire = {"schema_version": worker.SCHEMA, "request": request,
            "max_input_tokens": max_tokens, "max_forwards": 1, "timeout_ms": timeout_ms}
    observation = worker.infer(wire, manifest_path)
    error = compare_probabilities(official, observation, tolerance)
    expected = worker.pack_observation(request, official, temperature, captured["input_tokens"],
                                       manifest["policy"], [])
    if (observation["judgment"] != expected["judgment"]
            or observation["input_tokens"] != captured["input_tokens"]
            or observation["temperature"] != temperature
            or observation["forwards"] != 1
            or [s["candidate_id"] for s in observation["scores"]]
                != [c["id"] for c in request["candidates"]]):
        raise ValueError("official/worker contract mismatch")
    record = {"schema_version": SCHEMA, "request": request, "row": row,
              "messages": messages, "prompt": prompt,
              "prompt_utf8_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
              "prompt_layout": config.get("prompt_layout", "state-first"),
              "codes": codes, "token_ids": token_ids, "temperature": temperature,
              "official": {**captured, "probabilities": official, "judgment": expected["judgment"]},
              "worker_observation": observation,
              "comparison": {"max_absolute_error": error, "tolerance": tolerance},
              "provenance": {"manifest_sha256": worker.digest(manifest_path),
                             "source_revision": manifest["source_revision"],
                             "exporter_sha256": worker.digest(Path(__file__)),
                             "python": sys.version, "dependencies": versions,
                             "device": "cpu", "dtype": "float32",
                             "cpu_threads": manifest["policy"]["cpu_threads"]}}
    # Exclusive output and allow_nan=False prevent overwriting or recording invalid numbers.
    encoded = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-input-tokens", type=int, default=512)
    parser.add_argument("--timeout-ms", type=int, default=120000)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args()
    result = export_reference(args.manifest, args.request, args.output,
                              args.max_input_tokens, args.timeout_ms, args.tolerance)
    print(json.dumps({"schema_version": SCHEMA, "input_tokens": result["official"]["input_tokens"],
                      "comparison": result["comparison"]}))


if __name__ == "__main__":
    main()
