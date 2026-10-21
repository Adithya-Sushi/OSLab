"""Run the remaining observer validity check after the frozen research phase."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from harness.common import ROOT,source_manifest,write_json
from harness.run_matrix import reboot,job,wait_job

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    while True:
        path=ROOT/"results/derived/pilot-status.json"
        status=json.loads(path.read_text()) if path.exists() else {}
        if status.get("state") in ("stopped_at_checkpoint_A","stopped_at_checkpoint_B"):break
        if status.get("state") in ("execution_failure","ready_for_controller_pilot"):
            print("requires review before post-pilot checks",status,flush=True);return
        time.sleep(2)
    subprocess.run([sys.executable,"-m","analysis.snapshot_source"],cwd=ROOT,check=True)
    agent=ROOT/"scripts/guest_agent.py";old=agent.read_text();before=sha(agent)
    if 'operation in ("trial","overhead")' not in old:
        changed=old.replace('if operation=="trial":','if operation in ("trial","overhead"):')
        changed=changed.replace('command=[sys.executable,"-m","harness.run_trial",str(config),"--cgroup-parent",str(parent)]',
                               'module="harness.run_trial" if operation=="trial" else "analysis.overhead_trial"\n                command=[sys.executable,"-m",module,str(config),"--cgroup-parent",str(parent)]')
        changed=changed.replace('elif operation=="check":','elif operation=="packages":command=["dpkg-query","-W"]\n            elif operation=="check":')
        if changed==old:raise RuntimeError("agent extension did not apply")
        compile(changed,str(agent),"exec");agent.write_text(changed)
    write_json(ROOT/"docs/post-pilot-source-change.json",{"reason":"After the frozen donor/estimator phases: extend only guest dispatch for collector on/off trials and complete read-only package capture.",
        "original_agent_sha256":before,"extended_agent_sha256":sha(agent),"extended_runtime_source":source_manifest()["sha256"],
        "overhead_trial_sha256":sha(ROOT/"analysis/overhead_trial.py"),"overhead_driver_sha256":sha(ROOT/"analysis/run_observer_overhead.py"),
        "primary_phase_completed_before_change":status})
    reboot()
    identifier=job("packages");result=wait_job(identifier,30)
    if result.get("status")!="complete":raise RuntimeError("package capture failed")
    (ROOT/"docs/complete-guest-packages.txt").write_text((ROOT/"vm/outbox"/(identifier+".log")).read_text())
    with (ROOT/"results/derived/overhead-execution.log").open("a") as log:
        subprocess.run([sys.executable,"-m","analysis.run_observer_overhead"],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    write_json(ROOT/"results/derived/post-pilot-checks.json",{"state":"complete","observer_overhead":"results/derived/observer-overhead.json","packages":"docs/complete-guest-packages.txt"})
    print("post-pilot validity checks complete",flush=True)

if __name__=="__main__":main()
