"""Repeat only predeclared technical-invalid validation arms; retain originals."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from harness.common import ROOT,source_manifest,write_json
from harness.run_matrix import reboot,job,wait_job
from .reference_effects import load_attempts
from .estimator_quality import evaluate
from .run_bounded_pilot import gate_b

FROZEN="9c97540f4796907fac1ba63434890fc63f04ccaa4fde0dcc9d83b07a38c6d7a5"

def main():
    while not (ROOT/"results/derived/post-pilot-checks.json").exists():time.sleep(2)
    subprocess.run([sys.executable,"-m","analysis.snapshot_source"],cwd=ROOT,check=True)
    agent=ROOT/"scripts/guest_agent.py"
    history=json.loads((ROOT/"docs/post-pilot-source-change.json").read_text())
    original=ROOT/"docs/executed-source"/FROZEN/"scripts/guest_agent.py"
    current=hashlib.sha256(agent.read_bytes()).hexdigest()
    if current not in (history["extended_agent_sha256"],hashlib.sha256(original.read_bytes()).hexdigest()):
        raise RuntimeError("guest dispatcher has independent edits; refusing to replace it")
    shutil.copy2(original,agent)
    if source_manifest()["sha256"]!=FROZEN:raise RuntimeError("frozen research runtime is not restored exactly")
    validation=json.loads((ROOT/"results/derived/estimator-validation.json").read_text())
    repeat_log=ROOT/"configs/validation-technical-repeats.json"
    log=json.loads(repeat_log.read_text()) if repeat_log.exists() else {"attempts":[]}
    matrix_path=ROOT/"configs/validation-matrix.json"
    matrix=json.loads(matrix_path.read_text())
    for invalid in validation["reference"]["technical_invalid_attempts"]:
        original_id=invalid["attempt"]
        if any(a["original_attempt"]==original_id and not a["technical_invalidity"] for a in log["attempts"]):continue
        if invalid["reasons"]!=["generator_schedule_overloaded"]:raise RuntimeError("unreviewed technical-invalidity reason")
        old=json.loads((ROOT/"results/raw"/original_id/"config.json").read_text())
        index=old["execution"]["index"]
        for ordinal in range(1,4):
            reboot()
            config=dict(matrix["runs"][index])
            config["execution"]={"matrix":"configs/validation-matrix.json","matrix_sha256":hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
                                 "index":index,"technical_repeat_of":original_id,"repeat_ordinal":ordinal,
                                 "reason":"Predeclared generator scheduling limit exceeded; outcome was retained and is technically invalid."}
            path=ROOT/"configs/generated"/f"validation-repeat-{index:04d}-{ordinal}.json";write_json(path,config)
            identifier=job("trial",config=str(path.relative_to(ROOT)))
            response=wait_job(identifier,240)
            if response.get("status")!="complete":raise RuntimeError("technical-repeat execution failed")
            outputs=(ROOT/"vm/outbox"/(identifier+".log")).read_text().splitlines()
            event=next(json.loads(line) for line in reversed(outputs) if line.startswith('{"attempt"'))
            outcome=json.loads((ROOT/"results/raw"/event["attempt"]/"outcome.json").read_text())
            record={"original_attempt":original_id,"new_attempt":event["attempt"],"request":identifier,
                    "technical_invalidity":outcome["technical_invalidity"],"adverse_outcomes":outcome["adverse_outcomes"],"source":FROZEN}
            log["attempts"].append(record);write_json(repeat_log,log);print(json.dumps(record),flush=True)
            if not outcome["technical_invalidity"]:break
        else:raise RuntimeError("three technical repeats did not restore a valid reference arm")
    result=evaluate(load_attempts(ROOT/"results/raw","configs/validation-matrix.json",purpose="validation"))
    write_json(ROOT/"results/derived/estimator-validation.json",result)
    protocol=json.loads((ROOT/"docs/validation-protocol.json").read_text())["criteria"]
    passed,reasons=gate_b(result,protocol)
    gates={"A_passed":True,"B_passed":passed,"B_reasons":reasons,"C_passed":False}
    write_json(ROOT/"configs/gates.json",gates)
    write_json(ROOT/"results/derived/pilot-status.json",{"state":"ready_for_controller_pilot" if passed else "stopped_at_checkpoint_B",
               "gates":gates,"reasons":reasons,"future_action_prediction_validated":False,"technical_repeats":len(log["attempts"])})
    write_json(ROOT/"results/derived/technical-repeats-status.json",{"state":"complete","attempts":len(log["attempts"]),"restored_runtime":FROZEN})

if __name__=="__main__":main()
