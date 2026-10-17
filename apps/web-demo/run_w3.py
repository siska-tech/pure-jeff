"""W3/W4 end-to-end check of the built web demo in a fresh headless browser profile.

W3 mode serves site and model from one HTTP origin on 127.0.0.1. W4 mode (--w4) serves the site
from https://demo.test and the model from https://models.test with CORS (as Cloudflare Pages +
an R2 bucket would), trusts only a throwaway self-signed certificate, and first aborts a
download. Feasibility only: single observations are not performance results."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import re
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
    "attempt": "schema pure_jeff.attempt.v1; artifacts include the manifest files, bundle_manifest, "
               "wasm_engine (= deployed engine hash), prompt, rendered_prompt and policy",
    "save": "the downloaded JSON equals the displayed Attempt, with top-level fields in pure_jeff::Attempt order",
    "repeat": "results after cancel recovery and after page reload are bitwise equal to the first",
    "delete": "after delete no pure-jeff-model cache remains and a reload shows the model as not downloaded",
    "languages": "the language selector switches to English, Vietnamese and back to Japanese: the document "
                 "language, URL ?lang=, page state and title follow; English and Vietnamese pages contain no "
                 "Japanese text outside the selector; the rest of the run is in Japanese (opened with ?lang=ja)",
}
# Added for W4 (replaces single_download); registered before the first W4 run.
GATES_W4 = {
    "https": "every page/Worker request is https and goes to the site origin or the model origin; the site "
             "origin serves no model/ file and the model origin serves only model/ files",
    "abort": "after stopping a download while model.safetensors streams, it is not in Cache Storage, the UI "
             "shows the model as not downloaded with evaluation disabled, and the server saw an incomplete transfer",
    "single_download": "model.safetensors is transferred completely exactly once, and no model/ request "
                       "follows the first completed download (cancel recovery and reload read Cache Storage)",
}
# External model host (e.g. Hugging Face) and/or a deployed site: there is no model server log, so
# download checks use the browser's own network log (page and Workers). Registered before the first run.
GATES_EXTERNAL = {
    "consent": "no request to the model host before the download button is pressed",
    "abort": "after stopping a download while model.safetensors streams, it is not in Cache Storage and the UI "
             "shows the model as not downloaded with evaluation disabled; leftover partial data can be deleted from "
             "the page (delete enabled) and no cache remains afterwards",
    "single_download": "after the second download click, model.safetensors is requested exactly once from the "
                       "model host, and no model-host request follows the completed download",
    "hosts": "every page/Worker request goes to the site origin, the model host or its download CDN (*.hf.co), "
             "over https except a local http site",
    "deployed": "with --site-url, the deployed demo-config.json and engine equal the local build",
    "engine_retry": "with --stale-engine-once, the first engine request gets other bytes (a deploy switching "
                    "over); the page fetches the config again, the engine is requested a second time and every "
                    "other gate still passes",
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
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/jeff-rust-bundle.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=5400)
    parser.add_argument("--w4", action="store_true", help="HTTPS, separate model origin with CORS, download abort")
    parser.add_argument("--site-port", type=int, default=9443)
    parser.add_argument("--model-port", type=int, default=9444)
    parser.add_argument("--external-model", action="store_true",
                        help="the build fetches the model from an external https host (e.g. Hugging Face)")
    parser.add_argument("--site-url", help="test an already deployed site instead of serving --dist locally")
    parser.add_argument("--stale-engine-once", action="store_true",
                        help="local W3 only: serve other bytes for the first engine request")
    args = parser.parse_args()
    if args.stale_engine_once and (args.w4 or args.site_url):
        raise SystemExit("--stale-engine-once needs the local W3 server")
    external = args.external_model or bool(args.site_url)
    args.output.mkdir(parents=True)
    config = json.loads((args.dist / "demo-config.json").read_text(encoding="utf-8"))
    site_origin = f"https://demo.test:{args.site_port}" if args.w4 else None
    model_origin = f"https://models.test:{args.model_port}" if args.w4 else None
    if args.w4 and config.get("model_base_url") != f"{model_origin}/model/":
        raise SystemExit(f"build the demo with --model-base-url {model_origin}/model/")
    refs = [json.loads((ROOT / path).read_text(encoding="utf-8")) for _, _, path in SAMPLES]
    save(args.output / "preregistration.json", {
        "schema_version": "kaze_judge.web_demo_w3_preregistration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "gates": GATES,
        "mode": "external" if external else "w4" if args.w4 else "w3",
        "gates_w4": GATES_W4 if args.w4 else None, "gates_external": GATES_EXTERNAL if external else None,
        "site_url": args.site_url, "model_base_url": config.get("model_base_url"),
        "origins": {"site": site_origin, "model": model_origin},
        "browser": {"path": str(args.browser), "sha256": sha(args.browser)},
        "dist": {"build_info_sha256": sha(args.dist / "build-info.json"),
                 "build_info": json.loads((args.dist / "build-info.json").read_text(encoding="utf-8"))},
        "driver_sha256": sha(__file__), "e2e_sha256": sha(HERE / "e2e_w3.mjs"),
        "samples": {label: sha(ROOT / path) for _, label, path in SAMPLES},
        "headless": True,
    })

    flags = []
    if args.w4:
        tls_dir = args.output / "tls"
        tls_dir.mkdir()
        cert, key = tls_dir / "cert.pem", tls_dir / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=demo.test",
                        "-addext", "subjectAltName=DNS:demo.test,DNS:models.test",
                        "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
        pubkey = subprocess.run(["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"],
                                check=True, capture_output=True).stdout
        der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "der"], input=pubkey,
                             check=True, capture_output=True).stdout
        spki = base64.b64encode(hashlib.sha256(der).digest()).decode()
        server, requests = make_server(args.dist, args.manifest, args.site_port, role="site", tls=(cert, key))
        model_server, model_requests_log = make_server(args.dist, args.manifest, args.model_port, role="model",
                                                       tls=(cert, key), cors_origin=site_origin)
        threading.Thread(target=model_server.serve_forever, daemon=True).start()
        origin = site_origin
        # Only this throwaway certificate is trusted, and only the two test names resolve locally.
        flags = ["--host-resolver-rules=MAP demo.test 127.0.0.1,MAP models.test 127.0.0.1",
                 f"--ignore-certificate-errors-spki-list={spki}"]
    elif args.site_url:
        server, requests, model_server, model_requests_log = None, [], None, None
        origin = args.site_url.rstrip("/")
    else:
        stale = {config["engine"]["url"]} if args.stale_engine_once else ()
        server, requests = make_server(args.dist, args.manifest, role="site" if external else "all",
                                       stale_once=stale)
        model_server, model_requests_log = None, None
        origin = f"http://127.0.0.1:{server.server_port}"
    if server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = Path(tempfile.mkdtemp(prefix="pj-w3-profile-"))
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={profile}",
                                "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
                                "--disable-extensions", "--disable-sync", "--disable-background-networking",
                                *flags, "about:blank"])
    try:
        port_file = profile / "DevToolsActivePort"
        for _ in range(200):
            if port_file.exists() and len(port_file.read_text().split()) >= 2:
                break
            time.sleep(0.1)
        port, ws_path = port_file.read_text().split()[:2]
        e2e = subprocess.run(["node", str(HERE / "e2e_w3.mjs"), f"ws://127.0.0.1:{port}{ws_path}",
                              f"{origin}/index.html?lang=ja", str(args.output),
                              *(["--abort-download"] if args.w4 or external else [])],
                             timeout=args.timeout, capture_output=True, text=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
        if server:
            server.shutdown()
        if model_server:
            model_server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    save(args.output / "server-requests.json", requests)
    if model_requests_log is not None:
        save(args.output / "model-server-requests.json", model_requests_log)
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

    click, ready = window(marks, "download:click", "download:ready")
    first_click = window(marks, "abort:click", "abort:stopped")[0] if args.w4 or external else click
    all_requests = requests + (model_requests_log or [])
    model_requests = [r for r in all_requests if r["path"].startswith("/model/")]
    if args.stale_engine_once:
        engine_requests = [r for r in requests if r["path"].split("?")[0] == "/" + config["engine"]["url"]]
        g["engine_retry"] = {"passed": len(engine_requests) >= 2 and engine_requests[0]["stale"]
                             and engine_requests[1]["complete"],
                             "engine_requests": [(r["status"], r["bytes"], r["stale"]) for r in engine_requests]}
    g["consent"] = {"passed": not [r for r in model_requests if r["time"] < first_click],
                    "requests_before_click": [r["path"] for r in all_requests if r["time"] < first_click]}
    counts = {}
    for r in model_requests:
        counts[r["path"]] = counts.get(r["path"], 0) + 1
    if external:
        base = config["model_base_url"]
        host_net = [n for n in result["network"] if n["url"].startswith(base) or ".hf.co/" in n["url"]]
        g["consent"] = {"passed": not [n for n in host_net if n["time"] < first_click],
                        "model_host_requests_before_click": [n["url"] for n in host_net if n["time"] < first_click]}
        weights = [n for n in result["network"] if n["url"] == base + "model.safetensors"]
        g["single_download"] = {"passed": len([n for n in weights if n["time"] > click]) == 1
                                and not [n for n in host_net if n["time"] > ready],
                                "model_requests": len(weights), "after_second_click": len([n for n in weights if n["time"] > click])}
        abort = steps["abort"]
        g["abort"] = {"passed": abort["model_in_cache"] is False and abort["evaluate_disabled"]
                      and "取得していません" in abort["status"] and bool([n for n in weights if n["time"] < click])
                      and abort.get("cache_after_cleanup") is False
                      and (abort.get("state") != "partial" or abort.get("delete_enabled") is True),
                      "step": abort}
        net = [n["url"] for n in result["network"] if not n["url"].startswith(("blob:", "about:", "data:"))]
        hosts = sorted({u.split("/")[2] for u in net})
        site_host = origin.split("/")[2]
        model_host = base.split("/")[2]
        g["hosts"] = {"passed": all(h in (site_host, model_host) or h.endswith(".hf.co") for h in hosts)
                      and all(u.startswith("https://") or u.startswith(origin) for u in net), "hosts": hosts}
        if args.site_url:
            import urllib.request

            def fetch(path, timeout):
                # Cloudflare may reject the default Python-urllib user agent (HTTP 403).
                request = urllib.request.Request(f"{origin}/{path}", headers={"User-Agent": "pure-jeff-e2e/1"})
                return urllib.request.urlopen(request, timeout=timeout).read()
            deployed = json.loads(fetch("demo-config.json", 60))
            engine = fetch(config["engine"]["url"], 120)
            g["deployed"] = {"passed": deployed == config and hashlib.sha256(engine).hexdigest() == config["engine"]["sha256"],
                             "engine_sha256": hashlib.sha256(engine).hexdigest()}
    elif args.w4:
        weights = [r for r in model_requests if r["path"].endswith("/model.safetensors")]
        g["single_download"] = {"passed": sum(r["complete"] for r in weights) == 1
                                and not [r for r in model_requests if r["time"] > ready],
                                "counts": counts, "model_transfers": [(r["bytes"], r["complete"]) for r in weights]}
        abort = steps["abort"]
        aborted = [r for r in weights if r["time"] < click and not r["complete"]]
        g["abort"] = {"passed": abort["model_in_cache"] is False and abort["evaluate_disabled"]
                      and "取得していません" in abort["status"] and bool(aborted), "step": abort,
                      "incomplete_transfers": len(aborted)}
        net = [n["url"] for n in result["network"] if not n["url"].startswith(("blob:", "about:", "data:"))]
        g["https"] = {"passed": all(u.startswith((site_origin + "/", model_origin + "/")) for u in net)
                      and not [r for r in requests if r["path"].startswith("/model/") and r["status"] == 200]
                      and all(r["path"].startswith("/model/") for r in model_requests_log),
                      "origins": sorted({u.split("/")[2] for u in net})}
    else:
        expected = {f"/{config['manifest']['url']}"} | {f"/{a['url']}" for a in config["assets"]}
        g["single_download"] = {"passed": set(counts) == expected and all(v == 1 for v in counts.values()),
                                "counts": counts}
    eval_windows = [window(marks, f"{name}:start", f"{name}:end") for name in
                    ("eval0", "eval2", "eval5", "eval6", "eval-no-reason", "eval-after-cancel", "eval-after-reload")]
    during = [n for n in result["network"] if any(s <= n["time"] <= e for s, e in eval_windows)]
    during += [r for r in all_requests if any(s <= r["time"] <= e for s, e in eval_windows)]
    # External mode allows the whole model host (its redirects, e.g. Hugging Face's /api/resolve-cache/,
    # are outside the pinned resolve/ prefix) and its *.hf.co CDN, matching the "hosts" gate.
    external_host = config["model_base_url"].split("/")[2] if external else None
    allowed = tuple(o for o in (origin, model_origin, f"https://{external_host}/" if external_host else None) if o)
    foreign = [n["url"] for n in result["network"] if not n["url"].startswith(allowed)
               and not n["url"].startswith(("blob:", "about:", "data:"))
               and not (external and ".hf.co/" in n["url"])]
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
    g["attempt"] = {"passed": attempt["schema_version"] == "pure_jeff.attempt.v1" and required <= set(artifacts)
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
    languages = steps["languages"]
    # kana, CJK ideographs and full-width forms
    japanese = re.compile("[%s-%s%s-%s%s-%s]" % tuple(map(chr, (0x3040, 0x30FF, 0x3400, 0x9FFF, 0xFF01, 0xFF60))))
    g["languages"] = {"passed": all(languages[c]["lang"] == c and languages[c]["state_lang"] == c
                                    and languages[c]["url_lang"] == c for c in ("en", "vi", "ja"))
                      and len({languages[c]["title"] for c in ("en", "vi", "ja")}) == 3
                      and not japanese.search(languages["en"]["text"]) and not japanese.search(languages["vi"]["text"])
                      and "取得していません" in languages["ja"]["status"],
                      "status": {c: languages[c]["status"] for c in ("en", "vi", "ja")}}
    g["delete"] = {"passed": not [n for n in deleted["cache_names"] if n.startswith("pure-jeff-model-")]
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
