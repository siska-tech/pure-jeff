"""W0 browser Wasm feasibility run: small fixtures only; no model forward, no performance claim."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.server
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).resolve().parent / "web"
GOLDEN = ROOT / "tests/fixtures/jeff-golden"
CASES = ["candidate-request", "reversed", "asr-unicode", "long-text", "special-token-text",
         "maximum-candidates", "token-limit-8192"]
# Registered before the run; never relaxed after seeing results. v1 (elementwise 1e-5 abs+rel)
# failed on GEMM near-zero outputs in wasm-w0-chrome-20261011; float64 diagnosis showed both
# targets within ~2 eps of the exact product, so v2 judges error against the tensor's scale and
# the GEMM error against the float64 backward-error bound. v1 is not overturned.
EPS32 = 2.0 ** -23
THRESHOLDS = {"version": 2, "ops_tensor_rel": 1e-5,
              "rule": "per tensor max|wasm-native| <= ops_tensor_rel*max(1, max|native|); equal shapes; finite",
              "gemm_backward": 4 * EPS32,
              "gemm_rule": "for input-only GEMMs, max|out-exact64| / (|x|·|w|ᵀ) <= gemm_backward, native and wasm",
              "browser_repeat": "ops_0 and ops_1 values bitwise identical (timings excluded)",
              "tokenize": "hash, answer codes/IDs, single-token property, every prompt and input_ids exact",
              "native_reference_threads": 1}
# Generator order in ops.rs: (case name, inputs taken before it, x shape, w shape).
GEMM_INPUTS = {"gemm_17x1024_by_3584x1024T": (0, (17, 1024), (3584, 1024)),
               "gemm_odd_5x64_by_33x64T": (17 * 1024 + 3584 * 1024 + 1024 * 3584, (5, 64), (33, 64))}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def make_job(manifest):
    bundle = json.loads(manifest.read_text(encoding="utf-8"))
    tokenizer_sha = next(f["sha256"] for f in bundle["files"] if f["path"] == "tokenizer.json")
    cases, codes, token_ids = [], None, None
    for name in CASES:
        golden = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
        assert codes in (None, golden["codes"]) and token_ids in (None, golden["token_ids"])
        codes, token_ids = golden["codes"], golden["token_ids"]
        [input_ids] = golden["official"]["inputs"]["input_ids"]
        cases.append({"name": name, "request": golden["request"], "prompt": golden["prompt"],
                      "prompt_layout": golden["prompt_layout"], "input_ids": input_ids})
    return {"tokenizer_sha256": tokenizer_sha, "codes": codes, "token_ids": token_ids, "cases": cases}


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def generated(skip, count):
    """Replays ops.rs's integer generator (bit-exact f32 values) as float64."""
    import numpy as np
    state, mask = 0x4A4546465730, (1 << 64) - 1
    out = np.empty(count)
    for i in range(skip + count):
        state = (state * 6364136223846793005 + 1442695040888963407) & mask
        if i >= skip:
            out[i - skip] = (state >> 40) / float(1 << 23) - 1.0
    return out


def gemm_exact():
    exact = {}
    for name, (skip, xs, ws) in GEMM_INPUTS.items():
        values = generated(skip, xs[0] * xs[1] + ws[0] * ws[1])
        x, w = values[:xs[0] * xs[1]].reshape(xs), values[xs[0] * xs[1]:].reshape(ws)
        exact[name] = (x @ w.T, abs(x) @ abs(w).T)
    return exact


def backward_error(case, exact):
    import numpy as np
    product, scale = exact[case["name"]]
    return float((np.abs(np.array(case["values"]).reshape(product.shape) - product) / scale).max())


def compare_ops(native, browser, exact):
    rows, passed = [], True
    by_name = {case["name"]: case for case in browser["cases"]}
    for ref in native["cases"]:
        got = by_name.get(ref["name"])
        row = {"name": ref["name"], "shape": ref["shape"]}
        if got is None or got["shape"] != ref["shape"] or len(got["values"]) != len(ref["values"]):
            row.update(passed=False, reason="missing or shape mismatch")
        else:
            worst_abs = worst_rel = 0.0
            identical = 0
            for r, b in zip(ref["values"], got["values"]):
                error = abs(b - r)
                worst_abs = max(worst_abs, error)
                worst_rel = max(worst_rel, error / abs(r) if r else (0.0 if error == 0 else math.inf))
                identical += bits(r) == bits(b)
            scale = max(1.0, max(abs(r) for r in ref["values"]))
            row.update(elements=len(ref["values"]), max_abs_error=worst_abs, max_rel_error=worst_rel,
                       tensor_scale=scale, bitwise_identical=identical,
                       passed=all(math.isfinite(b) for b in got["values"])
                       and worst_abs <= THRESHOLDS["ops_tensor_rel"] * scale,
                       native_ms=ref["elapsed_ms"], wasm_ms=got["elapsed_ms"])
            if ref["name"] in exact:
                row["native_backward_error"] = backward_error(ref, exact)
                row["wasm_backward_error"] = backward_error(got, exact)
                row["passed"] &= max(row["native_backward_error"], row["wasm_backward_error"]) \
                    <= THRESHOLDS["gemm_backward"]
        passed &= row["passed"]
        rows.append(row)
    return passed, rows


def values_only(ops):
    return [(case["name"], case["shape"], case["values"]) for case in ops["cases"]]


def tokenize_passed(result):
    return all(result[key] for key in ("codes_match", "token_ids_match", "single_token_after_prefix")) \
        and len(result["cases"]) == len(CASES) \
        and all(case["prompt_match"] and case["ids_match"] for case in result["cases"])


def serve(routes, received):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0].lstrip("/") or "index.html"
            if path not in routes:
                self.send_error(404)
                return
            body, kind = routes[path]
            self.send_response(200)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/result" or "body" in received:
                self.send_error(404)
                return
            received["body"] = self.rfile.read(int(self.headers["content-length"]))
            self.send_response(204)
            self.end_headers()
            received["event"].set()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="native w0_reference.exe")
    parser.add_argument("--variant", action="append", required=True, metavar="NAME=PATH.wasm")
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    variants = dict(item.split("=", 1) for item in args.variant)
    tokenizer = args.manifest.parent / json.loads(args.manifest.read_text(encoding="utf-8"))["checkpoint_dir"] / "tokenizer.json"
    job = make_job(args.manifest)
    assert sha(tokenizer) == job["tokenizer_sha256"]
    save(args.output / "tokenize-job.json", job)
    save(args.output / "preregistration.json", {
        "schema_version": "kaze_judge.wasm_w0_preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "thresholds": THRESHOLDS, "cases": CASES,
        "prior_failed_run": "experiments/runs/wasm-w0-chrome-20261011 (v1 thresholds; stays failed)",
        "browser": {"path": str(args.browser), "sha256": sha(args.browser)},
        "reference_sha256": sha(args.reference),
        "variants": {name: {"path": path, "sha256": sha(path), "bytes": Path(path).stat().st_size}
                     for name, path in variants.items()},
        "web": {name: sha(WEB / name) for name in ("index.html", "worker.js")},
        "driver_sha256": sha(__file__), "tokenizer_sha256": job["tokenizer_sha256"],
        "golden": {name: sha(GOLDEN / f"{name}.json") for name in CASES},
        "headless": True, "threads": "single (no SharedArrayBuffer, not cross-origin isolated)",
    })

    reference_path = args.output / "native-reference.json"
    threads = str(THRESHOLDS["native_reference_threads"])
    subprocess.run([str(args.reference), str(tokenizer), str(args.output / "tokenize-job.json"),
                    str(reference_path)], check=True, timeout=args.timeout,
                   env=os.environ | {"RAYON_NUM_THREADS": threads, "CANDLE_NUM_THREADS": threads})
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    assert reference["environment"]["candle_num_threads"] == THRESHOLDS["native_reference_threads"]
    exact = gemm_exact()

    job_bytes = (args.output / "tokenize-job.json").read_bytes()
    config = {"variants": [{"name": name, "wasm": f"wasm/{name}.wasm", "tokenizer": "tokenizer.json",
                            "job": "job.json", "requires_simd128": "simd" in name} for name in variants]}
    routes = {"index.html": ((WEB / "index.html").read_bytes(), "text/html; charset=utf-8"),
              "worker.js": ((WEB / "worker.js").read_bytes(), "text/javascript; charset=utf-8"),
              "config.json": (json.dumps(config).encode(), "application/json"),
              "tokenizer.json": (tokenizer.read_bytes(), "application/json"),
              "job.json": (job_bytes, "application/json")}
    routes.update({f"wasm/{name}.wasm": (Path(path).read_bytes(), "application/wasm")
                   for name, path in variants.items()})
    received = {"event": threading.Event()}
    server = serve(routes, received)
    profile = Path(tempfile.mkdtemp(prefix="pj-w0-profile-"))
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={profile}",
                                "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                                "--disable-sync", "--disable-background-networking",
                                f"http://127.0.0.1:{server.server_port}/index.html"])
    try:
        completed = received["event"].wait(args.timeout)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    if not completed:
        save(args.output / "failure.json", {"reason": "browser did not report within timeout"})
        raise SystemExit("browser timeout")
    browser_result = json.loads(received["body"])
    save(args.output / "browser.json", browser_result)

    summary = {"schema_version": "kaze_judge.wasm_w0_summary.v1", "page": browser_result.get("page"),
               "fatal": browser_result.get("fatal"), "native_environment": reference["environment"],
               "native_tokenize_passed": tokenize_passed(reference["tokenize"]), "variants": {}}
    passed = summary["fatal"] is None and summary["native_tokenize_passed"]
    for result in browser_result.get("results", []):
        entry = {key: result.get(key) for key in ("error", "panic", "skipped", "simd128_supported",
                                                   "environment", "steps", "final_linear_memory_bytes")}
        if result.get("ops_0") and result.get("ops_1") and result.get("tokenize"):
            ops_passed, rows = compare_ops(reference["ops"], result["ops_0"], exact)
            entry.update(ops_passed=ops_passed, ops=rows,
                         browser_repeat_identical=values_only(result["ops_0"]) == values_only(result["ops_1"]),
                         tokenize_passed=tokenize_passed(result["tokenize"]),
                         tokenize={k: v for k, v in result["tokenize"].items() if k != "cases"},
                         tokenize_cases=result["tokenize"]["cases"])
            entry["passed"] = ops_passed and entry["browser_repeat_identical"] and entry["tokenize_passed"] \
                and not result.get("error") and not result.get("panic")
        else:
            entry["passed"] = False
        passed &= entry["passed"] or bool(result.get("skipped"))
        summary["variants"][result["variant"]] = entry
    summary["passed"] = passed and bool(summary["variants"])
    save(args.output / "summary.json", summary)
    print(json.dumps({name: {k: v.get(k) for k in ("passed", "ops_passed", "tokenize_passed",
                                                   "browser_repeat_identical", "error", "panic", "skipped")}
                      for name, v in summary["variants"].items()} | {"passed": summary["passed"]}, indent=1))
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
