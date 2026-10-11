"""Exact-name ONNX provenance for profile nodes; shape metadata is not inferred."""
import argparse
from collections import Counter
import json
from pathlib import Path

import onnx

from benchmark_pilot import save, sha


def metadata(value):
    if not value.type.HasField("tensor_type"):
        return None
    tensor = value.type.tensor_type
    return {"dtype": tensor.elem_type,
        "shape": [d.dim_value if d.HasField("dim_value") else d.dim_param or None for d in tensor.shape.dim]
            if tensor.HasField("shape") else None}


def inspect(model, names):
    nodes = {}
    for node in model.graph.node:
        if node.name in nodes:
            raise ValueError("duplicate ONNX node name")
        nodes[node.name] = node
    values = {v.name: metadata(v) for v in
        list(model.graph.input)+list(model.graph.value_info)+list(model.graph.output)}
    for value in model.graph.initializer:
        values[value.name] = {"dtype":value.data_type,"shape":list(value.dims),"initializer":True}

    def describe(node):
        attributes = {}
        for attr in node.attribute:
            if attr.type == onnx.AttributeProto.INT:
                attributes[attr.name] = attr.i
            elif attr.type == onnx.AttributeProto.INTS:
                attributes[attr.name] = list(attr.ints)
            elif attr.type == onnx.AttributeProto.STRING:
                attributes[attr.name] = attr.s.decode("utf-8")
        return {"name":node.name,"op":node.op_type,"domain":node.domain,"attributes":attributes,
            "inputs":[{"name":v,"metadata":values.get(v)} for v in node.input],
            "outputs":[{"name":v,"metadata":values.get(v)} for v in node.output]}

    return {"node_counts":dict(sorted(Counter(n.op_type for n in model.graph.node).items())),
        "matched_profile_nodes":[describe(nodes[name]) for name in sorted(names) if name in nodes],
        "unmatched_profile_names":sorted(names-set(nodes)),
        "array_nodes":[describe(n) for n in model.graph.node if n.op_type in ["ScatterElements","Trilu","Transpose"]],
        "scope":"ONNX stored metadata only; no inferred shape, no external tensor load; exact names only; optimizer nodes may be unmatched"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--expected-model-sha256",required=True)
    parser.add_argument("--profiles",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists() or sha(args.model) != args.expected_model_sha256:
        raise ValueError("new output and matching model hash required")
    names, logs = set(), []
    for path in sorted(args.profiles.glob("*.stdout.jsonl")):
        logs.append({"path":path.name,"sha256":sha(path)})
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("forward_profile") and not event["warmup"]:
                names.update(n["name"] for n in event["forward_profile"]["top_nodes"])
    if not names:
        raise ValueError("no measured profile nodes")
    model = onnx.load(args.model,load_external_data=False)
    result = inspect(model,names)
    result.update(model_sha256=args.expected_model_sha256,script_sha256=sha(__file__),source_logs=logs)
    save(args.output,result)
    print(json.dumps({"matched":len(result["matched_profile_nodes"]),
        "unmatched":len(result["unmatched_profile_names"]),"array_nodes":len(result["array_nodes"])}))


if __name__ == "__main__":
    main()
