"""Speed and peak memory, main vs branch, processes pinned from their start to the P-cores (where
the branch changes kc from 1024 to 512). Per repetition and thread count, one process per arm
(order alternates), each deciding a warm-up and then 128, 874, 3206 and 8192 tokens once.
usage: speed_compare.py <repo> <base resident_bench> <base jeff> <new resident_bench> <new jeff> <out> [reps]"""
import json
from pathlib import Path
import statistics
import subprocess
import sys

repo, base_rb, base_jeff, new_rb, new_jeff, out = sys.argv[1:7]
reps = int(sys.argv[7]) if len(sys.argv) > 7 else 3
sys.path.insert(0, str(Path(repo) / "bench"))
import catalog as cat  # noqa: E402
import host_matrix as hm  # noqa: E402

out = Path(out)
out.mkdir(parents=True)
by_id = cat.by_id(cat.load())
cases = ["candidate-request", "long-text", "maximum-candidates", "token-limit-8192"]
job = [{"name": "candidate-request", "phase": "warmup", "max_input_tokens": cat.MAX_TOKENS,
        "request": by_id["candidate-request"]["request"]}]
job += [{"name": n, "phase": "measure", "max_input_tokens": cat.MAX_TOKENS, "request": by_id[n]["request"]}
        for n in cases]
(out / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
models = Path(repo) / "models"
arms = {"base": (base_rb, base_jeff), "new": (new_rb, new_jeff)}
bundles = {}
for arm, (_, jeff) in arms.items():
    for t in (1, 4):
        path = models / f"speed-{arm}-t{t}.json"
        path.unlink(missing_ok=True)
        subprocess.run([jeff, "lock", str(models / "jeff-checkpoint"), str(path), hm.REVISION, "0.7", "0.1", str(t)],
                       check=True, capture_output=True)
        bundles[(arm, t)] = path
records = []
for rep in range(reps):
    for t in (1, 4):
        order = ["base", "new"] if (rep + t) % 2 == 0 else ["new", "base"]
        for arm in order:
            r = hm.run([arms[arm][0], "--mode", "api", str(bundles[(arm, t)]), str(out / "job.json")],
                       out / f"{arm}-t{t}-r{rep}", cpus=list(range(8)))
            init = next(e for e in r["events"] if e.get("event") == "init")
            walls = {e["name"]: e["wall_s"] for e in r["events"]
                     if e.get("event") == "decision" and e["phase"] == "measure"}
            records.append({"arm": arm, "threads": t, "rep": rep, "rc": r["returncode"], "load_s": init.get("load_s"),
                            "walls": walls, "memory": r["memory"]})
            print(arm, t, rep, r["returncode"], {k: round(v, 2) for k, v in walls.items()}, r["memory"], flush=True)
summary = {}
for t in (1, 4):
    for n in cases:
        med = {arm: statistics.median(x["walls"][n] for x in records if x["arm"] == arm and x["threads"] == t)
               for arm in arms}
        summary[f"t{t} {n}"] = {**{f"{a}_median_s": v for a, v in med.items()}, "ratio_new_over_base": med["new"] / med["base"]}
    for key in ("peak_private_bytes", "peak_working_set_bytes"):
        mx = {arm: max(x["memory"][key] for x in records if x["arm"] == arm and x["threads"] == t) for arm in arms}
        summary[f"t{t} {key}"] = {**mx, "ratio_new_over_base": mx["new"] / mx["base"]}
(out / "records.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
(out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
for k, v in summary.items():
    print(k, {a: (round(b, 3) if isinstance(b, float) else b) for a, b in v.items()})
for path in bundles.values():
    path.unlink()
