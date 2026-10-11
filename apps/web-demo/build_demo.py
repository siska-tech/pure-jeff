"""Assemble the static web demo: page, Worker, engine wasm, deployment config and samples.
The model files are served from `model/`; --copy-model puts them into the output for hosting."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
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
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle-p3.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--copy-model", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    for name in ("index.html", "app.js", "engine-worker.js", "style.css"):
        shutil.copyfile(WEB / name, args.output / name)
    shutil.copyfile(args.engine_wasm, args.output / "engine.wasm")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    checkpoint = args.manifest.parent / manifest["checkpoint_dir"]
    records = {f["path"]: f["sha256"] for f in manifest["files"]}
    assets = []
    for slot, path in enumerate(ASSET_PATHS):
        assert sha(checkpoint / path) == records[path], f"{path} differs from the manifest"
        assets.append({"slot": slot, "path": path, "url": f"model/{path}", "sha256": records[path],
                       "bytes": (checkpoint / path).stat().st_size})
    manifest_sha = sha(args.manifest)
    config = {
        "schema_version": "kaze_judge.web_demo_config.v1",
        "engine": {"url": "engine.wasm", "sha256": sha(args.engine_wasm), "bytes": args.engine_wasm.stat().st_size},
        "manifest": {"path": "manifest.json", "url": "model/manifest.json", "sha256": manifest_sha,
                     "bytes": args.manifest.stat().st_size},
        "assets": assets,
        "total_download_bytes": args.manifest.stat().st_size + sum(a["bytes"] for a in assets),
        "cache_name": f"kazejudge-model-{manifest_sha[:16]}",
        "max_input_tokens": MAX_INPUT_TOKENS,
        "max_input_bytes": MAX_INPUT_BYTES,
        "heap_reserve_bytes": HEAP_RESERVE_BYTES,
    }
    write_json(args.output / "demo-config.json", config)
    write_json(args.output / "samples.json", [
        {"label": label, "request": json.loads((ROOT / path).read_text(encoding="utf-8"))["request"]}
        for label, path in SAMPLES])
    if args.copy_model:
        (args.output / "model").mkdir()
        shutil.copyfile(args.manifest, args.output / "model/manifest.json")
        for path in ASSET_PATHS:
            shutil.copyfile(checkpoint / path, args.output / "model" / path)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "apps/web-demo", "runtime/wasm", "src"],
                                capture_output=True, text=True).stdout.strip())
    write_json(args.output / "build-info.json", {
        "source_commit": commit, "source_dirty": dirty, "copy_model": args.copy_model,
        "files": {p.relative_to(args.output).as_posix(): sha(p) for p in sorted(args.output.rglob("*"))
                  if p.is_file() and p.name != "build-info.json" and p.parent.name != "model"},
    })
    print(json.dumps({"output": str(args.output), "engine_sha256": config["engine"]["sha256"],
                      "total_download_bytes": config["total_download_bytes"]}, indent=1))


if __name__ == "__main__":
    main()
