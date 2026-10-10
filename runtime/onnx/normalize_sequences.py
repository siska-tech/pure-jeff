"""Development-only lowering of statically bounded ONNX tensor sequences.

Accept only SplitToSequence -> constant SequenceAt, keepdims=1, known axis
extent and positive split sizes. Reject all other consumers/dynamic indices.
Weights remain external; the source and destination must share a directory.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper


def lower(model):
    if not any(o.domain == "" and o.version == 18 for o in model.opset_import):
        raise ValueError("this lowering is validated for default-domain opset 18 only")
    graph = model.graph
    if any(a.type in (onnx.AttributeProto.GRAPH, onnx.AttributeProto.GRAPHS)
           for n in graph.node for a in n.attribute):
        raise ValueError("nested graphs are outside this top-level lowering")
    constants = {t.name: numpy_helper.to_array(t) for t in graph.initializer
                 if t.data_location != onnx.TensorProto.EXTERNAL}
    for node in graph.node:
        if node.op_type == "Constant" and node.domain == "":
            attrs = {a.name: helper.get_attribute_value(a) for a in node.attribute}
            if "value" in attrs:
                constants[node.output[0]] = numpy_helper.to_array(attrs["value"])
    infos = {v.name: v for v in [*graph.input, *graph.value_info, *graph.output]}
    names = {s for n in graph.node for s in [*n.input, *n.output]}
    names.update(t.name for t in graph.initializer)
    consumers = {}
    for node in graph.node:
        for name in node.input:
            consumers.setdefault(name, []).append(node)
    replacements, sequence_names, initializers = {}, set(), []
    splits = selections = 0
    for ordinal, node in enumerate(graph.node):
        if node.op_type != "SplitToSequence" or node.domain:
            continue
        if len(node.input) != 2 or len(node.output) != 1:
            raise ValueError("explicit split and one sequence output required")
        attrs = {a.name: helper.get_attribute_value(a) for a in node.attribute}
        if attrs.get("keepdims", 1) != 1:
            raise ValueError("keepdims=0 unsupported")
        value = infos.get(node.input[0])
        if value is None or not value.type.HasField("tensor_type"):
            raise ValueError("tensor shape required")
        dims = value.type.tensor_type.shape.dim
        axis = attrs.get("axis", 0)
        if not -len(dims) <= axis < len(dims):
            raise ValueError("invalid split axis")
        extent = dims[axis].dim_value
        if extent <= 0:
            raise ValueError("static positive axis extent required")
        split = constants.get(node.input[1])
        if split is None or split.dtype.kind not in "iu" or split.ndim > 1:
            raise ValueError("constant integer scalar/vector split required")
        if split.ndim == 0:
            size = int(split)
            if size <= 0:
                raise ValueError("nonpositive split")
            sizes = [min(size, extent - start) for start in range(0, extent, size)]
        else:
            sizes = [int(s) for s in split]
            if not sizes or min(sizes) <= 0 or sum(sizes) != extent:
                raise ValueError("split sizes must partition the axis")
        sequence = node.output[0]
        if sequence in {v.name for v in graph.output}:
            raise ValueError("sequence graph output unsupported")
        users = consumers.get(sequence, [])
        if not users:
            raise ValueError("unused sequence unsupported")
        prefix = f"__kaze_sequence_{ordinal}"
        generated = [prefix + "_sizes", *[f"{prefix}_{i}" for i in range(len(sizes))]]
        if any(s in names for s in generated):
            raise ValueError("generated name collision")
        names.update(generated)
        outputs = generated[1:]
        for user in users:
            if user.domain or user.op_type != "SequenceAt" or len(user.input) != 2 or user.input[0] != sequence:
                raise ValueError("non-SequenceAt consumer unsupported")
            index = constants.get(user.input[1])
            if index is None or index.ndim != 0 or index.dtype.kind not in "iu":
                raise ValueError("constant scalar integer index required")
            i = int(index)
            if not -len(sizes) <= i < len(sizes):
                raise ValueError("sequence index out of range")
            replacements[tuple(user.output)] = helper.make_node("Identity", [outputs[i]], list(user.output), name=user.name)
            selections += 1
        replacements[tuple(node.output)] = helper.make_node("Split", [node.input[0], generated[0]], outputs,
                                                  name=node.name, axis=axis)
        initializers.append(numpy_helper.from_array(np.array(sizes, dtype=np.int64), generated[0]))
        sequence_names.add(sequence)
        splits += 1
    nodes = [replacements.get(tuple(n.output), n) for n in graph.node]
    del graph.node[:]
    graph.node.extend(nodes)
    graph.initializer.extend(initializers)
    values = [v for v in graph.value_info if v.name not in sequence_names]
    del graph.value_info[:]
    graph.value_info.extend(values)
    if any(n.op_type in ("SequenceAt", "SplitToSequence") and not n.domain for n in graph.node):
        raise ValueError("unhandled sequence operation remains")
    return {"split_to_sequence_lowered": splits, "sequence_at_lowered": selections}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve().parent != args.output.resolve().parent:
        raise ValueError("preserve relative external weight locations: use same directory")
    if args.output.exists() or args.report.exists():
        raise ValueError("new output/report required")
    model = onnx.load(args.source, load_external_data=False)
    for tensor in model.graph.initializer:
        if tensor.data_location == onnx.TensorProto.EXTERNAL:
            external = {item.key: item.value for item in tensor.external_data}
            location = Path(external["location"])
            if location.is_absolute() or not (args.source.parent / location).resolve().is_relative_to(args.source.parent.resolve()):
                raise ValueError("external weight path escapes the model directory")
    result = lower(model)
    onnx.save_model(model, args.output)
    result.update(source_sha256=sha(args.source), output_sha256=sha(args.output),
                  onnx_version=onnx.__version__, checker_passed=False)
    try:
        onnx.checker.check_model(str(args.output))
        result["checker_passed"] = True
    except Exception as error:
        result["checker_error"] = str(error)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    if not result["checker_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
