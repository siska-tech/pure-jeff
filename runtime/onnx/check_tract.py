"""Development-only whole-model Tract parity gate; not a performance benchmark."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from check_oracle import probabilities, worker, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--padding-gate", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    manifest = worker.verify_bundle(args.manifest)
    oracle = json.loads(args.oracle.read_text(encoding="utf-8"))
    if (not oracle["passed"] or len(oracle["cases"]) != 4
            or oracle["manifest_sha256"] != worker.digest(args.manifest)
            or oracle["model_sha256"] != worker.digest(args.model)):
        raise ValueError("matching passed four-case oracle required")
    padding_path = args.padding_gate
    padding = json.loads(padding_path.read_text(encoding="utf-8"))
    if worker.digest(padding_path) != oracle["padding_gate_sha256"]:
        raise ValueError("padding gate hash mismatch")
    results = []
    for case in oracle["cases"]:
        name = case["case"]
        golden_path = ROOT / "tests/fixtures/jeff-golden" / f"{name}.json"
        baseline = next(c for c in padding["cases"] if c["case"] == name)
        if worker.digest(golden_path) != baseline["golden_sha256"]:
            raise ValueError("golden hash mismatch")
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        values = {}
        for key, batch in golden["official"]["inputs"].items():
            if len(batch) != 1 or len(batch[0]) > 512:
                raise ValueError("expected batch one, at most 512 tokens")
            fill = oracle["pad_token_id"] if key == "input_ids" else 0
            values[key] = [fill] * (512-len(batch[0])) + batch[0]
        inputs = args.output_dir / f"{name}.inputs.json"
        inputs.write_text(json.dumps(values), encoding="utf-8")
        probe = args.output_dir / f"{name}.probe.json"
        subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("run_probe.py")),
                        "--executable", str(args.executable), "--model", str(args.model),
                        "--stage", "run-typed", "--inputs", str(inputs), "--timeout", "180",
                        "--output", str(probe)], stdout=subprocess.DEVNULL, check=True)
        record = json.loads(probe.read_text(encoding="utf-8"))
        output = json.loads(record["stdout"])
        raw = np.array(output["raw_logits"], dtype=np.float32)
        if not output["forward_executed"] or raw.shape != (255,) or not np.isfinite(raw).all():
            raise ValueError("invalid Tract logits")
        count = len(golden["request"]["candidates"])
        actual = probabilities(raw, count, golden["temperature"])
        reference = probabilities(np.array(case["raw_logits"]), count, golden["temperature"])
        errors = {"oracle_probability_error": float(np.max(np.abs(actual-reference))),
                  "golden_probability_error": float(np.max(np.abs(actual-np.array(golden["official"]["probabilities"])))),
                  "raw_logit_max_abs_error": float(np.max(np.abs(raw-np.array(case["raw_logits"]))))}
        judgment = worker.pack_observation(golden["request"], actual.tolist(), golden["temperature"],
                                           golden["official"]["input_tokens"], manifest["policy"], [])["judgment"]
        result = {"case": name, **errors, "judgment": judgment,
                  "passed": max(errors["oracle_probability_error"], errors["golden_probability_error"]) <= 1e-4
                  and judgment == golden["official"]["judgment"], "probe_sha256": worker.digest(probe)}
        results.append(result)
        print(json.dumps(result), flush=True)
    summary = {"schema_version": "kaze_judge.tract_parity.v1", "stage": "run-typed",
               "model_sha256": worker.digest(args.model), "oracle_sha256": worker.digest(args.oracle),
               "manifest_sha256": worker.digest(args.manifest), "harness_sha256": worker.digest(Path(__file__)),
               "probability_tolerance": 1e-4, "cases": results,
               "passed": all(c["passed"] for c in results), "performance_benchmark": False}
    (args.output_dir / "parity.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
