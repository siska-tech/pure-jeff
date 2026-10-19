"""Issue #18: the multi-thread Native path on one host, on any OS and CPU (Windows, Linux, macOS;
x86_64, ARM64). Standard library only, so it also runs on CI runners.

  host       OS, CPU model, logical CPUs, the OS cache description where readable (Linux sysfs),
             and gemm's CACHE_INFO from `thread_probe`: unpinned, and with the process pinned
             from its start to each logical CPU (Windows, Linux), grouped by distinct value;
  matrix     `resident_bench --mode api` at each thread count, `--processes` independent
             processes each deciding every input twice (the second pass in reverse order); the
             reference is the first process at one thread, pass 1;
  pinned     one process per CACHE_INFO group (and one restricted to the CPUs other than CPU0)
             at each `--pinned-threads` count, pinned to that group's CPUs from its start,
             deciding the short inputs once (skipped where pinning is not supported);
  timeout    `timeout_reuse` at each `--timeout-threads` count.

Every decision must pass the common numeric gate (bench/validate.py) and equal the reference
bit for bit (probabilities and judgment). Load, startup, per-decision wall time and the peak
memory of every process are recorded as observations only (no speed verdict; CI runners are
shared machines). The bundles are locked with `jeff lock` next to the checkpoint for the run and
removed afterwards (copies are kept in the output).

    python -B bench/host_matrix.py --output <new dir> --bin <cargo release dir> \
        [--checkpoint models/jeff-checkpoint] [--threads 1 2 4 8] [--processes 2]"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time

import catalog as cat
import validate

ROOT = cat.ROOT
REVISION = "51552f39a943d62e8387c4ea5e17026a1408729f"
OLD_GATE = ROOT / "docs/research/jeff-onnx-tract/native-cache-fixed-gate-2026-10-11/old-gate-reference.json"
SHORT_MAX_TOKENS = 600
WINDOWS = os.name == "nt"
LINUX = sys.platform.startswith("linux")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def command_output(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def bits(outcome):
    if outcome.get("status") == "completed":
        return [float(p).hex() for p in outcome["probabilities"]] + [json.dumps(outcome.get("judgment"), sort_keys=True)]
    return ["failed", outcome.get("failure")]


# --- processes pinned from their start, and their peak memory ---------------------------------

if WINDOWS:
    import ctypes as c
    from ctypes import wintypes as w

    class Counters(c.Structure):
        _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [(name, c.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

    _kernel = c.WinDLL("kernel32", use_last_error=True)
    _psapi = c.WinDLL("psapi", use_last_error=True)
    _ntdll = c.WinDLL("ntdll")
    CREATE_SUSPENDED = 0x00000004

    def _handle(process):
        return w.HANDLE(int(process._handle))  # Popen keeps the process handle open after exit

    def _pin_and_resume(process, cpus):
        if cpus is not None:
            mask = sum(1 << cpu for cpu in cpus)
            if not _kernel.SetProcessAffinityMask(_handle(process), c.c_size_t(mask)):
                process.kill()
                raise OSError(f"SetProcessAffinityMask failed ({c.get_last_error()})")
        if _ntdll.NtResumeProcess(_handle(process)) != 0:
            process.kill()
            raise OSError("NtResumeProcess failed")

    def _peak_memory(process):
        value = Counters(cb=c.sizeof(Counters))
        if not _psapi.GetProcessMemoryInfo(_handle(process), c.byref(value), c.sizeof(value)):
            return None
        return {"peak_working_set_bytes": value.PeakWorkingSetSize, "peak_private_bytes": value.PeakPagefileUsage}


def pinning_supported():
    return WINDOWS or LINUX


def run(command, stem, cpus=None, timeout=4 * 3600):
    """Run `command` with stdout/stderr in `<stem>.stdout.jsonl` / `<stem>.stderr.log`, pinned to
    `cpus` from its first instruction when given."""
    out_path, err_path = Path(f"{stem}.stdout.jsonl"), Path(f"{stem}.stderr.log")
    env = os.environ | {"PYTHONUTF8": "1"}
    started = time.perf_counter()
    memory = None
    with out_path.open("xb") as out, err_path.open("xb") as err:
        if WINDOWS:
            process = subprocess.Popen(command, stdout=out, stderr=err, env=env,
                                       creationflags=CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW)
            _pin_and_resume(process, cpus)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            memory = _peak_memory(process)
            returncode = process.returncode
        else:
            preexec = (lambda: os.sched_setaffinity(0, cpus)) if cpus is not None else None
            process = subprocess.Popen(command, stdout=out, stderr=err, env=env, preexec_fn=preexec)
            timer = threading.Timer(timeout, process.kill)
            timer.start()
            try:
                _, status, usage = os.wait4(process.pid, 0)
            finally:
                timer.cancel()
            returncode = os.waitstatus_to_exitcode(status)
            process.returncode = returncode
            # ru_maxrss: KiB on Linux, bytes on macOS.
            memory = {"peak_rss_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)}
    stdout = out_path.read_text(encoding="utf-8", errors="replace")
    return {"returncode": returncode, "wall_s": time.perf_counter() - started, "memory": memory, "cpus": cpus,
            "events": [json.loads(line) for line in stdout.splitlines() if line.startswith("{")],
            "stderr": err_path.read_text(encoding="utf-8", errors="replace")[-2000:]}


# --- host description -------------------------------------------------------------------------

def linux_caches():
    """Per logical CPU: the sysfs cache description and, on hybrid CPUs, the core type."""
    base = Path("/sys/devices/system/cpu")
    types = {}
    for kind in base.glob("types/*"):  # e.g. intel_core_*, intel_atom_* on hybrid parts
        cpus = (kind / "cpulist").read_text().strip() if (kind / "cpulist").exists() else ""
        types[kind.name] = cpus
    per_cpu = {}
    for cpu in sorted(base.glob("cpu[0-9]*"), key=lambda p: int(p.name[3:])):
        entries = []
        for index in sorted(cpu.glob("cache/index*")):
            read = lambda name: (index / name).read_text().strip() if (index / name).exists() else None
            entries.append({k: read(k) for k in ("level", "type", "size", "ways_of_associativity",
                                                  "coherency_line_size", "shared_cpu_list")})
        per_cpu[int(cpu.name[3:])] = entries
    groups = {}
    for cpu, entries in per_cpu.items():
        key = json.dumps([{k: v for k, v in e.items() if k != "shared_cpu_list"} for e in entries], sort_keys=True)
        groups.setdefault(key, []).append(cpu)
    return {"core_types": types, "cache_groups": [{"cpus": v, "caches": json.loads(k)} for k, v in groups.items()]}


def host():
    info = {"platform": platform.platform(), "system": platform.system(), "machine": platform.machine(),
            "python": sys.version.split()[0], "logical_cpus": os.cpu_count(),
            "runner": {k: os.environ.get(k) for k in ("RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH", "ImageOS",
                                                      "ImageVersion") if os.environ.get(k)}}
    if hasattr(os, "sched_getaffinity"):
        info["process_affinity"] = sorted(os.sched_getaffinity(0))
    if LINUX:
        text = Path("/proc/cpuinfo").read_text(errors="replace")
        fields = {}
        for line in text.splitlines():
            key, _, value = line.partition(":")
            key = key.strip()
            if key in ("model name", "CPU implementer", "CPU part", "CPU variant", "flags", "Features"):
                fields.setdefault(key, set()).add(value.strip())
        info["cpuinfo"] = {k: sorted(v) if k not in ("flags", "Features") else
                           sorted({f for s in v for f in s.split()}) for k, v in fields.items()}
        info["lscpu"] = command_output("lscpu")
        info["memory_total"] = next((l for l in Path("/proc/meminfo").read_text().splitlines()
                                     if l.startswith("MemTotal")), None)
        info["os_caches"] = linux_caches()
    elif WINDOWS:
        info["processor"] = command_output(
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,"
            "MaxClockSpeed,L2CacheSize,L3CacheSize | ConvertTo-Json -Compress")
        info["memory_total"] = command_output(
            "powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")
    elif sys.platform == "darwin":
        info["processor"] = command_output("sysctl", "machdep.cpu.brand_string", "hw.perflevel0.logicalcpu",
                                           "hw.perflevel1.logicalcpu", "hw.l1dcachesize", "hw.l2cachesize",
                                           "hw.memsize")
    return info


def probe_caches(probe, output):
    """CACHE_INFO unpinned (three processes) and pinned to each logical CPU from the start."""
    def one(stem, cpus):
        result = run([str(probe)], output / stem, cpus=cpus, timeout=120)
        line = result["events"][0] if result["events"] else None
        return {"cpus": cpus, "returncode": result["returncode"], "result": line}
    unpinned = [one(f"probe-unpinned-{i}", None) for i in range(3)]
    pinned = [one(f"probe-cpu{cpu}", [cpu]) for cpu in range(os.cpu_count())] if pinning_supported() else []
    groups = {}
    for record in unpinned + pinned:
        info = (record["result"] or {}).get("gemm_cache_info")
        groups.setdefault(json.dumps(info, sort_keys=True), {"gemm_cache_info": info, "pinned_cpus": [],
                                                             "unpinned_processes": 0})
        if record["cpus"] is None:
            groups[json.dumps(info, sort_keys=True)]["unpinned_processes"] += 1
        else:
            groups[json.dumps(info, sort_keys=True)]["pinned_cpus"] += record["cpus"]
    return {"unpinned": unpinned, "pinned": pinned, "groups": list(groups.values())}


# --- the run ----------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bin", type=Path, required=True, help="cargo release directory of runtime/rust")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "models/jeff-checkpoint")
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--processes", type=int, default=2)
    parser.add_argument("--pinned-threads", type=int, nargs="*", default=None,
                        help="thread counts of the pinned processes (default: 1 and the largest of --threads)")
    parser.add_argument("--timeout-threads", type=int, nargs="*", default=None,
                        help="default: 1 and the largest of --threads")
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    parser.add_argument("--cases", nargs="*", default=None, help="catalog IDs (default: every case)")
    args = parser.parse_args()
    if args.threads[0] != 1:
        raise SystemExit("the first thread count must be 1 (the reference)")
    top = max(args.threads)
    pinned_threads = args.pinned_threads if args.pinned_threads is not None else sorted({1, top})
    timeout_threads = args.timeout_threads if args.timeout_threads is not None else sorted({1, top})
    suffix = ".exe" if WINDOWS else ""
    exe = {name: args.bin / f"{name}{suffix}" for name in ("jeff",)}
    exe |= {name: args.bin / "examples" / f"{name}{suffix}" for name in ("resident_bench", "timeout_reuse",
                                                                         "thread_probe")}
    for path in exe.values():
        if not path.is_file():
            raise SystemExit(f"missing {path}")
    catalog = cat.load()
    by_id = cat.by_id(catalog)
    names = args.cases or [case["id"] for case in catalog["cases"]]
    short = [n for n in names if by_id[n]["tokens"] <= SHORT_MAX_TOKENS]
    args.output.mkdir(parents=True)
    output = args.output.resolve()
    (output / "logs").mkdir()
    job = lambda selected, phase: [{"name": n, "phase": phase, "max_input_tokens": cat.MAX_TOKENS,
                                    "request": by_id[n]["request"]} for n in selected]
    jobs = {"matrix": job(names, "pass1") + job(names[::-1], "pass2"), "pinned": job(short, "pinned")}
    for key, value in jobs.items():
        (output / f"{key}-job.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    run_id = f"host-matrix-{os.getpid()}"
    bundle_dir = args.checkpoint.resolve().parent
    bundles = {}
    for n in sorted(set(args.threads) | set(pinned_threads) | set(timeout_threads)):
        path = bundle_dir / f"{run_id}-t{n}.json"
        locked = subprocess.run([str(exe["jeff"]), "lock", str(args.checkpoint), str(path), REVISION, "0.7", "0.1",
                                 str(n)], capture_output=True, text=True)
        if locked.returncode:
            raise SystemExit(f"jeff lock t{n} failed: {locked.stderr.strip()}")
        bundles[n] = path
        shutil.copyfile(path, output / f"bundle-t{n}.json")
    try:
        info = {"schema_version": "pure_jeff.host_matrix.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
                "source": {"commit": command_output("git", "-C", str(ROOT), "rev-parse", "HEAD"),
                           "dirty": command_output("git", "-C", str(ROOT), "status", "--porcelain")},
                "rustc": command_output("rustc", "-V"), "host": host(),
                "plan": {"cases": names, "short_cases": short, "threads": args.threads, "processes": args.processes,
                         "pinned_threads": pinned_threads, "timeout_threads": timeout_threads,
                         "timeout_seconds": args.timeout_seconds, "gates": validate.GATE},
                "hashes": {"driver": sha(__file__), "catalog": sha(cat.CATALOG),
                           **{name: sha(path) for name, path in exe.items()},
                           "bundles": {f"t{n}": sha(path) for n, path in bundles.items()}}}
        print(f"host: {info['host']['platform']} {info['host']['machine']} cpus={info['host']['logical_cpus']}",
              flush=True)
        caches = probe_caches(exe["thread_probe"], output / "logs")
        info["cache_probe"] = caches
        for group in caches["groups"]:
            print(f"CACHE_INFO {group['gemm_cache_info']} pinned={group['pinned_cpus']} "
                  f"unpinned={group['unpinned_processes']}", flush=True)
        save(output / "host.json", info)
        results = execute(args, exe, bundles, by_id, names, short, caches, output, pinned_threads, timeout_threads)
    finally:
        for path in bundles.values():
            path.unlink(missing_ok=True)
    save(output / "results.json", results)
    (output / "summary.md").write_text(summary(info, results), encoding="utf-8")
    print("failures:", {k: v for k, v in results["failures"].items() if v} or "none", "passed:", results["passed"])
    raise SystemExit(0 if results["passed"] else 1)


def decide(exe, bundle, job_file, stem, by_id, cpus=None):
    result = run([str(exe), "--mode", "api", str(bundle), str(job_file)], stem, cpus=cpus)
    init = next((e for e in result["events"] if e.get("event") == "init"), None)
    decisions = [e for e in result["events"] if e.get("event") == "decision"]
    for d in decisions:
        d["gate"] = validate.check(by_id[d["name"]], "native", d["outcome"])
    result.pop("events")
    return {**result, "init": init, "decisions": decisions}


def execute(args, exe, bundles, by_id, names, short, caches, output, pinned_threads, timeout_threads):
    logs = output / "logs"
    processes = []

    def record(arm, n, index, run_result, expected):
        mismatches = [f"{d['phase']}/{d['name']}" for d in run_result["decisions"]
                      if expected is not None and bits(d["outcome"]) != expected.get(d["name"])]
        deltas = [validate.max_abs(d["outcome"]["probabilities"], reference[d["name"]]) for d in run_result["decisions"]
                  if reference and d["outcome"].get("status") == "completed" and d["name"] in reference]
        processes.append({"arm": arm, "threads": n, "process": index, **run_result, "mismatches": mismatches,
                          "max_abs_vs_reference": max(deltas, default=None)})
        gate = sum(bool(d["gate"]) for d in run_result["decisions"])
        print(f"{arm} t{n} p{index} cpus={run_result['cpus'] and len(run_result['cpus'])} "
              f"rc={run_result['returncode']} decisions={len(run_result['decisions'])} gate_failures={gate} "
              f"mismatches={len(mismatches)} wall={run_result['wall_s']:.1f}s", flush=True)

    expected, reference = None, {}
    for index in range(args.processes):
        for n in (args.threads if index % 2 == 0 else args.threads[::-1]):
            result = decide(exe["resident_bench"], bundles[n], output / "matrix-job.json",
                            logs / f"matrix-t{n}-p{index}", by_id)
            if expected is None:
                expected = {d["name"]: bits(d["outcome"]) for d in result["decisions"] if d["phase"] == "pass1"}
                reference.update({d["name"]: d["outcome"]["probabilities"] for d in result["decisions"]
                                  if d["phase"] == "pass1" and d["outcome"].get("status") == "completed"})
            record("matrix", n, index, result, expected)

    pin_sets = []
    if pinning_supported():
        for i, group in enumerate(caches["groups"]):
            if group["pinned_cpus"]:
                pin_sets.append((f"cache-group-{i}", sorted(group["pinned_cpus"])))
        if os.cpu_count() > 1:
            pin_sets.append(("without-cpu0", list(range(1, os.cpu_count()))))
    for label, cpus in pin_sets:
        for n in pinned_threads:
            result = decide(exe["resident_bench"], bundles[n], output / "pinned-job.json",
                            logs / f"pinned-{label}-t{n}", by_id, cpus=cpus)
            result["label"] = label
            record("pinned", n, 0, result, expected)

    golden = ROOT / "tests/fixtures/jeff-golden"
    timeouts = []
    for n in timeout_threads:
        result = run([str(exe["timeout_reuse"]), str(bundles[n]), str(golden / "token-limit-8192.json"),
                      str(golden / "candidate-request.json"), str(args.timeout_seconds)], logs / f"timeout-t{n}",
                     timeout=3600)
        line = result["events"][0] if result["events"] else None
        timeouts.append({"threads": n, "returncode": result["returncode"], "result": line, "stderr": result["stderr"]})
        print(f"timeout t{n} rc={result['returncode']} {line}", flush=True)

    expected_counts = {"matrix": 2 * len(names), "pinned": len(short)}
    failures = {
        "process_failures": [(p["arm"], p.get("label"), p["threads"], p["process"]) for p in processes
                             if p["returncode"] != 0],
        "missing_decisions": [(p["arm"], p.get("label"), p["threads"], p["process"]) for p in processes
                              if len(p["decisions"]) != expected_counts[p["arm"]]],
        "gate_failures": [(p["arm"], p.get("label"), p["threads"], d["name"], d["gate"]) for p in processes
                          for d in p["decisions"] if d["gate"]],
        "bit_mismatches": [(p["arm"], p.get("label"), p["threads"], p["process"], m) for p in processes
                           for m in p["mismatches"]],
        "timeout_reuse": [t["threads"] for t in timeouts if t["returncode"] != 0 or not t["result"]
                          or not (t["result"].get("timeout") and t["result"].get("reuse_bitwise_equal"))]}
    return {"processes": processes, "timeouts": timeouts, "failures": failures, "passed": not any(failures.values()),
            "observations": observations(processes, by_id)}


def observations(processes, by_id):
    """Descriptive only: differences from the official reference and the old 28-case gate, and
    load / startup / wall time / peak memory per thread count."""
    reference = next(p for p in processes if p["arm"] == "matrix")
    first = {d["name"]: d["outcome"] for d in reference["decisions"] if d["phase"] == "pass1"}
    official = {n: validate.max_abs(o["probabilities"], by_id[n]["reference"]["probabilities"])
                for n, o in first.items() if o.get("status") == "completed"}
    old = json.loads(OLD_GATE.read_text(encoding="utf-8")) if OLD_GATE.exists() else {}
    old_gate = {n: validate.max_abs(first[n]["probabilities"], p) for n, p in old.items()
                if n in first and first[n].get("status") == "completed"}
    per_threads = {}
    for p in processes:
        if p["arm"] != "matrix":
            continue
        entry = per_threads.setdefault(p["threads"], {"load_s": [], "startup_s": [], "memory": [], "wall_s": {}})
        if p["init"]:
            entry["load_s"].append(p["init"].get("load_s"))
            entry["startup_s"].append(p["init"].get("startup_s"))
            entry["compute_threads"] = p["init"].get("compute_threads")
            entry["kernel"] = p["init"].get("kernel")
        entry["memory"].append(p["memory"])
        for d in p["decisions"]:
            if d["outcome"].get("status") == "completed":
                entry["wall_s"].setdefault(d["name"], []).append(d["wall_s"])
    for entry in per_threads.values():
        entry["median_wall_s"] = {n: statistics.median(v) for n, v in entry.pop("wall_s").items()}
    return {"max_abs_vs_official": max(official.values(), default=None),
            "max_abs_vs_official_by_case": official,
            "old_28_case_gate": {"cases": len(old_gate), "max_abs": max(old_gate.values(), default=None),
                                 "by_case": old_gate},
            "per_threads": per_threads}


def fmt_bytes(value):
    return "–" if value is None else f"{value / 2**20:,.1f} MiB"


def summary(info, results):
    h = info["host"]
    cpuinfo = h.get("cpuinfo", {})
    cpu = h.get("processor") or ", ".join(cpuinfo.get("model name", [])) or \
        ", ".join(f"{k} {'/'.join(v)}" for k, v in cpuinfo.items() if k.startswith("CPU "))
    obs, failures = results["observations"], results["failures"]
    lines = [f"## Native host matrix: {h['system']} {h['machine']}", "",
             f"- commit `{info['source']['commit']}`{' (dirty)' if info['source']['dirty'] else ''}, {info['rustc']}",
             f"- CPU: {cpu or 'unknown'}; logical CPUs {h['logical_cpus']}",
             f"- **passed: {results['passed']}**"
             + ("" if results["passed"] else " — " + ", ".join(f"{k} {len(v)}" for k, v in failures.items() if v)
                + " (details in results.json)"),
             f"- max abs difference from the official reference: {obs['max_abs_vs_official']:.3g}",
             f"- old 28-case Native gate ({obs['old_28_case_gate']['cases']} cases): max abs difference "
             f"{obs['old_28_case_gate']['max_abs'] if obs['old_28_case_gate']['max_abs'] is not None else '–'}"
             " (a different build and dependencies; descriptive)", "",
             "### gemm CACHE_INFO", "", "| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |",
             "| --- | --- | ---: |"]
    for group in info["cache_probe"]["groups"]:
        value = " / ".join(f"{c['bytes']}/{c['associativity']}" for c in group["gemm_cache_info"] or [])
        cpus = group["pinned_cpus"]
        lines.append(f"| {value or '–'} | {compress(cpus) if cpus else '–'} | {group['unpinned_processes']} |")
    lines += ["", "### Processes", "", "| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches |"
              " max abs vs reference | load s | wall s | peak |",
              "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for p in results["processes"]:
        where = (f"{p['label']} ({compress(p['cpus'])})" if p.get("label") else f"p{p['process']}")
        mem = p["memory"] or {}
        peak = " / ".join(f"{k.replace('_bytes', '').replace('peak_', '')} {fmt_bytes(v)}" for k, v in mem.items())
        load = p["init"].get("load_s") if p["init"] else None
        lines.append(f"| {p['arm']} | {p['threads']} | {where} | {p['returncode']} | {len(p['decisions'])} | "
                     f"{sum(bool(d['gate']) for d in p['decisions'])} | {len(p['mismatches'])} | "
                     f"{'–' if p['max_abs_vs_reference'] is None else format(p['max_abs_vs_reference'], '.3g')} | "
                     f"{'–' if load is None else f'{load:.2f}'} | {p['wall_s']:.1f} | {peak} |")
    lines += ["", "### timeout_reuse", ""]
    for t in results["timeouts"]:
        lines.append(f"- t{t['threads']}: rc={t['returncode']} {json.dumps(t['result'])}")
    probe = {"128": "candidate-request", "874": "long-text", "3206": "maximum-candidates", "8192": "token-limit-8192"}
    lines += ["", "### Median decision wall time (s, descriptive)", "",
              "| threads | " + " | ".join(f"{k} tokens" for k in probe) + " |",
              "| ---: | " + " | ".join("---:" for _ in probe) + " |"]
    for n, entry in sorted(obs["per_threads"].items()):
        cells = [entry["median_wall_s"].get(name) for name in probe.values()]
        lines.append(f"| {n} | " + " | ".join("–" if v is None else f"{v:.2f}" for v in cells) + " |")
    return "\n".join(lines) + "\n"


def compress(cpus):
    cpus, out, start = sorted(cpus), [], None
    for i, cpu in enumerate(cpus):
        start = cpu if start is None else start
        if i + 1 == len(cpus) or cpus[i + 1] != cpu + 1:
            out.append(f"{start}" if start == cpu else f"{start}-{cpu}")
            start = None
    return ",".join(out)


if __name__ == "__main__":
    main()
