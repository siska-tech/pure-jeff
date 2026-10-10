"""Gate C: CPU ONNX Runtime oracle versus patched and original frozen outputs."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
import jeff_worker as worker


def probabilities(raw, count, temperature):
    logits = raw.astype(np.float32).copy()
    logits[count:] = np.float32(-1e9)
    logits /= np.float32(temperature)
    exp = np.exp(logits - logits.max())
    return (exp / exp.sum())[:count]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--padding-gate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("new output required")
    manifest = worker.verify_bundle(args.manifest)
    export = json.loads((args.model.parent / "export.json").read_text(encoding="utf-8"))
    patch = json.loads((args.model.parent / "patch-gate.json").read_text(encoding="utf-8"))
    padding = json.loads(args.padding_gate.read_text(encoding="utf-8"))
    digest = worker.digest(args.manifest)
    if not patch["passed"] or not padding["passed"] or any(h != digest for h in
            [export["checkpoint_manifest_sha256"], patch["manifest_sha256"], padding["manifest_sha256"]]):
        raise ValueError("matching passed export gates required")
    for asset in export["assets"]:
        if worker.digest(args.model.parent / asset["path"]) != asset["sha256"]:
            raise ValueError("export asset hash mismatch")
    config = Path(manifest["checkpoint"])
    tokenizer = json.loads((config / "tokenizer.json").read_text(encoding="utf-8"))
    tokenizer_config = json.loads((config / "tokenizer_config.json").read_text(encoding="utf-8"))
    vocabulary = dict(tokenizer["model"]["vocab"])
    vocabulary.update({t["content"]: t["id"] for t in tokenizer["added_tokens"]})
    pad_id = vocabulary[tokenizer_config["pad_token"]]
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.log_severity_level = 3
    print("Loading CPU oracle with graph optimizations disabled", flush=True)
    session = ort.InferenceSession(str(args.model), sess_options=options, providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("CPU-only oracle required")
    if sorted(i.name for i in session.get_inputs()) != ["attention_mask", "input_ids", "mm_token_type_ids"]:
        raise ValueError("unexpected model inputs")
    cases = []
    for case in patch["cases"]:
        golden_path = ROOT / "tests/fixtures/jeff-golden" / (case["case"] + ".json")
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        baseline = next(c for c in padding["cases"] if c["case"] == case["case"])
        if worker.digest(golden_path) != baseline["golden_sha256"]:
            raise ValueError("golden hash mismatch")
        inputs = {}
        for name, values in golden["official"]["inputs"].items():
            array = np.array(values, dtype=np.int64)
            fill = pad_id if name == "input_ids" else 0
            inputs[name] = np.pad(array, ((0, 0), (512-array.shape[1], 0)), constant_values=fill)
        (raw,) = session.run(["logits"], inputs)
        if raw.shape != (1, 255) or raw.dtype != np.float32 or not np.isfinite(raw).all():
            raise ValueError("invalid raw logits")
        count = len(golden["request"]["candidates"])
        actual = probabilities(raw[0], count, golden["temperature"])
        patched = probabilities(np.array(case["raw_logits"]), count, golden["temperature"])
        padded = probabilities(np.array(baseline["padded_raw_logits"]), count, golden["temperature"])
        errors = {"onnx_patch_probability_error": float(np.max(np.abs(actual-patched))),
                  "onnx_original_padded_probability_error": float(np.max(np.abs(actual-padded))),
                  "onnx_golden_probability_error": float(np.max(np.abs(actual-np.array(golden["official"]["probabilities"]))))}
        judgment = worker.pack_observation(golden["request"], actual.tolist(), golden["temperature"],
                                           golden["official"]["input_tokens"], manifest["policy"], [])["judgment"]
        result = {"case": case["case"], **errors, "raw_logits": raw[0].tolist(), "judgment": judgment,
                  "passed": max(errors.values()) <= 1e-4 and judgment == golden["official"]["judgment"]}
        cases.append(result)
        print(json.dumps({k:v for k,v in result.items() if k != "raw_logits"}), flush=True)
    record = {"schema_version": "kaze_judge.onnx_oracle.v1", "series": "C", "provider": session.get_providers(),
              "onnxruntime_version": ort.__version__, "numpy_version": np.__version__, "graph_optimization": "disabled",
              "threads": 1, "manifest_sha256": digest, "model_sha256": worker.digest(args.model),
              "harness_sha256": worker.digest(Path(__file__)), "padding_gate_sha256": worker.digest(args.padding_gate),
              "patch_gate_sha256": worker.digest(args.model.parent / "patch-gate.json"),
              "pad_token_id": pad_id, "probability_tolerance": 1e-4, "cases": cases,
              "passed": len(cases) == 4 and all(c["passed"] for c in cases), "performance_benchmark": False}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    if not record["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
