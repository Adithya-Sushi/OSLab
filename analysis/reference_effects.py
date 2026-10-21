import argparse
import csv
import json
from pathlib import Path
import statistics
from harness.common import ROOT,MIB,write_json
from .statistics import bootstrap_mean

def load_attempts(raw_root,matrix=None,purpose="discovery"):
    records=[]
    for directory in sorted(Path(raw_root).iterdir()):
        if not directory.is_dir() or not (directory/"outcome.json").exists():continue
        config=json.loads((directory/"config.json").read_text())
        if config.get("purpose")!=purpose:continue
        if matrix is not None and config.get("execution",{}).get("matrix")!=matrix:continue
        outcome=json.loads((directory/"outcome.json").read_text())
        records.append({"directory":directory,"config":config,"outcome":outcome})
    return records

def summarize(records):
    blocks={};incomplete=[];effects=[];invalid=[];failed=[]
    all_boots=[]
    for record in records:
        config,outcome=record["config"],record["outcome"]
        if outcome["status"]!="complete":failed.append({"attempt":outcome["attempt"],"error":outcome.get("error")});continue
        if outcome["technical_invalidity"]:
            invalid.append({"attempt":outcome["attempt"],"reasons":outcome["technical_invalidity"]});continue
        key=(config["regime"],config["block"])
        if config["arm"] in blocks.setdefault(key,{}):raise ValueError("duplicate arm; explicitly resolve repeated attempts before analysis")
        blocks[key][config["arm"]]=record
        all_boots.append(outcome["boot_id"])
    if len(all_boots)!=len(set(all_boots)):raise ValueError("independent trials share a boot ID")
    regimes={}
    for (regime,block),arms in sorted(blocks.items()):
        if set(arms)!={"none","A","B"}:
            incomplete.append({"regime":regime,"block":block,"present_arms":list(arms)});continue
        baseline=arms["none"]["outcome"]["delta_headroom_bytes"]
        gains={donor:arms[donor]["outcome"]["delta_headroom_bytes"]-baseline for donor in ("A","B")}
        donors=arms["A"]["config"]["donors"]
        if regime=="R2":
            better=next(d for d in ("A","B") if "reuse-after" not in donors[d])
        else:
            better=next(d for d in ("A","B") if donors[d]["pattern"]=="structured")
        other="B" if better=="A" else "A"
        row={"regime":regime,"block":block,"gain_A_mib":gains["A"]/MIB,"gain_B_mib":gains["B"]/MIB,
             "expected_better":better,"signed_gap_mib":(gains[better]-gains[other])/MIB,
             "no_action_delta_mib":baseline/MIB,"attempts":{arm:r["outcome"]["attempt"] for arm,r in arms.items()}}
        effects.append(row);regimes.setdefault(regime,[]).append(row)
    summary={}
    for regime,rows in regimes.items():
        result=bootstrap_mean([r["signed_gap_mib"] for r in rows])
        result.update(gain_A=bootstrap_mean([r["gain_A_mib"] for r in rows]),
                      gain_B=bootstrap_mean([r["gain_B_mib"] for r in rows]),
                      no_action_sd_mib=statistics.stdev([r["no_action_delta_mib"] for r in rows]) if len(rows)>1 else None)
        result["practical_8mib_gap"]=result["mean"]>=8
        result["interval_excludes_zero"]=result["ci95"][0]>0
        result["at_least_8_independent_blocks"]=len(rows)>=8
        summary[regime]=result
    return {"kind":"matched_reference_characterization","unit":"MiB","regimes":summary,"paired_effects":effects,
            "incomplete_blocks":incomplete,"technical_invalid_attempts":invalid,"failed_attempts":failed,
            "total_attempts":len(records),"adverse_attempts":[{"attempt":r["outcome"]["attempt"],"outcomes":r["outcome"]["adverse_outcomes"]}
                for r in records if r["outcome"]["adverse_outcomes"]],
            "checkpoint_A_passed":all(regime in summary and summary[regime]["practical_8mib_gap"] and summary[regime]["interval_excludes_zero"] and summary[regime]["at_least_8_independent_blocks"] for regime in ("R1","R2")),
            "limitations":["Bootstrap intervals resample independent matched seed blocks.",
                            "Reference contrasts are noisy; no exact donor ownership is inferred.",
                            "This characterization does not validate future-action predictions or controller superiority."]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--matrix",default="configs/discovery-matrix.json")
    parser.add_argument("--purpose",default="discovery")
    parser.add_argument("--output",default="results/derived/reference-summary.json")
    args=parser.parse_args()
    result=summarize(load_attempts(ROOT/"results/raw",args.matrix,args.purpose))
    write_json(ROOT/args.output,result)
    rows=[{k:v for k,v in row.items() if k!="attempts"} for row in result["paired_effects"]]
    if rows:
        with (ROOT/args.output).with_suffix(".csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:v for k,v in result.items() if k!="paired_effects"},indent=2))

if __name__=="__main__":main()
