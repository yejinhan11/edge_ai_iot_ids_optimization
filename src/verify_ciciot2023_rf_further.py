"""Audit final artifacts and benchmark saved models in a separate serial process."""
import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from build_dataset import FEATURES
from run_ciciot2023_balanced_rf import metrics

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/ciciot2023_rf_further'
LOCAL=ROOT/'data/processed/ciciot2023_rf_further'


def main():
    status=json.loads((OUT/'status.json').read_text(encoding='utf-8'))
    assert status['status']=='complete'
    df=pd.read_csv(OUT/'runs.csv')
    test=df[df.stage=='test']
    assert not df.duplicated(['stage','candidate','seed']).any()
    for _,r in df.iterrows():
        cm=np.array([[r.tn,r.fp],[r.fn,r.tp]],dtype=np.int64)
        assert cm.sum()==r.n and (cm>=0).all()
        calculated=metrics(cm)
        for key in ['accuracy','f1_macro','false_alarm_rate','missed_ddos_rate']:
            assert abs(calculated[key]-r[key])<1e-12
    archived=pd.read_csv(ROOT/'results/ciciot2023_balanced_rf/results.csv')
    archive_checks=[]
    for name,old_name in [('t100_d0_l1','baseline'),('t20_d0_l1','compact')]:
        for seed in [42,43,44]:
            old=archived[(archived.regime=='natural') & (archived.candidate==old_name) & (archived.seed==seed)].iloc[0]
            new=test[(test.candidate==name) & (test.seed==seed)].iloc[0]
            assert old.training_indices_sha256==new.train_indices_sha256
            matches=all(int(old[k])==int(new[k]) for k in ['tn','fp','fn','tp'])
            assert matches, (name,seed,'archive confusion mismatch')
            archive_checks.append(dict(candidate=name,seed=seed,training_indices_match=True,exact_confusion_match=True))
    ids=np.load(ROOT/'data/processed/ciciot2023_balanced_rf/test_indices.npy')
    bi=np.random.default_rng(42).choice(ids,100000,replace=False)
    x=np.memmap(ROOT/'data/processed/ciciot2023_balanced_rf/features.float32',dtype='float32',mode='r',shape=(20990150,len(FEATURES)))
    xb=np.ascontiguousarray(x[bi]); del x
    models={}
    for _,r in test.iterrows():
        key=(r.candidate,int(r.seed))
        bundle=joblib.load(LOCAL/f'{key[0]}_seed{key[1]}.joblib')
        assert bundle['features']==FEATURES
        model=bundle['model']; model.n_jobs=1
        model.predict(xb)  # full-batch warm-up, outside timings
        models[key]=model
    raw=[]
    rng=np.random.default_rng(20261113)
    keys=list(models)
    for repeat in range(7):
        for pos in rng.permutation(len(keys)):
            name,seed=keys[pos]
            t=time.perf_counter(); models[(name,seed)].predict(xb); duration=time.perf_counter()-t
            raw.append(dict(candidate=name,seed=seed,repeat=repeat,total_sec=duration,
                            infer_us_per_sample=duration/len(xb)*1e6))
        print('BENCHMARK_ROUND',repeat+1,flush=True)
    raw=pd.DataFrame(raw)
    raw.to_csv(OUT/'benchmark_repeats.csv',index=False)
    for (name,seed),g in raw.groupby(['candidate','seed']):
        mask=(df.stage=='test') & (df.candidate==name) & (df.seed==seed)
        for key in ['infer_us_per_sample','infer_total_ms','infer_samples_per_sec']:
            old_key='during_training_'+key
            if old_key not in df:
                df[old_key]=np.nan
            if df.loc[mask,old_key].isna().all():
                df.loc[mask,old_key]=df.loc[mask,key]
        seconds=g.total_sec.median()
        df.loc[mask,'infer_us_per_sample']=seconds/len(xb)*1e6
        df.loc[mask,'infer_total_ms']=seconds*1000
        df.loc[mask,'infer_samples_per_sec']=len(xb)/seconds
    df.to_csv(OUT/'runs.csv',index=False)
    measures=['accuracy','f1_macro','false_alarm_rate','missed_ddos_rate','model_mb','infer_us_per_sample','train_sec','total_nodes']
    summary=df.groupby(['stage','candidate'])[measures].agg(['mean','std'])
    summary.columns=['_'.join(c) for c in summary.columns]
    summary.reset_index().to_csv(OUT/'summary.csv',index=False)
    comp=pd.read_csv(OUT/'comparisons.csv')
    for seed in [42,43,44]:
        rows=df[(df.stage=='test') & (df.seed==seed)].set_index('candidate')
        for name,r in rows.iterrows():
            mask=(comp.candidate==name) & (comp.seed==seed)
            ratio=r.infer_us_per_sample/rows.loc['t20_d0_l1','infer_us_per_sample']
            comp.loc[mask,'latency_ratio_to_c1']=ratio
            comp.loc[mask,'speed_target_met']=ratio<=.7
    comp.to_csv(OUT/'comparisons.csv',index=False)
    validation=json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
    validation.update(metrics_recomputed_from_all_confusion_matrices=True,archive_checks=archive_checks,
        final_benchmark=dict(method='separate process, saved RFs, n_jobs=1, full 100k warmup, 7 rounds with randomized model order; median per model',
            rows=len(xb),benchmark_indices_sha256=hashlib.sha256(bi.tobytes()).hexdigest(),
            original_during_training_timings_preserved=True))
    (OUT/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
    print('AUDIT_COMPLETE',len(df),'runs;',len(test),'saved models;',len(archive_checks),'exact archive matches')


if __name__=='__main__':
    main()
