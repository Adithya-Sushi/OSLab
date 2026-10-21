"""Export standalone scientific figures using matplotlib (analysis dependency)."""
import argparse
import csv
import json
from pathlib import Path
from harness.common import ROOT,MIB

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--summary",default="results/derived/reference-summary.json")
    args=parser.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"serif","font.size":9,"axes.spines.top":False,"axes.spines.right":False})
    result=json.loads((ROOT/args.summary).read_text())
    regimes=sorted(result["regimes"])
    if not regimes:raise SystemExit("no complete blocks to plot")
    fig,axis=plt.subplots(figsize=(6.8,2.8),layout="constrained")
    for i,regime in enumerate(regimes):
        data=result["regimes"][regime];mean=data["mean"];low,high=data["ci95"]
        axis.errorbar(i,mean,yerr=[[max(0,mean-low)],[max(0,high-mean)]],fmt="o",capsize=4,color="#194a6b")
        points=[r["signed_gap_mib"] for r in result["paired_effects"] if r["regime"]==regime]
        axis.scatter([i+.08]*len(points),points,s=12,color="#999999",alpha=.6)
    axis.axhline(0,color="black",lw=.7);axis.axhline(8,color="#a04a28",lw=.8,linestyle="--",label="Pilot target: 8 MiB")
    axis.set_xticks(range(len(regimes)),regimes);axis.set_ylabel("Delayed donor-benefit gap (MiB)")
    axis.legend(frameon=False,loc="best")
    output=ROOT/"results/figures";output.mkdir(exist_ok=True)
    fig.savefig(output/"donor-gap.pdf");fig.savefig(output/"donor-gap.png",dpi=220);plt.close(fig)
    # Representative timelines are chosen deterministically: the lowest seed block per regime.
    fig,axes=plt.subplots(1,len(regimes),figsize=(7,2.6),layout="constrained",squeeze=False)
    for axis,regime in zip(axes[0],regimes):
        block=min((r for r in result["paired_effects"] if r["regime"]==regime),key=lambda r:r["block"])
        for arm,attempt in block["attempts"].items():
            directory=ROOT/"results/raw"/attempt
            outcome=json.loads((directory/"outcome.json").read_text())
            with (directory/"telemetry.csv").open() as stream:rows=list(csv.DictReader(stream))
            anchor=outcome["action_t"];before=outcome["headroom_before_bytes"]
            selected=[r for r in rows if -20<=float(r["t"])-anchor<=20]
            axis.plot([float(r["t"])-anchor for r in selected],[(float(r["headroom_bytes"])-before)/MIB for r in selected],label=arm,lw=.9)
        axis.axvline(0,color="black",linestyle=":",lw=.7);axis.set_title(regime);axis.set_xlabel("Time from dispatch (s)")
    axes[0][0].set_ylabel("Headroom change (MiB)");axes[0][-1].legend(frameon=False,fontsize=8)
    fig.savefig(output/"headroom-timelines.pdf");fig.savefig(output/"headroom-timelines.png",dpi=220)

if __name__=="__main__":main()
