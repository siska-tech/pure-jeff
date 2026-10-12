"""The benchmark's evaluation inputs: one entry per distinct request, with every earlier name it
had (golden fixtures, the 2026-10-11/12 comparison set, the 28 migrated Tract cases, the W2
browser references) recorded as an alias. `build_catalog.py` writes `cases/catalog.json`;
this module only reads sources and the catalog (no model, no third-party imports)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
CATALOG = HERE / "cases/catalog.json"
REQUESTS = HERE / "cases/requests"
GOLDEN = ROOT / "tests/fixtures/jeff-golden"
LENGTH_INPUTS = ROOT / "docs/research/jeff-onnx-tract/accepted-threads-2026-10-11/length-inputs.json"
W2_REFS = ROOT / "docs/research/wasm-demo/w2-2026-10-11/official-references"
GOLDEN_IDS = ["candidate-request", "reversed", "asr-unicode", "special-token-text", "long-text",
              "maximum-candidates", "token-limit-8192"]
# bench/run_benchmark.py before this change (benchmark-results-2026-10-11/12).
COMPARISON_V1 = ["candidate-request", "asr-unicode", "synthetic-ocr-ja-2-256", "synthetic-asr-unicode-2-384",
                 "synthetic-asr-mixed-2-512", "synthetic-ocr-ascii-8-512"]
# Native and official CLI limit, and the browser engine's validated range.
MAX_TOKENS = 8192
WASM_MAX_TOKENS = 512
# Input-length groups for the equivalence verdicts; a group is judged on its own.
GROUPS = {"128": (127, 129), "256": (256, 256), "384": (384, 384), "512": (511, 513),
          "874": (874, 874), "3206": (3206, 3206), "8192": (8192, 8192)}
STAGES = {"short": ["128", "256", "384", "512"], "long": ["874", "3206", "8192"]}  # full length = short + long


def request_sha256(request):
    """Canonical digest of a request (sorted keys, no whitespace, UTF-8)."""
    text = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ids_sha256(ids):
    return hashlib.sha256(b"".join(int(i).to_bytes(4, "little") for i in ids)).hexdigest()


def group_of(tokens):
    for name, (low, high) in GROUPS.items():
        if tokens is not None and low <= tokens <= high:
            return name
    return None


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sources():
    """(set, name, path, request) for every earlier input, in a fixed order."""
    out = []
    for name in GOLDEN_IDS:
        path = GOLDEN / f"{name}.json"
        out.append(("golden", name, path, read(path)["request"]))
    path = ROOT / "tests/fixtures/jeff-requests/token-limit-8193.json"
    out.append(("golden-reject", "token-limit-8193", path, read(path)))
    for name in COMPARISON_V1:
        path = GOLDEN / f"{name}.json" if name in GOLDEN_IDS else W2_REFS / f"{name}.json"
        out.append(("comparison-v1", name, path, read(path)["request"]))
    inputs = read(LENGTH_INPUTS)
    for check in inputs["golden_checks"]:
        out.append(("migrated-28", check["id"], GOLDEN / f"{check['id']}.json",
                    read(GOLDEN / f"{check['id']}.json")["request"]))
    for case in inputs["cases"]:
        out.append(("migrated-28", case["id"], LENGTH_INPUTS, case["request"]))
    out.append(("migrated-boundary", "synthetic-ocr-ascii-3-513", LENGTH_INPUTS, inputs["boundary_513"]["request"]))
    for path in sorted((W2_REFS / "requests").glob("*.json")):
        out.append(("w2", path.stem, path, read(path)))
    for path in sorted(REQUESTS.glob("*.json")):
        out.append(("generated", path.stem, path, read(path)["request"]))
    return out


def load():
    catalog = read(CATALOG)
    for case in catalog["cases"]:
        source = case["request_source"]
        value = read(ROOT / source["path"])
        for key in source.get("pointer", []):
            value = value[key] if not isinstance(value, list) else next(
                c for c in value if c.get("id") == key)
        if request_sha256(value) != case["request_sha256"]:
            raise SystemExit(f"{case['id']}: request differs from the catalog")
        case["request"] = value
    return catalog


def by_id(catalog):
    return {case["id"]: case for case in catalog["cases"]}
