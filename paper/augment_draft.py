"""Insert standalone result figures/tables, and order IEEE references by citation."""
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def number(value,digits=2):return "--" if value is None else f"{value:.{digits}f}"
def row(values):return " & ".join(map(str,values))+" "+chr(92)*2

def table(caption,label,headers,rows):
    return ("\\begin{table}[t]\n\\caption{"+caption+"}\n\\label{"+label+"}\n\\centering\\small\n"
            "\\begin{tabular}{@{}l"+"r"*(len(headers)-1)+"@{}}\n\\toprule\n"+row(headers)+"\n\\midrule\n"+
            "\n".join(row(values) for values in rows)+"\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")

def gap_figure(regimes):
    if not regimes:return ""
    data="x mean lo hi\n"+"\n".join(f"{i+1} {d['mean']:.6f} {max(0,d['mean']-d['ci95'][0]):.6f} {max(0,d['ci95'][1]-d['mean']):.6f}" for i,(name,d) in enumerate(sorted(regimes.items())))
    result=r"""\begin{figure}[t]
\centering
\begin{tikzpicture}
\begin{axis}[width=.97\columnwidth,height=1.7in,
  xlabel={Donor regime},ylabel={Delayed gap (MiB)},
  tick label style={font=\footnotesize},label style={font=\footnotesize},
  xtick={@@TICKS@@},xticklabels={@@LABELS@@},
  xmin=.5,xmax=@@XMAX@@,ymin=0,axis lines=left,ymajorgrids=true,grid style={gray!15}]
\addplot+[only marks,mark=*,black,error bars/.cd,y dir=both,y explicit]
table[x=x,y=mean,y error minus=lo,y error plus=hi] {
@@DATA@@
};
\addplot[gray,dashed,domain=.5:@@XMAX@@] {8};
\end{axis}
\end{tikzpicture}
\caption{Prespecified delayed donor contrast with 95\% seed-block bootstrap
intervals. The dashed line marks the initial 8-MiB practical target.}
\label{fig:gaps}
\end{figure}
"""
    return result.replace("@@TICKS@@",",".join(str(i+1) for i in range(len(regimes)))).replace("@@LABELS@@",",".join(sorted(regimes))).replace("@@XMAX@@",str(len(regimes)+.5)).replace("@@DATA@@",data)

def augment(tex,reference):
    tex=tex.replace(r"\usepackage[hidelinks]{hyperref}",r"\usepackage[hidelinks]{hyperref}"+"\n"+
                    r"\hypersetup{pdftitle={Estimating Reclaim Benefit Across Cgroups Sharing Compressed Swap},pdfauthor={Adithya Sushil},pdfsubject={Initial research draft, 21 October 2026},pdfkeywords={Linux,zram,cgroups,memory reclaim}}")
    inserted=gap_figure(reference["regimes"])
    sensitivity_path=ROOT/"results/derived/horizon-sensitivity.json"
    if sensitivity_path.exists():
        sensitivity=json.loads(sensitivity_path.read_text());r2=sensitivity["regimes"].get("R2")
        if r2:
            inserted+=(f"An exploratory sensitivity analysis reuses the same discovery blocks at 2, 5, 10, 20, and 24 s. In R2, the mean donor contrast is "
                       f"{number(r2['2']['mean'])} MiB at 2 s (95\\% interval [{number(r2['2']['ci95'][0])}, {number(r2['2']['ci95'][1])}]) and "
                       f"{number(r2['20']['mean'])} MiB at the primary 20-s endpoint. ")
            delta=sensitivity.get("paired_20s_minus_2s",{}).get("R2")
            if delta:
                inserted+=(f"The paired 20-s-minus-2-s difference is {number(delta['mean'])} MiB "
                           f"([{number(delta['ci95'][0])}, {number(delta['ci95'][1])}]). ")
            inserted+=("These correlated horizons do not supply additional independent replicates or replace the prespecified endpoint. Their intervals are descriptive and are not multiplicity-adjusted. The full sensitivity results are preserved in the artifact.\n\n")
    performance_path=ROOT/"results/derived/performance-summary.json"
    if performance_path.exists():
        performance=json.loads(performance_path.read_text())
        count=sum(r["offered"] for r in performance["runs"]);failures=sum(r["failed_or_missed"] for r in performance["runs"])
        inserted+=(f"The post-dispatch windows contain {count:,} scheduled foreground arrivals and {failures:,} failed, missed, or incorrect replies. "
                   "Table~\\ref{tab:latency} reports the mean of independent-run p99 values. These reference arms do not establish a calibrated service-protection guarantee.\n\n")
        rows=[]
        for regime,arms in sorted(performance["summary"].items()):
            rows.append([regime,*[number(arms[arm]["p99_ms"]["mean"]) for arm in ("none","A","B")]])
        inserted+=table("Mean Run-Level Foreground p99, in Milliseconds","tab:latency",["Regime","No action","Reclaim A","Reclaim B"],rows)
    validation_path=ROOT/"results/derived/estimator-validation.json"
    if validation_path.exists():
        validation=json.loads(validation_path.read_text())
        gates=json.loads((ROOT/"configs/gates.json").read_text())
        count=validation["reference"]["total_attempts"]
        valid_count=3*len(validation["reference"]["paired_effects"])
        invalid_count=len(validation["reference"]["technical_invalid_attempts"])
        inserted+=("\\subsection{Held-Out Post-Probe Attribution}\n"
                   f"A separate frozen phase contains {count} held-out reference attempts, yielding {valid_count} usable trials in complete matched blocks, using new seeds, later reuse timings, and different interference allocations. "
                   "E1 is evaluated after each probe's horizon against matched reference effects; held-out references are never estimator inputs. "
                   "This evaluates attribution of an observed probe, not advance prediction of that intervention.\n\n")
        rows=[]
        for regime,data in sorted(validation["regimes"].items()):
            rows.append([regime,number(data["absolute_error_mib"]["mean"]),number(100*data["ranking_accuracy"],1) if data["ranking_accuracy"] is not None else "--",
                         number(100*data["envelope_coverage"],1) if data["envelope_coverage"] is not None else "--"])
        inserted+=table("Held-Out E1 Attribution Diagnostics","tab:estimator",["Regime","MAE (MiB)","Rank (\\%)","Envelope (\\%)"],rows)
        inserted+=("MAE is mean absolute attribution error. Ranking uses material donor differences of at least 8 MiB. Envelope coverage is the fraction of "
                   "reference effects inside E1's heuristic uncertainty envelope; it is not a calibrated confidence level. Errors are resampled by matched seed block. "
                   "The engineering protocol, frozen before validation, requires useful coverage, at least 80\\% ranking accuracy, and either predictable abstention "
                   "under interference or mean error no greater than the 8-MiB practical resolution with at least 80\\% heuristic-envelope coverage.\n\n")
        for regime,data in sorted(validation["regimes"].items()):
            interval=data["absolute_error_mib"]["ci95"]
            rank_interval=data["ranking_ci95"]
            inserted+=(f"For {regime}, the 95\\% block-bootstrap MAE interval is [{number(interval[0])}, {number(interval[1])}] MiB; "
                       f"known-estimate coverage is {number(100*data['probe_coverage'],1)}\\%. ")
            if rank_interval:
                inserted+=(f"There are {data['correct_rankings']} correct rankings among {data['ranked_pairs']} ranked material pairs "
                           f"(95\\% Wilson interval [{number(100*rank_interval[0],1)}, {number(100*rank_interval[1],1)}]\\%). ")
        inserted+="\n\n"
        if not gates.get("B_passed"):
            inserted+=("The baseline candidate does not meet Checkpoint B. Its interference bias demonstrates why a useful donor ranking can coexist with an "
                       "unusable benefit estimate. Unrelated memory activity must be accounted for, or the estimator must abstain reliably. Coordinated-policy "
                       "evaluation is therefore deferred pending a declared estimator redesign. This finding does not rule out better estimators.\n\n")
        if invalid_count:
            inserted+=(f"The execution record retains {invalid_count} technical-invalid attempts exceeding the predeclared 100-ms generator lateness limit. "
                       "Only those arms are repeated, with the exact frozen source, settings and seeds; adverse outcomes are not grounds for repetition.\n\n")
        abstract_addition=f"A separate held-out attribution study supplies {valid_count} usable trials. "
        if not gates.get("B_passed"):abstract_addition+="Its attribution error under unrelated memory activity prevents advancement to coordinated-policy evaluation. "
        tex=tex.replace("These observations characterize the measurement problem.",abstract_addition+"These observations characterize the measurement problem.")
        tex=tex.replace("The next estimator experiment must freeze its parameters and use new seed\nblocks and unseen access patterns.",
                        "Follow-up estimator experiments must address the observed attribution failure,\nfreeze revised parameters, and use fresh seeds and access patterns.")
        if not gates.get("B_passed"):
            tex=tex.replace(r"\section*{Artifact Availability}",
                "The held-out baseline fails the usefulness and reliability gate. The next mechanism step is a declared estimator redesign that separates intervention benefit from unrelated memory activity, followed by fresh validation.\n\n"+r"\section*{Artifact Availability}")
    overhead_path=ROOT/"results/derived/observer-overhead.json"
    if overhead_path.exists():
        overhead=json.loads(overhead_path.read_text());metrics=overhead["summary"]
        cpu=metrics["collector_thread_cpu_seconds"]
        rss=metrics["extra_harness_rss_growth_mib"]
        latency=metrics["foreground_p99_ratio"]
        inserted+=("\\subsection{Collector Overhead}\n"
                   f"A separate validity study uses {len(overhead['paired_differences'])} randomized fresh-boot on/off pairs with the same workloads and a 40-s measurement interval. "
                   f"The collector consumes a mean {number(cpu['mean']*1000)} ms of thread CPU per interval "
                   f"(95\\% block-bootstrap interval [{number(cpu['ci95'][0]*1000)}, {number(cpu['ci95'][1]*1000)}] ms). "
                   f"Incremental harness RSS growth is {number(rss['mean'])} MiB "
                   f"([{number(rss['ci95'][0])}, {number(rss['ci95'][1])}]); the mean foreground p99 on/off ratio is {number(latency['mean'],3)} "
                   f"([{number(latency['ci95'][0],3)}, {number(latency['ci95'][1],3)}]). "
                   "Thread CPU is read from the collector's Linux pthread CPU clock. Matched harness differences include interactions with client logging and scheduling. "
                   "This validity phase does not tune the frozen estimator.\n\n")
        tex=tex.replace("isolated observer overhead, and other\narrival/access patterns.","other arrival/access patterns, and overhead sensitivity under stronger\npressure.")
        tex=tex.replace("The current harness process CPU counter includes client and\norchestration work, so it does not isolate collector overhead.",
                        "The primary harness CPU counter includes client and orchestration work; the\nseparate on/off study and thread clock isolate the collector's incremental cost.")
        inserted+=("The observer study uses a dispatcher-only extension recorded as a separate source version. The exact original research runtime is restored for technical repeats. All executed versions are archived; donor, foreground, collector, and estimator implementations are unchanged across these phases.\n\n")
    tex=tex.replace("Two VMs on one host do not constitute independent\nhardware.",
                    "Two VMs on one host do not constitute independent hardware. Host memory\nsnapshots are retained, while the host CPU-load query was unavailable under\nthe execution permissions; host interference is not fully controlled.")
    marker=r"\section{Remaining Validation and Threats to Validity}"
    tex=tex.replace(marker,inserted+"\n"+marker)
    # IEEE citations must be numbered in first-appearance order.
    start=tex.index(r"\begin{thebibliography}")
    end=tex.index(r"\end{thebibliography}",start)
    body=tex[:start];bibliography=tex[start:end]
    header=bibliography.split("\n",1)[0]
    entries={match.group(1):match.group(0).strip() for match in re.finditer(r"\\bibitem\{([^}]+)\}.*?(?=\\bibitem|\Z)",bibliography,flags=re.S)}
    order=[]
    for group in re.findall(r"\\cite\{([^}]+)\}",body):
        for key in group.split(","):
            if key not in order:order.append(key)
    if set(order)!=set(entries):raise ValueError("uncited or undefined bibliography keys")
    tex=body+header+"\n"+"\n".join(entries[key] for key in order)+"\n"+tex[end:]
    if "@@" in tex:raise ValueError("unresolved manuscript placeholder")
    return tex
