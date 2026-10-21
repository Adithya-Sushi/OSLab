"""Derive actual-interval PSI and guest CPU use from preserved raw counters."""
import json
from harness.common import ROOT,MIB,write_json
from harness.parsers import keyed,pressure,mm_stat,pressure_fraction
from .reference_effects import load_attempts

def counter_at(points,t):
    points=[p for p in points if p[1] is not None]
    for (t0,v0),(t1,v1) in zip(points,points[1:]):
        if t0<=t<=t1 and t1>t0:
            if v1<v0:return None
            return v0+(v1-v0)*(t-t0)/(t1-t0)
    return None

def cpu_values(text):
    if not text:return None
    fields=text.splitlines()[0].split()
    if not fields or fields[0]!="cpu":return None
    values=list(map(int,fields[1:9]))
    if len(values)<5:return None
    return {"total":sum(values),"idle":values[3]+values[4]}

def main():
    rows=[]
    for record in load_attempts(ROOT/"results/raw","configs/discovery-matrix.json"):
        outcome,config=record["outcome"],record["config"]
        if outcome["status"]!="complete":continue
        start=outcome["action_t"];end=start+config["horizon_seconds"]
        raw=[json.loads(line) for line in (record["directory"]/"raw_counters.jsonl").read_text().splitlines()]
        memory_points={kind:[] for kind in ("some","full")};cpu_points={kind:[] for kind in ("total","idle")}
        for sample in raw:
            psi=pressure(sample["raw"]["pressure_memory"]) or {}
            cpu=cpu_values(sample["raw"]["stat"])
            for kind in memory_points:memory_points[kind].append((sample["t"],psi.get(kind,{}).get("total")))
            for kind in cpu_points:cpu_points[kind].append((sample["t"],cpu[kind] if cpu else None))
        stalls={}
        for kind,points in memory_points.items():
            begin,finish=counter_at(points,start),counter_at(points,end)
            stalls[kind]=pressure_fraction(begin,finish,end-start)
        begin={key:counter_at(points,start) for key,points in cpu_points.items()}
        finish={key:counter_at(points,end) for key,points in cpu_points.items()}
        busy=None
        if all(value is not None for value in [*begin.values(),*finish.values()]):
            total=finish["total"]-begin["total"];idle=finish["idle"]-begin["idle"]
            if total>0:busy=1-idle/total
        rows.append({"attempt":outcome["attempt"],"regime":config["regime"],"block":config["block"],"arm":config["arm"],
                     "memory_psi_fraction":stalls,"guest_cpu_busy_fraction":busy})
    write_json(ROOT/"results/derived/resource-signals.json",{"runs":rows,
        "method":"Cumulative counter changes over actual elapsed time; boundary interpolation, missing/reset counters remain missing.",
        "cpu_method":"Sum first eight /proc/stat CPU fields; idle includes iowait. Guest/guest_nice are not double-counted."})
    print("derived PSI/CPU outcomes for",len(rows),"trials")

if __name__=="__main__":main()
