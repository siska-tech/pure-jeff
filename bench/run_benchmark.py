"""Side-by-side benchmark: official Jeff (Python/PyTorch), Rust Native and browser Wasm, 1 thread.
Same checkpoint, requests and policy; every decision is checked against official references.
Descriptive measurements only: no SLO, adoption or general speed-up claim is derived."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import tempfile
import threading
import time

from procmem import TreeSampler

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
W2_REFS = ROOT / "docs/research/wasm-demo/w2-2026-10-11/official-references"
CASES = {  # name -> official reference (128-512 tokens, 2/3/8 candidates)
    "candidate-request": ROOT / "tests/fixtures/jeff-golden/candidate-request.json",
    "asr-unicode": ROOT / "tests/fixtures/jeff-golden/asr-unicode.json",
    "synthetic-ocr-ja-2-256": W2_REFS / "synthetic-ocr-ja-2-256.json",
    "synthetic-asr-unicode-2-384": W2_REFS / "synthetic-asr-unicode-2-384.json",
    "synthetic-asr-mixed-2-512": W2_REFS / "synthetic-asr-mixed-2-512.json",
    "synthetic-ocr-ascii-8-512": W2_REFS / "synthetic-ocr-ascii-8-512.json",
}
WARMUP = "candidate-request"
ARMS = ["jeff", "native", "wasm"]
# Registered before the run; never relaxed after seeing results.
GATES = {
    "probability_max_abs_vs_official": 1e-4,
    "decision": "every recorded decision (one-shot, resident and warm-up) completes with the official "
                "judgment and input token count and probabilities within the bound",
    "repeat": "within an arm and mode, every decision of the same case has bitwise identical probabilities",
    "threads": "jeff torch intra-op threads 1 (OMP/MKL 1); native compute threads 1; wasm single-threaded",
    "environment": "AC power at start and end; no other benchmark/build process at start",
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


class Power(c.Structure):
    _fields_ = [("ac", c.c_ubyte), ("flag", c.c_ubyte), ("percent", c.c_ubyte), ("saver", c.c_ubyte),
                ("life", c.c_uint32), ("full", c.c_uint32)]


def environment():
    power = Power()
    c.windll.kernel32.GetSystemPowerStatus(c.byref(power))
    scheme = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True).stdout.strip()
    tasks = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-Process | Sort-Object CPU -Descending | Select-Object -First 12 ProcessName,Id,CPU,"
                            "@{n='WS_MB';e={[int]($_.WorkingSet64/1MB)}} | ConvertTo-Json -Compress"],
                           capture_output=True, text=True).stdout
    return {"time_utc": datetime.now(timezone.utc).isoformat(), "ac_line_status": power.ac,
            "battery_percent": power.percent, "battery_saver": power.saver, "power_scheme": scheme,
            "platform": platform.platform(), "processor": platform.processor(), "logical_cpus": os.cpu_count(),
            "top_processes": json.loads(tasks or "[]")}


def busy_processes():
    names = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout.lower()
    return [n for n in ("cargo.exe", "rustc.exe", "jeff.exe", "resident_bench.exe", "tract") if n in names]


def check(reference, probabilities, judgment, tokens):
    official = reference["official"]
    error = max(abs(a - b) for a, b in zip(probabilities, official["probabilities"], strict=True))
    return {"error": error, "passed": error <= GATES["probability_max_abs_vs_official"]
            and judgment == official["judgment"] and tokens == official["input_tokens"]}


def run_process(command, env, timeout):
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    with TreeSampler(process.pid) as sampler:
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            out, err = process.communicate()
    return {"returncode": process.returncode, "wall_s": time.perf_counter() - started, "stdout": out.decode("utf-8"),
            "stderr": err.decode("utf-8", errors="replace")[-4000:], "memory": sampler.result()}


def stats(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None}
    return {"n": len(values), "median": statistics.median(values), "min": values[0], "max": values[-1]}


def ratio(a, b):
    return a / b if a is not None and b else None


def wasm_session(args, job, workdir, timeout):
    """One browser session in a fresh profile; returns (report, browser memory)."""
    manifest = json.loads(args.rust_manifest.read_text(encoding="utf-8"))
    checkpoint = args.rust_manifest.parent / manifest["checkpoint_dir"]
    assets = [("manifest", args.rust_manifest), ("decision_config", checkpoint / "decision_config.json"),
              ("tokenizer", checkpoint / "tokenizer.json"), ("readout", checkpoint / "readout.safetensors"),
              ("model", checkpoint / "model.safetensors")]
    routes = {"bench.html": (HERE / "wasm/bench.html", "text/html; charset=utf-8"),
              "w2-worker.js": (ROOT / "runtime/wasm/web/w2-worker.js", "text/javascript; charset=utf-8"),
              "probe.wasm": (args.wasm, "application/wasm")}
    routes.update({f"assets/{n}": (p, "application/octet-stream") for n, p in assets})
    for i, (name, request) in enumerate(job):
        path = workdir / f"request-{i}.json"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        routes[f"requests/{i}.json"] = (path, "application/json")
    config = {"wasm": "probe.wasm", "max_input_tokens": 512, "heap_reserve_bytes": 768 << 20,
              "assets": [{"name": n, "url": f"assets/{n}", "bytes": p.stat().st_size} for n, p in assets],
              "job": [{"name": name, "url": f"requests/{i}.json"} for i, (name, _) in enumerate(job)]}
    config_path = workdir / "bench-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    routes["bench-config.json"] = (config_path, "application/json")
    received = {"event": threading.Event()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            route = routes.get(self.path.split("?")[0].lstrip("/"))
            if route is None:
                self.send_error(404)
                return
            source, kind = route
            self.send_response(200)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(source.stat().st_size))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, self.wfile, 4 << 20)

        def do_POST(self):
            received["body"] = self.rfile.read(int(self.headers["content-length"]))
            self.send_response(204)
            self.end_headers()
            received["event"].set()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = Path(tempfile.mkdtemp(prefix="pj-bench-profile-"))
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
                                "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                                "--disable-background-networking", f"http://127.0.0.1:{server.server_port}/bench.html"])
    try:
        with TreeSampler(browser.pid) as sampler:
            completed = received["event"].wait(timeout)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    if not completed:
        return {"fatal": "browser timeout"}, sampler.result()
    return json.loads(received["body"]), sampler.result()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True, help="interpreter of the official Jeff environment")
    parser.add_argument("--py-manifest", type=Path, required=True, help="official Jeff bundle (cpu_threads=1)")
    parser.add_argument("--rust-manifest", type=Path, default=ROOT / "models/jeff-rust-bundle-pj.json")
    parser.add_argument("--jeff-exe", type=Path, default=ROOT / "runtime/rust/target/release/jeff.exe")
    parser.add_argument("--resident-exe", type=Path,
                        default=ROOT / "runtime/rust/target/release/examples/resident_bench.exe")
    parser.add_argument("--wasm", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--reps", type=int, default=2, help="repetitions of each case per resident session")
    parser.add_argument("--oneshot-reps", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    busy = busy_processes()
    if busy:
        raise SystemExit(f"other benchmark/build processes are running: {busy}")
    refs = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in CASES.items()}
    py_manifest = json.loads(args.py_manifest.read_text(encoding="utf-8"))
    rust_manifest = json.loads(args.rust_manifest.read_text(encoding="utf-8"))
    if py_manifest["policy"] != rust_manifest["policy"] or py_manifest["policy"]["cpu_threads"] != 1:
        raise SystemExit("both bundles must use the same policy with cpu_threads=1")
    rust_files = {f["path"]: f["sha256"] for f in rust_manifest["files"]}
    if {f["path"]: f["sha256"] for f in py_manifest["checkpoint_files"]} != rust_files:
        raise SystemExit("the official and Rust bundles must pin the same checkpoint files")
    rng = random.Random(args.seed)
    oneshot_plan = [(arm, case, rep) for arm in ("jeff", "native") for case in CASES for rep in range(args.oneshot_reps)]
    rng.shuffle(oneshot_plan)
    resident_plan = []
    for block in range(args.sessions):
        order = ARMS[block % 3:] + ARMS[:block % 3]
        job = [name for name in CASES for _ in range(args.reps)]
        random.Random(args.seed + 1000 + block).shuffle(job)
        resident_plan.append({"block": block, "arm_order": order, "job": [WARMUP] + job})
    env_start = environment()
    save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.side_by_side_preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "gates": GATES, "cases": list(CASES),
        "warmup": WARMUP, "oneshot_plan": oneshot_plan, "resident_plan": resident_plan, "seed": args.seed,
        "hashes": {"python": sha(args.python), "py_manifest": sha(args.py_manifest),
                   "rust_manifest": sha(args.rust_manifest), "jeff_exe": sha(args.jeff_exe),
                   "resident_exe": sha(args.resident_exe), "wasm": sha(args.wasm), "browser": sha(args.browser),
                   "driver": sha(__file__), "jeff_resident": sha(HERE / "jeff_resident.py"),
                   "bench_page": sha(HERE / "wasm/bench.html"), "w2_worker": sha(ROOT / "runtime/wasm/web/w2-worker.js"),
                   "jeff_worker": sha(ROOT / "runtime/jeff_worker.py"),
                   "references": {name: sha(path) for name, path in CASES.items()}},
        "environment_start": env_start,
    })
    if env_start["ac_line_status"] != 1:
        raise SystemExit("AC power is required")
    child_env = os.environ | {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONIOENCODING": "utf-8"}
    work = args.output / "work"
    work.mkdir()

    # One-shot: one new process per request, the existing CLI worker protocol for both runtimes.
    oneshot = []
    for i, (arm, case, rep) in enumerate(oneshot_plan):
        wire = {"schema_version": "kaze_judge.worker.v1", "request": refs[case]["request"],
                "max_input_tokens": 512, "max_forwards": 1, "timeout_ms": 600000}
        request_path, response_path = work / f"oneshot-{i}.request.json", work / f"oneshot-{i}.response.json"
        request_path.write_text(json.dumps(wire, ensure_ascii=False), encoding="utf-8")
        if arm == "jeff":
            command = [str(args.python), "-B", str(ROOT / "runtime/jeff_worker.py"), "--manifest", str(args.py_manifest),
                       "--request", str(request_path), "--response", str(response_path)]
        else:
            command = [str(args.jeff_exe), "worker", "--manifest", str(args.rust_manifest),
                       "--request", str(request_path), "--response", str(response_path)]
        run = run_process(command, child_env, args.timeout)
        result = json.loads(response_path.read_text(encoding="utf-8"))["result"] if response_path.exists() else None
        entry = {"index": i, "arm": arm, "case": case, "rep": rep, "returncode": run["returncode"],
                 "wall_s": run["wall_s"], "memory": run["memory"], "stderr": run["stderr"], "result_status": None}
        if result and result["status"] == "completed":
            value = result["value"]
            probabilities = [s["option_probability"] for s in value["scores"]]
            entry.update(result_status="completed", probabilities=probabilities, judgment=value["judgment"],
                         input_tokens=value["input_tokens"],
                         gate=check(refs[case], probabilities, value["judgment"], value["input_tokens"]))
        else:
            entry["result_status"] = result
        oneshot.append(entry)
        print(f"oneshot {i + 1}/{len(oneshot_plan)} {arm} {case} {run['wall_s']:.1f}s", flush=True)
    save(args.output / "oneshot.json", oneshot)

    # Resident: model loaded once per session; sessions rotate the arm order per block.
    resident = []
    for plan in resident_plan:
        job = [(name, refs[name]["request"]) for name in plan["job"]]
        job_path = work / f"resident-job-{plan['block']}.json"
        job_path.write_text(json.dumps([{"name": n, "request": r} for n, r in job], ensure_ascii=False), encoding="utf-8")
        for arm in plan["arm_order"]:
            session = {"block": plan["block"], "arm": arm}
            if arm == "wasm":
                workdir = work / f"wasm-{plan['block']}"
                workdir.mkdir()
                started = time.perf_counter()
                report, memory = wasm_session(args, job, workdir, args.timeout)
                session.update(wall_s=time.perf_counter() - started, memory=memory, fatal=report.get("fatal"),
                               page=report.get("page"), startup=report.get("startup"), decisions=[])
                for d in report.get("decisions", []):
                    out = d.get("output") or {}
                    stages = {s["name"]: s["ms"] / 1000 for s in out.get("stages", [])}
                    session["decisions"].append({
                        "name": d["name"], "total_s": d["ms"] / 1000, "forward_s": stages.get("forward"),
                        "prompt_tokenize_s": stages.get("prompt_tokenize"), "readout_policy_s": stages.get("readout_policy"),
                        "probabilities": out.get("probabilities"), "judgment": out.get("judgment"),
                        "input_tokens": len(out.get("input_ids") or []), "code": d.get("code"),
                        "linear_memory_bytes": d.get("linear_memory_bytes")})
            else:
                command = ([str(args.python), "-B", str(HERE / "jeff_resident.py"), str(args.py_manifest), str(job_path)]
                           if arm == "jeff" else [str(args.resident_exe), str(args.rust_manifest), str(job_path)])
                run = run_process(command, child_env, args.timeout)
                events = [json.loads(line) for line in run["stdout"].splitlines() if line.startswith("{")]
                session.update(wall_s=run["wall_s"], memory=run["memory"], returncode=run["returncode"],
                               stderr=run["stderr"], init=next((e for e in events if e["event"] == "init"), None),
                               decisions=[e for e in events if e["event"] == "decision"])
            for index, decision in enumerate(session["decisions"]):
                decision["warmup"] = index == 0
                if decision.get("probabilities"):
                    decision["gate"] = check(refs[decision["name"]], decision["probabilities"], decision["judgment"],
                                             decision["input_tokens"])
            resident.append(session)
            print(f"resident block {plan['block']} {arm} {session['wall_s']:.1f}s "
                  f"decisions {len(session['decisions'])}", flush=True)
    save(args.output / "resident.json", resident)
    env_end = environment()
    save(args.output / "environment-end.json", env_end)

    # Gates and descriptive statistics.
    failures = []
    for e in oneshot:
        if e["result_status"] != "completed" or not e["gate"]["passed"]:
            failures.append({"mode": "oneshot", "index": e["index"], "arm": e["arm"], "case": e["case"]})
    for s in resident:
        expected = len(next(p for p in resident_plan if p["block"] == s["block"])["job"])
        if s.get("fatal") or s.get("returncode") not in (None, 0) or len(s["decisions"]) != expected:
            failures.append({"mode": "resident", "block": s["block"], "arm": s["arm"], "session": "incomplete"})
        for d in s["decisions"]:
            if not d.get("gate", {}).get("passed"):
                failures.append({"mode": "resident", "block": s["block"], "arm": s["arm"], "case": d["name"]})
    repeat = {}
    for mode, items in (("oneshot", [(e["arm"], e["case"], e.get("probabilities")) for e in oneshot]),
                        ("resident", [(s["arm"], d["name"], d.get("probabilities")) for s in resident for d in s["decisions"]])):
        for arm, case, probabilities in items:
            repeat.setdefault(f"{mode}/{arm}/{case}", set()).add(json.dumps(probabilities))
    repeat_failures = sorted(k for k, v in repeat.items() if len(v) != 1)
    summary = {"schema_version": "pure_jeff.side_by_side_summary.v1", "failures": failures,
               "repeat_failures": repeat_failures,
               "environment_ok": env_end["ac_line_status"] == 1,
               "threads": {"jeff": [s["init"]["torch_threads"] for s in resident if s["arm"] == "jeff" and s.get("init")],
                           "native": [s["init"]["compute_threads"] for s in resident if s["arm"] == "native" and s.get("init")]},
               "max_error_vs_official": {
                   arm: max([e["gate"]["error"] for e in oneshot if e["arm"] == arm and "gate" in e]
                            + [d["gate"]["error"] for s in resident if s["arm"] == arm for d in s["decisions"] if "gate" in d],
                            default=None) for arm in ARMS},
               "oneshot": {}, "resident": {}, "startup": {}, "memory": {}}
    summary["threads_ok"] = all(t == 1 for t in summary["threads"]["jeff"] + summary["threads"]["native"])
    summary["passed"] = not failures and not repeat_failures and summary["environment_ok"] and summary["threads_ok"]
    for arm in ("jeff", "native"):
        summary["oneshot"][arm] = {case: stats([e["wall_s"] for e in oneshot if e["arm"] == arm and e["case"] == case])
                                   for case in CASES}
        summary["memory"][f"oneshot/{arm}"] = stats([e["memory"]["max_tree_working_set"] for e in oneshot if e["arm"] == arm])
    for arm in ARMS:
        rows = [d for s in resident if s["arm"] == arm for d in s["decisions"] if not d["warmup"]]
        summary["resident"][arm] = {case: {"total_s": stats([d["total_s"] for d in rows if d["name"] == case]),
                                           "forward_s": stats([d["forward_s"] for d in rows if d["name"] == case])}
                                    for case in CASES}
        summary["memory"][f"resident/{arm}"] = stats([s["memory"]["max_tree_working_set"] for s in resident if s["arm"] == arm])
        summary["memory"][f"resident/{arm}/process_peak"] = stats(
            [s["memory"]["max_process_peak_working_set"] for s in resident if s["arm"] == arm])
    summary["startup"]["jeff"] = stats([s["init"]["startup_s"] for s in resident if s["arm"] == "jeff" and s.get("init")])
    summary["startup"]["native"] = stats([s["init"]["startup_s"] for s in resident if s["arm"] == "native" and s.get("init")])
    summary["startup"]["wasm"] = stats([sum(v["ms"] for v in s["startup"].values()) / 1000
                                        for s in resident if s["arm"] == "wasm" and s.get("startup")])
    summary["ratios_of_medians"] = {
        case: {"resident_total_jeff_over_native": ratio(summary["resident"]["jeff"][case]["total_s"]["median"],
                                                        summary["resident"]["native"][case]["total_s"]["median"]),
               "resident_total_wasm_over_native": ratio(summary["resident"]["wasm"][case]["total_s"]["median"],
                                                        summary["resident"]["native"][case]["total_s"]["median"]),
               "oneshot_jeff_over_native": ratio(summary["oneshot"]["jeff"][case]["median"],
                                                 summary["oneshot"]["native"][case]["median"])}
        for case in CASES}
    save(args.output / "summary.json", summary)
    print(json.dumps({"passed": summary["passed"], "failures": len(failures), "repeat_failures": repeat_failures,
                      "max_error": summary["max_error_vs_official"]}, indent=1))
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
