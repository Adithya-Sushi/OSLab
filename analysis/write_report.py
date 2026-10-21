import json
from pathlib import Path
from harness.common import ROOT,write_json

def main():
    reference=json.loads((ROOT/"results/derived/reference-summary.json").read_text())
    performance_path=ROOT/"results/derived/performance-summary.json"
    performance=json.loads(performance_path.read_text()) if performance_path.exists() else {}
    validation_path=ROOT/"results/derived/estimator-validation.json"
    validation=json.loads(validation_path.read_text()) if validation_path.exists() else None
    status_path=ROOT/"results/derived/pilot-status.json"
    status=json.loads(status_path.read_text()) if status_path.exists() else {"state":"discovery_running"}
    lines=["OSLab: Initial Experiment Report","="*32,"Adithya Sushil | 24BCI0286","21 October 2026, Asia/Kolkata","",
           "Research status: "+status["state"],"",
           "Environment: Debian 13 ARM64; Linux 6.12.113+deb13-arm64; 3 GiB RAM;",
           "two vCPUs; Apple Virtualization.framework; one 1-GiB logical lz4 zram device;",
           "no zswap or writeback. Host: Apple Silicon Mac, 16 GiB RAM.","",
           "All reported observations come from executed Linux guest workloads.",
           "Synthetic fixtures are used only for implementation verification.","",
           "Discovery phase","-"*15,f"Selected attempted trials: {reference['total_attempts']}",
           f"Complete matched seed blocks: {len(reference['paired_effects'])}",
           f"Failed attempts: {len(reference['failed_attempts'])}",
           f"Technical-invalid attempts: {len(reference['technical_invalid_attempts'])}",
           f"Attempts with adverse outcomes: {len(reference['adverse_attempts'])}",""]
    for regime,row in sorted(reference["regimes"].items()):
        interval=row["ci95"]
        lines.extend([f"{regime}: n={row['n']} independent matched blocks.",
                      f"  Mean prespecified donor-benefit gap: {row['mean']:.3f} MiB.",
                      f"  95% seed-block bootstrap interval: [{interval[0]:.3f}, {interval[1]:.3f}] MiB.",
                      f"  No-action headroom-change SD: {row['no_action_sd_mib']!r} MiB."])
    lines.extend(["","R1 compares structured versus random data; R2 compares a donor that",
                  "keeps its cold region unused with one that reuses it after dispatch;",
                  "R3 adds a separately controlled resident-memory allocation.","",
                  "Headroom is a 20-second time-weighted mean starting at request dispatch.",
                  "Each donor effect subtracts a matched no-action before/after contrast.",
                  "The A/B difference cancels the common no-action arm. Requested bytes are",
                  "control inputs and are not reported as measured freed bytes.","",
                  "Application outcomes","-"*20])
    runs=performance.get("runs",[])
    if runs:
        lines.extend([f"Post-dispatch offered foreground requests: {sum(r['offered'] for r in runs)}",
                      f"Failed/missed/incorrect replies: {sum(r['failed_or_missed'] for r in runs)}"])
        for regime,arms in sorted(performance["summary"].items()):
            for arm,row in arms.items():
                p99=row["p99_ms"]["mean"];cost=row["reclaim_wall_ms"]["mean"]
                lines.append(f"  {regime}/{arm}: mean run p99={p99:.3f} ms; mean actuator wall={cost:.3f} ms; n={row['n']}.")
    lines.extend(["","Estimator validation","-"*20])
    if validation:
        lines.append("Held-out reference attempts, including retained technical failures: "+str(validation["reference"]["total_attempts"]))
        lines.append("Usable trials in complete matched blocks: "+str(3*len(validation["reference"]["paired_effects"])))
        lines.append("Retained technical-invalid attempts: "+str(len(validation["reference"]["technical_invalid_attempts"])))
        for regime,row in sorted(validation["regimes"].items()):
            error=row["absolute_error_mib"]["mean"]
            lines.append(f"  {regime}: mean absolute error={error!r} MiB; ranking accuracy={row['ranking_accuracy']!r}; known coverage={row['probe_coverage']:.3f}; heuristic-envelope coverage={row['envelope_coverage']!r}.")
        lines.append("These estimates use observations after a probe. Advance prediction of")
        lines.append("that same probe or future controller superiority has not been established.")
    else:lines.append("Held-out validation has not completed in this report version.")
    lines.extend(["","Decision and remaining work","-"*27])
    for reason in status.get("reasons",[]):lines.append("  "+reason)
    if status["state"]=="stopped_at_checkpoint_A":
        lines.extend(["The characterization gate did not pass. The plan stops mechanism work",
                      "pending review/redesign; a full controller is not justified by these results."])
    elif status["state"]=="stopped_at_checkpoint_B":
        lines.extend(["Donor choice is useful in the tested regimes, but the baseline E1 estimator",
                      "does not meet the held-out usefulness/reliability gate. The plan stops the",
                      "mechanism claim pending estimator redesign. No policy-superiority claim",
                      "or strong-baseline improvement is made."])
    overhead_path=ROOT/"results/derived/observer-overhead.json"
    if overhead_path.exists():
        overhead=json.loads(overhead_path.read_text())
        lines.extend(["","Collector overhead validity study","-"*33,
                      f"Matched fresh-boot collector on/off pairs: {len(overhead['paired_differences'])}"])
        for key,row in overhead["summary"].items():
            lines.append(f"  {key}: mean={row['mean']!r}; 95% block-bootstrap interval={row['ci95']!r}; n={row['n']}.")
        lines.append("The collector's CPU clock is measured directly; incremental harness")
        lines.append("RSS/CPU and application latency are compared with a matched no-collector run.")
    else:lines.extend(["","Isolated collector-overhead validity measurements are still pending."])
    lines.extend(["","Active Senpai/DAMOS comparisons, SQLite validation, full confirmatory runs,",
                  "independent reproduction and final related-work",
                  "clearance remain pending. These have not been replaced by simulated results.","",
                  "Artifact verification","-"*21,
                  "Linux functional suite: 23 tests passed (saved guest log).",
                  "Portable native suite: 23 tests, one Linux-only skip (saved log).",
                  "Analysis pairing/error-handling checks: see analysis-tests-final.log.",
                  "Raw evidence: results/raw/<attempt>/; randomized order and host snapshots:",
                  "configs/*-matrix-progress.json; estimator decisions: estimator-validation.json.","",
                  "Calibration attempts are separately labeled and excluded from discovery.",
                  "No cgroup-owned physical zram bytes or macOS RAM return is inferred.",""])
    path=ROOT/"results/derived/EXPERIMENT_REPORT.txt";path.write_text("\n".join(lines));print(path)

if __name__=="__main__":main()
