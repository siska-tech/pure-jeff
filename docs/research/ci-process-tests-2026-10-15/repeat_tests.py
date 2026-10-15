"""Run the process test binaries N times (optionally with every logical CPU busy) and record
each test binary's result and duration as JSON lines."""
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time


def burn(stop):
    while not stop.is_set():
        sum(i * i for i in range(10000))


def main():
    runs, loaded, out = int(sys.argv[1]), sys.argv[2] == "load", sys.argv[3]
    env = os.environ | {"PURE_JEFF_PYTHON": sys.executable}
    # Build once, so only test time is measured.
    subprocess.run(["cargo", "test", "--locked", "--all-features", "--no-run", "--test", "process",
                    "--test", "process_launch", "--test", "native_process"], check=True, env=env,
                   capture_output=True)
    stop = multiprocessing.Event()
    workers = []
    if loaded:
        workers = [multiprocessing.Process(target=burn, args=(stop,)) for _ in range(os.cpu_count())]
        for w in workers:
            w.start()
    with open(out, "x", encoding="utf-8") as stream:
        for i in range(runs):
            for test in ("process", "process_launch", "native_process"):
                started = time.perf_counter()
                run = subprocess.run(["cargo", "test", "-q", "--locked", "--all-features", "--test", test],
                                     env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
                text = run.stdout + run.stderr
                result = re.search(r"test result: (\w+)\. (\d+) passed; (\d+) failed.*finished in ([\d.]+)s", text)
                row = {"run": i, "test": test, "loaded": loaded, "exit": run.returncode,
                       "passed": int(result[2]) if result else None, "failed": int(result[3]) if result else None,
                       "finished_s": float(result[4]) if result else None,
                       "wall_s": round(time.perf_counter() - started, 2),
                       "failures": re.findall(r"panicked at ([^\n]+)", text),
                       "notes": re.findall(r"did not reach the fixture[^\n]*", text)}
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                print(row["run"], test, row["exit"], row["finished_s"], row["failures"][:1], flush=True)
    stop.set()
    for w in workers:
        w.join()


if __name__ == "__main__":
    main()
