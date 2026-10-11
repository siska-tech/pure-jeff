"""Protocol fixture only: no model or recognition quality claims."""
import argparse
import json
from pathlib import Path
import time
p=argparse.ArgumentParser()
for name in ("manifest", "request", "response"):
    p.add_argument("--"+name, required=True)
a=p.parse_args()
w=json.loads(Path(a.request).read_text(encoding="utf-8"))
r=w["request"]
mode=r["original_text"]
if mode == "timeout":
    Path(a.manifest + ".started").write_text("started")
    time.sleep(2)
    Path(a.manifest + ".survived").write_text("should not exist")
if mode == "crash":
    raise SystemExit(2)
if mode == "oversized":
    Path(a.response).write_text(" " * 1048577)
    raise SystemExit()
if mode == "invalid_json":
    Path(a.response).write_text("{")
    raise SystemExit()
observation={"scores":[{"candidate_id":c["id"],"option_probability":p} for c,p in zip(r["candidates"],[0.8,0.2])],
             "judgment":{"kind":"selected","candidate_id":r["candidates"][0]["id"]},
             "temperature":1.0,"input_tokens":20,"forwards":1,
             "artifacts":[{"component":"fixture_only","sha256":"a"*64}]}
result={"status":"completed","value":observation}
if mode == "budget":
    observation["forwards"]=2
if mode == "unavailable":
    result={"status":"failed","value":"unavailable"}
Path(a.response).write_text(json.dumps({"schema_version":"kaze_judge.worker.v1",
    "request_id":"wrong" if mode == "wrong_id" else r["request_id"],"result":result}),encoding="utf-8")
