"""Freeze a randomized execution list, then send one trial per fresh VM boot."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time
import uuid
from .common import ROOT,write_json,command_version

def make_matrix(blocks=8,rate=200,donor_mib=512):
    rng=random.Random(20261021)
    runs=[]
    for regime in ("R1","R2","R3"):
        for block in range(blocks):
            common={"mib":donor_mib,"hot-mib":32,"reuse-mib":donor_mib,"pages-per-tick":128,"pattern":"structured"}
            donors={"A":dict(common,seed=1000+block),"B":dict(common,seed=2000+block)}
            if regime in ("R1","R3"):
                donors["B" if block%2==0 else "A"]["pattern"]="random"
            if regime=="R2":
                # Identical data/footprint. One donor reuses its cold region after dispatch.
                target="A" if block%2==0 else "B"
                donors[target].update({"reuse-after":26,"pages-per-tick":2048})
                donors["B" if target=="A" else "A"]["pages-per-tick"]=2048
            if regime=="R3":
                donors["interference"]={"mib":32,"hot-mib":8,"reuse-mib":32,"seed":3000+block,
                                         "pattern":"random","extra-mib":192,"allocate-after":29,"release-after":39}
            arms=["none","A","B"];rng.shuffle(arms)
            for arm in arms:
                runs.append({"purpose":"discovery","regime":regime,"block":block,"arm":arm,"policy":"reference",
                             "warmup_seconds":5,"pre_seconds":20,"horizon_seconds":20,"recovery_seconds":5,
                             "foreground":{"mib":128,"touches":65536,"rate":rate,"max_outstanding":64,"timeout_seconds":2},
                             "donors":donors,"request_bytes":33554432,"poll_seconds":.25,
                             "generator_lateness_limit_seconds":.1,"actuator_timeout_seconds":5,"swappiness_max":False})
    # Preserve seed-block adjacency, randomize blocks across regimes.
    blocks_list=[runs[i:i+3] for i in range(0,len(runs),3)]
    rng.shuffle(blocks_list)
    return [run for block in blocks_list for run in block]

def job(operation,**kwargs):
    identifier=f"{time.time_ns()}-{uuid.uuid4().hex[:6]}"
    write_json(ROOT/"vm/inbox"/(identifier+".json"),{"operation":operation,**kwargs})
    return identifier

def wait_job(identifier,timeout=240):
    response=ROOT/"vm/outbox"/(identifier+".json")
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if response.exists():return json.loads(response.read_text())
        time.sleep(.5)
    raise TimeoutError("guest operation timed out: "+identifier)

def reboot():
    state=ROOT/"vm/guest-status.json"
    previous=json.loads(state.read_text())["boot_id"]
    result=wait_job(job("reboot"),60)
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        try:
            current=json.loads(state.read_text())
            if current.get("state")=="ready" and current.get("boot_id")!=previous:return current
        except (OSError,json.JSONDecodeError):pass
        time.sleep(.5)
    raise TimeoutError("guest did not return with a fresh boot ID")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--create",action="store_true")
    parser.add_argument("--blocks",type=int,default=8)
    parser.add_argument("--rate",type=int,default=200)
    parser.add_argument("--donor-mib",type=int,default=512)
    parser.add_argument("--matrix",default="configs/discovery-matrix.json")
    parser.add_argument("--run",action="store_true")
    args=parser.parse_args();path=ROOT/args.matrix
    if args.create:
        if path.exists():raise SystemExit("refusing to overwrite a frozen matrix")
        runs=make_matrix(args.blocks,args.rate,args.donor_mib)
        write_json(path,{"kind":"discovery","randomization_seed":20261021,"runs":runs})
        print("frozen",len(runs),"trials",flush=True)
    matrix=json.loads(path.read_text())
    progress=path.with_name(path.stem+"-progress.json")
    state=json.loads(progress.read_text()) if progress.exists() else {"matrix_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"attempts":[]}
    if state["matrix_sha256"]!=hashlib.sha256(path.read_bytes()).hexdigest():raise SystemExit("matrix changed after execution began")
    if not args.run:return
    for index,config in enumerate(matrix["runs"]):
        # Previously completed/failed attempts are retained. Repeating failures is explicit.
        if any(row["index"]==index for row in state["attempts"]):continue
        print("reboot before trial",index,flush=True)
        fresh=reboot()
        config_path=ROOT/"configs/generated"/f"{path.stem}-{index:04d}.json"
        config["execution"]={"matrix":args.matrix,"matrix_sha256":state["matrix_sha256"],"index":index}
        write_json(config_path,config)
        host_before={"vm_stat":command_version(["vm_stat"]),"load":command_version(["sysctl","-n","vm.loadavg"])}
        request=job("trial",config=str(config_path.relative_to(ROOT)))
        result=wait_job(request,240)
        host_after={"vm_stat":command_version(["vm_stat"]),"load":command_version(["sysctl","-n","vm.loadavg"])}
        state["attempts"].append({"index":index,"request":request,"result":result,"boot_id":fresh["boot_id"],
                                  "host_before":host_before,"host_after":host_after})
        write_json(progress,state)
        print(json.dumps({"index":index,"total":len(matrix["runs"]),"regime":config["regime"],"block":config["block"],"arm":config["arm"],"result":result}),flush=True)
        if result.get("status")!="complete":
            print("stopping after failure; inspect saved attempt before resuming",flush=True);return

if __name__=="__main__":main()
