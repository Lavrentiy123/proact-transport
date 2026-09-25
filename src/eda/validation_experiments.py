import pandas as pd, numpy as np, os, warnings; warnings.filterwarnings("ignore")
from catboost import CatBoostRegressor
from sklearn.model_selection import GroupKFold
P=os.environ["TEMP"]
tr=pd.read_parquet(f"{P}/claude_F_train.parquet"); te=pd.read_parquet(f"{P}/claude_F_test.parquet")
real=set(te.tr_id)
twin={}  # synthetic -> real via order (from EDA: 9000000+2i,+1 -> i-th real sorted)
for i,r in enumerate(sorted(real)): twin[9000000+2*i]=r; twin[9000001+2*i]=r
tr["bus"]=tr.tr_id.map(lambda x: twin.get(x,x)); te["bus"]=te.tr_id
FE=[c for c in tr.columns if c not in("tr_id","sample_id","y","bus")]
NOTOD=[c for c in FE if c not in("tod_sin","tod_cos","hour")]
def fit(X,y,feats,seed=0):
    m=CatBoostRegressor(iterations=800,learning_rate=0.04,depth=6,loss_function="MAE",random_seed=seed,verbose=0,l2_leaf_reg=5)
    m.fit(X[feats],y); return m
def mae(a,b): return np.abs(a-b).mean()
def report(name,trn,tst,feats=FE):
    m=fit(trn,trn.y-trn.cur_dev_s,feats); p=tst.cur_dev_s+m.predict(tst[feats])
    base=mae(tst.y,tst.cur_dev_s)
    # shrink baseline fitted on trn
    best=min(((mae(trn.y,a*trn.cur_dev_s+b),a,b) for a in np.arange(.3,1.21,.05) for b in range(-40,61,5)))
    sh=mae(tst.y,best[1]*tst.cur_dev_s+best[2])
    print(f"{name:55s} n_tr={len(trn):5d} n_te={len(tst):4d} | base {base:6.1f} | shrink {sh:6.1f} | CB {mae(tst.y,p):6.1f}")
    return m
print("=== Official split (test labels as holdout) ===")
m_all=report("E1 train ALL (real+synthetic twins) -> test",tr,te)
report("E1b same, no time-of-day features",tr,te,NOTOD)
report("E2 train REAL only -> test",tr[tr.tr_id.isin(real)],te)
report("E2b train SYNTHETIC only -> test",tr[~tr.tr_id.isin(real)],te)
print("\n=== Honest: leave-bus-out (bus + its twins held out), real points pooled ===")
pool=pd.concat([tr,te],ignore_index=True)
realpool=pool[pool.tr_id.isin(real)].reset_index(drop=True)
for label,use_syn,feats in [("LOBO, train on other real buses",False,FE),("LOBO, + twins of other buses",True,FE),("LOBO, + twins, no TOD",True,NOTOD)]:
    preds=np.zeros(len(realpool)); sh=np.zeros(len(realpool))
    gkf=GroupKFold(n_splits=13)
    for trn_i,tst_i in gkf.split(realpool,groups=realpool.bus):
        held=set(realpool.bus.iloc[tst_i])
        trn=pool[~pool.bus.isin(held)]
        if not use_syn: trn=trn[trn.tr_id.isin(real)]
        m=fit(trn,trn.y-trn.cur_dev_s,feats); t=realpool.iloc[tst_i]
        preds[tst_i]=t.cur_dev_s+m.predict(t[feats])
    print(f"{label:55s} | base {mae(realpool.y,realpool.cur_dev_s):6.1f} | CB {mae(realpool.y,preds):6.1f}")
print("\n=== Honest: forward-in-time (train T<14:00 incl. twins, test real T>=14:15) ===")
T=lambda d: pd.to_datetime(d.sample_id.str.split("_").str[1].astype(int),unit="s")
pool["Tt"]=T(pool)
cut=pd.Timestamp("2026-01-06 14:00"); 
trn=pool[pool.Tt<cut- pd.Timedelta("15min")]; tst=pool[(pool.Tt>=cut)&pool.tr_id.isin(real)]
report("FWD time split",trn,tst)
fi=pd.Series(m_all.get_feature_importance(),index=FE).sort_values(ascending=False)
print("\nTop features (E1):",fi.head(12).round(1).to_dict())
