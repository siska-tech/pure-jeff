"""W3 end-to-end check of the built web demo in a fresh headless browser profile.
Feasibility only: single observations are not performance results."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

from build_demo import ROOT, SAMPLES
from serve_demo import make_server

HERE = Path(__file__).resolve().parent
# Registered before the run; never relaxed after seeing results.
GATES = {
    "probability_max_abs_vs_official": 1e-4,
    "max_main_thread_gap_ms": 250,
    "consent": "no model/ request before the download button is pressed",
    "single_download": "each model file is fetched from the server exactly once in the whole session "
                       "(cancel recovery and page reload read Cache Storage)",
    "private_inference": "no network request from the page or its Workers while any evaluation runs, "
                         "and every request goes to the demo origin",
    "results": "sample 0/2/5 completed Attempts match the official prompt hash, candidate order, judgment and "
               "probabilities; sample 6 (874 tokens) fails budget_exceeded after one provider call; "
               "reason none is not_selected with no provider call; duplicate IDs are rejected in the UI",
    "attempt": "schema kaze_judge.attempt.v1; artifacts include the manifest files, bundle_manifest, "
               "wasm_engine (= deployed engine hash), prompt, rendered_prompt and policy",
    "save": "the downloaded JSON equals the displayed Attempt, with top-level fields in kaze_judge::Attempt order",
    "repeat": "results after cancel recovery and after page reload are bitwise equal to the first",
    "delete": "after delete no kazejudge cache remains and a reload shows the model as not downloaded",
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def window(marks, start, end):
    times = {m["name"]: m["time"] for m in marks}
    return times[start], times[end]


def check_completed(step, reference, gate):
    attempt = step["attempt"]
    outcome = attempt["outcome"]
    if outcome.get("status") != "completed":
        return {"passed": False, "reason": f"outcome {outcome}"}
    obs = outcome["value"]
    official = reference["official"]
    ids = [s["candidate_id"] for s in obs["scores"]]
    error = max(abs(s["option_probability"] - p) for s, p in zip(obs["scores"], official["probabilities"], strict=True))
    artifacts = {a["component"]: a["sha256"] for a in obs["artifacts"]}
    checks = {
        "candidate_order": ids == [c["id"] for c in reference["request"]["candidates"]],
        "judgment": obs["judgment"] == official["judgment"],
        "rendered_prompt": artifacts.get("rendered_prompt") == reference["prompt_utf8_sha256"],
        "input_tokens": obs["input_tokens"] == official["input_tokens"],
        "probabilities": error <= gate,
        "provider_calls": attempt["provider_calls_started"] == 1,
    }
    return {"passed": all(checks.values()), "checks": checks, "probability_max_abs_vs_official": error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle-p3.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=5400)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    config = json.loads((args.dist / "demo-config.json").read_text(encoding="utf-8"))
    refs = [json.loads((ROOT / path).read_text(encoding="utf-8")) for _, path in SAMPLES]
    save(args.output / "preregistration.json", {
        "schema_version": "kaze_judge.web_demo_w3_preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "gates": GATES,
        "browser": {"path": str(args.browser), "sha256": sha(args.browser)},
        "dist": {"build_info_sha256": sha(args.dist / "build-info.json"),
                 "build_info": json.loads((args.dist / "build-info.json").read_text(encoding="utf-8"))},
        "driver_sha256": sha(__file__), "e2e_sha256": sha(HERE / "e2e_w3.mjs"),
        "samples": {label: sha(ROOT / path) for label, path in SAMPLES},
        "headless": True,
    })

    server, requests = make_server(args.dist, args.manifest)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    profile = Path(tempfile.mkdtemp(prefix="kj-w3-profile-"))
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={profile}",
                                "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
                                "--disable-extensions", "--disable-sync", "--disable-background-networking",
                                "about:blank"])
    try:
        port_file = profile / "DevToolsActivePort"
        for _ in range(200):
            if port_file.exists() and len(port_file.read_text().split()) >= 2:
                break
            time.sleep(0.1)
        port, ws_path = port_file.read_text().split()[:2]
        e2e = subprocess.run(["node", str(HERE / "e2e_w3.mjs"), f"ws://127.0.0.1:{port}{ws_path}",
                              f"{origin}/index.html", str(args.output)], timeout=args.timeout,
                             capture_output=True, text=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    save(args.output / "server-requests.json", requests)
    (args.output / "e2e.log").write_text(e2e.stdout + e2e.stderr, encoding="utf-8")
    result = json.loads((args.output / "e2e.json").read_text(encoding="utf-8"))
    steps, marks = result.get("steps", {}), result.get("marks", [])
    gate = GATES["probability_max_abs_vs_official"]
    summary = {"schema_version": "kaze_judge.web_demo_w3_summary.v1", "e2e_completed": bool(result.get("completed")),
               "e2e_error": result.get("error"), "gates": {}}
    g = summary["gates"]
    if not summary["e2e_completed"]:
        summary["passed"] = False
        save(args.output / "summary.json", summary)
        raise SystemExit(f"e2e failed: {result.get('error')}")

    click = window(marks, "download:click", "download:ready")[0]
    model_requests = [r for r in requests if r["path"].startswith("/model/")]
    g["consent"] = {"passed": not [r for r in model_requests if r["time"] < click],
                    "requests_before_click": [r["path"] for r in requests if r["time"] < click]}
    counts = {}
    for r in model_requests:
        counts[r["path"]] = counts.get(r["path"], 0) + 1
    expected = {f"/{config['manifest']['url']}"} | {f"/{a['url']}" for a in config["assets"]}
    g["single_download"] = {"passed": set(counts) == expected and all(v == 1 for v in counts.values()),
                            "counts": counts}
    eval_windows = [window(marks, f"{name}:start", f"{name}:end") for name in
                    ("eval0", "eval2", "eval5", "eval6", "eval-no-reason", "eval-after-cancel", "eval-after-reload")]
    during = [n for n in result["network"] if any(s <= n["time"] <= e for s, e in eval_windows)]
    during += [r for r in requests if any(s <= r["time"] <= e for s, e in eval_windows)]
    foreign = [n["url"] for n in result["network"] if not n["url"].startswith(origin) and not n["url"].startswith("blob:")
               and not n["url"].startswith("about:")]
    g["private_inference"] = {"passed": not during and not foreign, "during_evaluation": during, "foreign": foreign}

    rows = {}
    for key, index in (("eval_sample0", 0), ("eval_sample2", 2), ("eval_sample5", 5)):
        rows[key] = check_completed(steps[key], refs[index], gate)
    over = steps["eval_sample6"]["attempt"]
    rows["eval_sample6_budget"] = {"passed": over["outcome"] == {"status": "failed", "value": "budget_exceeded"}
                                   and over["provider_calls_started"] == 1, "outcome": over["outcome"]}
    none = steps["eval_no_reason"]["attempt"]
    rows["no_reason"] = {"passed": none["outcome"] == {"status": "not_selected"} and none["provider_calls_started"] == 0,
                         "outcome": none["outcome"]}
    rows["ui_validation"] = {"passed": "候補IDが重複" in steps["ui_validation"]["run_status"]
                             and not steps["ui_validation"]["running"], "message": steps["ui_validation"]["run_status"]}
    g["results"] = {"passed": all(r["passed"] for r in rows.values()), "rows": rows}

    attempt = steps["eval_sample0"]["attempt"]
    artifacts = {a["component"]: a["sha256"] for a in attempt["outcome"]["value"]["artifacts"]}
    required = {a["path"] for a in config["assets"]} | {"bundle_manifest", "wasm_engine", "prompt", "rendered_prompt", "policy"}
    g["attempt"] = {"passed": attempt["schema_version"] == "kaze_judge.attempt.v1" and required <= set(artifacts)
                    and artifacts["wasm_engine"] == config["engine"]["sha256"]
                    and artifacts["bundle_manifest"] == config["manifest"]["sha256"],
                    "components": sorted(artifacts)}
    saved = steps["save"]["content"]
    order = ["schema_version", "request", "provider_calls_started", "outcome"]
    g["save"] = {"passed": saved is not None and json.loads(saved) == attempt and list(json.loads(saved)) == order,
                 "file": steps["save"]["file"], "fields": list(json.loads(saved)) if saved else None}
    first = attempt["outcome"]["value"]["scores"]
    g["repeat"] = {"passed": all(steps[k]["attempt"]["outcome"]["value"]["scores"] == first
                                 for k in ("eval_after_cancel", "eval_after_reload"))}
    # An evaluation shorter than the 50 ms heartbeat records no gap (e.g. not_selected).
    gaps = {k: v["max_main_thread_gap_ms"] for k, v in steps.items()
            if isinstance(v, dict) and v.get("max_main_thread_gap_ms") is not None}
    g["main_thread"] = {"passed": max(gaps.values()) <= GATES["max_main_thread_gap_ms"], "max_gap_ms": gaps}
    deleted = steps["delete"]
    g["delete"] = {"passed": not [n for n in deleted["cache_names"] if n.startswith("kazejudge-model-")]
                   and "取得していません" in steps["after_delete_reload"]["status"],
                   "usage_before": deleted["usage_before"], "usage_after": deleted["usage_after"]}
    summary["timings"] = {
        "download_and_open": steps["download"]["report"],
        "load_from_cache": steps["load_cached"]["report"],
        "evaluations_ms": {k: v["elapsed_ms"] for k, v in steps.items() if isinstance(v, dict) and "elapsed_ms" in v},
    }
    summary["passed"] = all(v["passed"] for v in g.values())
    save(args.output / "summary.json", summary)
    print(json.dumps({"passed": summary["passed"], **{k: v["passed"] for k, v in g.items()}}, indent=1))
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
