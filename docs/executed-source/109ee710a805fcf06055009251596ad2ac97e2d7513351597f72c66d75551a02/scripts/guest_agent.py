"""Local file-queue agent for the dedicated VM. Accepts named operations only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from harness.common import boot_id,write_json

def main():
    if not Path("/etc/oslab-research-vm").exists():raise SystemExit("dedicated guest marker missing")
    os.chdir(ROOT)
    subprocess.run(["sh",str(ROOT/"scripts/provision_guest.sh")],check=True)
    subprocess.run(["make","all"],check=True)
    relative=next(line.split(":",2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))
    parent=Path("/sys/fs/cgroup")/relative.lstrip("/")
    observer=parent/"observer";observer.mkdir(exist_ok=True)
    (observer/"cgroup.procs").write_text(str(os.getpid()))
    (parent/"cgroup.subtree_control").write_text("+memory +cpu")
    inbox,outbox=ROOT/"vm/inbox",ROOT/"vm/outbox"
    inbox.mkdir(exist_ok=True);outbox.mkdir(exist_ok=True)
    write_json(ROOT/"vm/guest-status.json",{"state":"ready","boot_id":boot_id(),"parent":str(parent),"t":time.time()})
    while True:
        for request in sorted(inbox.glob("*.json")):
            response=outbox/request.name
            if response.exists():continue
            job=json.loads(request.read_text());operation=job.get("operation")
            write_json(ROOT/"vm/guest-status.json",{"state":"running","operation":operation,"request":request.stem,"boot_id":boot_id()})
            if operation in ("trial","overhead"):
                config=(ROOT/job["config"]).resolve()
                if not config.is_relative_to((ROOT/"configs").resolve()):raise ValueError("config outside project configs")
                module="harness.run_trial" if operation=="trial" else "analysis.overhead_trial"
                command=[sys.executable,"-m",module,str(config),"--cgroup-parent",str(parent)]
            elif operation=="packages":command=["dpkg-query","-W"]
            elif operation=="check":
                command=[sys.executable,"-m","harness.check_environment","--output",str(ROOT/"configs/environment.json"),"--cgroup-parent",str(parent)]
            elif operation=="test":command=[sys.executable,"-m","unittest","discover","-s","tests","-v"]
            elif operation=="calibrate":command=[sys.executable,"-m","harness.calibrate"]
            elif operation=="shutdown":
                write_json(response,{"status":"shutdown_requested","boot_id":boot_id()})
                subprocess.run(["systemctl","poweroff"]);return
            elif operation=="reboot":
                write_json(response,{"status":"reboot_requested","boot_id":boot_id()})
                subprocess.run(["systemctl","reboot"]);time.sleep(30);return
            else:
                write_json(response,{"status":"rejected","reason":"unsupported operation"});continue
            with (outbox/(request.stem+".log")).open("w") as log:
                result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
            write_json(response,{"status":"complete" if result.returncode==0 else "failed", "returncode":result.returncode,"boot_id":boot_id()})
            write_json(ROOT/"vm/guest-status.json",{"state":"ready","boot_id":boot_id(),"parent":str(parent),"t":time.time()})
        time.sleep(0.25)

if __name__=="__main__":main()
