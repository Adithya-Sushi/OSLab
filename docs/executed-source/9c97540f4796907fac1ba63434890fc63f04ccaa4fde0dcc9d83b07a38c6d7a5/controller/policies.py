class Policy:
    NAMES=("none","round_robin","coldness","immediate","delayed")
    def __init__(self,name,estimator,cost_floor=0.001,reprobe_seconds=60):
        if name not in self.NAMES:raise ValueError("unknown policy")
        self.name,self.estimator,self.cost_floor=name,estimator,cost_floor
        self.reprobe_seconds=reprobe_seconds;self.turn=0

    def choose(self,now,live,eligible):
        donors=sorted(d for d in ("A","B") if eligible.get(d,False))
        if self.name=="none" or not donors:return None,"no_action"
        predictions={d:self.estimator.predict(d,now) for d in donors}
        # All acting policies use identical exploration; every probe is charged.
        for donor in donors:
            evidence=self.estimator.history.get(donor)
            if evidence is None or now-evidence.measured_at>=self.reprobe_seconds:
                return donor,"probe"
        if self.name=="round_robin":
            donor=donors[self.turn%len(donors)];self.turn+=1;return donor,"round_robin"
        if self.name=="coldness":
            def coldness(donor):
                stat=live.get(donor,{}).get("stat") or {}
                inactive=stat.get("inactive_anon")
                if inactive is None:return float("-inf")
                return inactive/max(1,stat.get("anon",0))
            available=[d for d in donors if coldness(d)!=float("-inf")]
            if not available:return None,"missing_coldness"
            return max(available,key=coldness),"coldness"
        known=[d for d in donors if predictions[d]["status"]=="KNOWN"]
        if not known:return None,"abstain_unknown"
        score=(lambda d:predictions[d]["immediate_bytes"]) if self.name=="immediate" else (
            lambda d:predictions[d]["lower_bytes"]/max(self.cost_floor,predictions[d]["cost_seconds"]))
        donor=max(known,key=score)
        return (donor,"select") if score(donor)>0 else (None,"abstain_nonpositive")
