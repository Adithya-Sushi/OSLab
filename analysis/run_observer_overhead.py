"""Eight randomized fresh-boot pairs for the mandatory collector-overhead check."""
import json
import random
from harness.common import ROOT,write_json,command_version
from harness.run_matrix import job,wait_job,reboot
from .statistics import bootstrap_mean

def summarize():
    pairs={};runs=[]
    for directory in (ROOT/"results/overhead").iterdir():
        if not (directory/"outcome.json").exists():continue
        outcome=json.loads((directory/"outcome.json").read_text())
        runs.append(outcome)
        if outcome["status"]=="complete":pairs.setdefault(outcome["block"],{})[outcome["collect"]]=outcome
    differences=[]
    for block,arms in sorted(pairs.items()):
        if set(arms)!={True,False}:continue
        on,off=arms[True],arms[False]
        differences.append({"block":block,"extra_harness_cpu_seconds":on["harness_cpu_seconds"]-off["harness_cpu_seconds"],
                            "extra_harness_rss_growth_mib":(on["harness_rss_growth_bytes"]-off["harness_rss_growth_bytes"])/1048576,
                            "foreground_p99_ratio":on["service"]["p99_seconds"]/off["service"]["p99_seconds"],
                            "collector_thread_cpu_seconds":on["collector_thread_cpu_seconds"]})
    result={"kind":"matched_collector_overhead","runs":runs,"paired_differences":differences,
            "summary":{key:bootstrap_mean([r[key] for r in differences]) for key in
                       ("extra_harness_cpu_seconds","extra_harness_rss_growth_mib","foreground_p99_ratio","collector_thread_cpu_seconds")},
            "limitations":["Incremental harness costs include interactions with load generation and logging.",
                            "Direct collector thread CPU is read from its Linux pthread CPU clock.",
                            "This separate validity phase is not used to tune the frozen discovery/validation estimator."]}
    write_json(ROOT/"results/derived/observer-overhead.json",result)
    return result

def main():
    status=json.loads((ROOT/"results/derived/pilot-status.json").read_text())
    if status["state"] not in ("stopped_at_checkpoint_A","stopped_at_checkpoint_B"):
        raise SystemExit("complete the bounded research gates before the separate overhead phase")
    matrix_path=ROOT/"configs/overhead-matrix.json"
    if not matrix_path.exists():
        rng=random.Random(20261022);runs=[]
        for block in range(8):
            arms=[False,True];rng.shuffle(arms)
            runs.extend({"purpose":"observer_overhead","block":block,"seed":50000+block*2,"collect":collect} for collect in arms)
        write_json(matrix_path,{"randomization_seed":20261022,"measurement_seconds":40,"runs":runs})
    matrix=json.loads(matrix_path.read_text())
    progress_path=ROOT/"configs/overhead-matrix-progress.json"
    progress=json.loads(progress_path.read_text()) if progress_path.exists() else {"attempts":[]}
    for index,config in enumerate(matrix["runs"]):
        if any(a["index"]==index for a in progress["attempts"]):continue
        fresh=reboot()
        host_before=command_version(["vm_stat"])
        path=ROOT/"configs/generated"/f"overhead-{index:04d}.json";write_json(path,config)
        result=wait_job(job("overhead",config=str(path.relative_to(ROOT))),240)
        progress["attempts"].append({"index":index,"config":config,"result":result,"boot_id":fresh["boot_id"],
                                     "host_before":host_before,"host_after":command_version(["vm_stat"])})
        write_json(progress_path,progress)
        print(json.dumps({"index":index,"total":16,"collect":config["collect"],"result":result}),flush=True)
        if result.get("status")!="complete":raise SystemExit("overhead trial failed; preserve and inspect the attempt")
    print(json.dumps(summarize()["summary"],indent=2),flush=True)

if __name__=="__main__":main()
