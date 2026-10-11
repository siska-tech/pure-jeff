"""Local static server for the built demo (127.0.0.1 only). Serves the build output and maps
`model/` to the checkpoint when the build does not contain the model. Logs every request."""
import argparse
import http.server
import json
from pathlib import Path
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json", ".wasm": "application/wasm"}
MODEL_FILES = ["decision_config.json", "tokenizer.json", "readout.safetensors", "model.safetensors"]


def routes_for(dist, manifest):
    routes = {p.relative_to(dist).as_posix(): p for p in dist.rglob("*") if p.is_file()}
    checkpoint = manifest.parent / json.loads(manifest.read_text(encoding="utf-8"))["checkpoint_dir"]
    routes.setdefault("model/manifest.json", manifest)
    for name in MODEL_FILES:
        routes.setdefault(f"model/{name}", checkpoint / name)
    return routes


def make_server(dist, manifest, port=0, log=None):
    """Returns (server, request log list). Requests are appended to `log` (and the list)."""
    routes = routes_for(dist, manifest)
    requests = []
    lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def record(self, status, size):
            entry = {"time": time.time(), "method": self.command, "path": self.path, "status": status, "bytes": size}
            with lock:
                requests.append(entry)
                if log:
                    with open(log, "a", encoding="utf-8") as stream:
                        stream.write(json.dumps(entry) + "\n")

        def do_GET(self):
            path = self.path.split("?")[0].lstrip("/") or "index.html"
            source = routes.get(path)
            if source is None:
                self.send_error(404)
                self.record(404, 0)
                return
            size = source.stat().st_size
            self.send_response(200)
            self.send_header("content-type", TYPES.get(source.suffix, "application/octet-stream"))
            self.send_header("content-length", str(size))
            self.send_header("cache-control", "no-cache")
            self.end_headers()
            sent = 0
            try:
                with source.open("rb") as stream:
                    while chunk := stream.read(4 << 20):
                        self.wfile.write(chunk)
                        sent += len(chunk)
            except ConnectionError:
                pass  # the page may abort a download
            self.record(200, sent)

        def do_POST(self):
            self.send_error(405)
            self.record(405, 0)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server, requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle-p3.json")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    server, _ = make_server(args.dist, args.manifest, args.port, args.log)
    print(f"http://127.0.0.1:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
