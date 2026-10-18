"""Issue #18: are the candidate's decisions (DeltaNet heads on the compute threads) bitwise the
same when the process may run only on some CPUs? Each resident process (`--mode api`) has its
process affinity set right after it starts (before the bundle is loaded and the thread pool
exists) and decides a short, a long and a policy-boundary input; every probability is compared
with main at one thread without affinity. Descriptive; a substitute for, not a test on, hybrid
(P/E-core) CPUs.

    python -B bench/delta_heads_affinity.py --output <new dir> --baseline <dir> --candidate <dir>"""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import catalog as cat
import run_benchmark as rb
import validate

ROOT = cat.ROOT
CASES = ["candidate-request", "long-text", "policy-near-tie"]
# Logical CPU masks of the measuring machine (16 cores, SMT siblings 2c and 2c + 1).
MASKS = {"all": None, "cpus 0-15": 0x0000FFFF, "cpus 16-31": 0xFFFF0000,
         "one per core (even cpus)": 0x55555555, "cpus 8-11": 0x00000F00}
PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def set_affinity(pid, mask):
    kernel = c.windll.kernel32
    handle = kernel.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    try:
        if not handle or not kernel.SetProcessAffinityMask(c.c_void_p(handle), c.c_size_t(mask)):
            raise OSError(f"SetProcessAffinityMask failed for {pid}")
    finally:
        if handle:
            kernel.CloseHandle(c.c_void_p(handle))


def run(exe, bundle, job, mask):
    process = subprocess.Popen([str(exe), "--mode", "api", str(bundle), str(job)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    if mask is not None:
        set_affinity(process.pid, mask)
    placement = rb.affinity(process.pid)
    out, err = process.communicate(timeout=3600)
    decisions = [json.loads(line) for line in out.decode("utf-8").splitlines() if line.startswith("{")]
    decisions = [d for d in decisions if d.get("event") == "decision"]
    return {"returncode": process.returncode, "affinity": placement, "stderr": err.decode(errors="replace")[-1000:],
            "decisions": decisions}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--threads", type=int, nargs="+", default=[4, 16])
    args = parser.parse_args()
    if rb.busy_processes():
        raise SystemExit("build/install/benchmark processes are running")
    by_id = cat.by_id(cat.load())
    args.output.mkdir(parents=True)
    job = args.output / "job.json"
    job.write_text(json.dumps([{"name": n, "phase": "measure", "max_input_tokens": cat.MAX_TOKENS,
                                "request": by_id[n]["request"]} for n in CASES], ensure_ascii=False), encoding="utf-8")
    bits = lambda d: [float(p).hex() for p in d["outcome"]["probabilities"]]
    reference = run(args.baseline / "examples/resident_bench.exe", ROOT / "models/pure-jeff-bundle-t1-diag.json",
                    job, None)
    expected = {d["name"]: bits(d) for d in reference["decisions"]}
    if reference["returncode"] or len(expected) != len(CASES):
        raise SystemExit("the baseline reference run failed")
    rows = []
    for n in args.threads:
        for name, mask in MASKS.items():
            result = run(args.candidate / "examples/resident_bench.exe",
                         ROOT / f"models/pure-jeff-bundle-t{n}-delta-heads.json", job, mask)
            got = {d["name"]: d for d in result["decisions"]}
            row = {"threads": n, "mask": name, "mask_hex": None if mask is None else hex(mask),
                   "returncode": result["returncode"], "affinity": result["affinity"],
                   "bit_equal_to_main_1_thread": set(got) == set(CASES) and all(bits(got[c]) == expected[c] for c in CASES),
                   "gate_failures": sum(bool(validate.check(by_id[c], "native", got[c]["outcome"])) for c in got),
                   "wall_s": {c: got[c]["wall_s"] for c in got}, "stderr": result["stderr"]}
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("threads", "mask", "returncode", "bit_equal_to_main_1_thread",
                                                  "gate_failures", "wall_s")}), flush=True)
    rb.save(args.output / "results.json", {
        "created_utc": datetime.now(timezone.utc).isoformat(), "cases": CASES,
        "reference": "main (baseline) at 1 thread without affinity",
        "source": {"commit": rb.git("rev-parse", "HEAD"), "dirty": rb.git("status", "--porcelain")},
        "environment": rb.sample_environment(full=True), "rows": rows})
    raise SystemExit(0 if all(r["returncode"] == 0 and r["bit_equal_to_main_1_thread"] and not r["gate_failures"]
                              for r in rows) else 1)


if __name__ == "__main__":
    main()
