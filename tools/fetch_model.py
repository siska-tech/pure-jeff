"""Download the pinned Jeff checkpoint from Hugging Face and verify every file's SHA-256.

Usage: python tools/fetch_model.py [--output models/jeff-checkpoint]
Files are written as <name>.part and renamed only after the hash matches. An existing file
with the right hash is kept; one with a different hash is an error (nothing is overwritten).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 4 << 20


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def download(url, target, expected_bytes, expected_sha256):
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    received = 0
    request = urllib.request.Request(url, headers={"User-Agent": "pure-jeff-fetch/1"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
        while block := response.read(CHUNK):
            out.write(block)
            digest.update(block)
            received += len(block)
            print(f"\r  {target.name}: {received / 1e6:,.1f} / {expected_bytes / 1e6:,.1f} MB", end="", flush=True)
    print()
    if received != expected_bytes or digest.hexdigest() != expected_sha256:
        partial.unlink()
        raise SystemExit(f"{target.name}: size or SHA-256 mismatch; the partial download was removed")
    partial.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "models/jeff-checkpoint")
    parser.add_argument("--spec", type=Path, default=ROOT / "tools/checkpoint.json")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    base = f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}"
    print(f"{spec['repository']} @ {spec['revision']} -> {args.output}")
    for entry in spec["files"]:
        target = args.output / entry["path"]
        if target.exists():
            if sha256_file(target) != entry["sha256"]:
                raise SystemExit(f"{target} exists with a different SHA-256; move it away and retry")
            print(f"  {entry['path']}: present, verified")
            continue
        download(f"{base}/{entry['path']}", target, entry["bytes"], entry["sha256"])
    extra = sorted(p.name for p in args.output.iterdir() if p.name not in {e["path"] for e in spec["files"]})
    if extra:
        print(f"note: extra files in {args.output} (the Native bundle lock rejects unexpected files): {extra}",
              file=sys.stderr)
    print("all files verified")


if __name__ == "__main__":
    main()
