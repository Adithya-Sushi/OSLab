"""Matched collector on/off validity study, separate from donor-effect claims."""
import argparse
import json
from pathlib import Path
import resource
import sys
import time
import traceback
import uuid
from harness.common import ROOT,BIN,boot_id,write_json
from harness.check_environment import inspect
from harness.collector import Collector
from harness.launch import Worker,prepare_groups,remove_groups
from harness.load_generator import ScheduledClient
from harness.run_trial import donor_command
from .trial_outcomes import progress_at

def resident_bytes():
    return int(Path("/proc/self/statm").read_text().split()[1])*resource.getpagesize()

def cpu_seconds():
    usage=resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime+usage.ru_stime

def execute(config,parent):
    attempt=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-overhead-"+uuid.uuid4().hex[:8]
    output=ROOT/"results/overhead"/attempt;output.mkdir(parents=True)
    write_json(output/"config.json",config)
    outcome={"attempt":attempt,"status":"failed","boot_id":boot_id(),"collect":config["collect"],"block":config["block"],"adverse_outcomes":[]}
    workers=[];collector=None;trial=None;groups={};client=None
    try:
        env=inspect(parent,True);write_json(output/"manifest.json",env)
        if not env["eligible"]:raise RuntimeError(str(env["failures"]))
        if not Path("/etc/oslab-research-vm").exists():raise RuntimeError("dedicated guest marker missing")
        last=ROOT/"vm/last-experiment-boot.json"
        if last.exists() and json.loads(last.read_text()).get("boot_id")==boot_id():raise RuntimeError("fresh boot required")
        if any(d["used_bytes"] for d in env["swaps"]):raise RuntimeError("starting swap is not empty")
        write_json(last,{"boot_id":boot_id(),"attempt":attempt})
        trial,groups=prepare_groups(parent,"trial-"+attempt,128,512)
        if config["collect"]:
            collector=Collector(output,{"parent":trial,**groups});collector.start()
        endpoint=Path("/tmp")/("oslab-oh-"+uuid.uuid4().hex[:12]+".sock")
        foreground=Worker("foreground",[str(BIN/"foreground"),"--socket",str(endpoint),"--mib","128","--touches","65536"],output,groups["foreground"])
        workers.append(foreground);foreground.await_ready()
        for index,donor in enumerate(("A","B")):
            settings={"mib":512,"hot-mib":32,"reuse-mib":512,"pages-per-tick":128,"seed":config["seed"]+index,
                      "pattern":"structured" if index==config["block"]%2 else "random"}
            worker=Worker(donor,donor_command(settings,53),output,groups[donor]);workers.append(worker);worker.await_ready()
        client=ScheduledClient(endpoint,output/"requests.csv",200,50,128,65536)
        client.start()
        if not client.ready.wait(60) or client.error:raise RuntimeError("client preparation failed")
        epoch=time.monotonic()+1
        for worker in workers:
            if worker.name!="foreground":worker.start_at(epoch)
        client.start_at(epoch)
        start,end=epoch+5,epoch+45
        clock=time.pthread_getcpuclockid(collector.ident) if collector else None
        before=None;after=None
        while time.monotonic()<epoch+50:
            now=time.monotonic()
            if before is None and now>=start:
                before={"t":now,"cpu":cpu_seconds(),"rss":resident_bytes(),"collector_cpu":time.clock_gettime(clock) if clock is not None else None}
            if after is None and now>=end:
                after={"t":now,"cpu":cpu_seconds(),"rss":resident_bytes(),"collector_cpu":time.clock_gettime(clock) if clock is not None else None}
            if collector and collector.error:raise RuntimeError(collector.error)
            time.sleep(.02)
        client.join(12)
        if client.is_alive() or client.error:raise RuntimeError("client did not finish correctly")
        outcome.update(epoch=epoch,start=before,end=after,service=client.summary(start,end),
                       harness_cpu_seconds=after["cpu"]-before["cpu"],harness_rss_growth_bytes=after["rss"]-before["rss"],
                       collector_thread_cpu_seconds=after["collector_cpu"]-before["collector_cpu"] if clock is not None else None,
                       measurement_seconds=after["t"]-before["t"])
        if outcome["service"]["failed_or_missed"]:outcome["adverse_outcomes"].append("foreground_failed_or_missed")
        if outcome["service"]["max_generator_lateness_seconds"]>.1:outcome["adverse_outcomes"].append("generator_lateness_exceeded_100ms")
        outcome["status"]="complete"
    except Exception as error:
        outcome["error"]=repr(error);(output/"stderr.log").write_text(traceback.format_exc())
    finally:
        for worker in reversed(workers):
            try:worker.stop()
            except Exception as error:outcome.setdefault("cleanup_errors",[]).append(repr(error))
        if collector:collector.stop()
        events=sorted([event for worker in workers for event in worker.events],key=lambda e:e.get("t",0))
        (output/"workload_events.jsonl").write_text("".join(json.dumps(event)+"\n" for event in events))
        for worker in workers:
            if worker.name!="foreground" and not any(e.get("event")=="verified" and e.get("ok") for e in worker.events):
                outcome["adverse_outcomes"].append("checksum_failure_"+worker.name)
        if outcome.get("start") and outcome.get("end"):
            rates={}
            for donor in ("A","B"):
                u0=progress_at(events,donor,outcome["start"]["t"]);u1=progress_at(events,donor,outcome["end"]["t"])
                rates[donor]=(u1-u0)/outcome["measurement_seconds"] if u0 is not None and u1 is not None else None
            outcome["progress_units_per_second"]=rates
        if trial:
            try:remove_groups(trial,groups)
            except Exception as error:outcome.setdefault("cleanup_errors",[]).append(repr(error))
        write_json(output/"outcome.json",outcome);print(json.dumps({"attempt":attempt,"status":outcome["status"],"error":outcome.get("error")}))
    return outcome

def main():
    parser=argparse.ArgumentParser();parser.add_argument("config");parser.add_argument("--cgroup-parent",required=True)
    args=parser.parse_args();outcome=execute(json.loads(Path(args.config).read_text()),args.cgroup_parent)
    return 0 if outcome["status"]=="complete" else 2

if __name__=="__main__":raise SystemExit(main())
