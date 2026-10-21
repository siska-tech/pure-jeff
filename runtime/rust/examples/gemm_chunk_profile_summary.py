"""Summary of gemm_chunk_profile output: per thread count and sequence length, the time of each
variant summed over the forward's split products (each product's median times its count per
forward), the share of each shape, and whether every variant kept the bits of `chunks`.

    python -B runtime/rust/examples/gemm_chunk_profile_summary.py <t*.jsonl>..."""
import json
import sys
from collections import defaultdict


def main():
    rows = [json.loads(line) for path in sys.argv[1:] for line in open(path, encoding="utf-8") if line.startswith("{")]
    groups = defaultdict(list)
    for r in rows:
        groups[(r["threads"], r["seq"])].append(r)
    for (threads, seq), rs in sorted(groups.items()):
        variants = sorted({v for r in rs for v in r["variants"]})
        totals = {v: sum(r["count"] * r["variants"][v]["median_s"] for r in rs if v in r["variants"]) for v in variants}
        # The best bit-equal variant per shape (excluding plain and write_only).
        best = sum(r["count"] * min(r["variants"][v]["median_s"] for v in r["variants"]
                                     if v not in ("plain", "write_only")) for r in rs)
        broken = [(r["name"], v) for r in rs for v, x in r["variants"].items() if x["bitwise_equal_to_chunks"] is False]
        print(f"t{threads} seq {seq}: per forward (s): " + ", ".join(f"{v} {t:.3f}" for v, t in totals.items())
              + f", best per shape {best:.3f}; chunks - plain {totals['chunks'] - totals['plain']:+.3f}; bits broken: {broken or 'none'}")
        for r in rs:
            p = r["variants"]["plain"]["median_s"]
            cells = ", ".join(f"{v} {r['variants'][v]['median_s'] / p:.3f}" for v in r["variants"] if v != "plain")
            print(f"    {r['name']:12s} x{r['count']:<3d} m{r['m']} n{r['n']} k{r['k']} chunks {r['chunks']}: "
                  f"plain {p * 1e3:.2f} ms; {cells}; first call {r['first_call_s'] * 1e3:.2f} ms, "
                  f"later calls {r['later_calls_s'] * 1e3:.2f} ms")


if __name__ == "__main__":
    main()
