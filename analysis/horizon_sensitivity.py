"""Descriptive horizon sensitivity using the same independent discovery blocks."""
import csv
from .reference_effects import load_attempts
from .statistics import mean_window,bootstrap_mean
from harness.common import ROOT,MIB,write_json

def main():
    blocks={}
    for record in load_attempts(ROOT/"results/raw","configs/discovery-matrix.json"):
        if record["outcome"]["status"]!="complete" or record["outcome"]["technical_invalidity"]:continue
        c=record["config"];blocks.setdefault((c["regime"],c["block"]),{})[c["arm"]]=record
    curves={};paired=[]
    for (regime,block),arms in sorted(blocks.items()):
        if set(arms)!={"none","A","B"}:continue
        series={}
        for arm,r in arms.items():
            with (r["directory"]/"telemetry.csv").open() as stream:
                series[arm]=[{"t":float(row["t"]),"headroom_bytes":float(row["headroom_bytes"])} for row in csv.DictReader(stream)]
        donors=arms["A"]["config"]["donors"]
        better=next(d for d in ("A","B") if ("reuse-after" not in donors[d] if regime=="R2" else donors[d]["pattern"]=="structured"))
        other="B" if better=="A" else "A"
        for horizon in (2,5,10,20,24):
            deltas={}
            for arm,r in arms.items():
                action=r["outcome"]["action_t"]
                deltas[arm]=mean_window(series[arm],action,action+horizon)-mean_window(series[arm],action-20,action)
            gap=(deltas[better]-deltas[other])/MIB
            curves.setdefault(regime,{}).setdefault(horizon,[]).append(gap)
            paired.append({"regime":regime,"block":block,"horizon_seconds":horizon,"signed_gap_mib":gap})
    result={"regimes":{regime:{str(t):bootstrap_mean(values) for t,values in horizons.items()} for regime,horizons in curves.items()},
            "paired_20s_minus_2s":{regime:bootstrap_mean([late-early for early,late in zip(horizons[2],horizons[20])]) for regime,horizons in curves.items()},
            "paired":paired,"interpretation":"Exploratory sensitivity of the same discovery blocks; horizons are correlated and do not create additional independent replicates. The 20-s endpoint remains primary. The 24-s endpoint avoids workload shutdown/checksum activity at 25 s after dispatch."}
    write_json(ROOT/"results/derived/horizon-sensitivity.json",result)
    print(result["regimes"])

if __name__=="__main__":main()
