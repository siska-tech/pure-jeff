"""Start a launcher running a sleeping script, kill only the launcher, report whether the real interpreter survives."""
import subprocess, sys, time, json, os
launcher = sys.argv[1]
marker = os.path.join(os.environ["TMP"], f"child-{os.getpid()}.txt")
code = f"import os,time; open(r'{marker}','w').write(str(os.getpid())); time.sleep(30)"
p = subprocess.Popen([launcher, "-c", code])
for _ in range(100):
    if os.path.exists(marker): break
    time.sleep(0.1)
child = int(open(marker).read())
p.kill(); p.wait()
time.sleep(1)
alive = str(child) in subprocess.run(["tasklist", "/FI", f"PID eq {child}", "/NH"], capture_output=True, text=True).stdout
print(json.dumps({"launcher": launcher, "launcher_pid": p.pid, "interpreter_pid": child, "separate_process": child != p.pid, "interpreter_alive_after_launcher_killed": alive}))
if alive: subprocess.run(["taskkill", "/PID", str(child), "/F"], capture_output=True)
os.remove(marker)
