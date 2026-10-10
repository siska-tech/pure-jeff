"""Gate the upstream delta-rule substitution, then export the frozen checkpoint.

CPU development tooling only. Use the frozen vendor Python with the isolated
ONNX-tools directory on PYTHONPATH. No changes to the Native runtime or venv.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
import jeff_worker as worker


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--padding-gate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    manifest = worker.verify_bundle(args.manifest)
    versions = worker.check_dependencies(Path(manifest["source"]))
    gate = json.loads(args.padding_gate.read_text(encoding="utf-8"))
    if not gate["passed"] or gate["manifest_sha256"] != worker.digest(args.manifest):
        raise ValueError("passing padding gate for this exact checkpoint required")
    upstream = Path(__file__).parent / "upstream/export_onnx.py"
    if worker.digest(upstream) != "a090d94903b31b167e8eec0994ac2dff41782d197c3ad626d04a960a49cffa0b":
        raise ValueError("upstream source hash mismatch")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(Path(manifest["source"]) / "src"))
    spec = importlib.util.spec_from_file_location("jeff_onnx_upstream", upstream)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    import torch
    from jeff.model import DecisionModel
    model = DecisionModel(checkpoint=Path(manifest["checkpoint"]), device="cpu",
                          cpu_threads=manifest["policy"]["cpu_threads"])
    model.eval()
    exporter.patch_chunked_delta_rule()
    wrapped = exporter.JeffExport(model.backbone, model.readout).eval()
    results, example = [], None
    with torch.inference_mode():
        for case in gate["cases"]:
            golden = json.loads((ROOT / "tests/fixtures/jeff-golden" / (case["case"] + ".json")).read_text(encoding="utf-8"))
            batch = model.prepare([golden["row"]], max_length=512)
            padded = {}
            for key, tensor in batch.inputs.items():
                fill = model.processor.tokenizer.pad_token_id if key == "input_ids" else 0
                pad = 512 - tensor.shape[1]
                padded[key] = torch.cat([torch.full((1, pad), fill, dtype=torch.int64), tensor], dim=1)
            raw = wrapped(**padded).float()
            expected = torch.tensor([case["padded_raw_logits"]], dtype=torch.float32)
            count = len(golden["request"]["candidates"])
            mask = torch.arange(255)[None] >= count
            actual_probs = (raw.masked_fill(mask, -1e9) / model.temperature).softmax(-1)[0, :count]
            expected_probs = (expected.masked_fill(mask, -1e9) / model.temperature).softmax(-1)[0, :count]
            error = (actual_probs - expected_probs).abs().max().item()
            judgment = worker.pack_observation(golden["request"], actual_probs.tolist(), model.temperature,
                                               batch.input_tokens, manifest["policy"], [])["judgment"]
            passed = bool(torch.isfinite(raw).all() and error <= 1e-4 and judgment == case["judgment"])
            result = {"case": case["case"], "probability_error": error,
                      "raw_logits_error": (raw - expected).abs().max().item(),
                      "raw_logits": raw.tolist()[0], "passed": passed}
            results.append(result)
            print(json.dumps({k:v for k,v in result.items() if k != "raw_logits"}), flush=True)
            if example is None:
                example = tuple(padded[n] for n in ["input_ids", "attention_mask", "mm_token_type_ids"])
    args.output_dir.mkdir(parents=True)
    record = {"schema_version": "kaze_judge.onnx_export_patch_gate.v1", "device": "cpu", "dtype": "float32",
              "manifest_sha256": worker.digest(args.manifest), "padding_gate_sha256": worker.digest(args.padding_gate),
              "exporter_sha256": worker.digest(upstream), "wrapper_sha256": worker.digest(Path(__file__)),
              "dependencies": versions, "probability_tolerance": 1e-4, "cases": results,
              "passed": all(c["passed"] for c in results)}
    write_new(args.output_dir / "patch-gate.json", record)
    if not record["passed"]:
        raise SystemExit(1)
    if args.export:
        import onnx
        output = args.output_dir / "model.onnx"
        started = time.monotonic()
        with torch.no_grad():
            torch.onnx.export(wrapped, example, str(output), input_names=["input_ids", "attention_mask", "mm_token_type_ids"],
                              output_names=["logits"], opset_version=18, dynamo=True, optimize=False,
                              external_data=True)
        onnx.checker.check_model(str(output))
        assets = [{"path": p.name, "bytes": p.stat().st_size, "sha256": worker.digest(p)}
                  for p in sorted(args.output_dir.glob("model.onnx*"))]
        write_new(args.output_dir / "export.json", {"checkpoint_manifest_sha256": worker.digest(args.manifest),
                  "assets": assets, "elapsed_seconds": time.monotonic()-started, "checker_passed": True,
                  "batch_size": 1, "sequence_length": 512, "opset": 18, "forward_parity_checked": False})


if __name__ == "__main__":
    main()
