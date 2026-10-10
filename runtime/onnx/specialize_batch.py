"""Bind known exported batch dimension expressions to batch=1; retain other facts."""
import argparse
import json
from pathlib import Path
import re

import onnx
from normalize_sequences import sha


def specialize(model):
    count = 0
    for value in [*model.graph.input, *model.graph.value_info, *model.graph.output]:
        if not value.type.HasField("tensor_type"):
            continue
        for dim in value.type.tensor_type.shape.dim:
            if not dim.dim_param:
                continue
            match = re.fullmatch(r"(?:(\d+)\*)?batch", dim.dim_param)
            if not match:
                raise ValueError("unrecognized dimension expression: " + dim.dim_param)
            dim.dim_value = int(match.group(1) or 1)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve().parent != args.output.resolve().parent:
        raise ValueError("source/output must share the external-weight directory")
    if args.output.exists() or args.report.exists():
        raise ValueError("new output and report required")
    model = onnx.load(args.source, load_external_data=False)
    count = specialize(model)
    onnx.save(model, args.output)
    onnx.checker.check_model(str(args.output))
    result = {"batch_size": 1, "bound_dimensions": count, "source_sha256": sha(args.source),
              "output_sha256": sha(args.output), "checker_passed": True,
              "onnx_version": onnx.__version__}
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
