import math
import random
import statistics

def mean_window(samples,start,end,key="headroom_bytes"):
    """Time-weighted trapezoidal mean with interpolated boundaries; no extrapolation."""
    points = sorted((float(row["t"]),float(row[key])) for row in samples if row.get(key) not in (None,""))
    if end<=start or len(points)<2 or points[0][0]>start or points[-1][0]<end:
        raise ValueError("window is not fully covered by telemetry")
    area = 0.0
    for (t0,y0),(t1,y1) in zip(points,points[1:]):
        left,right=max(start,t0),min(end,t1)
        if right<=left or t1<=t0: continue
        a=y0+(y1-y0)*(left-t0)/(t1-t0)
        b=y0+(y1-y0)*(right-t0)/(t1-t0)
        area += (a+b)*(right-left)/2
    return area/(end-start)

def linear_drift(samples,start,end):
    points=[(row["t"],row["headroom_bytes"]) for row in samples if start<=row["t"]<=end and row.get("headroom_bytes") is not None]
    if len(points)<4: raise ValueError("insufficient quiet-window samples")
    tx=statistics.mean(x for x,y in points); ym=statistics.mean(y for x,y in points)
    denominator=sum((x-tx)**2 for x,y in points)
    slope=sum((x-tx)*(y-ym) for x,y in points)/denominator if denominator else 0
    residuals=[y-(ym+slope*(x-tx)) for x,y in points]
    return slope, statistics.pstdev(residuals)

def bootstrap_mean(values, seed=20261021, iterations=4000):
    if not values: return {"n":0,"mean":None,"ci95":None}
    rng=random.Random(seed)
    means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(iterations))
    return {"n":len(values),"mean":statistics.mean(values),
            "ci95":[means[int(.025*iterations)],means[min(iterations-1,int(.975*iterations))]]}

def wilson(success,total):
    if not total:return None
    z=1.95996398454;p=success/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den
    spread=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [center-spread,center+spread]
