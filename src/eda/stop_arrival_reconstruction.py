# Проверка: можно ли восстановить факт прибытия на остановки из телеметрии (нужно и для validate, и для онлайна)
import pandas as pd, numpy as np
D="data/"
sr=pd.read_csv(D+"train/schedule.csv"); tr=pd.read_csv(D+"train/traffic.csv",low_memory=False)
sr["tb"]=pd.to_datetime(sr.time_begin); sr["tf"]=pd.to_datetime(sr.time_fact_begin); sr["dev"]=(sr.tf-sr.tb).dt.total_seconds()
g=sr.geom.str.extract(r"POINT \(([-\d.]+) ([-\d.]+)\)").astype(float); sr["slon"],sr["slat"]=g[0],g[1]
tr=tr[tr.location_valid==True].copy(); tr["et"]=pd.to_datetime(tr.event_time)
print("tr with telemetry among sched tr:",len(set(sr.tr_id)&set(tr.tr_id)),"/",sr.tr_id.nunique())
def hav(lon1,lat1,lon2,lat2):
    lon1,lat1,lon2,lat2=map(np.radians,[lon1,lat1,lon2,lat2]); a=np.sin((lat2-lat1)/2)**2+np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 6371000*2*np.arcsin(np.sqrt(a))
res={R:[] for R in (25,40,60,100)}; mind=[]
for tid,s in sr.groupby("tr_id"):
    t=tr[tr.tr_id==tid].sort_values("et")
    if len(t)==0: continue
    tt=t.et.values; la=t.lat.values; lo=t.lon.values; sp=t.speed.values
    for r in s.itertuples():
        w=(tt>=np.datetime64(r.tb-pd.Timedelta("20min")))&(tt<=np.datetime64(r.tb+pd.Timedelta("25min")))
        if not w.any(): continue
        d=hav(lo[w],la[w],r.slon,r.slat); ts=tt[w]
        mind.append(d.min())
        for R in res:
            k=np.where(d<R)[0]
            if len(k): res[R].append((pd.Timestamp(ts[k[0]])-r.tf).total_seconds())
print("min dist telemetry->stop quantiles m:",np.quantile(mind,[.1,.5,.75,.9,.95]).round(0))
for R,v in res.items():
    v=np.array(v); print(f"R={R}m coverage={len(v)/len(mind):.2f} err(first-in-zone - fact) median={np.median(v):.1f}s MAE={np.abs(v).mean():.1f}s P(|err|<30s)={(np.abs(v)<30).mean():.2f}")
