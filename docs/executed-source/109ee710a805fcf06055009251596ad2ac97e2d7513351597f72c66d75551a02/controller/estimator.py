from dataclasses import dataclass
import math
from analysis.statistics import mean_window,linear_drift

@dataclass(frozen=True)
class Evidence:
    donor:str
    measured_at:float
    delayed_bytes:float
    immediate_bytes:float
    uncertainty_bytes:float
    wall_seconds:float
    interference:bool

class LastProbeEstimator:
    """E1 candidate. Uncertainty is a heuristic until held-out coverage is measured."""
    def __init__(self,horizon=20,stale_seconds=90,uncertainty_floor=2*1024*1024,interference_threshold=8*1024*1024):
        self.horizon=horizon;self.stale_seconds=stale_seconds
        self.floor=uncertainty_floor;self.interference_threshold=interference_threshold
        self.history={}

    def observe(self,donor,dispatch,samples,result):
        horizon=self.horizon
        slope,noise=linear_drift(samples,dispatch-horizon,dispatch)
        before=mean_window(samples,dispatch-horizon,dispatch)
        after=mean_window(samples,dispatch,dispatch+horizon)
        short=min(2,horizon)
        immediate=mean_window(samples,dispatch,dispatch+short)-mean_window(samples,dispatch-short,dispatch)-slope*short
        delayed=after-before-slope*horizon
        # This floor/residual envelope is not a statistical confidence interval.
        uncertainty=max(self.floor,2*noise)
        evidence=Evidence(donor,dispatch+horizon,delayed,immediate,uncertainty,
                          result["wall_seconds"],noise>self.interference_threshold)
        self.history[donor]=evidence
        return evidence

    def predict(self,donor,now):
        evidence=self.history.get(donor)
        if evidence is None:return {"status":"UNKNOWN","reason":"no_probe"}
        age=now-evidence.measured_at
        if age<0 or age>self.stale_seconds:return {"status":"UNKNOWN","reason":"stale_probe"}
        if evidence.interference:return {"status":"UNKNOWN","reason":"interference"}
        penalty=evidence.uncertainty_bytes*(1+age/self.stale_seconds)
        return {"status":"KNOWN","predicted_bytes":evidence.delayed_bytes,"lower_bytes":evidence.delayed_bytes-penalty,
                "immediate_bytes":evidence.immediate_bytes,"cost_seconds":evidence.wall_seconds,
                "age_seconds":age,"uncertainty_bytes":penalty}
