"""Recompute pilot statistics from validated raw records, without running inference."""
import argparse
import json
import math
from pathlib import Path
from benchmark_pilot import save, sha, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--native-api", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.directory.glob("*.validated.json"))]
    registration = json.loads((args.directory/"preregistration.json").read_text(encoding="utf-8"))
    if len(records) != 2*registration["repeats"]+2 or any(r["status"] != "completed" for r in records):
        raise ValueError("complete validated pilot required")
    result = {"pilot": True, "formal_slo_acceptance": False,
              "quantile": "nearest-rank", "process_attempts": len(records),
              "process_failures": 0, "numerically_valid_requests": 0, "warmups_excluded": 0,
              "registration_sha256": sha(args.directory/"preregistration.json"),
              "analysis_source_sha256": sha(Path(__file__)), "backends": {}}
    for backend in ["native", "tract"]:
        cold = [r for r in records if r["backend"] == backend and r["phase"] == "cold"]
        resident = [r for r in records if r["backend"] == backend and r["phase"] == "resident"]
        if len(cold) != registration["repeats"] or len(resident) != 1:
            raise ValueError("unexpected cell count")
        events = resident[0]["events"][1:-1]
        by_case = {}
        for case in registration["warm_inputs"]:
            selected = [e for e in events if e["case"] == case and not e["warmup"]]
            if len(selected) != registration["repeats"]:
                raise ValueError("missing resident samples")
            keys = [k for k in selected[0] if k.endswith("_ns")]
            timings = {key.removesuffix("_ns")+"_ms": stats([e[key]/1e6 for e in selected]) for key in keys}
            timings["compute_and_softmax_ms"] = stats([
                (e["backbone_ns"]+e["head_softmax_ns"] if backend == "native" else e["forward_ns"]+e["score_ns"])/1e6
                for e in selected])
            by_case[case] = {"n": len(selected), "effective_tokens": selected[0]["effective_tokens"],
                             "physical_tokens": selected[0]["physical_tokens"], "timings": timings,
                             "max_probability_error": max(e["probability_max_abs_error"] for e in selected)}
        init = cold[0]["events"][0]
        initialization = {key.removesuffix("_ns")+"_ms": stats([r["events"][0][key]/1e6 for r in cold])
                          for key in init if key.endswith("_ns")}
        result["backends"][backend] = {"cold_parent_process_ms": stats([r["parent_process_ns"]/1e6 for r in cold]),
             "cold_startup_stages": initialization,
             "cold_peak_working_set_bytes": stats([r["peak_working_set_bytes"] for r in cold]),
             "resident_session_peak_working_set_bytes": resident[0]["peak_working_set_bytes"],
             "resident_session_startup_ms": resident[0]["events"][0]["startup_ns"]/1e6,
             "resident": by_case}
    for record in records:
        for event in record["events"][1:-1]:
            if not event["judgment_match"] or event["probability_max_abs_error"] > 1e-4:
                raise ValueError("numerical acceptance missing")
            result["numerically_valid_requests"] += 1
            result["warmups_excluded"] += int(event["warmup"])
    # These are next-experiment budget hypotheses, not validated service SLOs.
    budgets = {}
    for backend, data in result["backends"].items():
        worst_compute = max(c["timings"]["compute_and_softmax_ms"]["p95"] for c in data["resident"].values())
        peak = max(data["cold_peak_working_set_bytes"]["max"], data["resident_session_peak_working_set_bytes"])
        budgets[backend] = {"compute_and_softmax_seconds": math.ceil(worst_compute*1.2/1000),
                            "engine_process_cold_seconds": math.ceil(data["cold_parent_process_ms"]["p95"]*1.2/1000),
                            "process_memory_gib": math.ceil(peak*1.25/1024**3*2)/2,
                            "scope": "observed short-input diagnostic engine only; not a service SLO"}
    result["next_experiment_budget_hypotheses"] = budgets
    if args.native_api:
        api = json.loads((args.native_api/"summary.json").read_text(encoding="utf-8"))
        result["native_api"] = api
        result["native_cli_slo_candidate_seconds"] = math.ceil(api["cli_e2e_ms"]["p95"]*1.2/1000)
        result["native_cli_slo_candidate_scope"] = "candidate-request, one thread, cache uncontrolled; must validate on independent runs"
    save(args.output, result)
    for backend, data in result["backends"].items():
        print(backend, "cold ms", data["cold_parent_process_ms"])
        for case, cell in data["resident"].items():
            print(case, cell["effective_tokens"], cell["timings"]["compute_and_softmax_ms"])


if __name__ == "__main__":
    main()
