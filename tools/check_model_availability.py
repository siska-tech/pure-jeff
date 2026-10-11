"""Check that the pinned checkpoint is still served by Hugging Face with the expected content.

The web demo and tools/fetch_model.py depend on the pinned revision of a third-party repository
(jeff-legacy/Jeff-Qwen3.5-0.8B). Large (LFS) files are checked without downloading: Hugging Face
reports their SHA-256 and size in X-Linked-ETag / X-Linked-Size. Small files are downloaded and
hashed. Exits non-zero if any file is missing or differs.

  python tools/check_model_availability.py
"""
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = {"User-Agent": "pure-jeff-availability-check/1"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def head(url):
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, method="HEAD", headers=USER_AGENT)
    try:
        response = opener.open(request, timeout=60)
    except urllib.error.HTTPError as redirect:  # 3xx arrives as an HTTPError without a handler
        if redirect.code in (301, 302, 303, 307, 308):
            return redirect.code, redirect.headers
        raise
    return response.status, response.headers


def main():
    spec = json.loads((ROOT / "tools/checkpoint.json").read_text(encoding="utf-8"))
    base = f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}"
    failures = []
    for entry in spec["files"]:
        url = f"{base}/{entry['path']}"
        try:
            status, headers = head(url)
            etag = (headers.get("X-Linked-ETag") or "").strip('"')
            if len(etag) == 64:  # LFS object: the ETag is the SHA-256
                size = int(headers.get("X-Linked-Size") or -1)
                ok, how = etag == entry["sha256"] and size == entry["bytes"], "head"
            else:
                request = urllib.request.Request(url, headers=USER_AGENT)
                body = urllib.request.urlopen(request, timeout=120).read()
                ok, how = hashlib.sha256(body).hexdigest() == entry["sha256"] and len(body) == entry["bytes"], "download"
        except Exception as error:  # report every file, then fail
            ok, how = False, f"error: {error}"
        print(f"{'ok ' if ok else 'BAD'} {entry['path']} ({how})")
        if not ok:
            failures.append(entry["path"])
    if failures:
        sys.exit(f"pinned checkpoint not available as expected: {failures}")
    print(f"{spec['repository']}@{spec['revision'][:7]}: all {len(spec['files'])} files available")


if __name__ == "__main__":
    main()
