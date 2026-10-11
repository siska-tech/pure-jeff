"""Real-tokenizer boundary checks for migration; no model forward is permitted."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch

import jeff_worker as worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = worker.verify_bundle(args.manifest)
    worker.check_dependencies(Path(manifest["source"]))
    golden = worker.read_json(args.golden)
    if worker.digest(args.manifest) != golden["provenance"]["manifest_sha256"]:
        raise ValueError("manifest/reference mismatch")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(Path(manifest["source"]) / "src"))
    import jeff.model as upstream

    calls = []
    class GuardedModel(upstream.DecisionModel):
        def forward(self, *unused_args, **unused_kwargs):
            calls.append(True)
            raise AssertionError("boundary checks must not start a forward")

    request = golden["request"]
    tokens = golden["official"]["input_tokens"]
    model = GuardedModel(checkpoint=Path(manifest["checkpoint"]), device="cpu", cpu_threads=1)
    row = worker.make_row(request)
    assert model.prepare([row], max_length=tokens).input_tokens == tokens
    try:
        model.prepare([row], max_length=tokens-1)
    except ValueError as error:
        assert "token limit" in str(error)
    else:
        raise AssertionError("one-token undersized budget accepted")
    largest = copy.deepcopy(request)
    largest["candidates"] = [{"id":f"c{i}", "text":request["original_text"] if i==0 else f"candidate {i}"}
                             for i in range(255)]
    largest_batch = model.prepare([worker.make_row(largest)], max_length=8192)
    assert largest_batch.counts == (255,)
    largest["candidates"].append({"id":"c255", "text":"extra"})
    try:
        worker.make_row(largest)
    except worker.Rejected as error:
        assert error.failure == "invalid_request"
    else:
        raise AssertionError("256 candidates accepted")
    # Independent worker load with a guard proves its token preflight precedes forward.
    del model
    import gc
    gc.collect()
    wire = {"schema_version":worker.SCHEMA, "request":request,
            "max_input_tokens":tokens-1, "max_forwards":1, "timeout_ms":120000}
    with patch.object(upstream, "DecisionModel", GuardedModel):
        try:
            worker.infer(wire, args.manifest)
        except worker.Rejected as error:
            assert error.failure == "budget_exceeded"
        else:
            raise AssertionError("worker accepted undersized token budget")
    assert not calls
    probabilities = golden["official"]["probabilities"]
    best, second = sorted(probabilities, reverse=True)[:2]
    policy = {"min_probability":best, "min_margin":best-second, "cpu_threads":1}
    pack = lambda p, policy: worker.pack_observation(request,p,golden["temperature"],tokens,policy,[])["judgment"]["kind"]
    assert pack(probabilities,policy) == "selected"
    assert pack(probabilities,{**policy,"min_probability":math.nextafter(best,1.0)}) == "abstained"
    assert pack(probabilities,{**policy,"min_margin":math.nextafter(best-second,1.0)}) == "abstained"
    assert pack([0.5,0.5],{"min_probability":0,"min_margin":0,"cpu_threads":1}) == "abstained"
    result = {"schema_version":"kaze_judge.jeff_boundaries.v1", "manifest_sha256":worker.digest(args.manifest),
              "golden_sha256":worker.digest(args.golden), "checker_sha256":worker.digest(Path(__file__)),
              "exact_token_limit":tokens, "undersized_token_limit":tokens-1,
              "worker_undersized_result":"budget_exceeded", "forward_guard_calls":len(calls),
              "maximum_candidates":255, "maximum_candidates_input_tokens":largest_batch.input_tokens,
              "over_maximum_candidates":"invalid_request", "threshold_equality":"selected",
              "probability_threshold_nextafter":"abstained", "margin_threshold_nextafter":"abstained",
              "tie":"abstained"}
    encoded = json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        stream.write(encoded)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
