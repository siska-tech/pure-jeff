"""Main vs branch on every catalog case, each process pinned from its start to P-cores or E-cores.
usage: compare_partition.py <repo> <base resident_bench> <base jeff> <new resident_bench> <new jeff> <out dir>"""
import json
from pathlib import Path
import subprocess
import sys

repo, base_rb, base_jeff, new_rb, new_jeff, out = sys.argv[1:7]
sys.path.insert(0, str(Path(repo) / "bench"))
import catalog as cat  # noqa: E402
import host_matrix as hm  # noqa: E402
import validate  # noqa: E402

out = Path(out)
out.mkdir(parents=True)
by_id = cat.by_id(cat.load())
names = list(by_id)
job = out / "job.json"
job.write_text(json.dumps([{"name": n, "phase": "measure", "max_input_tokens": cat.MAX_TOKENS,
                            "request": by_id[n]["request"]} for n in names], ensure_ascii=False), encoding="utf-8")
models = Path(repo) / "models"
bundles = {}
for arm, jeff in (("base", base_jeff), ("new", new_jeff)):
    path = models / f"partition-{arm}-t4.json"
    path.unlink(missing_ok=True)
    subprocess.run([jeff, "lock", str(models / "jeff-checkpoint"), str(path), hm.REVISION, "0.7", "0.1", "4"],
                   check=True, capture_output=True)
    bundles[arm] = path
runs = {}
for cores, cpus in (("P", list(range(8))), ("E", list(range(8, 16)))):
    for arm, rb in (("base", base_rb), ("new", new_rb)):
        r = hm.run([rb, "--mode", "api", str(bundles[arm]), str(job)], out / f"{arm}-{cores}", cpus=cpus)
        decisions = {e["name"]: e["outcome"] for e in r["events"] if e.get("event") == "decision"}
        gate = {n: validate.check(by_id[n], "native", o) for n, o in decisions.items()}
        runs[(arm, cores)] = decisions
        print(arm, cores, "rc", r["returncode"], "decisions", len(decisions),
              "gate_failures", sum(bool(v) for v in gate.values()), flush=True)
bits = hm.bits
summary = {}
for a, b in ((("base", "P"), ("new", "P")), (("base", "E"), ("new", "E")), (("new", "P"), ("new", "E")),
             (("base", "P"), ("base", "E"))):
    differ = [n for n in names if bits(runs[a][n]) != bits(runs[b][n])]
    key = f"{a[0]}-{a[1]} vs {b[0]}-{b[1]}"
    summary[key] = {n: {"tokens": by_id[n]["tokens"],
                        "max_abs": validate.max_abs(runs[a][n]["probabilities"], runs[b][n]["probabilities"])
                        if runs[a][n].get("status") == "completed" else None,
                        "judgment_equal": runs[a][n].get("judgment") == runs[b][n].get("judgment")} for n in differ}
    print(key, "differing:", summary[key])
(out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
for path in bundles.values():
    path.unlink()
