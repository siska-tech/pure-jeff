"""Write bench/cases/catalog.json: the distinct evaluation inputs with their aliases, token IDs
checked by both tokenizers, and the official reference outputs.

Run with the official Jeff interpreter and its 1-thread reference bundle:
    python -B bench/build_catalog.py --manifest models/pure-jeff-reference-bundle-t1.json \
        --jeff-exe runtime/rust/target/release/jeff.exe --rust-manifest models/pure-jeff-bundle-t1.json

For every distinct request (canonical SHA-256) the official processor gives the token IDs
without a length limit, and the Native `jeff prepare` must give the same IDs (inputs over the
8192-token limit must be rejected by both). Accepted inputs are then decided once by the
official model exactly as `runtime/jeff_worker.py` does; those probabilities, judgment and
token count are the reference every benchmark arm is gated against. Earlier stored official
references (golden fixtures, W2) are compared with the new ones and the differences recorded."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import catalog as cat

sys.path.insert(0, str(cat.ROOT / "runtime"))
import jeff_worker as worker  # noqa: E402

PRECEDENCE = ["golden", "golden-reject", "migrated-boundary", "migrated-28", "generated", "comparison-v1", "w2"]
SPECIAL = {"special-token-text"}


def pointer(kind, name, path):
    if path == cat.LENGTH_INPUTS:
        return ["boundary_513", "request"] if kind == "migrated-boundary" else ["cases", name, "request"]
    if kind in ("w2",) or name == "token-limit-8193":
        return []
    return ["request"]


def tags(case_id, request):
    text = request["original_text"] + "".join(c["text"] for c in request["candidates"])
    out = [request["source"], f"candidates-{len(request['candidates'])}"]
    if any(ord(ch) > 127 for ch in text):
        out.append("unicode")
    if any(0x3040 <= ord(ch) <= 0x30ff or 0x4e00 <= ord(ch) <= 0x9fff for ch in text):
        out.append("japanese")
    if case_id in SPECIAL:
        out.append("special-token")
    if case_id == "reversed":
        out.append("candidate-reversed")
    if case_id.startswith("policy-"):
        out.append("policy-boundary")
    return out


def native_prepare(exe, manifest, request):
    with tempfile.TemporaryDirectory(prefix="pj-catalog-") as folder:
        path = Path(folder) / "request.json"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        run = subprocess.run([str(exe), "prepare", str(manifest), str(path), "600000", str(cat.MAX_TOKENS)],
                             capture_output=True, text=True, encoding="utf-8")
    if run.returncode != 0:
        return None, run.stderr.strip()[-500:]
    return json.loads(run.stdout)["token_ids"], None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="official reference bundle, cpu_threads=1")
    parser.add_argument("--jeff-exe", type=Path, required=True)
    parser.add_argument("--rust-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=cat.CATALOG)
    parser.add_argument("--replace", action="store_true", help="overwrite an existing catalog")
    args = parser.parse_args()
    if args.output.exists() and not args.replace:
        raise SystemExit(f"{args.output} exists; pass --replace to rebuild it")
    manifest = worker.verify_bundle(args.manifest)
    if manifest["policy"]["cpu_threads"] != 1:
        raise SystemExit("references are taken at one thread")
    versions = worker.check_dependencies(Path(manifest["source"]))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(Path(manifest["source"]) / "src"))
    import torch
    from jeff.model import DecisionModel
    model = DecisionModel(checkpoint=Path(manifest["checkpoint"]), device="cpu", cpu_threads=1)
    model.eval()

    distinct = {}
    for kind, name, path, request in cat.sources():
        key = cat.request_sha256(request)
        entry = distinct.setdefault(key, {"request": request, "aliases": []})
        entry["aliases"].append({"set": kind, "name": name, "path": path.relative_to(cat.ROOT).as_posix(),
                                 "pointer": pointer(kind, name, path)})
    cases = []
    for key, entry in distinct.items():
        primary = min(entry["aliases"], key=lambda a: PRECEDENCE.index(a["set"]))
        case_id, request = primary["name"], entry["request"]
        if any(c["id"] == case_id for c in cases):
            raise SystemExit(f"two different requests are both named {case_id}")
        row = worker.make_row(request)
        batch = model.prepare([row], max_length=1 << 30)
        ids = batch.inputs["input_ids"][0].tolist()
        native_ids, native_error = native_prepare(args.jeff_exe, args.rust_manifest, request)
        tokens = len(ids)
        accepted = tokens <= cat.MAX_TOKENS
        case = {
            "id": case_id, "request_sha256": key,
            "request_source": {"path": primary["path"], "pointer": primary["pointer"]},
            "aliases": [a for a in entry["aliases"] if a is not primary],
            "tokens": tokens, "group": cat.group_of(tokens), "candidates": len(request["candidates"]),
            "candidate_ids": [c["id"] for c in request["candidates"]], "tags": tags(case_id, request),
            "input_ids_sha256": cat.ids_sha256(ids),
            "token_check": {"official_tokens": tokens, "native_tokens": len(native_ids) if native_ids else None,
                            "native_error": native_error,
                            "ids_equal": native_ids == ids if native_ids is not None else None,
                            "passed": (native_ids == ids) if accepted else (native_ids is None)},
            "expect": {arm: "completed" if tokens <= limit else "budget_exceeded"
                       for arm, limit in (("jeff", cat.MAX_TOKENS), ("native", cat.MAX_TOKENS),
                                          ("wasm", cat.WASM_MAX_TOKENS))},
        }
        if accepted:
            started = time.perf_counter()
            with torch.inference_mode():
                probabilities = (model(batch) / model.temperature).softmax(-1).cpu().tolist()[0][:len(request["candidates"])]
            observation = worker.pack_observation(request, probabilities, model.temperature, tokens,
                                                  manifest["policy"], [])
            ranked = sorted(probabilities, reverse=True)
            case["reference"] = {"probabilities": probabilities, "judgment": observation["judgment"],
                                 "input_tokens": tokens, "top1": ranked[0], "margin": ranked[0] - ranked[1],
                                 "forward_s": time.perf_counter() - started}
            stored = []
            for alias in [primary] + case["aliases"]:
                value = cat.read(cat.ROOT / alias["path"])
                if isinstance(value, dict) and "official" in value:
                    official = value["official"]
                    stored.append({"path": alias["path"], "input_tokens_equal": official["input_tokens"] == tokens,
                                   "judgment_equal": official["judgment"] == observation["judgment"],
                                   "max_abs_diff": max(abs(a - b) for a, b in
                                                       zip(official["probabilities"], probabilities, strict=True))})
            case["reference"]["stored_official"] = stored
        cases.append(case)
        print(f"{case_id}: {tokens} tokens, ids_equal={case['token_check']['ids_equal']}", flush=True)
    order = {name: i for i, name in enumerate(cat.GROUPS)}
    cases.sort(key=lambda c: (c["tokens"] > cat.MAX_TOKENS, order.get(c["group"], -1), c["tokens"], c["id"]))
    failed = [c["id"] for c in cases if not c["token_check"]["passed"]]
    value = {
        "schema_version": "pure_jeff.bench_catalog.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "reference": {"engine": "official Jeff (PyTorch), CPU FP32, 1 thread, as runtime/jeff_worker.py",
                      "source_revision": manifest["source_revision"], "versions": versions,
                      "torch_cpu_capability": torch.backends.cpu.get_cpu_capability(),
                      "policy": manifest["policy"],
                      "checkpoint_files": manifest["checkpoint_files"],
                      "bundle_manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                      "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "groups": {k: list(v) for k, v in cat.GROUPS.items()}, "stages": cat.STAGES,
        "token_check_failures": failed, "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w" if args.replace else "x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")
    print(json.dumps({"cases": len(cases), "token_check_failures": failed}))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
