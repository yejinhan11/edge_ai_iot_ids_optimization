"""Fixed-protocol, equal-budget class-balance ablation for archived CICIoT2023 RFs.

No preprocessing/split/feature tuning, no test resampling, no device experiments.
Natural and balanced training share the same pre-existing 70% time partition.
"""
import gc
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

from build_dataset import FEATURES
from metrics import inference_cost, model_size_mb, model_stats
from train_rf import time_split

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/ciciot2023_balanced_rf'
LOCAL = ROOT / 'data/processed/ciciot2023_balanced_rf'
MODELS = ROOT / 'results/models/ciciot2023_balanced_rf'
SEEDS = [42, 43, 44]
CONFIGS = [('baseline', 38, 100), ('top5', 5, 100), ('compact', 38, 20)]


def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def sample_indices(pool, labels, seed, regime, cap=1_000_000):
    rng = np.random.default_rng(seed)
    if regime == 'natural':
        return rng.choice(pool, cap, replace=False)
    if regime != 'balanced':
        raise ValueError(regime)
    groups = [pool[labels[pool] == label] for label in [0, 1]]
    if cap % 2 or min(map(len, groups)) < cap // 2:
        raise ValueError('insufficient training rows for equal-budget balancing')
    idx = np.concatenate([rng.choice(g, cap // 2, replace=False) for g in groups])
    rng.shuffle(idx)
    return idx


def metrics(cm):
    tn, fp, fn, tp = map(int, cm.ravel())
    div = lambda a, b: a / b if b else 0.
    bp, br = div(tn, tn+fn), div(tn, tn+fp)
    dp, dr = div(tp, tp+fp), div(tp, tp+fn)
    bf, df = div(2*tn, 2*tn+fp+fn), div(2*tp, 2*tp+fp+fn)
    n = tn+fp+fn+tp
    return dict(n=n, n_benign=tn+fp, n_ddos=fn+tp, tn=tn, fp=fp, fn=fn, tp=tp,
                accuracy=div(tn+tp,n), precision=dp, recall=dr, f1=df,
                benign_precision=bp, benign_recall=br, benign_f1=bf,
                f1_macro=(bf+df)/2, f1_weighted=div(bf*(tn+fp)+df*(fn+tp),n),
                balanced_accuracy=(br+dr)/2, false_alarm_rate=div(fp,tn+fp),
                missed_ddos_rate=div(fn,fn+tp))


def archive_reference(name):
    if name == 'top5':
        d = pd.read_csv(ROOT/'results/tables/sweep_features.csv')
        return d[(d.train_subset=='all') & (d.test_subset=='all') & (d.top_k==5)].iloc[0]
    path = 'rf_v1.csv' if name=='baseline' else 'rf_final_c1.csv'
    d = pd.read_csv(ROOT/'results/tables'/path)
    return d[(d.train_subset=='all') & (d.test_subset=='all')].iloc[0]


def main():
    previous_elapsed = 0.
    previous_models = 0
    if (OUT/'results.csv').exists():
        previous_models = len(pd.read_csv(OUT/'results.csv'))
        if (OUT/'status.json').exists():
            previous_elapsed = json.loads((OUT/'status.json').read_text(encoding='utf-8')).get('elapsed_sec', 0.)
    started = time.time() - previous_elapsed
    for p in [OUT, LOCAL, MODELS]: p.mkdir(parents=True, exist_ok=True)
    write_json(OUT/'status.json',dict(status='loading', started=started, total_models=18,
                                    resumed_completed_models=previous_models,carried_elapsed_sec=previous_elapsed))
    print('RESUME',previous_models,'completed models; carried elapsed seconds',previous_elapsed,flush=True)
    files=sorted((ROOT/'data/processed/dataset_v1_parts').glob('*.parquet'))
    assert files
    meta=pd.read_parquet(ROOT/'data/processed/dataset_v1_parts',
                         columns=['source_pcap','row_in_file','binary_label','attack_type'])
    labels=meta.binary_label.to_numpy(copy=True)
    train_mask=time_split(meta,.7)
    train=np.flatnonzero(train_mask)
    test=np.flatnonzero(~train_mask)
    assert len(meta)==20_990_150 and len(test)==6_297_039
    assert (int((labels[test]==0).sum()),int((labels[test]==1).sum()))==(329_362,5_967_677)
    rank_path=ROOT/'results/tables/rf_v1_feature_importance.csv'
    rank=pd.read_csv(rank_path,index_col=0).importance.sort_values(ascending=False).index.tolist()
    top5=[f for f in rank if f in FEATURES][:5]
    assert top5==['Tot size','Tot sum','AVG','HTTPS','Max']
    # Exact source order and fixed archived feature order are retained.
    x=np.memmap(LOCAL/'features.float32',dtype='float32',mode='w+',shape=(len(meta),len(FEATURES)))
    offset=0
    for path in files:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=131072,columns=FEATURES):
            arr=np.column_stack([c.to_numpy(zero_copy_only=False) for c in batch.columns])
            assert np.isfinite(arr).all()
            x[offset:offset+len(arr)]=arr
            offset+=len(arr)
        print('LOADED',path.name,offset,flush=True)
    assert offset==len(meta)
    x.flush()
    partition_rows=[]
    for source, group in meta.groupby('source_pcap',observed=True):
        ids=group.index.to_numpy()
        for part,mask in [('train_pool',train_mask[ids]),('test',~train_mask[ids])]:
            ys=labels[ids[mask]]
            partition_rows.append(dict(source=source,partition=part,rows=len(ys),
                                       benign=int((ys==0).sum()),ddos=int((ys==1).sum())))
    pd.DataFrame(partition_rows).to_csv(OUT/'partition_audit.csv',index=False)
    protocol=dict(dataset='CICIoT2023 PCAP-derived dataset_v1_parts; archived first chunks',
        resumed_completed_models=previous_models,carried_elapsed_sec=previous_elapsed,
        rows=len(meta),train_pool_rows=len(train),test_rows=len(test),
        train_pool_benign=int((labels[train]==0).sum()),train_pool_ddos=int((labels[train]==1).sum()),
        test_benign=329362,test_ddos=5967677,train_pool_sha256=digest(train),test_sha256=digest(test),
        split='existing time_split(data,0.7), per source row_in_file cutoff; unchanged',
        training_cap=1000000,balanced_per_class=500000,seeds=SEEDS,features=FEATURES,top5=top5,
        configs=[dict(name=n,features=k,trees=t) for n,k,t in CONFIGS],
        class_weight='balanced in both regimes; balanced equal counts imply unit weights',
        max_depth=None,min_samples_leaf=1,
        feature_selection='fixed archived RF importance, no new feature ranking or hyperparameter selection',
        validation='no new validation split; prespecified ablation, no test-driven candidate selection',
        test_previously_observed=True,
        benchmark='same 100000 original test rows, single-thread RF.predict, 5-repeat median, warmup',
        inference_benchmark_seed=42,
        controls='equal sample budget; natural and balanced evaluated on identical unchanged test; no 1.54m arm',
        limitations=['archived test reused; not a fresh external holdout',
                     'class balancing changes empirical training distribution and distinct benign coverage together',
                     'no MLP quantization or cross-machine speed comparison',
                     'no device-subset experiments or LOAO in this ablation'],
        python=sys.version,sklearn=sklearn.__version__,numpy=np.__version__,pandas=pd.__version__,
        platform=platform.platform(),
        hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in files+[rank_path,Path(__file__),ROOT/'src/train_rf.py',ROOT/'src/metrics.py']})
    write_json(OUT/'protocol.json',protocol)
    bench_local=np.random.default_rng(42).choice(len(test),min(100000,len(test)),replace=False)
    np.save(LOCAL/'test_indices.npy',test)
    np.save(LOCAL/'benchmark_test_indices.npy',test[bench_local])
    sample_rows=[]
    results=[]
    if (OUT/'results.csv').exists():results=pd.read_csv(OUT/'results.csv').to_dict('records')
    done={(r['regime'],r['candidate'],int(r['seed'])) for r in results}
    for seed in SEEDS:
        for regime in ['natural','balanced']:
            idx=sample_indices(train,labels,seed,regime)
            assert len(idx)==len(np.unique(idx))==1000000
            assert train_mask[idx].all()
            if regime=='balanced':assert (labels[idx]==0).sum()==500000
            counts=dict(regime=regime,seed=seed,train_rows=len(idx),
                        train_benign=int((labels[idx]==0).sum()),train_ddos=int((labels[idx]==1).sum()),
                        training_indices_sha256=digest(idx))
            np.savez_compressed(LOCAL/f'train_indices_{regime}_{seed}.npz',indices=idx)
            audit=meta.iloc[idx].groupby(['source_pcap','binary_label'],observed=True).size()
            for (source,label),count in audit.items():
                sample_rows.append(dict(regime=regime,seed=seed,source=source,label=int(label),rows=int(count)))
            pd.DataFrame(sample_rows).to_csv(OUT/'sampling_audit.csv',index=False)
            for name,k,trees in CONFIGS:
                if (regime,name,seed) in done:continue
                feats=top5 if k==5 else FEATURES
                columns=[FEATURES.index(f) for f in feats]
                status=dict(status='running',stage='training',regime=regime,candidate=name,seed=seed,
                            completed=len(results),total_models=18,elapsed_sec=time.time()-started)
                write_json(OUT/'status.json',status)
                print('FIT',counts,name,trees,flush=True)
                rf=RandomForestClassifier(n_estimators=trees,class_weight='balanced',
                                           n_jobs=-1,random_state=seed,max_depth=None,min_samples_leaf=1)
                xt=np.ascontiguousarray(x[idx][:,columns])
                t=time.perf_counter();rf.fit(xt,labels[idx]);train_sec=time.perf_counter()-t
                del xt;gc.collect()
                status.update(stage='evaluating',train_sec=train_sec)
                write_json(OUT/'status.json',status)
                cm=np.zeros((2,2),dtype=np.int64)
                for start in range(0,len(test),200000):
                    ti=test[start:start+200000]
                    cm+=confusion_matrix(labels[ti],rf.predict(x[ti][:,columns]),labels=[0,1])
                m=metrics(cm)
                # Same fixed 100k sample for every model; helper seed=42 reproduces the stored benchmark ids.
                xb=np.ascontiguousarray(x[test[bench_local]][:,columns])
                bench=inference_cost(rf,xb,n_samples=len(xb),repeats=5,seed=42)
                del xb
                row=dict(**counts,candidate=name,n_features=k,n_estimators=trees,
                         features=';'.join(feats),class_weight='balanced',train_sec=train_sec,
                         model_mb=model_size_mb(rf),**model_stats(rf),**m,**bench)
                if regime=='natural' and seed==42:
                    ref=archive_reference(name)
                    checks={key:dict(archived=int(ref[key]),current=int(m[key]))
                            for key in ['n','n_benign','n_ddos','tn','fp','fn','tp']}
                    matched=all(v['archived']==v['current'] for v in checks.values())
                    write_json(OUT/f'archive_reproduction_{name}.json',dict(exact_counts_match=matched,checks=checks))
                    assert matched, f'Archived reproduction mismatch: {name}'
                bundle=dict(model=rf,features=feats,labels={0:'Benign',1:'DDoS'},
                            protocol='results/ciciot2023_balanced_rf/protocol.json',training=counts)
                path=MODELS/f'{regime}_{name}_seed{seed}.joblib'
                joblib.dump(bundle,path,compress=3)
                loaded=joblib.load(path)
                probe=np.ascontiguousarray(x[test[:1000]][:,columns])
                assert np.array_equal(rf.predict(probe),loaded['model'].predict(probe))
                row['model_file_mb']=path.stat().st_size/1e6
                row['saved_model_reload_verified']=True
                results.append(row)
                pd.DataFrame(results).to_csv(OUT/'results.csv',index=False)
                write_json(OUT/'status.json',dict(status='running',stage='between_models',completed=len(results),
                           total_models=18,elapsed_sec=time.time()-started,last_model=f'{regime}/{name}/{seed}'))
                print('DONE',regime,name,seed,'train_s',round(train_sec,2),
                      'macroF1',round(m['f1_macro'],6),'benign_recall',round(m['benign_recall'],6),
                      'elapsed_min',round((time.time()-started)/60,2),flush=True)
                del loaded,rf;gc.collect()
    df=pd.DataFrame(results)
    measure=['accuracy','f1','f1_macro','f1_weighted','balanced_accuracy','benign_precision',
             'benign_recall','benign_f1','recall','false_alarm_rate','missed_ddos_rate',
             'model_mb','model_file_mb','infer_us_per_sample','train_sec','total_nodes']
    summary=df.groupby(['regime','candidate'])[measure].agg(['mean','std'])
    summary.columns=['_'.join(c) for c in summary.columns]
    summary.reset_index().to_csv(OUT/'summary.csv',index=False)
    paired=[]
    for seed in SEEDS:
        for name,_,_ in CONFIGS:
            natural=df[(df.regime=='natural')&(df.candidate==name)&(df.seed==seed)].iloc[0]
            balanced=df[(df.regime=='balanced')&(df.candidate==name)&(df.seed==seed)].iloc[0]
            paired.append(dict(seed=seed,candidate=name,
                               **{m+'_delta':float(balanced[m]-natural[m]) for m in measure}))
    pd.DataFrame(paired).to_csv(OUT/'paired_deltas.csv',index=False)
    write_json(OUT/'status.json',dict(status='complete',completed=len(results),total_models=18,
               elapsed_sec=time.time()-started,models_reload_verified=True))
    if (OUT/'failure.json').exists():
        write_json(OUT/'failure.json',dict(status='resolved',resolved_at=time.time(),
                   reason='early result assembly error corrected before any completed result was written'))
    print('COMPLETE',len(results),'models, minutes',round((time.time()-started)/60,2),flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        OUT.mkdir(parents=True,exist_ok=True)
        write_json(OUT/'failure.json',dict(traceback=traceback.format_exc(),time=time.time()))
        raise
