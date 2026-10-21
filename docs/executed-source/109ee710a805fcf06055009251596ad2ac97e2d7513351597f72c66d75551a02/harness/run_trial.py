import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
import uuid
from .actuator import Actuator
from .check_environment import inspect
from .collector import Collector
from .common import ROOT, BIN, MIB, boot_id, read_text, write_json
from .launch import Worker, prepare_groups, remove_groups
from .load_generator import ScheduledClient
from analysis.statistics import mean_window
from controller.budget import Budget
from controller.estimator import LastProbeEstimator
from controller.policies import Policy

def donor_command(settings, duration):
    options={"mib":512,"hot-mib":32,"seed":1,"pattern":"structured","pages-per-tick":32,
             "reuse-after":999999,"reuse-mib":512,"duration":duration,"tick-seconds":0.01}
    options.update(settings)
    return [str(BIN/"donor"),"--wait-start",*[str(value) for key,value in options.items() for value in ("--"+key,value)]]

def validate_config(config):
    if config.get("arm","none") not in ("none","A","B"):raise ValueError("unknown reference arm")
    if config.get("purpose") not in ("calibration","discovery","validation","policy","integration"):
        raise ValueError("explicit experiment purpose is required")
    if config.get("pre_seconds",20)<20 or config.get("horizon_seconds",20)<20:
        raise ValueError("research windows must be at least 20 seconds")
    if config.get("request_bytes",32*MIB)!=32*MIB:raise ValueError("initial pilot has a fixed 32 MiB dose")
    if config.get("policy") not in (None,"reference"):
        gate=json.loads((ROOT/"configs/gates.json").read_text())
        if not gate.get("A_passed") or not gate.get("B_passed"):
            raise ValueError("policy experiments require documented Checkpoints A and B")
        for field in ("foreground_p99_ceiling_seconds","donor_progress_floors","wall_cap_seconds","cost_floor_seconds"):
            if field not in config:raise ValueError("calibrated policy threshold missing: "+field)

def execute(config, parent, output_root=None):
    validate_config(config)
    attempt=f"{time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())}-{uuid.uuid4().hex[:8]}"
    output=Path(output_root or ROOT/"results/raw")/attempt;output.mkdir(parents=True)
    write_json(output/"config.json",config)
    outcome={"attempt":attempt,"status":"failed","technical_invalidity":[],"adverse_outcomes":[],"purpose":config["purpose"]}
    workers=[];collector=None;actuator=None;client=None;trial=None;groups={};completions=[];decisions=[]
    try:
        env=inspect(parent,strict=True);write_json(output/"manifest.json",{"environment":env,"config":config,"attempt":attempt})
        if not env["eligible"]:raise RuntimeError("; ".join(env["failures"]))
        if not Path("/etc/oslab-research-vm").exists():raise RuntimeError("dedicated guest marker missing")
        last=ROOT/"vm/last-experiment-boot.json"
        if last.exists() and json.loads(last.read_text()).get("boot_id")==boot_id():
            raise RuntimeError("fresh guest reboot required between independent trials")
        for pool in env["zram"]:
            # mkswap writes a one-page swap header into an otherwise empty zram device.
            if pool["mm_stat"] and int(pool["mm_stat"].split()[0])>env["page_size"]:
                raise RuntimeError("zram store must be empty at trial start")
        if any(device["used_bytes"] for device in env["swaps"]):
            raise RuntimeError("logical swap usage must be zero at trial start")
        fg=config.get("foreground",{});fg_mib=fg.get("mib",128);touches=fg.get("touches",256)
        donor_settings=config.get("donors",{})
        max_donor=max([int(s.get("mib",512)) for s in donor_settings.values()]+[512])
        trial,groups=prepare_groups(parent,"trial-"+attempt,fg_mib,max_donor)
        outcome["group_settings"]={name:{key:read_text(group/key) for key in ("memory.max","memory.low","memory.swap.max","memory.oom.group")} for name,group in groups.items()}
        warmup=config.get("warmup_seconds",5);pre=config.get("pre_seconds",20)
        horizon=config.get("horizon_seconds",20);recovery=config.get("recovery_seconds",5)
        policy_mode=config.get("policy") not in (None,"reference")
        total=warmup+pre+(config.get("policy_seconds",200) if policy_mode else horizon)+recovery
        write_json(last,{"boot_id":boot_id(),"attempt":attempt})
        collector=Collector(output,{"parent":trial,**groups},config.get("poll_seconds",.25));collector.start()
        socket=Path("/tmp")/("oslab-"+uuid.uuid4().hex[:12]+".sock")
        foreground=Worker("foreground",[str(BIN/"foreground"),"--socket",str(socket),"--mib",str(fg_mib),"--touches",str(touches)],output,groups["foreground"])
        workers.append(foreground);foreground.await_ready()
        for donor,settings in donor_settings.items():
            if donor not in ("A","B","interference"):raise ValueError("unregistered donor")
            worker=Worker(donor,donor_command(settings,total+3),output,groups[donor]);workers.append(worker);worker.await_ready()
        # Scripted phases and workload labels remain in config/evaluation files.
        # The policy receives counters, progress and prior probe evidence only.
        client=ScheduledClient(socket,output/"requests.csv",fg.get("rate",200),total,fg_mib,touches,
                               fg.get("max_outstanding",64),fg.get("timeout_seconds",2))
        client.start()
        if not client.ready.wait(60) or client.error:raise RuntimeError("load generator preparation failed: "+str(client.error))
        epoch=time.monotonic()+1.0
        for worker in workers:
            if worker.name!="foreground":worker.start_at(epoch)
        client.start_at(epoch)
        anchor=epoch+warmup+pre;end=epoch+total
        actuator=Actuator(trial,output,config.get("swappiness_max",False))
        outcome.update(epoch=epoch,nominal_action_t=anchor,boot_id=boot_id())
        budget=Budget(wall_cap=config.get("wall_cap_seconds",2))
        estimator=LastProbeEstimator(horizon=horizon)
        policy=Policy(config.get("policy","none") if policy_mode else "none",estimator,
                      config.get("cost_floor_seconds",.001))
        dispatched=False;pending=None;last_decision=0;state="OBSERVE"
        while time.monotonic()<end:
            now=time.monotonic()
            result=actuator.poll(config.get("actuator_timeout_seconds",5))
            if result:
                completions.append(result)
                if policy_mode:budget.complete(result)
                if pending:pending["result"]=result
                if result["errno"]:outcome["adverse_outcomes"].append("reclaim_errno_"+str(result["errno"]))
            if actuator.overdue:
                budget.overdue();state="STOP"
                if "overdue_reclaim" not in outcome["adverse_outcomes"]:outcome["adverse_outcomes"].append("overdue_reclaim")
            if collector.error:raise RuntimeError("collector failure: "+collector.error)
            if not policy_mode and not dispatched and now>=anchor:
                if config["arm"]!="none":
                    event=actuator.dispatch(config["arm"],32*MIB);outcome["action_t"]=event["t"]
                else:outcome["action_t"]=anchor
                dispatched=True
            if policy_mode:
                if pending and now>=pending["t"]+horizon and pending.get("result") and collector.samples[-1]["t"]>=pending["t"]+horizon:
                    try:
                        evidence=estimator.observe(pending["donor"],pending["t"],collector.samples,pending["result"])
                        decisions.append({"event":"evidence","t":now,**asdict(evidence)})
                    except ValueError as error:
                        decisions.append({"event":"abstain","t":now,"reason":str(error)})
                    pending=None;state="SELECT"
                if now>=anchor and now-last_decision>=1 and pending is None and not actuator.current and not budget.stopped:
                    last_decision=now
                    latest=collector.samples[-1] if collector.samples else {}
                    stats=client.summary(now-20,now)
                    # Until a full service window exists, continue observing.
                    healthy=stats["offered"]>=100 and stats["failed_or_missed"]==0 and stats["p99_seconds"] is not None and stats["p99_seconds"]<=config["foreground_p99_ceiling_seconds"]
                    eligible={}
                    for donor in ("A","B"):
                        events=[e for w in workers if w.name==donor for e in w.events if e.get("event")=="progress" and now-20<=e["t"]<=now]
                        rate=(events[-1]["units"]-events[0]["units"])/(events[-1]["t"]-events[0]["t"]) if len(events)>1 else None
                        eligible[donor]=healthy and rate is not None and rate>=config["donor_progress_floors"][donor]
                    selected,reason=policy.choose(now,latest.get("groups",{}),eligible)
                    decision={"event":"decision","t":now,"state":state,"donor":selected,"reason":reason,
                              "eligible":eligible,"service":stats,"budget":budget.snapshot(),
                              "predictions":{d:estimator.predict(d,now) for d in ("A","B")}}
                    if selected and now+horizon<=end-recovery and budget.admit(32*MIB):
                        pending=actuator.dispatch(selected,32*MIB);state="WAIT_FOR_EFFECT"
                    else:state="COOLDOWN"
                    decisions.append(decision)
            time.sleep(.02)
        outcome["measurement_end_t"]=end-recovery
        # Include a final reply if one arrived at the end of the measurement.
        result=actuator.poll()
        if result:completions.append(result)
        client.join(timeout=fg.get("timeout_seconds",2)+10)
        if client.is_alive() or client.error:raise RuntimeError("load generator did not finish correctly: "+str(client.error))
        outcome["service"]=client.summary(epoch+warmup,end-recovery)
        maximum_lateness=outcome["service"]["max_generator_lateness_seconds"] or 0
        if maximum_lateness>config.get("generator_lateness_limit_seconds",.1):
            outcome["technical_invalidity"].append("generator_schedule_overloaded")
        if outcome["service"]["failed_or_missed"]:outcome["adverse_outcomes"].append("foreground_failed_or_missed_requests")
        if not policy_mode:
            action=outcome["action_t"]
            before=mean_window(collector.samples,action-pre,action)
            after=mean_window(collector.samples,action,action+horizon)
            outcome.update(headroom_before_bytes=before,headroom_after_bytes=after,delta_headroom_bytes=after-before)
        outcome["budget"]=budget.snapshot()
        outcome["status"]="complete"
    except Exception as error:
        outcome["error"]=repr(error)
        (output/"stderr.log").write_text(traceback.format_exc())
    finally:
        if actuator:
            try:actuator.close()
            except Exception as error:outcome["actuator_cleanup_error"]=repr(error)
        for worker in reversed(workers):
            try:worker.stop()
            except Exception as error:outcome.setdefault("cleanup_errors",[]).append(repr(error))
        if collector:
            collector.stop()
            if collector.error:outcome["technical_invalidity"].append("collector_failure")
        events=sorted((event for worker in workers for event in worker.events),key=lambda e:e.get("t",0))
        with (output/"workload_events.jsonl").open("w") as stream:
            for event in events:stream.write(json.dumps(event)+"\n")
        with (output/"decisions.jsonl").open("w") as stream:
            for event in decisions:stream.write(json.dumps(event)+"\n")
        for worker in workers:
            if worker.error or worker.process.returncode not in (0,None):
                outcome["adverse_outcomes"].append(f"worker_{worker.name}_exit_{worker.process.returncode}")
            if worker.name!="foreground" and not any(e.get("event")=="verified" and e.get("ok") for e in worker.events):
                outcome["adverse_outcomes"].append("missing_or_failed_checksum_"+worker.name)
        if collector and collector.samples:
            final=collector.samples[-1]
            outcome["final_telemetry"]=final
            for name,value in final.get("groups",{}).items():
                if (value.get("events") or {}).get("oom_kill",0):outcome["adverse_outcomes"].append("oom_kill_"+name)
        if trial:
            try:remove_groups(trial,groups)
            except Exception as error:outcome.setdefault("cleanup_errors",[]).append(repr(error))
        if outcome.get("cleanup_errors"):outcome["technical_invalidity"].append("cleanup_incomplete")
        write_json(output/"outcome.json",outcome)
        (output/"stdout.log").write_text(json.dumps({"attempt":attempt,"status":outcome["status"]})+"\n")
        print(json.dumps({"attempt":attempt,"status":outcome["status"],"output":str(output),"error":outcome.get("error")}))
    return outcome

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("config");parser.add_argument("--cgroup-parent",required=True)
    parser.add_argument("--output-root")
    args=parser.parse_args()
    outcome=execute(json.loads(Path(args.config).read_text()),args.cgroup_parent,args.output_root)
    return 0 if outcome["status"]=="complete" else 2

if __name__=="__main__":raise SystemExit(main())
