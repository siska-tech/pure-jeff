"""Performance-parity benchmark: official Jeff (Python/PyTorch), Rust Native and the current
browser engine (apps/web-demo/engine), on the inputs of bench/cases/catalog.json.

Stages (each is its own run and its own acceptance; see bench/README.md and the plan in
docs/benchmark-parity-plan.md):
  short    resident Jeff vs Native, input groups 128/256/384/512 (127-129, 511-513)
  long     resident Jeff vs Native, input groups 874/3206/8192 (full-length acceptance = short + long)
  wasm     resident browser engine, inputs up to its 512-token limit (a separate baseline)
  oneshot  one new process per request through the default CLI worker path, Jeff and Native

Every decision of every arm (warm-up, measured and gate) passes the common numeric gate of
validate.py against the catalog's official reference, or the run fails. The plan (sessions,
input order, warm-up, gate inputs, statistics, extension rule) and all hashes are written to
preregistration.json before the first measurement; nothing is relaxed afterwards."""
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
import subprocess
import sys
import tempfile
import threading
import time

import catalog as cat
from procmem import TreeSampler
import stats
import validate

ROOT = cat.ROOT
HERE = cat.HERE
SCHEMA = "pure_jeff.bench_parity"
# Registered measured inputs. Every other catalog input of the stage's range is gate-only.
TIMED = {
    "short": ["synthetic-ocr-ja-2-127", "candidate-request", "synthetic-ocr-ja-2-128", "synthetic-ocr-ja-2-129",
              "synthetic-ocr-ja-2-256", "synthetic-ocr-ascii-8-256", "synthetic-asr-unicode-2-384",
              "synthetic-ocr-ascii-8-384", "synthetic-ocr-ja-2-511", "synthetic-ocr-ja-2-512",
              "synthetic-ocr-ascii-3-513", "synthetic-ocr-ascii-8-512"],
    "long": ["long-text", "maximum-candidates", "token-limit-8192"],
    "oneshot": ["candidate-request", "synthetic-ocr-ja-2-512"],
}
DEFAULTS = {  # stage -> blocks, extension blocks, reps per measured case and session
    "short": (6, 6, 4), "long": (6, 0, 4), "wasm": (6, 0, 4), "oneshot": (10, 0, 1)}
# Processes that must not run alongside a measurement (builds, installs, other benchmarks).
BUSY = ("cargo.exe", "rustc.exe", "link.exe", "cl.exe", "uv.exe", "pip.exe", "jeff.exe", "resident_bench.exe",
        "bench.exe", "wasm-pack.exe", "wasm-opt.exe")
MAX_INPUT_BYTES = 1 << 20


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def git(*args, cwd=ROOT):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


class Power(c.Structure):
    _fields_ = [("ac", c.c_ubyte), ("flag", c.c_ubyte), ("percent", c.c_ubyte), ("saver", c.c_ubyte),
                ("life", c.c_uint32), ("full", c.c_uint32)]


def powershell_json(script):
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script + " | ConvertTo-Json -Compress -Depth 4"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return {"unparsed": out[:2000]}


def sample_environment(full=False):
    """AC power, CPU load / performance / frequency (WMI class names are not localized), thermal
    zones when readable, and (full) power scheme, platform and the busiest processes."""
    power = Power()
    c.windll.kernel32.GetSystemPowerStatus(c.byref(power))
    value = {"time_utc": datetime.now(timezone.utc).isoformat(), "ac_line_status": power.ac,
             "battery_percent": power.percent, "battery_saver": power.saver,
             "cpu": powershell_json(
                 "$p = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation -Filter \"Name='_Total'\"; "
                 "$l = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter \"Name='_Total'\"; "
                 "$c = Get-CimInstance Win32_Processor | Select-Object -First 1; "
                 "[ordered]@{load_percent=$l.PercentProcessorTime; processor_performance_percent="
                 "$p.PercentProcessorPerformance; processor_frequency_mhz=$p.ProcessorFrequency; "
                 "current_clock_mhz=$c.CurrentClockSpeed; max_clock_mhz=$c.MaxClockSpeed}"),
             "thermal": powershell_json(
                 "try { Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature -ErrorAction Stop | "
                 "ForEach-Object { [ordered]@{zone=$_.InstanceName; celsius=[math]::Round($_.CurrentTemperature/10-273.15,1)} } }"
                 " catch { [ordered]@{unavailable=$_.Exception.Message} }")}
    if full:
        value["power_scheme"] = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True,
                                               encoding="utf-8", errors="replace").stdout.strip()
        value["platform"] = platform.platform()
        value["processor"] = powershell_json(
            "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,L2CacheSize,L3CacheSize")
        value["logical_cpus"] = os.cpu_count()
        value["top_processes"] = powershell_json(
            "Get-Process | Sort-Object CPU -Descending | Select-Object -First 12 ProcessName,Id,CPU,"
            "@{n='WS_MB';e={[int]($_.WorkingSet64/1MB)}}")
    return value


def busy_processes():
    names = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stdout.lower()
    busy = [n for n in BUSY if f'"{n}"' in names]
    if "uv.exe" in busy:
        # Long-lived `uv tool run` / `uv run` servers (e.g. editor extensions) are background load,
        # recorded with the environment; only installing or building uv commands block a run.
        lines = powershell_json("Get-CimInstance Win32_Process -Filter \"Name='uv.exe'\" | "
                                "ForEach-Object { $_.CommandLine }") or []
        lines = [lines] if isinstance(lines, str) else lines
        installing = (" sync", " pip ", " add ", " lock", " build", " venv", " python install", " tool install")
        if not any(any(word in (line or "").lower() for word in installing) for line in lines):
            busy.remove("uv.exe")
    return busy


def affinity(pid):
    kernel = c.windll.kernel32
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    process, system = c.c_size_t(), c.c_size_t()
    ok = kernel.GetProcessAffinityMask(handle, c.byref(process), c.byref(system))
    kernel.CloseHandle(handle)
    return {"process_mask": hex(process.value), "system_mask": hex(system.value)} if ok else None


def run_process(command, env, timeout, cwd=None):
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    placement = affinity(process.pid)
    with TreeSampler(process.pid) as sampler:
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            out, err = process.communicate()
    return {"returncode": process.returncode, "wall_s": time.perf_counter() - started,
            "stdout": out.decode("utf-8"), "stderr": err.decode("utf-8", errors="replace")[-4000:],
            "memory": sampler.result(), "affinity": placement}


# ---------------------------------------------------------------------------------------------
# Plans


def timed_cases(stage):
    return TIMED["long"] if stage == "long" else TIMED["short"]


def gate_cases(stage, cases):
    """Every catalog input in the stage's range, measured or not (wasm: every input, since the
    engine must reject those over 512 tokens)."""
    if stage == "wasm":
        return [c["id"] for c in cases]
    if stage == "short":
        return [c["id"] for c in cases if c["tokens"] <= 513]
    return [c["id"] for c in cases]


def resident_plan(stage, arms, blocks, extension, reps, seed, cases):
    by_id = {c["id"]: c for c in cases}
    timed = [t for t in timed_cases(stage) if stage != "wasm" or by_id[t]["expect"]["wasm"] == "completed"]
    # Warm-up: each measured case once, longest first, so every length has run before measuring.
    warmup = sorted(timed, key=lambda t: (-by_id[t]["tokens"], t))
    gate = [g for g in gate_cases(stage, cases)]
    plan = []
    for block in range(blocks + extension):
        job = [t for t in timed for _ in range(reps)]
        random.Random(seed * 1000 + block).shuffle(job)
        order = arms if block % 2 == 0 else arms[::-1]  # AB / BA
        plan.append({"block": block, "extension": block >= blocks, "arm_order": order, "warmup": warmup,
                     "measure": job, "gate": gate if block == 0 else []})
    return plan


def oneshot_plan(blocks, seed):
    """Each block runs every (case, arm) once; the arm order alternates per block and case."""
    plan = []
    for block in range(blocks):
        items = []
        for i, case in enumerate(TIMED["oneshot"]):
            order = ["jeff", "native"] if (block + i) % 2 == 0 else ["native", "jeff"]
            items.append([(arm, case) for arm in order])
        random.Random(seed * 1000 + block).shuffle(items)
        plan.append({"block": block, "runs": [run for pair in items for run in pair]})
    return plan


def job_items(plan_entry, by_id, budget):
    items = []
    for phase in ("warmup", "measure", "gate"):
        for name in plan_entry[phase]:
            items.append({"name": name, "phase": phase, "max_input_tokens": budget, "request": by_id[name]["request"]})
    return items


# ---------------------------------------------------------------------------------------------
# Wasm (current web demo engine through its own Worker)


def wasm_engine(args, work):
    sys.path.insert(0, str(ROOT / "apps/web-demo"))
    from strip_exports import strip  # noqa: E402
    engine, _, removed = strip(args.engine_wasm.read_bytes())
    path = work / "engine.wasm"
    path.write_bytes(engine)
    return path, removed


def wasm_session(args, engine, items, workdir, timeout):
    manifest = json.loads(args.rust_manifest.read_text(encoding="utf-8"))
    checkpoint = args.rust_manifest.parent / manifest["checkpoint_dir"]
    records = {f["path"]: f["sha256"] for f in manifest["files"]}
    paths = ["decision_config.json", "tokenizer.json", "readout.safetensors", "model.safetensors"]
    routes = {"engine-bench.html": (HERE / "wasm/engine-bench.html", "text/html; charset=utf-8"),
              "engine-worker.js": (ROOT / "apps/web-demo/web/engine-worker.js", "text/javascript; charset=utf-8"),
              "engine.wasm": (engine, "application/wasm"),
              "model/manifest.json": (args.rust_manifest, "application/json")}
    routes.update({f"model/{p}": (checkpoint / p, "application/octet-stream") for p in paths})
    job = []
    for i, item in enumerate(items):
        path = workdir / f"request-{i}.json"
        path.write_text(json.dumps(item["request"], ensure_ascii=False), encoding="utf-8")
        routes[f"requests/{i}.json"] = (path, "application/json")
        job.append({"name": item["name"], "phase": item["phase"], "url": f"requests/{i}.json",
                    "max_input_tokens": item["max_input_tokens"]})
    config = {"engine": {"url": "engine.wasm", "sha256": sha(engine)},
              "manifest": {"path": "manifest.json", "url": "model/manifest.json", "sha256": sha(args.rust_manifest),
                           "bytes": args.rust_manifest.stat().st_size},
              "assets": [{"slot": i, "path": p, "url": f"model/{p}", "sha256": records[p],
                          "bytes": (checkpoint / p).stat().st_size} for i, p in enumerate(paths)],
              "cache_name": f"pure-jeff-bench-{workdir.name}", "heap_reserve_bytes": 768 << 20,
              "max_input_bytes": MAX_INPUT_BYTES, "job": job}
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
    started = time.perf_counter()
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
                                "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                                "--disable-background-networking",
                                f"http://127.0.0.1:{server.server_port}/engine-bench.html"])
    try:
        with TreeSampler(browser.pid) as sampler:
            completed = received["event"].wait(timeout)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    wall = time.perf_counter() - started
    if not completed:
        return {"fatal": "browser timeout", "wall_s": wall, "memory": sampler.result(), "decisions": []}
    report = json.loads(received["body"])
    decisions = []
    for index, d in enumerate(report.get("decisions", [])):
        value = d.get("value") or {}
        outcome = (value.get("attempt") or {}).get("outcome") or {}
        if d.get("code") == 0 and outcome.get("status") == "completed":
            o = outcome["value"]
            result = {"status": "completed", "candidate_ids": [s["candidate_id"] for s in o["scores"]],
                      "probabilities": [s["option_probability"] for s in o["scores"]], "judgment": o["judgment"],
                      "input_tokens": o["input_tokens"], "forwards": o["forwards"]}
        elif d.get("code") == 0 and outcome.get("status") == "failed":
            result = {"status": "failed", "failure": outcome["value"]}
        else:
            result = {"status": "failed", "failure": "invalid_request" if d.get("code") == 1 else "unavailable",
                      "error": value.get("error") or d.get("error")}
        decisions.append({"index": index, "name": d["name"], "phase": d["phase"], "wall_s": d["elapsed_ms"] / 1000,
                          "stages": {s["name"]: s["ms"] / 1000 for s in value.get("stages", [])},
                          "linear_memory_bytes": d.get("linear_memory_bytes"), "outcome": result})
    return {"fatal": report.get("fatal"), "wall_s": wall, "memory": sampler.result(), "page": report.get("page"),
            "init": report.get("load"), "decisions": decisions}


# ---------------------------------------------------------------------------------------------
# Analysis


def gate_session(session, by_id, arm):
    failures = []
    for d in session["decisions"]:
        violations = validate.check(by_id[d["name"]], arm, d["outcome"])
        d["gate"] = violations
        if violations:
            failures.append({"block": session["block"], "arm": arm, "index": d["index"], "case": d["name"],
                             "violations": violations})
    return failures


def error_vs_reference(case, outcome):
    """Largest absolute probability difference from the reference, or None when not comparable."""
    try:
        return validate.max_abs([float(p) for p in outcome["probabilities"]], case["reference"]["probabilities"])
    except (KeyError, TypeError, ValueError):
        return None


def median_by_case(session, phase="measure"):
    rows = {}
    for d in session["decisions"]:
        if d["phase"] == phase and d["outcome"].get("status") == "completed":
            rows.setdefault(d["name"], []).append(d["wall_s"])
    return {name: stats.describe(values)["median"] for name, values in rows.items()}


def analyse_resident(stage, plan, sessions, by_id, arms, blocks):
    summary = {"cases": {}, "load": {}, "first": {}, "groups": {}}
    for arm in arms:
        own = [s for s in sessions if s["arm"] == arm and s["block"] < blocks]
        summary["load"][arm] = stats.describe([(s.get("init") or {}).get("load_s", (s.get("init") or {}).get(
            "startup_s")) for s in own])
        summary["first"][arm] = stats.describe([s["decisions"][0]["wall_s"] for s in own if s["decisions"]])
        for case in timed_cases(stage):
            values = [d["wall_s"] for s in own for d in s["decisions"]
                      if d["phase"] == "measure" and d["name"] == case and d["outcome"].get("status") == "completed"]
            if values:
                summary["cases"].setdefault(case, {})[arm] = stats.describe(values)
    if set(arms) != {"jeff", "native"}:
        return summary
    groups = {}
    for case in timed_cases(stage):
        groups.setdefault(by_id[case]["group"], []).append(case)
    for group, members in groups.items():
        ratios = []
        for block in range(blocks):
            medians = {s["arm"]: median_by_case(s) for s in sessions if s["block"] == block}
            try:
                ratios.append(stats.geomean(medians["native"][m] / medians["jeff"][m] for m in members))
            except (KeyError, TypeError, ZeroDivisionError):
                ratios.append(None)
        summary["groups"][group] = {"cases": members, **stats.equivalence(ratios)}
    for case, row in summary["cases"].items():
        per_block = []
        for block in range(blocks):
            medians = {s["arm"]: median_by_case(s) for s in sessions if s["block"] == block}
            if case in medians.get("native", {}) and case in medians.get("jeff", {}):
                per_block.append(medians["native"][case] / medians["jeff"][case])
        row["native_over_jeff"] = stats.equivalence(per_block)
    return summary


# ---------------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["short", "long", "wasm", "oneshot"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--path", choices=["api", "internal"], default="api",
                        help="resident measurement boundary (internal is diagnostic only)")
    parser.add_argument("--threads", type=int, default=1, help="must equal both bundles' cpu_threads")
    parser.add_argument("--python", type=Path, help="interpreter of the official Jeff environment")
    parser.add_argument("--py-manifest", type=Path, help="official Jeff reference bundle")
    parser.add_argument("--rust-manifest", type=Path, required=True)
    parser.add_argument("--jeff-exe", type=Path, default=ROOT / "runtime/rust/target/release/jeff.exe")
    parser.add_argument("--resident-exe", type=Path,
                        default=ROOT / "runtime/rust/target/release/examples/resident_bench.exe")
    parser.add_argument("--retain-f32", action="store_true",
                        help="Native resident loads with LoadOptions::retain_f32 (API path only)")
    parser.add_argument("--engine-wasm", type=Path, help="unstripped web demo engine (tools/build_wasm.py engine)")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--blocks", type=int)
    parser.add_argument("--extension-blocks", type=int)
    parser.add_argument("--reps", type=int)
    parser.add_argument("--seed", type=int, default=20261012)
    parser.add_argument("--timeout", type=float, default=4 * 3600)
    parser.add_argument("--smoke", action="store_true",
                        help="harness check: allows fewer blocks; the run is never accepted")
    args = parser.parse_args()
    blocks, extension, reps = DEFAULTS[args.stage]
    blocks = args.blocks if args.blocks is not None else blocks
    extension = args.extension_blocks if args.extension_blocks is not None else extension
    reps = args.reps if args.reps is not None else reps
    if args.stage in ("short", "long", "oneshot") and blocks < stats.MIN_BLOCKS and not args.smoke:
        raise SystemExit(f"at least {stats.MIN_BLOCKS} blocks are required")
    arms = ["wasm"] if args.stage == "wasm" else ["jeff", "native"]
    if args.retain_f32 and (args.path != "api" or args.stage not in ("short", "long")):
        raise SystemExit("--retain-f32 needs a resident stage on the API path")
    if "jeff" in arms and (args.python is None or args.py_manifest is None):
        raise SystemExit("--python and --py-manifest are required")
    if "wasm" in arms and (args.engine_wasm is None or args.browser is None):
        raise SystemExit("--engine-wasm and --browser are required")
    busy = busy_processes()
    if busy:
        raise SystemExit(f"build/install/benchmark processes are running: {busy}")
    catalog = cat.load()
    if catalog["token_check_failures"]:
        raise SystemExit("the catalog has token check failures")
    by_id = cat.by_id(catalog)
    rust_manifest = json.loads(args.rust_manifest.read_text(encoding="utf-8"))
    if rust_manifest["policy"]["cpu_threads"] != args.threads and args.stage != "wasm":
        raise SystemExit("the Native bundle's cpu_threads differs from --threads")
    if {f["path"]: f["sha256"] for f in rust_manifest["files"]} != {
            f["path"]: f["sha256"] for f in catalog["reference"]["checkpoint_files"]}:
        raise SystemExit("the Native bundle pins other checkpoint files than the catalog reference")
    if rust_manifest["policy"]["min_probability"] != catalog["reference"]["policy"]["min_probability"] or \
            rust_manifest["policy"]["min_margin"] != catalog["reference"]["policy"]["min_margin"]:
        raise SystemExit("the Native policy differs from the catalog reference")
    hashes = {"driver": sha(__file__), "catalog_module": sha(HERE / "catalog.py"), "catalog": sha(cat.CATALOG),
              "validate": sha(HERE / "validate.py"), "stats": sha(HERE / "stats.py"), "procmem": sha(HERE / "procmem.py"),
              "rust_manifest": sha(args.rust_manifest), "cargo_lock": sha(ROOT / "Cargo.lock"),
              "cli_cargo_lock": sha(ROOT / "runtime/rust/Cargo.lock"),
              "requests": {c["id"]: c["request_sha256"] for c in catalog["cases"]}}
    if "jeff" in arms:
        py_manifest = json.loads(args.py_manifest.read_text(encoding="utf-8"))
        if py_manifest["policy"] != rust_manifest["policy"] or py_manifest["policy"]["cpu_threads"] != args.threads:
            raise SystemExit("both bundles must use the same policy with cpu_threads = --threads")
        hashes |= {"python": sha(args.python), "py_manifest": sha(args.py_manifest),
                   "jeff_resident": sha(HERE / "jeff_resident.py"), "jeff_worker": sha(ROOT / "runtime/jeff_worker.py"),
                   "jeff_source_revision": py_manifest["source_revision"],
                   "jeff_uv_lock": sha(Path(py_manifest["source"]) / "uv.lock")}
    if args.stage in ("short", "long"):
        hashes |= {"resident_exe": sha(args.resident_exe), "resident_source": sha(
            ROOT / "runtime/rust/examples/resident_bench.rs")}
    if args.stage == "oneshot":
        hashes["jeff_exe"] = sha(args.jeff_exe)
    if "wasm" in arms:
        hashes |= {"engine_wasm_unstripped": sha(args.engine_wasm), "browser": sha(args.browser),
                   "engine_worker": sha(ROOT / "apps/web-demo/web/engine-worker.js"),
                   "engine_bench_page": sha(HERE / "wasm/engine-bench.html")}
    budget = cat.WASM_MAX_TOKENS if args.stage == "wasm" else cat.MAX_TOKENS
    plan = (oneshot_plan(blocks, args.seed) if args.stage == "oneshot"
            else resident_plan(args.stage, arms, blocks, extension, reps, args.seed, catalog["cases"]))
    args.output.mkdir(parents=True)
    work = args.output / "work"
    work.mkdir()
    engine = None
    if "wasm" in arms:
        engine, removed = wasm_engine(args, work)
        hashes |= {"engine_wasm_stripped": sha(engine), "engine_removed_exports": removed}
    env_start = sample_environment(full=True)
    save(args.output / "preregistration.json", {
        "schema_version": f"{SCHEMA}.preregistration.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "stage": args.stage, "smoke": args.smoke, "arms": arms, "path": args.path,
        "native_options": {"retain_f32": args.retain_f32}, "threads": args.threads, "budget_tokens": budget,
        "boundaries": {
            "api": "resident: wall time around Model::decide (Native) / jeff_worker.infer after loading (Jeff); "
                   "includes request checks, budgets, deadline, artifacts and output validation",
            "internal": "resident, diagnostic: tokenize + forward + readout + policy called directly, timers between",
            "load": "resident: bundle verification + tokenizer + weights (Native Model::load; Jeff verify, import, "
                    "DecisionModel)",
            "first": "resident: the first decision after loading (the first warm-up item)",
            "warm": "resident: measured decisions after the warm-up of every measured length",
            "oneshot": "parent wall time of one new worker process per request (default CLI worker path), "
                       "including process start, verification, load and one decision",
            "wasm": "browser: elapsed time of demo_evaluate in the Worker; load = download + streamed hash + open",
        },
        "gates": validate.GATE, "statistics": stats.RULES,
        "extension_rule": (f"after {blocks} blocks, if any input group's verdict is 'insufficient', run the "
                           f"registered {extension} extension blocks once and judge on all blocks; never more")
        if extension else "no extension",
        "blocks": blocks, "extension_blocks": extension, "reps": reps, "seed": args.seed,
        "timed": timed_cases(args.stage) if args.stage != "oneshot" else TIMED["oneshot"], "plan": plan,
        "source": {"commit": git("rev-parse", "HEAD"), "dirty": git("status", "--porcelain"),
                   "features": {"library": "default (native)", "cli": "pure-jeff-cli (process)",
                                "resident_bench": "pure-jeff-cli example, library default features"},
                   "rustc": subprocess.run(["rustc", "-Vv"], capture_output=True, text=True).stdout.strip()},
        "checkpoint": {"revision": rust_manifest.get("checkpoint_revision"), "files": rust_manifest["files"]},
        "policy": rust_manifest["policy"], "hashes": hashes, "environment_start": env_start,
    })
    if env_start["ac_line_status"] != 1:
        raise SystemExit("AC power is required")
    child_env = os.environ | {"OMP_NUM_THREADS": str(args.threads), "MKL_NUM_THREADS": str(args.threads),
                              "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    sessions_dir = args.output / "sessions"
    sessions_dir.mkdir()
    failures, sessions, records = [], [], []

    def guarded(run):
        busy = busy_processes()
        if busy:
            raise SystemExit(f"build/install/benchmark processes started during the run: {busy}")
        before = sample_environment()
        result = run()
        result["environment"] = {"before": before, "after": sample_environment()}
        return result

    if args.stage == "oneshot":
        for entry in plan:
            for i, (arm, case) in enumerate(entry["runs"]):
                tag = f"oneshot-{entry['block']}-{i}"
                wire = {"schema_version": "pure_jeff.worker.v1", "request": by_id[case]["request"],
                        "max_input_tokens": budget, "max_forwards": 1, "timeout_ms": int(args.timeout * 1000)}
                request_path, response_path = work / f"{tag}.request.json", work / f"{tag}.response.json"
                request_path.write_text(json.dumps(wire, ensure_ascii=False), encoding="utf-8")
                command = ([str(args.python), "-B", str(ROOT / "runtime/jeff_worker.py"), "--manifest",
                            str(args.py_manifest), "--request", str(request_path), "--response", str(response_path)]
                           if arm == "jeff" else
                           [str(args.jeff_exe), "worker", "--manifest", str(args.rust_manifest), "--request",
                            str(request_path), "--response", str(response_path)])
                run = guarded(lambda: run_process(command, child_env, args.timeout))
                result = json.loads(response_path.read_text(encoding="utf-8"))["result"] \
                    if response_path.exists() else None
                if result and result["status"] == "completed":
                    o = result["value"]
                    outcome = {"status": "completed", "candidate_ids": [s["candidate_id"] for s in o["scores"]],
                               "probabilities": [s["option_probability"] for s in o["scores"]],
                               "judgment": o["judgment"], "input_tokens": o["input_tokens"], "forwards": o["forwards"]}
                else:
                    outcome = {"status": "failed", "failure": (result or {}).get("value", "no response")}
                session = {"block": entry["block"], "arm": arm, "index": i, "case": case, **{
                    k: run[k] for k in ("returncode", "wall_s", "memory", "affinity", "stderr", "environment")},
                    "decisions": [{"index": 0, "name": case, "phase": "measure", "wall_s": run["wall_s"],
                                   "outcome": outcome}]}
                failures += gate_session(session, by_id, arm)
                if run["returncode"] != 0:
                    failures.append({"block": entry["block"], "arm": arm, "index": i, "case": case,
                                     "violations": [f"exit code {run['returncode']}"]})
                records.append((arm, "oneshot", case, outcome))
                sessions.append(session)
                save(sessions_dir / f"{tag}-{arm}.json", session)
                print(f"{tag} {arm} {case} {run['wall_s']:.2f}s", flush=True)
    else:
        def run_block(entry):
            items = job_items(entry, by_id, budget)
            job_path = work / f"job-{entry['block']}.json"
            job_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            for arm in entry["arm_order"]:
                if arm == "wasm":
                    workdir = work / f"wasm-{entry['block']}"
                    workdir.mkdir()
                    session = guarded(lambda: wasm_session(args, engine, items, workdir, args.timeout))
                    session.update(block=entry["block"], arm=arm, returncode=None)
                else:
                    command = ([str(args.python), "-B", str(HERE / "jeff_resident.py"), "--mode", args.path,
                                str(args.py_manifest), str(job_path)] if arm == "jeff" else
                               [str(args.resident_exe), *(["--retain-f32"] if args.retain_f32 else []),
                                "--mode", args.path, str(args.rust_manifest), str(job_path)])
                    run = guarded(lambda: run_process(command, child_env, args.timeout))
                    events = [json.loads(line) for line in run["stdout"].splitlines() if line.startswith("{")]
                    session = {"block": entry["block"], "arm": arm, **{
                        k: run[k] for k in ("returncode", "wall_s", "memory", "affinity", "stderr", "environment")},
                        "init": next((e for e in events if e["event"] == "init"), None),
                        "decisions": [e for e in events if e["event"] == "decision"]}
                    threads = (session["init"] or {}).get("torch_threads" if arm == "jeff" else "compute_threads")
                    if threads != args.threads:
                        failures.append({"block": entry["block"], "arm": arm, "violations": [f"threads {threads}"]})
                if session.get("fatal") or session.get("returncode") not in (None, 0) or \
                        len(session["decisions"]) != len(items):
                    failures.append({"block": entry["block"], "arm": arm, "violations": [
                        f"incomplete session: {session.get('fatal') or session.get('stderr', '')[-300:]}"]})
                failures.extend(gate_session(session, by_id, arm))
                records.extend((arm, args.path, d["name"], d["outcome"]) for d in session["decisions"])
                sessions.append(session)
                save(sessions_dir / f"block-{entry['block']}-{arm}.json", session)
                print(f"block {entry['block']} {arm} {session['wall_s']:.1f}s decisions {len(session['decisions'])} "
                      f"gate failures {len(failures)}", flush=True)

        for entry in plan[:blocks]:
            run_block(entry)
        extended = False
        if extension and not failures:
            interim = analyse_resident(args.stage, plan, sessions, by_id, arms, blocks)
            if any(g["verdict"] == "insufficient" for g in interim["groups"].values()):
                extended = True
                for entry in plan[blocks:]:
                    run_block(entry)

    env_end = sample_environment(full=True)
    save(args.output / "environment-end.json", env_end)
    repeat = validate.repeat_violations(records)
    summary = {"schema_version": f"{SCHEMA}.summary.v1", "stage": args.stage, "smoke": args.smoke, "path": args.path,
               "native_options": {"retain_f32": args.retain_f32},
               "threads": args.threads, "gate_failures": failures, "repeat_violations": repeat,
               "environment_ok": env_end["ac_line_status"] == 1 and all(
                   s["environment"]["before"]["ac_line_status"] == 1 and s["environment"]["after"]["ac_line_status"] == 1
                   for s in sessions),
               "max_abs_vs_official": {arm: max([e for a, _, c, o in records if a == arm
                                                 for e in [error_vs_reference(by_id[c], o)] if e is not None],
                                                default=None) for arm in arms}}
    if args.stage == "oneshot":
        summary["cases"] = {case: {arm: {
            "wall_s": stats.describe([s["wall_s"] for s in sessions if s["arm"] == arm and s["case"] == case]),
            "max_process_peak_working_set": stats.describe([s["memory"]["max_process_peak_working_set"]
                                                            for s in sessions if s["arm"] == arm and s["case"] == case]),
            "max_tree_working_set": stats.describe([s["memory"]["max_tree_working_set"]
                                                    for s in sessions if s["arm"] == arm and s["case"] == case]),
            "max_tree_private": stats.describe([s["memory"]["max_tree_private"]
                                                for s in sessions if s["arm"] == arm and s["case"] == case]),
            "max_process_page_faults": stats.describe([s["memory"].get("max_process_page_faults")
                                                       for s in sessions if s["arm"] == arm and s["case"] == case]),
        } for arm in arms} for case in TIMED["oneshot"]}
        summary["probabilities"] = {case: {arm: next((o["probabilities"] for a, _, c, o in records
                                                      if a == arm and c == case and o.get("status") == "completed"), None)
                                           for arm in arms} for case in TIMED["oneshot"]}
    else:
        used = blocks + (extension if extended else 0)
        summary.update(blocks_used=used, extended=extended,
                       **analyse_resident(args.stage, plan, sessions, by_id, arms, used))
        summary["memory"] = {arm: {
            "max_tree_working_set": stats.describe([s["memory"]["max_tree_working_set"]
                                                    for s in sessions if s["arm"] == arm]),
            "max_process_peak_working_set": stats.describe([s["memory"]["max_process_peak_working_set"]
                                                            for s in sessions if s["arm"] == arm]),
            "max_tree_private": stats.describe([s["memory"]["max_tree_private"] for s in sessions if s["arm"] == arm]),
            "max_process_page_faults": stats.describe([s["memory"].get("max_process_page_faults")
                                                       for s in sessions if s["arm"] == arm])} for arm in arms}
        summary["kernel"] = {arm: next(((s.get("init") or {}).get("kernel") for s in sessions if s["arm"] == arm), None)
                             for arm in arms}
        if "wasm" in arms:
            summary["wasm_page"] = next((s.get("page") for s in sessions if s.get("page")), None)
        if args.stage != "wasm":
            summary["verdict"] = {g: v["verdict"] for g, v in summary["groups"].items()}
    summary["valid"] = not failures and not repeat and summary["environment_ok"]
    if args.stage in ("short", "long"):
        summary["accepted"] = not args.smoke and summary["valid"] and all(v == "equivalent" for v in summary["verdict"].values())
    save(args.output / "summary.json", summary)
    print(json.dumps({k: summary.get(k) for k in ("valid", "accepted", "verdict", "repeat_violations",
                                                  "max_abs_vs_official")}, indent=1))
    print(f"gate failures: {len(failures)}")
    raise SystemExit(0 if summary["valid"] else 1)


if __name__ == "__main__":
    main()
