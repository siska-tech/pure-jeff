"""W1 browser Wasm run: one real-model decision, a mid-forward cancel and a fresh rerun.
Feasibility only; single observations are not performance results."""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

from run_w0 import GOLDEN, ROOT, save, sha

WEB = Path(__file__).resolve().parent / "web"
# Registered before the run; never relaxed after seeing results.
GATES = {
    "probability_max_abs_vs_golden": 1e-4,
    "runs_a_and_c": "completed without error/panic; rendered prompt SHA-256, input_ids, candidate order "
                    "and judgment equal the official golden; probability error within the bound",
    "rerun": "run C probabilities and last hidden state bitwise equal run A",
    "cancel": "run B terminated after decide_started and before completion; run C then completes",
    "browser": "page reports within the timeout (no tab/renderer crash)",
    "native_reference_threads": 1,
}
DIAGNOSTICS = ["wasm vs native same-code probabilities and hidden state",
               "hidden state vs official golden", "stage timings", "linear memory bytes",
               "browser process-tree PeakWorkingSetSize / PeakPagefileUsage"]


class ProcessEntry(c.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", c.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260)]


class Counters(c.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [(name, c.c_size_t) for name in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]


def tree_memory(root_pid):
    """Lifetime peaks of every live process under root_pid (shared pages counted per process)."""
    kernel = c.WinDLL("kernel32", use_last_error=True)
    psapi = c.WinDLL("psapi", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.OpenProcess.restype = w.HANDLE
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    entry, children = ProcessEntry(dwSize=c.sizeof(ProcessEntry)), {}
    more = kernel.Process32FirstW(snapshot, c.byref(entry))
    while more:
        children.setdefault(entry.th32ParentProcessID, []).append((entry.th32ProcessID, entry.szExeFile))
        more = kernel.Process32NextW(snapshot, c.byref(entry))
    kernel.CloseHandle(snapshot)
    out, pending = [], [(root_pid, "browser")]
    while pending:
        pid, name = pending.pop()
        pending.extend(children.get(pid, []))
        handle = kernel.OpenProcess(0x1000, False, pid)
        counters = Counters(cb=c.sizeof(Counters))
        if handle and psapi.GetProcessMemoryInfo(w.HANDLE(handle), c.byref(counters), c.sizeof(counters)):
            out.append({"pid": pid, "name": name, "peak_working_set": counters.PeakWorkingSetSize,
                        "peak_pagefile": counters.PeakPagefileUsage})
        if handle:
            kernel.CloseHandle(handle)
    return out


def serve(routes, received):
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
                pass  # a terminated Worker may abort its download

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


def max_abs(a, b):
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def judge_run(run, golden, gate):
    result = run.get("result") or {}
    checks = {
        "completed": run.get("outcome") == "completed" and run.get("code") == 0
                     and not run.get("error") and not run.get("panic"),
        "prompt": result.get("rendered_prompt_sha256") == golden["prompt_utf8_sha256"],
        "input_ids": result.get("input_ids") == golden["official"]["inputs"]["input_ids"][0],
        "candidate_order": result.get("candidate_ids") == [c["id"] for c in golden["request"]["candidates"]],
        "judgment": result.get("judgment") == golden["official"]["judgment"],
    }
    error = None
    if result.get("probabilities") and len(result["probabilities"]) == len(golden["official"]["probabilities"]):
        error = max_abs(result["probabilities"], golden["official"]["probabilities"])
    checks["probabilities"] = error is not None and error <= gate
    return checks, error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="native w1_reference.exe")
    parser.add_argument("--wasm", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle.json")
    parser.add_argument("--case", default="candidate-request")
    parser.add_argument("--max-input-tokens", type=int, default=512)
    parser.add_argument("--cancel-forward-fraction", type=float, default=0.5)
    parser.add_argument("--heap-reserve-bytes", type=int, default=0,
                        help="grow linear memory once after loading assets, then free it")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    golden_path = GOLDEN / f"{args.case}.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    request_path = args.output / "request.json"
    save(request_path, golden["request"])
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    checkpoint = args.manifest.parent / manifest["checkpoint_dir"]
    assets = [("manifest", args.manifest), ("decision_config", checkpoint / "decision_config.json"),
              ("tokenizer", checkpoint / "tokenizer.json"), ("readout", checkpoint / "readout.safetensors"),
              ("model", checkpoint / "model.safetensors"), ("request", request_path)]
    save(args.output / "preregistration.json", {
        "schema_version": "kaze_judge.wasm_w1_preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "gates": GATES, "diagnostics": DIAGNOSTICS, "case": args.case,
        "golden_sha256": sha(golden_path), "max_input_tokens": args.max_input_tokens,
        "cancel_forward_fraction": args.cancel_forward_fraction,
        "heap_reserve_bytes": args.heap_reserve_bytes,
        "browser": {"path": str(args.browser), "sha256": sha(args.browser)},
        "wasm": {"path": str(args.wasm), "sha256": sha(args.wasm), "bytes": args.wasm.stat().st_size},
        "reference_sha256": sha(args.reference), "driver_sha256": sha(__file__),
        "web": {name: sha(WEB / name) for name in ("w1.html", "w1-worker.js")},
        "manifest_sha256": sha(args.manifest),
        "headless": True, "threads": "single (no SharedArrayBuffer, not cross-origin isolated)",
    })

    reference_path = args.output / "native-reference.json"
    threads = str(GATES["native_reference_threads"])
    subprocess.run([str(args.reference), str(args.manifest), str(request_path), str(args.max_input_tokens),
                    str(reference_path)], check=True, timeout=args.timeout,
                   env=os.environ | {"RAYON_NUM_THREADS": threads, "CANDLE_NUM_THREADS": threads})
    reference = json.loads(reference_path.read_text(encoding="utf-8"))

    routes = {"w1.html": ((WEB / "w1.html").read_bytes(), "text/html; charset=utf-8"),
              "w1-worker.js": ((WEB / "w1-worker.js").read_bytes(), "text/javascript; charset=utf-8"),
              "probe.wasm": (args.wasm, "application/wasm")}
    routes.update({f"assets/{name}": (path, "application/octet-stream") for name, path in assets})
    routes["w1-config.json"] = (json.dumps({
        "wasm": "probe.wasm", "max_input_tokens": args.max_input_tokens,
        "cancel_forward_fraction": args.cancel_forward_fraction,
        "heap_reserve_bytes": args.heap_reserve_bytes,
        "assets": [{"name": name, "url": f"assets/{name}", "bytes": path.stat().st_size} for name, path in assets],
    }).encode(), "application/json")
    received = {"event": threading.Event()}
    server = serve(routes, received)
    profile = Path(tempfile.mkdtemp(prefix="pj-w1-profile-"))
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={profile}",
                                "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                                "--disable-sync", "--disable-background-networking",
                                f"http://127.0.0.1:{server.server_port}/w1.html"])
    try:
        completed = received["event"].wait(args.timeout)
        processes = tree_memory(browser.pid)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    save(args.output / "browser-processes.json", processes)
    if not completed:
        save(args.output / "failure.json", {"reason": "browser did not report within timeout"})
        raise SystemExit("browser timeout")
    report = json.loads(received["body"])
    save(args.output / "browser.json", report)

    summary = {"schema_version": "kaze_judge.wasm_w1_summary.v1", "page": report.get("page"),
               "fatal": report.get("fatal"), "runs": {}}
    runs = report.get("runs", {})
    passed = summary["fatal"] is None
    for name in ("a", "c"):
        run = runs.get(name, {})
        checks, error = judge_run(run, golden, GATES["probability_max_abs_vs_golden"])
        result = run.get("result") or {}
        entry = {"checks": checks, "probability_max_abs_vs_golden": error, "error": run.get("error"),
                 "panic": run.get("panic"), "steps": run.get("steps"), "stages": result.get("stages"),
                 "final_linear_memory_bytes": run.get("final_linear_memory_bytes"),
                 "probabilities": result.get("probabilities"), "judgment": result.get("judgment")}
        if result.get("probabilities") and result.get("last_hidden_state"):
            entry["vs_native_same_code"] = {
                "probability_max_abs": max_abs(result["probabilities"], reference["probabilities"]),
                "hidden_max_abs": max_abs(result["last_hidden_state"], reference["last_hidden_state"])}
            entry["hidden_max_abs_vs_golden"] = max_abs(result["last_hidden_state"],
                                                        golden["official"]["last_hidden_state"][0])
        passed &= all(checks.values())
        summary["runs"][name] = entry
    a, b, c_run = (runs.get(k, {}) for k in "abc")
    rerun = bool(a.get("result") and c_run.get("result")) \
        and a["result"]["probabilities"] == c_run["result"]["probabilities"] \
        and a["result"]["last_hidden_state"] == c_run["result"]["last_hidden_state"]
    cancel = b.get("outcome") == "terminated" \
        and any(p.get("phase") == "decide_started" for p in b.get("progress", [])) \
        and summary["runs"].get("c", {}).get("checks", {}).get("completed", False)
    summary["rerun_bitwise_identical"] = rerun
    summary["cancel"] = {"passed": cancel, "outcome": b.get("outcome"), "cancel_after_ms": b.get("cancel_after_ms"),
                         "progress": b.get("progress")}
    summary["native_reference"] = {
        "probability_max_abs_vs_golden": max_abs(reference["probabilities"], golden["official"]["probabilities"]),
        "stages": reference["stages"]}
    summary["browser_process_peaks"] = {
        "max_peak_working_set": max((p["peak_working_set"] for p in processes), default=None),
        "max_peak_pagefile": max((p["peak_pagefile"] for p in processes), default=None),
        "processes": len(processes)}
    summary["passed"] = passed and rerun and cancel
    save(args.output / "summary.json", summary)
    print(json.dumps({"passed": summary["passed"], "rerun": rerun, "cancel": cancel,
                      "a": summary["runs"]["a"]["checks"], "c": summary["runs"]["c"]["checks"],
                      "a_error": summary["runs"]["a"]["error"], "a_panic": summary["runs"]["a"]["panic"]}, indent=1))
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
