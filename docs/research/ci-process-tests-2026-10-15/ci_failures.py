"""List failing tests in Windows/Linux CI jobs of recent runs (every attempt), via gh api."""
import json
import re
import subprocess
import sys


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


runs = json.loads(gh("run", "list", "--workflow", "ci.yml", "--limit", sys.argv[1] if len(sys.argv) > 1 else "100",
                     "--json", "databaseId,createdAt,headBranch,event,attempt"))
rows = []
for run in runs:
    for attempt in range(1, run["attempt"] + 1):
        jobs = json.loads(gh("api", f"repos/siska-tech/pure-jeff/actions/runs/{run['databaseId']}/attempts/{attempt}/jobs"))
        for job in jobs.get("jobs", []):
            if job["conclusion"] != "failure":
                continue
            log = gh("api", f"repos/siska-tech/pure-jeff/actions/jobs/{job['id']}/logs").replace("\r", "")
            panics = re.findall(r"panicked at (tests[\\/][\w]+\.rs:\d+):\d+:\n[^\n]*?Z (.*)", log)
            results = re.findall(r"test result: FAILED\. (\d+) passed; (\d+) failed.*finished in ([\d.]+)s", log)
            failed_tests = re.findall(r"^\S+\s+(\w+) \.\.\. FAILED", log, re.M)
            other = [] if panics else re.findall(r"##\[error\](.*)", log)[:2]
            rows.append({"run": run["databaseId"], "attempt": attempt, "created": run["createdAt"],
                         "branch": run["headBranch"], "event": run["event"], "job": job["name"],
                         "failed_tests": failed_tests, "panics": panics, "results": results, "errors": other})
for r in rows:
    print(json.dumps(r, ensure_ascii=False))
