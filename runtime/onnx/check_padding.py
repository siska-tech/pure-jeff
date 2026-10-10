"""Gate B: compare the frozen checkpoint before/after left padding, CPU only.

Run with the frozen vendor Python; no ONNX dependency or modified model kernel.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
import jeff_worker as worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("new output required")
    manifest = worker.verify_bundle(args.manifest)
    versions = worker.check_dependencies(Path(manifest["source"]))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(Path(manifest["source"]) / "src"))
    import torch
    from jeff.model import DecisionModel
    model = DecisionModel(checkpoint=Path(manifest["checkpoint"]), device="cpu",
                          cpu_threads=manifest["policy"]["cpu_threads"])
    model.eval()
    cases = []
    with torch.inference_mode():
        for name in ["candidate-request", "reversed", "asr-unicode", "special-token-text"]:
            golden_path = ROOT / "tests/fixtures/jeff-golden" / (name + ".json")
            golden = json.loads(golden_path.read_text(encoding="utf-8"))
            batch = model.prepare([golden["row"]], max_length=512)
            for key, tensor in batch.inputs.items():
                if tensor.tolist() != golden["official"]["inputs"][key]:
                    raise ValueError("golden input mismatch: " + key)
            raw = model.readout(model.backbone(**batch.inputs, use_cache=False).last_hidden_state[:, -1]).float()
            pad = 512 - batch.inputs["input_ids"].shape[1]
            padded = {}
            for key, tensor in batch.inputs.items():
                if key not in ("input_ids", "attention_mask", "mm_token_type_ids"):
                    raise ValueError("unexpected text input: " + key)
                fill = model.processor.tokenizer.pad_token_id if key == "input_ids" else 0
                if fill is None:
                    raise ValueError("missing pad token ID")
                padded[key] = torch.cat([torch.full((1, pad), fill, dtype=tensor.dtype), tensor], dim=1)
            padded_raw = model.readout(model.backbone(**padded, use_cache=False).last_hidden_state[:, -1]).float()
            count = len(golden["request"]["candidates"])
            mask = torch.arange(255)[None] >= count
            expected = (raw.masked_fill(mask, -1e9) / model.temperature).softmax(-1)[0, :count]
            actual = (padded_raw.masked_fill(mask, -1e9) / model.temperature).softmax(-1)[0, :count]
            regression_error = max(abs(a-b) for a,b in zip(expected.tolist(), golden["official"]["probabilities"]))
            error = (actual - expected).abs().max().item()
            judgment = worker.pack_observation(golden["request"], actual.tolist(), model.temperature,
                                               batch.input_tokens, manifest["policy"], [])["judgment"]
            passed = (torch.isfinite(raw).all().item() and torch.isfinite(padded_raw).all().item()
                      and regression_error <= 1e-4 and error <= 1e-4 and judgment == golden["official"]["judgment"])
            result = {"case": name, "golden_sha256": worker.digest(golden_path), "input_tokens": batch.input_tokens,
                      "padding_tokens": pad, "padding_mm_token_type_id": 0,
                      "unpadded_golden_probability_error": regression_error, "padding_probability_error": error,
                      "raw_logits_error": (raw-padded_raw).abs().max().item(), "judgment": judgment,
                      "unpadded_raw_logits": raw.tolist()[0], "padded_raw_logits": padded_raw.tolist()[0],
                      "passed": bool(passed)}
            cases.append(result)
            print(json.dumps({k:v for k,v in result.items() if not k.endswith("raw_logits")}), flush=True)
    record = {"schema_version": "kaze_judge.onnx_padding.v1", "series": "B", "device": "cpu",
              "dtype": "float32", "manifest_sha256": worker.digest(args.manifest),
              "harness_sha256": worker.digest(Path(__file__)), "dependencies": versions,
              "probability_tolerance": 1e-4, "cases": cases, "passed": all(c["passed"] for c in cases)}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    if not record["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
