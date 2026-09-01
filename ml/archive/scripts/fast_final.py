import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, json
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (f1_score, average_precision_score, roc_auc_score,
                             classification_report, confusion_matrix)
from lightgbm import LGBMClassifier
RS=42
e=pd.read_csv("accidents_enriched_explanatory.csv",low_memory=False)
e=e[e["v_n_vehicle_rows"].notna()].reset_index(drop=True)
sev=e["Accident_Severity"]; le=LabelEncoder().fit(sev); y=le.transform(sev)
names=le.classes_.tolist(); FI,GI,MI=(names.index(c) for c in ["Fatal","Grievous","Minor"])
y_ksi=(sev!="Minor").astype(int).values
CATS=["Day_of_Week","Junction_Control","Junction_Detail","Light_Conditions",
 "Local_Authority_(District)","Police_Force","Road_Surface_Conditions","Road_Type",
 "Urban_or_Rural_Area","Weather_Conditions","Vehicle_Type"]
e["Hour"]=pd.to_datetime(e["Time"],format="%H:%M",errors="coerce").dt.hour
e["Month"]=pd.to_datetime(e["Accident_Date"],errors="coerce").dt.month
X=e[CATS+["Latitude","Longitude","Number_of_Casualties","Number_of_Vehicles","Speed_limit","Hour","Month"]].copy()
for c in CATS: X[c]=LabelEncoder().fit_transform(X[c].fillna("Unknown").astype(str))
new=[c for c in e.columns if c[:2] in ("v_","c_","k_") and "police_officer_attend" not in c]
N=e[new].copy()
for c in N.columns:
    if N[c].dtype==object: N[c]=LabelEncoder().fit_transform(N[c].fillna("NA").astype(str))
X=pd.concat([X,N],axis=1).apply(pd.to_numeric,errors="coerce").replace([np.inf,-np.inf],np.nan)
tr,te=train_test_split(np.arange(len(e)),test_size=0.2,random_state=RS,stratify=y)
mk=lambda: LGBMClassifier(n_estimators=400,learning_rate=0.05,num_leaves=63,min_child_samples=40,
                          class_weight="balanced",random_state=RS,n_jobs=-1,verbose=-1)
print("OOF for threshold tuning ...")
oof=np.zeros((len(tr),3))
for k,(a,b) in enumerate(StratifiedKFold(3,shuffle=True,random_state=RS).split(tr,y[tr]),1):
    oof[b]=mk().fit(X.iloc[tr[a]],y[tr[a]]).predict_proba(X.iloc[tr[b]]); print("  fold",k)
def tune(P,yt):
    g=np.concatenate([np.arange(.25,3.01,.25),np.arange(3.5,12.1,.5)]); best=(-1.,1.,1.)
    for mf in g:
        sf=P[:,FI]*mf
        for mg in g:
            s=f1_score(yt,np.argmax(np.column_stack([sf,P[:,GI]*mg,P[:,MI]]),1),average="macro")
            if s>best[0]: best=(s,mf,mg)
    return best
s0,mf,mg=tune(oof,y[tr]); print(f"multipliers: Fatal x{mf:.2f} Grievous x{mg:.2f} (OOF F1 {s0:.4f})")
m=mk().fit(X.iloc[tr],y[tr]); P=m.predict_proba(X.iloc[te])
ksi_auc=roc_auc_score(y_ksi[te],mk().fit(X.iloc[tr],y_ksi[tr]).predict_proba(X.iloc[te])[:,1])
def rep(tag,pred):
    ap=[average_precision_score((y[te]==i).astype(int),P[:,i]) for i in range(3)]
    return {"model":tag,"macro_F1":f1_score(y[te],pred,average="macro"),
            "macro_AP":float(np.mean(ap)),"AP_Fatal":ap[0],"AP_Grievous":ap[1]}
tuned=np.argmax(np.column_stack([P[:,FI]*mf,P[:,GI]*mg,P[:,MI]]),1)
r=pd.DataFrame([rep("LightGBM argmax",P.argmax(1)),rep("LightGBM threshold-tuned",tuned)])
print("\n"+"="*88); print(r.round(4).to_string(index=False)); print(f"KSI ROC-AUC: {ksi_auc:.4f}")
print("\n"+classification_report(y[te],tuned,target_names=names,digits=3))
print(pd.DataFrame(confusion_matrix(y[te],tuned),index=names,columns=names))
o=np.argsort(-P[:,FI]); t=(y[te]==FI).astype(int)[o]; base=t.mean()
print(f"\nFatal risk ranking (base {base*100:.2f}%):")
for f in [.01,.05,.1,.2,.3]:
    k=int(len(t)*f); print(f"  top {f:>4.0%}: {t[:k].mean()*100:6.2f}%  lift {t[:k].mean()/base:5.2f}x  captured {t[:k].sum()/t.sum()*100:5.1f}%")
r.to_csv("fast_final_results.csv",index=False)
json.dump({"multipliers":{"Fatal":float(mf),"Grievous":float(mg),"Minor":1.0},"ksi_roc_auc":float(ksi_auc)},open("fast_final_config.json","w"),indent=2)
