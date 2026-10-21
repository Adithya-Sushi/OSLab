"""Audit executed trial provenance and protocol completeness before delivery."""
import csv
import hashlib
import json
from pathlib import Path
from harness.common import ROOT,write_json

def digest(path):
    with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()

def main():
    findings=[];runs=[];boots=[];sources={}
    for directory in sorted((ROOT/"results/raw").iterdir()):
        if not directory.is_dir() or not (directory/"outcome.json").exists():continue
        config=json.loads((directory/"config.json").read_text());outcome=json.loads((directory/"outcome.json").read_text())
        if config.get("purpose") not in ("discovery","validation"):continue
        attempt=outcome["attempt"]
        record={"attempt":attempt,"purpose":config["purpose"],"regime":config["regime"],"block":config["block"],"arm":config["arm"],"findings":[]}
        required=("manifest.json","config.json","telemetry.csv","raw_counters.jsonl","requests.csv","workload_events.jsonl","reclaim_events.jsonl","decisions.jsonl","outcome.json","stdout.log","stderr.log")
        # stderr.log is created only on a runner exception; worker stderr files exist in clean runs.
        for name in required:
            if name=="stderr.log" and outcome["status"]=="complete":continue
            if not (directory/name).exists():record["findings"].append("missing "+name)
        manifest=json.loads((directory/"manifest.json").read_text())
        source=manifest["environment"]["source"];sources[source["sha256"]]=sources.get(source["sha256"],0)+1
        for relative,expected in source["files"].items():
            file=ROOT/relative
            if not file.exists() or digest(file)!=expected:
                snapshot=ROOT/"docs/executed-source"/source["sha256"]/relative
                if not snapshot.exists() or digest(snapshot)!=expected:
                    record["findings"].append("executed source is missing from current tree and snapshot: "+relative)
        execution=config.get("execution",{})
        if execution:
            matrix_path=ROOT/execution["matrix"]
            if digest(matrix_path)!=execution["matrix_sha256"]:record["findings"].append("matrix hash mismatch")
            expected=json.loads(matrix_path.read_text())["runs"][execution["index"]]
            actual={key:value for key,value in config.items() if key!="execution"}
            if actual!=expected:record["findings"].append("trial configuration differs from frozen execution list")
        if outcome.get("boot_id"):boots.append(outcome["boot_id"])
        if outcome["status"]=="complete":
            with (directory/"requests.csv").open() as stream:requests=list(csv.DictReader(stream))
            duration=sum(config.get(key,default) for key,default in (("warmup_seconds",5),("pre_seconds",20),("horizon_seconds",20),("recovery_seconds",5)))
            expected_count=int(duration*config["foreground"]["rate"])
            ids=sorted(int(row["id"]) for row in requests)
            if ids!=list(range(expected_count)):record["findings"].append("arrival IDs are missing, duplicated or unexpected")
            for row in requests:
                if row["completion"] and row["latency_seconds"]:
                    if abs(float(row["latency_seconds"])-(float(row["completion"])-float(row["scheduled"])))>1e-6:
                        record["findings"].append("latency omits scheduled-arrival time");break
            events=[json.loads(line) for line in (directory/"reclaim_events.jsonl").read_text().splitlines()]
            dispatches=[event for event in events if event["event"]=="dispatch"]
            if len(dispatches)!=(0 if config["arm"]=="none" else 1):record["findings"].append("unexpected proactive-action count")
            if any(event["donor"]!=config["arm"] or event["requested_bytes"]!=33554432 for event in dispatches):
                record["findings"].append("actuator dose or target differs from frozen arm")
            previous=None;count=0
            with (directory/"telemetry.csv").open() as stream:
                for row in csv.DictReader(stream):
                    current=float(row["t"]);count+=1
                    if previous is not None and current<=previous:record["findings"].append("nonmonotonic telemetry");break
                    previous=current
            record.update(requests=len(requests),telemetry_samples=count,adverse_outcomes=outcome["adverse_outcomes"],technical_invalidity=outcome["technical_invalidity"])
        runs.append(record)
        findings.extend({"attempt":attempt,"finding":message} for message in record["findings"])
    primary_boots=len(set(boots));overhead_runs=[]
    for directory in sorted((ROOT/"results/overhead").glob("*")):
        if not (directory/"outcome.json").exists():continue
        outcome=json.loads((directory/"outcome.json").read_text())
        manifest=json.loads((directory/"manifest.json").read_text())
        source=manifest["source"];sources[source["sha256"]]=sources.get(source["sha256"],0)+1
        for relative,expected in source["files"].items():
            current=ROOT/relative;snapshot=ROOT/"docs/executed-source"/source["sha256"]/relative
            if not ((current.exists() and digest(current)==expected) or (snapshot.exists() and digest(snapshot)==expected)):
                findings.append({"attempt":outcome["attempt"],"finding":"overhead executed source missing: "+relative})
        if outcome["status"]!="complete" or outcome.get("cleanup_errors"):
            findings.append({"attempt":outcome["attempt"],"finding":"overhead attempt is incomplete or cleanup failed"})
        if outcome.get("boot_id"):boots.append(outcome["boot_id"])
        overhead_runs.append({"attempt":outcome["attempt"],"block":outcome["block"],"collect":outcome["collect"],"adverse_outcomes":outcome["adverse_outcomes"]})
    if len(boots)!=len(set(boots)):findings.append({"finding":"fresh-boot identifiers reused across independent research/overhead attempts"})
    result={"valid":not findings,"research_attempts":len(runs),"overhead_attempts":len(overhead_runs),"distinct_primary_boot_ids":primary_boots,
            "distinct_boot_ids":len(set(boots)),"runtime_source_hashes":sources,"overhead_runs":overhead_runs,
            "findings":findings,"runs":runs,"scope":"Protocol/provenance audit; it does not certify hypothesis truth or estimator novelty."}
    write_json(ROOT/"results/derived/artifact-verification.json",result)
    print(json.dumps({key:value for key,value in result.items() if key!="runs"},indent=2))
    return 0 if result["valid"] else 2

if __name__=="__main__":raise SystemExit(main())
