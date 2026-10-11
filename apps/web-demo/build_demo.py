"""Assemble the static web demo: page, Worker, engine wasm (development exports removed),
deployment config, samples and license notices.

The model files are fetched from `model/` next to the page, or from --model-base-url (another
origin, e.g. an R2 bucket with CORS). --copy-model puts them into the output for hosting.
The checkpoint's LICENSE and NOTICE are always included, because anyone hosting the weights
must ship them."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import audit_licenses  # noqa: E402
from strip_exports import strip  # noqa: E402
WEB = Path(__file__).resolve().parent / "web"
ASSET_PATHS = ["decision_config.json", "tokenizer.json", "readout.safetensors", "model.safetensors"]
MAX_INPUT_TOKENS = 512  # range validated in W2
MAX_INPUT_BYTES = 1 << 20
HEAP_RESERVE_BYTES = 768 << 20
SAMPLES = [  # (label, reference file relative to ROOT)
    ("OCR：2候補（128 tokens）", "tests/fixtures/jeff-golden/candidate-request.json"),
    ("OCR：同じ2候補を逆順（128 tokens）", "tests/fixtures/jeff-golden/reversed.json"),
    ("ASR：Unicode文字を含む3候補（206 tokens）", "tests/fixtures/jeff-golden/asr-unicode.json"),
    ("区切り記号に似た文字列を含む2候補（182 tokens）", "tests/fixtures/jeff-golden/special-token-text.json"),
    ("日本語OCR：2候補（256 tokens）",
     "docs/research/wasm-demo/w2-2026-10-11/official-references/synthetic-ocr-ja-2-256.json"),
    ("OCR：8候補（512 tokens、上限ちょうど）",
     "docs/research/wasm-demo/w2-2026-10-11/official-references/synthetic-ocr-ascii-8-512.json"),
    ("上限を超える長文（874 tokens、予算超過の例）", "tests/fixtures/jeff-golden/long-text.json"),
]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-wasm", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--copy-model", action="store_true")
    parser.add_argument("--model-base-url", default="model/",
                        help="where the page fetches model files (relative, or an https origin with CORS)")
    parser.add_argument("--manifest-url",
                        help="where the page fetches the bundle manifest (default: next to the model files). "
                             "A relative path is written into the output, e.g. bundle/manifest.json when the "
                             "model files come from Hugging Face")
    args = parser.parse_args()
    base = args.model_base_url if args.model_base_url.endswith("/") else args.model_base_url + "/"
    manifest_url = args.manifest_url or f"{base}manifest.json"
    args.output.mkdir(parents=True)
    for name in ("index.html", "app.js", "engine-worker.js", "style.css", "_headers"):
        shutil.copyfile(WEB / name, args.output / name)
    engine, kept, removed = strip(args.engine_wasm.read_bytes())
    (args.output / "engine.wasm").write_bytes(engine)
    licenses = args.output / "licenses"
    licenses.mkdir()
    audit_licenses.notices("engine", "wasm32-unknown-unknown", licenses / "THIRD_PARTY_LICENSES.txt")
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", licenses / "THIRD_PARTY_NOTICES.md")
    shutil.copyfile(ROOT / "runtime/licenses/jeff-source/LICENSE", licenses / "JEFF_SOURCE_LICENSE.txt")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    checkpoint = args.manifest.parent / manifest["checkpoint_dir"]
    records = {f["path"]: f["sha256"] for f in manifest["files"]}
    assets = []
    for slot, path in enumerate(ASSET_PATHS):
        assert sha(checkpoint / path) == records[path], f"{path} differs from the manifest"
        assets.append({"slot": slot, "path": path, "url": f"{base}{path}", "sha256": records[path],
                       "bytes": (checkpoint / path).stat().st_size})
    for name in ("LICENSE", "NOTICE"):
        assert sha(checkpoint / name) == records[name], f"{name} differs from the manifest"
        shutil.copyfile(checkpoint / name, licenses / f"MODEL_{name}.txt")
    manifest_sha = sha(args.manifest)
    config = {
        "schema_version": "kaze_judge.web_demo_config.v1",
        "engine": {"url": "engine.wasm", "sha256": sha(args.output / "engine.wasm"), "bytes": len(engine),
                   "removed_exports": removed},
        "manifest": {"path": "manifest.json", "url": manifest_url, "sha256": manifest_sha,
                     "bytes": args.manifest.stat().st_size},
        "assets": assets,
        "total_download_bytes": args.manifest.stat().st_size + sum(a["bytes"] for a in assets),
        "cache_name": f"pure-jeff-model-{manifest_sha[:16]}",
        "model_base_url": base,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "max_input_bytes": MAX_INPUT_BYTES,
        "heap_reserve_bytes": HEAP_RESERVE_BYTES,
    }
    write_json(args.output / "demo-config.json", config)
    write_json(args.output / "samples.json", [
        {"label": label, "request": json.loads((ROOT / path).read_text(encoding="utf-8"))["request"]}
        for label, path in SAMPLES])
    if "://" not in manifest_url and not manifest_url.startswith("model/"):
        target = args.output / manifest_url
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.manifest, target)
    if args.copy_model:
        (args.output / "model").mkdir()
        shutil.copyfile(args.manifest, args.output / "model/manifest.json")
        for path in ASSET_PATHS + ["LICENSE", "NOTICE"]:
            shutil.copyfile(checkpoint / path, args.output / "model" / path)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "apps/web-demo", "runtime/wasm",
                                 "src", "tools", "THIRD_PARTY_NOTICES.md"],
                                capture_output=True, text=True).stdout.strip())
    write_json(args.output / "build-info.json", {
        "source_commit": commit, "source_dirty": dirty, "copy_model": args.copy_model, "model_base_url": base,
        "engine_input_sha256": sha(args.engine_wasm), "engine_removed_exports": removed,
        "files": {p.relative_to(args.output).as_posix(): sha(p) for p in sorted(args.output.rglob("*"))
                  if p.is_file() and p.name != "build-info.json" and p.parent.name != "model"},
    })
    print(json.dumps({"output": str(args.output), "engine_sha256": config["engine"]["sha256"],
                      "kept_exports": kept, "model_base_url": base,
                      "total_download_bytes": config["total_download_bytes"]}, indent=1))


if __name__ == "__main__":
    main()
