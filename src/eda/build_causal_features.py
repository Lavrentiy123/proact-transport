import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
D="data/"
def hav(lon1,lat1,lon2,lat2):
    lon1,lat1,lon2,lat2=map(np.radians,[lon1,lat1,lon2,lat2]); a=np.sin((lat2-lat1)/2)**2+np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 6371000*2*np.arcsin(np.sqrt(np.clip(a,0,1)))
def prep(split):
    traf=pd.read_csv(D+f"{split}/traffic.csv",low_memory=False)
    sched=pd.read_csv(D+(f"{split}/schedule.csv" if split!="validate" else "validate/schedule_plan.csv"))
    pts=pd.read_csv(D+("labels/labels_train.csv" if split=="train" else "labels/labels_test.csv" if split=="test" else "validate/points.csv"))
    traf=traf[traf.location_valid==True].copy(); traf["et"]=pd.to_datetime(traf.event_time)
    sched["tb"]=pd.to_datetime(sched.time_begin)
    g=sched.geom.str.extract(r"POINT \(([-\d.]+) ([-\d.]+)\)").astype(float); sched["slon"],sched["slat"]=g[0],g[1]
    return pts,traf,sched
def build(pts,traf,sched):
    T_all=pd.to_datetime(pts["T"]); TT_all=pd.to_datetime(pts.target_time_begin)
    tg={k:v.sort_values("et") for k,v in traf.groupby("tr_id")}
    sg={k:v.sort_values("tb").reset_index(drop=True) for k,v in sched.groupby("tr_id")}
    # reconstructed arrival per sched row: first valid fix within 25 m in [plan-20m, plan+25m]
    rec={}
    for k,s in sg.items():
        t=tg.get(k); arr=np.full(len(s),np.datetime64("NaT"),dtype="datetime64[ns]")
        if t is not None:
            tt=t.et.values; la=t.lat.values; lo=t.lon.values
            for i,r in enumerate(s.itertuples()):
                w=(tt>=np.datetime64(r.tb-pd.Timedelta("20min")))&(tt<=np.datetime64(r.tb+pd.Timedelta("25min")))
                if w.any():
                    d=hav(lo[w],la[w],r.slon,r.slat); kk=np.where(d<25)[0]
                    if len(kk): arr[i]=tt[w][kk[0]]
        s=s.copy(); s["arr"]=arr; s["rdev"]=(s.arr-s.tb).dt.total_seconds(); sg[k]=s
    rows=[]
    for i,p in enumerate(pts.itertuples()):
        T=T_all.iloc[i]; TT=TT_all.iloc[i]; f={}
        f["cur_dev_s"]=p.cur_dev_s; f["horizon_s"]=(TT-T).total_seconds()
        m=T.hour*60+T.minute; f["tod_sin"]=np.sin(2*np.pi*m/1440); f["tod_cos"]=np.cos(2*np.pi*m/1440); f["hour"]=T.hour
        s=sg.get(p.tr_id); t=tg.get(p.tr_id)
        tgt=s[s.tt_action_item_id==p.target_stop_id] if s is not None else None
        tlon,tlat=(tgt.slon.iloc[0],tgt.slat.iloc[0]) if tgt is not None and len(tgt) else (np.nan,np.nan)
        if s is not None:
            past=s[s.tb<=T]; fut=s[(s.tb>T)&(s.tb<=TT)]
            f["n_stops_between"]=len(fut)
            f["since_last_plan_s"]=(T-past.tb.iloc[-1]).total_seconds() if len(past) else np.nan
            # causal reconstructed delays (arrival detected by T)
            known=s[(s.arr<=T)]
            f["rdev_last"]=known.rdev.iloc[-1] if len(known) else np.nan
            f["rdev_age_s"]=(T-known.arr.iloc[-1]).total_seconds() if len(known) else np.nan
            k5=known[known.arr<=T-pd.Timedelta("5min")]; k10=known[known.arr<=T-pd.Timedelta("10min")]
            f["rdev_trend5"]=f["rdev_last"]-k5.rdev.iloc[-1] if len(k5) and len(known) else np.nan
            f["rdev_trend10"]=f["rdev_last"]-k10.rdev.iloc[-1] if len(k10) and len(known) else np.nan
            # lower bound: planned stops with plan<=T not yet reached
            if len(known):
                pend=past[past.index>known.index[-1]]
            else: pend=past
            f["n_pending"]=len(pend); f["lb_delay_s"]=(T-pend.tb.iloc[0]).total_seconds() if len(pend) else 0.0
            # route distance along planned stops from nearest stop to target
            if len(tgt):
                ti=tgt.index[0]
        if t is not None:
            tp=t[t.et<=T]
            if len(tp):
                last=tp.iloc[-1]; f["tel_age_s"]=(T-last.et).total_seconds(); f["last_speed"]=last.speed
                for w in (1,3,5,10):
                    ww=tp[tp.et>=T-pd.Timedelta(minutes=w)]
                    f[f"v_mean_{w}m"]=ww.speed.mean() if len(ww) else np.nan
                    f[f"stop_ratio_{w}m"]=(ww.speed<2).mean() if len(ww) else np.nan
                    if len(ww)>1: f[f"disp_{w}m"]=hav(ww.lon.iloc[0],ww.lat.iloc[0],ww.lon.iloc[-1],ww.lat.iloc[-1])
                f["v_std_5m"]=tp[tp.et>=T-pd.Timedelta("5min")].speed.std()
                f["dist_to_target_m"]=hav(last.lon,last.lat,tlon,tlat)
                if s is not None and len(tgt):
                    # nearest planned stop in window [T-10m, TT] to current position -> path length to target via stop chain
                    cand=s[(s.tb>=T-pd.Timedelta("15min"))&(s.index<=ti)]
                    if len(cand):
                        dd=hav(last.lon,last.lat,cand.slon.values,cand.slat.values); j=cand.index[np.argmin(dd)]
                        chain=s.loc[j:ti]; seg=hav(chain.slon.values[:-1],chain.slat.values[:-1],chain.slon.values[1:],chain.slat.values[1:]).sum() if len(chain)>1 else 0
                        f["route_dist_m"]=dd.min()+seg
                        f["plan_stop_nearest_dev_s"]=(T-s.loc[j,"tb"]).total_seconds()  # position-based deviation estimate
                        v=np.nanmean([f.get("v_mean_10m",np.nan)]); v=max(v,5.0) if not np.isnan(v) else 15.0
                        f["proj_delay_s"]=(f["route_dist_m"]/(v/3.6))-f["horizon_s"]
        rows.append(f)
    return pd.DataFrame(rows)
out={}
for sp in ("train","test","validate"):
    pts,traf,sched=prep(sp); F=build(pts,traf,sched)
    F["tr_id"]=pts.tr_id.values; F["sample_id"]=pts.sample_id.values
    if "target_delay_s" in pts: F["y"]=pts.target_delay_s.values
    F.to_parquet(f"{__import__('os').environ['TEMP']}/claude_F_{sp}.parquet"); print(sp,F.shape, F.isna().mean().round(2).sort_values(ascending=False).head(5).to_dict())
