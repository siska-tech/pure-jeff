"""Pilot (not a decision): bits of the candidate against PR #41's bit reference, and a short
three-way speed comparison (main, PR head, candidate) at 4 and 16 threads."""
import json
import os
import random
import statistics as st
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "bench"))
import catalog as cat  # noqa: E402
import validate  # noqa: E402
from ab_acceptance_summary import outcome_key, digest  # noqa: E402

CAND = sys.argv[1]  # short commit of the candidate bundles
by_id = cat.by_id(cat.load())
ref = json.loads((ROOT / "docs/research/native-fixed-k-chunks-2026-10-20/amd-acceptance-2026-10-21/bit-reference-candidate.json").read_text(encoding="utf-8"))["outcomes"]
arms = {
    "main": (ROOT / ".venv/wt-main/runtime/rust/target/release/examples/resident_bench.exe", "models/pure-jeff-bundle-t{n}-main-4d7ec22.json"),
    "prhead": (ROOT / ".venv/pr41-1f4c62c-bin/examples/resident_bench.exe", "models/pure-jeff-bundle-t{n}-pr41-1f4c62c.json"),
    "cand": (ROOT / "runtime/rust/target/release/examples/resident_bench.exe", f"models/pure-jeff-bundle-t{{n}}-pr41split-{CAND}.json"),
}
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)


def run(arm, n, job):
    exe, bundle = arms[arm]
    path = out / "job.json"
    path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([str(exe), "--mode", "api", bundle.format(n=n), str(path)], capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr[-500:]
    return [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{") and '"decision"' in l]


job = lambda names, phase: [{"name": c, "phase": phase, "max_input_tokens": 8192, "request": by_id[c]["request"]} for c in names]

# 1. Bits: every catalog input, candidate at 4 and 16 threads, against the PR head's reference.
for n in (4, 16):
    ds = run("cand", n, job(sorted(by_id), "gate"))
    bad = [d["name"] for d in ds if digest(outcome_key(d["outcome"])) != ref[d["name"]]["sha256"]]
    gate = [d["name"] for d in ds if validate.check(by_id[d["name"]], "native", d["outcome"])]
    print(f"bits t{n}: {len(ds)} decisions, differ from PR head reference: {bad or 'none'}, gate failures: {gate or 'none'}", flush=True)

# 2. Speed: 128 / 512 / 874 tokens x 5, shuffled, arms rotated over 2 rounds.
timed = ["candidate-request", "synthetic-ocr-ascii-8-512", "long-text"] * 5
random.Random(7).shuffle(timed)
records = {}
for rnd in range(2):
    for n in (4, 16):
        order = ["main", "prhead", "cand"]
        order = order[rnd % 3:] + order[:rnd % 3]
        for arm in order:
            for d in run(arm, n, job(["synthetic-ocr-ja-2-256"], "warmup") + job(timed, "measure")):
                if d["phase"] == "measure":
                    records.setdefault((n, d["name"], arm), []).append(d["wall_s"])
for n in (4, 16):
    for c in ["candidate-request", "synthetic-ocr-ascii-8-512", "long-text"]:
        m = {a: st.median(records[(n, c, a)]) for a in arms}
        print(f"t{n} {by_id[c]['tokens']}: main {m['main']:.3f} prhead {m['prhead']:.3f} ({m['prhead']/m['main']:.3f}) cand {m['cand']:.3f} ({m['cand']/m['main']:.3f})", flush=True)
(out / "records.json").write_text(json.dumps({f"{k[0]}|{k[1]}|{k[2]}": v for k, v in records.items()}), encoding="utf-8")
