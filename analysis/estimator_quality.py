"""Evaluate post-probe attribution against held-out matched reference effects.

This evaluates estimates available after an isolated probe's delayed horizon.
It does not relabel that observation as a prediction made before the probe.
"""
import argparse
import csv
import json
from pathlib import Path
import statistics
from harness.common import ROOT,MIB,write_json
from controller.estimator import LastProbeEstimator
from .reference_effects import load_attempts,summarize
from .statistics import bootstrap_mean,wilson

def evaluate(records):
    reference=summarize(records)
    by_attempt={r["outcome"]["attempt"]:r for r in records}
    predictions={};errors=[];rankings=[]
    for effect in reference["paired_effects"]:
        estimates={}
        for donor in ("A","B"):
            record=by_attempt[effect["attempts"][donor]]
            directory,outcome=record["directory"],record["outcome"]
            with (directory/"telemetry.csv").open() as stream:
                samples=[{k:float(v) if v else None for k,v in row.items()} for row in csv.DictReader(stream)]
            events=[json.loads(line) for line in (directory/"reclaim_events.jsonl").read_text().splitlines()]
            complete=[e for e in events if e["event"]=="completion"]
            if len(complete)!=1:
                estimates[donor]={"status":"UNKNOWN","reason":"missing_or_multiple_completions"};continue
            model=LastProbeEstimator()
            evidence=model.observe(donor,outcome["action_t"],samples,complete[0])
            estimate=model.predict(donor,evidence.measured_at)
            actual=effect[f"gain_{donor}_mib"]
            estimates[donor]=estimate
            row={"regime":effect["regime"],"block":effect["block"],"donor":donor,"attempt":outcome["attempt"],
                 "reference_mib":actual,"status":estimate["status"],"estimated_mib":None,"error_mib":None,
                 "heuristic_envelope_covers_reference":None,"false_positive":False,"false_negative":False}
            if estimate["status"]=="KNOWN":
                estimated=estimate["predicted_bytes"]/MIB;uncertainty=estimate["uncertainty_bytes"]/MIB
                row.update(estimated_mib=estimated,error_mib=estimated-actual,
                           heuristic_envelope_covers_reference=abs(estimated-actual)<=uncertainty,
                           false_positive=estimated>0 and actual<0,false_negative=estimated<=0 and actual>=8,
                           uncertainty_mib=uncertainty)
            errors.append(row)
        known=all(estimates.get(d,{}).get("status")=="KNOWN" for d in ("A","B"))
        predicted_best=("A" if estimates["A"]["predicted_bytes"]>estimates["B"]["predicted_bytes"] else "B") if known else None
        actual_best="A" if effect["gain_A_mib"]>effect["gain_B_mib"] else "B"
        rankings.append({"regime":effect["regime"],"block":effect["block"],"known":known,
                         "material_gap":abs(effect["gain_A_mib"]-effect["gain_B_mib"])>=8,
                         "predicted_best":predicted_best,"actual_best":actual_best,
                         "correct":predicted_best==actual_best if known else None})
    summary={}
    for regime in sorted(set(row["regime"] for row in errors)):
        selected=[row for row in errors if row["regime"]==regime]
        known=[row for row in selected if row["status"]=="KNOWN"]
        pairs=[row for row in rankings if row["regime"]==regime and row["material_gap"]]
        ranked=[row for row in pairs if row["known"]]
        correct=sum(row["correct"] for row in ranked)
        block_errors={}
        for row in known:block_errors.setdefault(row["block"],[]).append(abs(row["error_mib"]))
        summary[regime]={"n_probes":len(selected),"known_probes":len(known),
                         "probe_coverage":len(known)/len(selected) if selected else 0,
                         "absolute_error_mib":bootstrap_mean([statistics.mean(values) for values in block_errors.values()]),
                         "envelope_coverage":sum(row["heuristic_envelope_covers_reference"] for row in known)/len(known) if known else None,
                         "false_positive_count":sum(row["false_positive"] for row in known),
                         "false_negative_count":sum(row["false_negative"] for row in known),
                         "material_pairs":len(pairs),"ranked_pairs":len(ranked),"correct_rankings":correct,
                         "ranking_accuracy":correct/len(ranked) if ranked else None,"ranking_ci95":wilson(correct,len(ranked))}
    return {"kind":"post_probe_attribution_diagnostic","reference":reference,"regimes":summary,"probes":errors,"rankings":rankings,
            "future_action_prediction_validated":False,
            "limitations":["Estimates use telemetry after the measured probe; this is attribution validation, not advance prediction.",
                            "Comparing A and B uses separate matched reference arms, not sequential probes in one controller run.",
                            "The E1 envelope is a heuristic; empirical coverage is reported without calling it a confidence interval."]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--purpose",default="discovery")
    parser.add_argument("--matrix",default="configs/discovery-matrix.json")
    parser.add_argument("--output",default="results/derived/estimator-discovery-diagnostic.json")
    args=parser.parse_args()
    result=evaluate(load_attempts(ROOT/"results/raw",args.matrix,args.purpose))
    write_json(ROOT/args.output,result)
    print(json.dumps({"kind":result["kind"],"regimes":result["regimes"],"future_action_prediction_validated":False},indent=2))

if __name__=="__main__":main()
