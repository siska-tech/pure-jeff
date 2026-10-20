"""gemm_probe pinned to P-cores and E-cores at 1 and 4 threads; digests compared per product, with
the blocking predicted from each process's CACHE_INFO.
usage: probe_pe.py <repo> <gemm_probe exe> <out dir>"""
import json
from pathlib import Path
import sys

repo, exe, out = sys.argv[1:4]
sys.path.insert(0, str(Path(repo) / "bench"))
sys.path.insert(0, str(Path(__file__).parent))
import host_matrix as hm  # noqa: E402
import kernel_params as kp  # noqa: E402

out = Path(out)
out.mkdir(parents=True)
runs = {}
for cores, cpus in (("P", list(range(8))), ("E", list(range(8, 16)))):
    for threads in (1, 4):
        r = hm.run([exe, str(threads)], out / f"probe-{cores}-t{threads}", cpus=cpus, timeout=3600)
        assert r["returncode"] == 0, r["stderr"]
        init = next(e for e in r["events"] if e["event"] == "init")
        runs[(cores, threads)] = (init, [e for e in r["events"] if e["event"] == "product"])
rows = []
for i, p in enumerate(runs[("P", 1)][1]):
    row = {"name": p["name"], "m": p["m"], "n": p["n"], "k": p["k"]}
    for cores in ("P", "E"):
        info = runs[(cores, 1)][0]["gemm_cache_info"]
        row[f"params_{cores}"] = kp.params(p["m"], p["n"], p["k"], "fma", info) if p["m"] > 1 else {"path": "gemv"}
    digests = {f"{c}-t{t}": runs[(c, t)][1][i]["sha256"] for (c, t) in runs}
    row["threads_equal"] = {c: digests[f"{c}-t1"] == digests[f"{c}-t4"] for c in ("P", "E")}
    row["p_equals_e"] = digests["P-t1"] == digests["E-t1"]
    ch = {f"{c}-t{t}": runs[(c, t)][1][i]["sha256_chunked"] for (c, t) in runs}
    row["chunk"] = p["chunk"]
    row["chunked_p_equals_e"] = len(set(ch.values())) == 1
    row["chunked_equals_plain"] = {c: ch[f"{c}-t1"] == digests[f"{c}-t1"] for c in ("P", "E")}
    row["time_ratio_t4"] = {c: runs[(c, 4)][1][i]["chunked_s"] / max(runs[(c, 4)][1][i]["plain_s"], 1e-9)
                            for c in ("P", "E")}
    pk, ek = row["params_P"].get("kc"), row["params_E"].get("kc")
    row["kc_differs"] = pk != ek
    row["mc_or_nc_differs"] = (row["params_P"].get("mc"), row["params_P"].get("nc")) != \
        (row["params_E"].get("mc"), row["params_E"].get("nc"))
    rows.append(row)
    print(f"{p['name']:<18} m={p['m']:<4} n={p['n']:<5} k={p['k']:<5} "
          f"kc P/E {row['params_P'].get('kc')}/{row['params_E'].get('kc')} | P==E {row['p_equals_e']} "
          f"| chunk {row['chunk']}: P==E {row['chunked_p_equals_e']} =plain {row['chunked_equals_plain']} "
          f"time x{row['time_ratio_t4']['P']:.2f}/{row['time_ratio_t4']['E']:.2f} | threads {row['threads_equal']}")
summary = {
    "cache_info": {c: runs[(c, 1)][0]["gemm_cache_info"] for c in ("P", "E")},
    "products": rows,
    "kc_differs_and_bits_differ": sum(r["kc_differs"] and not r["p_equals_e"] for r in rows),
    "kc_differs_but_bits_equal": sum(r["kc_differs"] and r["p_equals_e"] for r in rows),
    "kc_same_but_bits_differ": sum(not r["kc_differs"] and not r["p_equals_e"] for r in rows),
    "kc_same_and_bits_equal": sum(not r["kc_differs"] and r["p_equals_e"] for r in rows),
    "chunked_p_equals_e": sum(r["chunked_p_equals_e"] for r in rows),
    "chunked_equals_plain_on_E": sum(r["chunked_equals_plain"]["E"] for r in rows),
    "chunked_equals_plain_on_P": sum(r["chunked_equals_plain"]["P"] for r in rows),
    "product_count": len(rows),
}
(out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
print({k: v for k, v in summary.items() if k not in ("products", "cache_info")})
