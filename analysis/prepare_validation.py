"""Prepare unseen reference blocks without changing the discovery matrix."""
import copy
from harness.common import ROOT,write_json
from harness.run_matrix import make_matrix

def main():
    destination=ROOT/"configs/validation-matrix.json"
    if destination.exists():raise SystemExit("validation matrix is already frozen")
    runs=copy.deepcopy(make_matrix(blocks=8,rate=200,donor_mib=512))
    for run in runs:
        run["purpose"]="validation";block=run["block"];run["block"]+=100
        for donor in run["donors"].values():donor["seed"]+=10000
        if run["regime"]=="R2":
            for donor in run["donors"].values():
                if "reuse-after" in donor:donor["reuse-after"]=[25.5,27,29,31][block%4]
        if run["regime"]=="R3":
            workload=run["donors"]["interference"]
            workload["extra-mib"]=[128,160,224,256][block%4]
            workload["allocate-after"]=[28,30,32,28][block%4]
            workload["release-after"]=workload["allocate-after"]+[8,10,12,14][block%4]
    write_json(destination,{"kind":"validation","randomization_seed":20261021,
                            "scope":"Held-out post-probe attribution and donor ranking; future policy decisions remain unvalidated.",
                            "frozen_estimator":{"name":"E1","horizon":20,"stale_seconds":90,"uncertainty_floor_mib":2,"interference_threshold_mib":8},
                            "runs":runs})
    print("frozen",len(runs),"held-out reference trials")

if __name__=="__main__":main()
