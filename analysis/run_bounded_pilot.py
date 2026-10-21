"""Continue the currently authorized pilot through its evidence gates.

This is an ordinary running experiment process, not a recurring automation.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from harness.common import ROOT,write_json
from .reference_effects import load_attempts,summarize
from .estimator_quality import evaluate

def gate_b(result,protocol):
    reasons=[]
    for regime in ("R1","R2","R3"):
        row=result["regimes"].get(regime)
        reference=result["reference"]["regimes"].get(regime)
        if not row or not reference or reference["n"]<8:
            reasons.append(regime+": fewer than eight complete held-out blocks");continue
        coverage=row["probe_coverage"]
        if regime in ("R1","R2"):
            if coverage<protocol["minimum_probe_coverage"]:reasons.append(regime+": insufficient known-estimate coverage")
            if row["ranking_accuracy"] is None or row["ranking_accuracy"]<protocol["minimum_ranking_accuracy"]:
                reasons.append(regime+": donor-ranking target not met")
        # Under interference, predictable abstention is acceptable. Unflagged,
        # badly biased estimates are not useful input to the proposed allocator.
        if regime=="R3" and coverage<=protocol["maximum_interference_known_coverage_when_abstaining"]:continue
        error=row["absolute_error_mib"]["mean"]
        if error is None or error>protocol["maximum_mean_absolute_error_mib"]:
            reasons.append(regime+": benefit error exceeds practical 8-MiB resolution")
        if row["envelope_coverage"] is None or row["envelope_coverage"]<protocol["minimum_heuristic_envelope_coverage"]:
            reasons.append(regime+": uncertainty envelope does not cover reference effects reliably")
    return not reasons,reasons

def main():
    progress=ROOT/"configs/discovery-matrix-progress.json"
    status=ROOT/"results/derived/pilot-status.json"
    while True:
        state=json.loads(progress.read_text()) if progress.exists() else {"attempts":[]}
        attempts=state["attempts"]
        if attempts and attempts[-1]["result"].get("status")!="complete":
            write_json(status,{"state":"execution_failure","phase":"discovery","attempt":attempts[-1]});return
        if len(attempts)==72:break
        time.sleep(2)
    reference=summarize(load_attempts(ROOT/"results/raw","configs/discovery-matrix.json"))
    write_json(ROOT/"results/derived/reference-summary.json",reference)
    gates={"A_passed":reference["checkpoint_A_passed"],"B_passed":False,"C_passed":False}
    write_json(ROOT/"configs/gates.json",gates)
    if not gates["A_passed"]:
        write_json(status,{"state":"stopped_at_checkpoint_A","reason":"Frozen discovery did not meet the practical characterization gate.","gates":gates});return
    write_json(status,{"state":"validating_post_probe_estimator","gates":gates})
    with (ROOT/"results/derived/validation-execution.log").open("a") as log:
        command=[sys.executable,"-m","harness.run_matrix","--matrix","configs/validation-matrix.json","--run"]
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    validation_progress=json.loads((ROOT/"configs/validation-matrix-progress.json").read_text())
    if len(validation_progress["attempts"])!=72 or any(a["result"].get("status")!="complete" for a in validation_progress["attempts"]):
        write_json(status,{"state":"execution_failure","phase":"validation","gates":gates});return
    result=evaluate(load_attempts(ROOT/"results/raw","configs/validation-matrix.json",purpose="validation"))
    write_json(ROOT/"results/derived/estimator-validation.json",result)
    protocol=json.loads((ROOT/"docs/validation-protocol.json").read_text())["criteria"]
    gates["B_passed"],reasons=gate_b(result,protocol)
    gates["B_reasons"]=reasons
    write_json(ROOT/"configs/gates.json",gates)
    write_json(status,{"state":"ready_for_controller_pilot" if gates["B_passed"] else "stopped_at_checkpoint_B",
                       "gates":gates,"reasons":reasons,"future_action_prediction_validated":False})
    print(json.dumps(json.loads(status.read_text()),indent=2),flush=True)

if __name__=="__main__":main()
