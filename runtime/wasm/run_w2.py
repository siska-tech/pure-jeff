"""W2 browser Wasm run: one resident session over 128-512 token cases, invalid requests,
corrupted assets, a mid-forward cancel and a page reload. Feasibility only, not performance."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import http.server

from run_w0 import GOLDEN, ROOT, save, sha
from run_w1 import judge_run, max_abs, tree_memory

WEB = Path(__file__).resolve().parent / "web"
GOLDEN_CASES = ["candidate-request", "reversed", "special-token-text", "asr-unicode"]
LENGTH_CASES = ["synthetic-asr-unicode-2-128", "synthetic-ocr-ascii-3-128", "synthetic-ocr-ja-2-256",
                "synthetic-ocr-ascii-8-256", "synthetic-asr-unicode-2-384", "synthetic-ocr-ascii-3-511",
                "synthetic-asr-mixed-2-512", "synthetic-ocr-ascii-8-512"]
# Registered before the run; never relaxed after seeing results.
GATES = {
    "probability_max_abs_vs_official": 1e-4,
    "valid": "every pass-1, pass-2, cancel-rerun and reload decision: code 0, no panic/trap; rendered "
             "prompt SHA-256, input_ids, candidate order and judgment equal the official reference",
    "repeat": "pass 2 (reverse order, same session) probabilities and hidden state bitwise equal pass 1; "
              "cancel rerun and reload results bitwise equal pass 1",
    "memory": "linear memory after pass 2 equals linear memory after pass 1",
    "invalid": "every invalid request returns code 1 without panic/trap; the session keeps working",
    "corrupt": "a flipped byte in an asset makes open fail with '<asset> hash mismatch'; open then succeeds",
    "cancel": "Worker terminated after decide_started; a fresh Worker then decides correctly",
    "browser": "both page parts report within the timeout",
    "native_reference_threads": 1,
}


def references(reference_dir):
    out = {name: GOLDEN / f"{name}.json" for name in GOLDEN_CASES}
    out.update({name: reference_dir / f"{name}.json" for name in LENGTH_CASES})
    return out


def invalid_requests(base):
    def variant(**changes):
        return json.dumps(base | changes, ensure_ascii=False)
    first = base["candidates"][0]
    return [
        {"name": "invalid_json", "text": '{"request_id": '},
        {"name": "one_candidate", "text": variant(candidates=[first])},
        {"name": "duplicate_candidate_ids", "text": variant(candidates=[first, first | {"text": "x"}])},
        {"name": "unsupported_question", "text": variant(question_id="other.v1")},
        {"name": "no_routing_reason", "text": variant(reason=None)},
        {"name": "token_budget_exceeded", "text": json.dumps(base, ensure_ascii=False), "max_input_tokens": 64},
    ]


def serve(routes, parts):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0].lstrip("/")
            if path not in routes:
                self.send_error(404)
                return
            source, kind = routes[path]
            size = source.stat().st_size if isinstance(source, Path) else len(source)
            self.send_response(200)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(size))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            try:
                if isinstance(source, Path):
                    with source.open("rb") as stream:
                        shutil.copyfileobj(stream, self.wfile, 4 << 20)
                else:
                    self.wfile.write(source)
            except ConnectionError:
                pass

        def do_POST(self):
            part = self.path.partition("part=")[2]
            if not self.path.startswith("/result") or part not in ("a", "b", "fatal") or part in parts:
                self.send_error(404)
                return
            parts[part] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            self.send_response(204)
            self.end_headers()
            if "b" in parts or "fatal" in parts:
                parts["event"].set()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def as_run(reply):
    return {"outcome": "completed" if reply and not reply.get("terminated") else "terminated",
            "code": reply.get("code"), "result": reply.get("output"), "error": reply.get("error"),
            "panic": reply.get("panic")}


def same(a, b):
    return bool(a and b) and a.get("probabilities") == b.get("probabilities") \
        and a.get("last_hidden_state") == b.get("last_hidden_state")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="native w2_reference.exe")
    parser.add_argument("--wasm", type=Path, required=True)
    parser.add_argument("--official", type=Path, required=True, help="directory of exported length references")
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle.json")
    parser.add_argument("--max-input-tokens", type=int, default=512)
    parser.add_argument("--heap-reserve-bytes", type=int, default=805306368)
    parser.add_argument("--cancel-case", default="synthetic-asr-mixed-2-512")
    parser.add_argument("--reload-case", default="candidate-request")
    parser.add_argument("--cancel-forward-fraction", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=7200)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    refs = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in references(args.official).items()}
    requests = args.output / "requests"
    requests.mkdir()
    for name, ref in refs.items():
        save(requests / f"{name}.json", ref["request"])
    save(args.output / "cases.json", [{"name": name, "request": f"requests/{name}.json"} for name in refs])
    invalid = invalid_requests(refs["candidate-request"]["request"])
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    checkpoint = args.manifest.parent / manifest["checkpoint_dir"]
    assets = [("manifest", args.manifest), ("decision_config", checkpoint / "decision_config.json"),
              ("tokenizer", checkpoint / "tokenizer.json"), ("readout", checkpoint / "readout.safetensors"),
              ("model", checkpoint / "model.safetensors")]
    sizes = {name: path.stat().st_size for name, path in assets}
    corrupt = [{"asset": "tokenizer", "path": "tokenizer.json", "offset": 1000},
               {"asset": "model", "path": "model.safetensors", "offset": sizes["model"] // 2}]
    save(args.output / "preregistration.json", {
        "schema_version": "kaze_judge.wasm_w2_preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "gates": GATES, "cases": list(refs), "invalid": [item["name"] for item in invalid],
        "corrupt": corrupt, "cancel_case": args.cancel_case, "reload_case": args.reload_case,
        "max_input_tokens": args.max_input_tokens, "heap_reserve_bytes": args.heap_reserve_bytes,
        "cancel_forward_fraction": args.cancel_forward_fraction,
        "official_references": {name: sha(path) for name, path in references(args.official).items()},
        "browser": {"path": str(args.browser), "sha256": sha(args.browser)},
        "wasm": {"path": str(args.wasm), "sha256": sha(args.wasm), "bytes": args.wasm.stat().st_size},
        "reference_sha256": sha(args.reference), "driver_sha256": sha(__file__),
        "web": {name: sha(WEB / name) for name in ("w2.html", "w2-worker.js")},
        "manifest_sha256": sha(args.manifest),
        "headless": True, "threads": "single (no SharedArrayBuffer, not cross-origin isolated)",
    })

    reference_path = args.output / "native-reference.json"
    threads = str(GATES["native_reference_threads"])
    subprocess.run([str(args.reference), str(args.manifest), str(args.output / "cases.json"),
                    str(args.max_input_tokens), str(reference_path)], check=True, timeout=args.timeout,
                   env=os.environ | {"RAYON_NUM_THREADS": threads, "CANDLE_NUM_THREADS": threads})
    native = json.loads(reference_path.read_text(encoding="utf-8"))["results"]

    routes = {"w2.html": ((WEB / "w2.html").read_bytes(), "text/html; charset=utf-8"),
              "w2-worker.js": ((WEB / "w2-worker.js").read_bytes(), "text/javascript; charset=utf-8"),
              "probe.wasm": (args.wasm, "application/wasm")}
    routes.update({f"assets/{name}": (path, "application/octet-stream") for name, path in assets})
    routes.update({f"requests/{name}.json": (requests / f"{name}.json", "application/json") for name in refs})
    routes["w2-config.json"] = (json.dumps({
        "wasm": "probe.wasm", "max_input_tokens": args.max_input_tokens,
        "heap_reserve_bytes": args.heap_reserve_bytes, "cancel_forward_fraction": args.cancel_forward_fraction,
        "cancel_case": args.cancel_case, "reload_case": args.reload_case,
        "assets": [{"name": name, "url": f"assets/{name}", "bytes": sizes[name]} for name, _ in assets],
        "cases": [{"name": name, "url": f"requests/{name}.json"} for name in refs],
        "invalid": invalid, "corrupt": [{"asset": c["asset"], "offset": c["offset"]} for c in corrupt],
    }, ensure_ascii=False).encode(), "application/json")
    parts = {"event": threading.Event()}
    server = serve(routes, parts)
    profile = Path(tempfile.mkdtemp(prefix="pj-w2-profile-"))
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={profile}",
                                "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                                "--disable-sync", "--disable-background-networking",
                                f"http://127.0.0.1:{server.server_port}/w2.html"])
    try:
        completed = parts["event"].wait(args.timeout)
        processes = tree_memory(browser.pid)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    save(args.output / "browser-processes.json", processes)
    del parts["event"]
    save(args.output / "browser.json", parts)
    if not completed:
        save(args.output / "failure.json", {"reason": "browser did not report within timeout",
                                            "parts": sorted(parts)})
        raise SystemExit("browser timeout")

    a, b = parts.get("a", {}), parts.get("b", {})
    gate = GATES["probability_max_abs_vs_official"]
    summary = {"schema_version": "kaze_judge.wasm_w2_summary.v1", "page": a.get("page"),
               "fatal": parts.get("fatal"), "cases": {}, "invalid": {}, "corrupt": []}
    ok = summary["fatal"] is None and bool(a) and bool(b)
    pass1, pass2 = a.get("pass1", {}), a.get("pass2", {})
    for name, ref in refs.items():
        row = {}
        for label, reply in (("pass1", pass1.get(name)), ("pass2", pass2.get(name))):
            checks, error = judge_run(as_run(reply or {}), ref, gate)
            row[label] = {"checks": checks, "probability_max_abs_vs_official": error,
                          "stages": ((reply or {}).get("output") or {}).get("stages"),
                          "linear_memory_bytes": (reply or {}).get("linear_memory_bytes")}
            ok &= all(checks.values())
        out1 = (pass1.get(name) or {}).get("output") or {}
        row["pass2_bitwise_equal_pass1"] = same(out1, (pass2.get(name) or {}).get("output"))
        ok &= row["pass2_bitwise_equal_pass1"]
        if out1.get("probabilities"):
            row["vs_native_same_code"] = {
                "probability_max_abs": max_abs(out1["probabilities"], native[name]["probabilities"]),
                "hidden_max_abs": max_abs(out1["last_hidden_state"], native[name]["last_hidden_state"])}
            row["tokens"] = len(out1["input_ids"])
            row["candidates"] = len(out1["probabilities"])
        summary["cases"][name] = row
    memory1 = [pass1[n].get("linear_memory_bytes") for n in refs if n in pass1]
    memory2 = [pass2[n].get("linear_memory_bytes") for n in reversed(list(refs)) if n in pass2]
    summary["memory"] = {"after_open": next((s.get("linear_memory_bytes") for s in a.get("setup", [])
                                             if s.get("cmd") == "open"), None),
                         "pass1": memory1, "pass2": memory2,
                         "passed": bool(memory1 and memory2) and memory2[-1] == memory1[-1]
                         and max(memory2) == memory1[-1]}
    ok &= summary["memory"]["passed"]
    for name, reply in a.get("invalid", {}).items():
        passed = reply.get("code") == 1 and not reply.get("panic") and not reply.get("error")
        summary["invalid"][name] = {"passed": passed, "message": (reply.get("output") or {}).get("error"),
                                    "error": reply.get("error"), "panic": reply.get("panic")}
        ok &= passed
    ok &= len(summary["invalid"]) == len(invalid)
    for item, spec in zip(a.get("corrupt", []), corrupt):
        message = (item.get("output") or {}).get("error") or ""
        passed = item.get("code") == 1 and f"{spec['path']} hash mismatch" in message and not item.get("panic")
        summary["corrupt"].append({"asset": spec["asset"], "offset": spec["offset"], "passed": passed,
                                   "message": message, "ms": item.get("ms")})
        ok &= passed
    ok &= len(summary["corrupt"]) == len(corrupt)
    cancel = a.get("cancel", {})
    cancel_ref = refs[args.cancel_case]
    rerun_checks, rerun_error = judge_run(as_run(a.get("rerun") or {}), cancel_ref, gate)
    summary["cancel"] = {"outcome": cancel.get("outcome"), "decide_started": cancel.get("decide_started"),
                         "cancel_after_ms": cancel.get("cancel_after_ms"), "rerun_checks": rerun_checks,
                         "rerun_probability_max_abs_vs_official": rerun_error,
                         "rerun_bitwise_equal_pass1": same((pass1.get(args.cancel_case) or {}).get("output"),
                                                           (a.get("rerun") or {}).get("output"))}
    summary["cancel"]["passed"] = cancel.get("outcome") == "terminated" and bool(cancel.get("decide_started")) \
        and all(rerun_checks.values()) and summary["cancel"]["rerun_bitwise_equal_pass1"]
    ok &= summary["cancel"]["passed"]
    reload_checks, reload_error = judge_run(as_run(b.get("reload") or {}), refs[args.reload_case], gate)
    summary["reload"] = {"checks": reload_checks, "probability_max_abs_vs_official": reload_error,
                         "bitwise_equal_pass1": same((pass1.get(args.reload_case) or {}).get("output"),
                                                     (b.get("reload") or {}).get("output"))}
    summary["reload"]["passed"] = all(reload_checks.values()) and summary["reload"]["bitwise_equal_pass1"]
    ok &= summary["reload"]["passed"]
    summary["native_reference_vs_official"] = {
        name: max_abs(native[name]["probabilities"], ref["official"]["probabilities"]) for name, ref in refs.items()}
    summary["browser_process_peaks"] = {
        "max_peak_working_set": max((p["peak_working_set"] for p in processes), default=None),
        "max_peak_pagefile": max((p["peak_pagefile"] for p in processes), default=None),
        "processes": len(processes)}
    summary["passed"] = ok
    save(args.output / "summary.json", summary)
    failing = [n for n, r in summary["cases"].items()
               if not (all(r["pass1"]["checks"].values()) and all(r["pass2"]["checks"].values())
                       and r["pass2_bitwise_equal_pass1"])]
    print(json.dumps({"passed": ok, "failing_cases": failing, "memory": summary["memory"]["passed"],
                      "invalid": {k: v["passed"] for k, v in summary["invalid"].items()},
                      "corrupt": [c["passed"] for c in summary["corrupt"]],
                      "cancel": summary["cancel"]["passed"], "reload": summary["reload"]["passed"],
                      "fatal": summary["fatal"]}, indent=1))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
