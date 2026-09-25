import pandas as pd, numpy as np
D="data/"
lt=pd.read_csv(D+"labels/labels_train.csv"); ls=pd.read_csv(D+"labels/labels_test.csv"); vp=pd.read_csv(D+"validate/points.csv")
sr=pd.read_csv(D+"train/schedule.csv"); st=pd.read_csv(D+"test/schedule.csv"); sv=pd.read_csv(D+"validate/schedule_plan.csv")
tr,te,va=set(lt.tr_id),set(ls.tr_id),set(vp.tr_id)
print("tr_id: train",len(tr),"test",len(te),"val",len(va)," test&train",len(te&tr)," val&train",len(va&tr)," val&test",len(va&te))
print("sched tr: train",sr.tr_id.nunique(),"test",st.tr_id.nunique(),"val",sv.tr_id.nunique(), "val sched tr == test sched tr:", set(sv.tr_id)==set(st.tr_id))
print("test label sample_id in train labels:",ls.sample_id.isin(lt.sample_id).mean(), " test target_stop in train labels:", ls.target_stop_id.isin(lt.target_stop_id).mean())
print("val target_stop in train labels:",vp.target_stop_id.isin(lt.target_stop_id).mean())
# same (tr_id,T) between val and train?
k=lambda d: d.tr_id.astype(str)+"_"+d["T"].astype(str)
print("val (tr,T) in train:",k(vp).isin(k(lt)).mean()," test (tr,T) in train:",k(ls).isin(k(lt)).mean())
# fact availability in test sched for val targets
m=vp.merge(st[["tt_action_item_id","time_begin","time_fact_begin"]],left_on="target_stop_id",right_on="tt_action_item_id",how="left")
print("val targets with fact in test/schedule:",m.time_fact_begin.notna().mean())
# fact in train sched for val targets
m2=vp.merge(sr[["tt_action_item_id","time_fact_begin"]],left_on="target_stop_id",right_on="tt_action_item_id",how="left")
print("val targets with fact in train/schedule:",m2.time_fact_begin.notna().mean())
# check consistency: labels target == fact-plan in schedule
mm=lt.merge(sr[["tt_action_item_id","time_begin","time_fact_begin"]],left_on="target_stop_id",right_on="tt_action_item_id",how="left")
d=(pd.to_datetime(mm.time_fact_begin)-pd.to_datetime(mm.time_begin)).dt.total_seconds()
print("train label == sched fact-plan:",np.isclose(d,mm.target_delay_s,atol=1).mean())
# cur_dev reconstruction: last stop with fact <= T
s=sr.copy(); s["tb"]=pd.to_datetime(s.time_begin); s["tf"]=pd.to_datetime(s.time_fact_begin); s["dev"]=(s.tf-s.tb).dt.total_seconds()
s=s.sort_values("tf")
ok=[];ok2=[]
for _,r in lt.sample(600,random_state=0).iterrows():
    g=s[(s.tr_id==r.tr_id)&(s.tf<=pd.Timestamp(r["T"]))]
    if len(g): ok.append(np.isclose(g.dev.iloc[-1],r.cur_dev_s,atol=1))
    g2=s[(s.tr_id==r.tr_id)&(s.tb<=pd.Timestamp(r["T"]))&s.tf.notna()].sort_values("tb")
    if len(g2): ok2.append(np.isclose(g2.dev.iloc[-1],r.cur_dev_s,atol=1))
print("cur_dev == dev of last stop by fact<=T:",np.mean(ok)," by plan<=T:",np.mean(ok2))
print("sched fact null frac train/test:",sr.time_fact_begin.isna().mean().round(3),st.time_fact_begin.isna().mean().round(3), " manual_fill frac:",sr.manual_fill.mean().round(3))
# delay distribution in schedule facts (all stops)
print("sched dev quantiles:",s.dev.quantile([.01,.25,.5,.75,.99]).round(0).tolist())
# fact seconds pattern
print("fact seconds value counts top:",s.tf.dt.second.value_counts().head(5).to_dict())
print("plan seconds:",pd.to_datetime(sr.time_begin).dt.second.value_counts().head(3).to_dict())
# stops per tr, headway between stops
g=s.sort_values(["tr_id","tb"]).groupby("tr_id").tb.diff().dt.total_seconds()
print("plan inter-stop gap s:",g.describe().round(0).to_dict())
# unique stop geoms (physical stops)
print("unique geoms:",sr.geom.nunique()," unique addr:",sr.building_address.nunique())
# how many tr share geoms (same route)?
gg=sr.groupby("geom").tr_id.nunique()
print("geoms shared by >1 tr:",(gg>1).mean().round(3), "max tr per geom", gg.max())
