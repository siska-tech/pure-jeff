"""Cache reuse and offline inference across a redeploy, in one persistent browser profile.

    python -B run_deploy_cache.py --browser <exe> --site-url <url> --profile <dir> --output <new dir> prepare
    (deploy)
    python -B run_deploy_cache.py --browser <exe> --site-url <url> --profile <same dir> --output <new dir> reuse

prepare (before the deploy, on the live site) downloads the model into the profile's Cache
Storage and decides samples 0 and 5. reuse (after the deploy, same profile) passes when:
  - cached_at_open: the page shows the model as saved before anything is clicked
  - no_model_download: loading requests none of the model assets the config lists (bundle
    manifest and checkpoint files, wherever they are hosted)
  - same_cache: the Cache Storage name is the one prepare filled
  - engine: every Attempt names the engine of the deployed demo-config.json (wasm_engine
    artifact) and the engine was fetched under its content-addressed name
  - offline: with the network cut for the page and its Workers a fetch fails, and samples 0
    and 5 still complete
  - results: every decision matches the official reference (probability <= 1e-4, judgment,
    token count) and the offline decisions equal the online ones and prepare's bit for bit
Single observations; not a performance result."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

from build_demo import ROOT, SAMPLES
from run_w3 import check_completed

HERE = Path(__file__).resolve().parent


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def probabilities(decision):
    return [s["option_probability"] for s in decision["attempt"]["outcome"]["value"]["scores"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["prepare", "reuse"])
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--site-url", required=True)
    parser.add_argument("--profile", type=Path, required=True, help="persistent browser profile shared by both modes")
    parser.add_argument("--prepared", type=Path, help="reuse: the prepare output directory, for bitwise comparison")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    # Chrome nests Cache Storage several directories deep in the profile; on Windows a long
    # profile path exceeds the path limit and CacheStorage.open fails with an internal error.
    if len(str(args.profile.resolve())) > 80:
        raise SystemExit("use a profile path of at most 80 characters")
    args.output.mkdir(parents=True)
    args.profile.mkdir(parents=True, exist_ok=args.mode == "reuse")
    origin = args.site_url.rstrip("/")
    save(args.output / "preregistration.json", {
        "schema_version": "pure_jeff.web_demo_deploy_cache.v1", "mode": args.mode,
        "created_utc": datetime.now(timezone.utc).isoformat(), "site": origin,
        "browser_sha256": hashlib.sha256(args.browser.read_bytes()).hexdigest(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "e2e_sha256": hashlib.sha256((HERE / "e2e_deploy_cache.mjs").read_bytes()).hexdigest(),
        "gates": __doc__.split("passes when:")[1].split("Single")[0].strip()})
    port_file = args.profile / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    browser = subprocess.Popen([str(args.browser), "--headless=new", f"--user-data-dir={args.profile}",
                                "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
                                "--disable-extensions", "--disable-sync", "--disable-background-networking",
                                "about:blank"])
    raw = args.output / "e2e.json"
    try:
        for _ in range(200):
            if port_file.exists() and len(port_file.read_text().split()) >= 2:
                break
            time.sleep(0.1)
        port, ws_path = port_file.read_text().split()[:2]
        run = subprocess.run(["node", str(HERE / "e2e_deploy_cache.mjs"), f"ws://127.0.0.1:{port}{ws_path}",
                              f"{origin}/index.html?lang=ja", str(raw), args.mode],
                             timeout=args.timeout, capture_output=True, text=True)
        (args.output / "e2e.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        browser.wait()
    result = json.loads(raw.read_text(encoding="utf-8"))
    refs = {i: json.loads((ROOT / SAMPLES[i][2]).read_text(encoding="utf-8")) for i in (0, 5)}
    gates = {}
    if result.get("completed"):
        config = result["config"]
        gates["results"] = all(check_completed(d, refs[d["sample"]], 1e-4)["passed"] for d in result["decisions"])
        engines = {next(a["sha256"] for a in d["attempt"]["outcome"]["value"]["artifacts"]
                        if a["component"] == "wasm_engine") for d in result["decisions"]}
        engine_urls = [n["url"] for n in result["network"] if n.get("url", "").split("?")[0].endswith(".wasm")]
        gates["engine"] = (engines == {config["engine"]["sha256"]}
                           and any(u.split("?")[0].endswith("/" + config["engine"]["url"]) for u in engine_urls))
        if args.mode == "reuse":
            loaded = [n for n in result["network"] if n.get("url") and n["time"] >= result["marks"]["load_click"]]
            gates["cached_at_open"] = result["model_state_at_open"] == "cached"
            assets = [config["manifest"]["url"]] + [a["url"] for a in config["assets"]]
            assets = [u.split("://", 1)[-1].lstrip("/") for u in assets]
            gates["no_model_download"] = not [n for n in loaded
                                              if any(n["url"].split("?")[0].endswith(a) for a in assets)]
            gates["offline"] = (result["offline_fetch_fails"]
                                and len([d for d in result["decisions"] if d["offline"]]) == 2)
            online = {d["sample"]: probabilities(d) for d in result["decisions"] if not d["offline"]}
            offline = {d["sample"]: probabilities(d) for d in result["decisions"] if d["offline"]}
            same = online == offline
            if args.prepared:
                prepared = json.loads((args.prepared / "e2e.json").read_text(encoding="utf-8"))
                gates["same_cache"] = set(result["cache_names"]) == set(prepared["cache_names"])
                same = same and online == {d["sample"]: probabilities(d) for d in prepared["decisions"]}
            gates["results"] = gates["results"] and same
    summary = {"mode": args.mode, "completed": result.get("completed"), "error": result.get("error"),
               "engine_url": (result.get("config") or {}).get("engine", {}).get("url"),
               "model_state_at_open": result.get("model_state_at_open"), "gates": gates,
               "passed": bool(result.get("completed")) and all(gates.values())}
    save(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=1))
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
