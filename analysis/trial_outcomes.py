"""Summarize performance/cost alongside headroom, at independent-run level."""
import csv
import json
from pathlib import Path
import statistics
from harness.common import ROOT,write_json
from harness.load_generator import percentile
from .reference_effects import load_attempts
from .statistics import bootstrap_mean

def progress_at(events,worker,t):
    points=sorted((e["t"],e["units"]) for e in events if e.get("worker")==worker and "units" in e)
    for (t0,u0),(t1,u1) in zip(points,points[1:]):
        if t0<=t<=t1 and t1>t0:return u0+(u1-u0)*(t-t0)/(t1-t0)
    return None

def read_outcome(record):
    directory,config,outcome=record["directory"],record["config"],record["outcome"]
    if outcome["status"]!="complete":return None
    start=outcome["action_t"];end=start+config["horizon_seconds"]
    with (directory/"requests.csv").open() as stream:
        requests=[row for row in csv.DictReader(stream) if start<=float(row["scheduled"])<end]
    good=[float(row["latency_seconds"]) for row in requests if row["status"]=="ok"]
    events=[json.loads(line) for line in (directory/"workload_events.jsonl").read_text().splitlines()]
    rates={}
    for donor in ("A","B"):
        before,after=progress_at(events,donor,start),progress_at(events,donor,end)
        rates[donor]=(after-before)/(end-start) if before is not None and after is not None else None
    reclaim=[json.loads(line) for line in (directory/"reclaim_events.jsonl").read_text().splitlines()]
    complete=[row for row in reclaim if row["event"]=="completion"]
    return {"attempt":outcome["attempt"],"regime":config["regime"],"block":config["block"],"arm":config["arm"],
            "p99_ms":percentile(good,.99)*1000 if good else None,"p50_ms":percentile(good,.5)*1000 if good else None,
            "offered":len(requests),"failed_or_missed":len(requests)-len(good),"donor_progress_units_per_second":rates,
            "reclaim_wall_ms":sum(row["wall_seconds"] for row in complete)*1000,
            "reclaim_cpu_ms":sum(row["cpu_seconds"] for row in complete)*1000,
            "reclaim_errors":[row["errno"] for row in complete if row["errno"]],
            "adverse_outcomes":outcome["adverse_outcomes"],"technical_invalidity":outcome["technical_invalidity"]}

def main():
    records=load_attempts(ROOT/"results/raw","configs/discovery-matrix.json")
    rows=[row for record in records if (row:=read_outcome(record)) is not None]
    grouped={};paired=[]
    for row in rows:grouped.setdefault((row["regime"],row["block"]),{})[row["arm"]]=row
    for key,arms in sorted(grouped.items()):
        if set(arms)!={"none","A","B"}:continue
        baseline=arms["none"]
        for arm in ("A","B"):
            row=arms[arm]
            p99ratio=row["p99_ms"]/baseline["p99_ms"] if row["p99_ms"] and baseline["p99_ms"] else None
            ratios={d:row["donor_progress_units_per_second"][d]/baseline["donor_progress_units_per_second"][d]
                    if baseline["donor_progress_units_per_second"][d] and row["donor_progress_units_per_second"][d] is not None else None for d in ("A","B")}
            paired.append({"regime":key[0],"block":key[1],"arm":arm,"p99_ratio_to_no_action":p99ratio,"progress_ratios":ratios})
    summary={}
    for regime in sorted(set(row["regime"] for row in rows)):
        summary[regime]={}
        for arm in ("none","A","B"):
            selected=[row for row in rows if row["regime"]==regime and row["arm"]==arm]
            summary[regime][arm]={"n":len(selected),"p99_ms":bootstrap_mean([r["p99_ms"] for r in selected if r["p99_ms"] is not None]),
                                  "reclaim_wall_ms":bootstrap_mean([r["reclaim_wall_ms"] for r in selected]),
                                  "failed_or_missed":sum(r["failed_or_missed"] for r in selected),
                                  "offered":sum(r["offered"] for r in selected)}
    write_json(ROOT/"results/derived/performance-summary.json",{"runs":rows,"paired":paired,"summary":summary,
        "scope":"Reference-arm outcomes only; no coordinated policy or calibrated SLO claim.",
        "latency_note":"p99 uses completed correct replies; failed/missed requests are reported alongside it."})
    print(json.dumps(summary,indent=2))

if __name__=="__main__":main()
