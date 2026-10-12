"""Search fixed requests near the selection policy's boundaries and write them to
bench/cases/requests/policy-*.json (existing files are never overwritten).

Variants (generated deterministically below: noisy OCR/ASR texts with two or three candidates
that differ in one character) are decided once by the Native resident wrapper (API path). The
chosen requests are the closest to each boundary whose distance is at least twice the parity
tolerance (2e-4), so a Native/official difference within the gate cannot flip the judgment:
  policy-top1-above  top1 >= 0.7 (selected), smallest top1 - 0.7
  policy-top1-below  top1 <  0.7 (abstained, margin >= 0.1), smallest 0.7 - top1
  policy-near-tie    smallest top1 - top2 (abstained)
  policy-margin-near three candidates, margin closest to 0.1. With min_probability 0.7 the
                     margin threshold cannot decide (top1 >= 0.7 implies margin >= 0.4); the
                     equality cases stay in the policy unit tests (tests/fixtures/jeff-golden/
                     boundaries.json), and this input only checks the abstention near it.
The official reference is taken later by build_catalog.py, which must agree on every judgment.

    python -B bench/search_policy_boundary.py --manifest models/pure-jeff-bundle-t1.json"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import catalog as cat

SENTENCES = [
    ("ocr", "請求金額は12,800円です"), ("ocr", "The meeting starts at 10:30"), ("ocr", "東京都千代田区丸の内1-1"),
    ("ocr", "Total: 4,560 JPY"), ("ocr", "受付番号 A-1029"), ("ocr", "Lot 7B shipped on 2026-03-14"),
    ("asr", "明日の天気は晴れのち曇り"), ("asr", "Call 03-5555-0123 for support"),
    ("asr", "会議は午後三時に始まります"), ("ocr", "Invoice No. 88-417"),
]
SWAPS = {"0": "8", "1": "7", "2": "Z", "3": "8", "4": "A", "5": "S", "6": "b", "7": "1", "8": "B", "9": "g",
         "a": "o", "e": "c", "o": "0", "i": "l", "t": "f", "s": "5", "n": "m", "r": "n",
         "円": "门", "日": "曰", "晴": "睛", "曇": "雲", "午": "牛", "三": "二", "千": "干", "内": "肉",
         "金": "全", "額": "頻", "番": "審", "会": "合", "始": "治", "天": "夫"}
NOISE = ["?", "■", ""]
DISTANCE = 2e-4


def variants():
    out = []
    for s_index, (source, text) in enumerate(SENTENCES):
        positions = [i for i, ch in enumerate(text) if ch in SWAPS]
        for position in positions:
            wrong = text[:position] + SWAPS[text[position]] + text[position + 1:]
            for n_index, noise in enumerate(NOISE):
                observed = text[:position] + noise + text[position + 1:]
                for order in (0, 1):
                    candidates = [{"id": "original", "text": text}, {"id": "alternative", "text": wrong}]
                    if order:
                        candidates.reverse()
                    name = f"v{s_index}-{position}-{n_index}-{order}"
                    out.append((name, source, observed, candidates))
            third = wrong[:max(0, position - 1)] + "?" + wrong[max(0, position - 1) + 1:] if position else wrong + "?"
            out.append((f"v{s_index}-{position}-3c", source, text[:position] + "?" + text[position + 1:],
                        [{"id": "original", "text": text}, {"id": "alternative", "text": wrong},
                         {"id": "third", "text": third}]))
    return [(name, {"request_id": f"policy-search-{name}", "document_id": "policy-boundary",
                    "segment_id": name, "original_text": observed, "source": source,
                    "profile_id": "synthetic.policy-boundary", "domain": None,
                    "question_id": "transcription-candidate.v1", "candidates": candidates,
                    "reason": "candidate_competition"}) for name, source, observed, candidates in out]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True, help="Native bundle")
    parser.add_argument("--resident-exe", type=Path,
                        default=cat.ROOT / "runtime/rust/target/release/examples/resident_bench.exe")
    parser.add_argument("--log", type=Path, required=True, help="new JSON file for every searched variant")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    policy = manifest["policy"]
    pool = variants()
    with tempfile.TemporaryDirectory(prefix="pj-policy-") as folder:
        job = Path(folder) / "job.json"
        job.write_text(json.dumps([{"name": n, "phase": "search", "max_input_tokens": 8192, "request": r}
                                   for n, r in pool], ensure_ascii=False), encoding="utf-8")
        run = subprocess.run([str(args.resident_exe), "--mode", "api", str(args.manifest), str(job)],
                             capture_output=True, text=True, encoding="utf-8", check=True)
    events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    requests = dict(pool)
    rows = []
    for e in events:
        if e["event"] != "decision" or e["outcome"]["status"] != "completed":
            continue
        p = sorted(e["outcome"]["probabilities"], reverse=True)
        rows.append({"name": e["name"], "top1": p[0], "margin": p[0] - p[1], "candidates": len(p),
                     "judgment": e["outcome"]["judgment"], "probabilities": e["outcome"]["probabilities"],
                     "input_tokens": e["outcome"]["input_tokens"]})
    with args.log.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump({"policy": policy, "variants": len(pool), "decided": rows}, stream, ensure_ascii=False, indent=1)
    threshold, margin = policy["min_probability"], policy["min_margin"]
    picks = {
        "policy-top1-above": min((r for r in rows if r["top1"] - threshold >= DISTANCE and r["candidates"] == 2),
                                 key=lambda r: r["top1"] - threshold, default=None),
        "policy-top1-below": min((r for r in rows if threshold - r["top1"] >= DISTANCE and r["margin"] >= margin
                                  and r["candidates"] == 2), key=lambda r: threshold - r["top1"], default=None),
        "policy-near-tie": min(rows, key=lambda r: r["margin"], default=None),
        "policy-margin-near": min((r for r in rows if r["candidates"] == 3 and abs(r["margin"] - margin) >= DISTANCE),
                                  key=lambda r: abs(r["margin"] - margin), default=None),
    }
    cat.REQUESTS.mkdir(parents=True, exist_ok=True)
    for name, row in picks.items():
        if row is None:
            print(f"{name}: none found")
            continue
        request = {**requests[row["name"]], "request_id": name}
        value = {"provenance": f"bench/search_policy_boundary.py variant {row['name']} of {len(pool)}; Native API "
                               f"search result below (the reference is the official one in the catalog)",
                 "search": {k: row[k] for k in ("top1", "margin", "probabilities", "judgment", "input_tokens")},
                 "policy": policy, "request": request}
        with (cat.REQUESTS / f"{name}.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1)
            stream.write("\n")
        print(f"{name}: {row['name']} top1={row['top1']:.6f} margin={row['margin']:.6f} {row['judgment']}")


if __name__ == "__main__":
    main()
