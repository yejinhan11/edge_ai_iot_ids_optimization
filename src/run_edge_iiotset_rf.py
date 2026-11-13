"""Train fixed 100-tree RF baselines and export shared Edge-IIoTset partitions."""
import gc
import hashlib
import json
import platform
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

from build_dataset import FEATURES
from metrics import inference_cost,model_size_mb,model_stats
from prepare_edge_iiotset import OUT,LOCAL,ROOT,save_json,sha256
from run_ciciot2023_balanced_rf import metrics
from train_rf import time_split

SEEDS=[42,43,44]


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def main():
    started=time.time()
    preparation=json.loads((OUT/'preparation.json').read_text(encoding='utf-8'))
    assert preparation['status']=='complete'
    code_hash=sha256(Path(__file__))
    protocol_path=OUT/'protocol.json'
    if protocol_path.exists():
        assert json.loads(protocol_path.read_text(encoding='utf-8'))['code_hash']==code_hash,'Training code changed; use a new result directory.'
    paths=sorted((LOCAL/'parts').glob('*.parquet'))
    assert len(paths)==14
    data=pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True)
    x=np.ascontiguousarray(data[FEATURES].to_numpy(dtype=np.float32));y=data.binary_label.to_numpy(dtype=np.int8)
    train_mask=time_split(data,.7);fit_mask=time_split(data,.56)
    train=np.flatnonzero(train_mask);test=np.flatnonzero(~train_mask)
    fit=np.flatnonzero(fit_mask);validation=np.flatnonzero(train_mask & ~fit_mask)
    assert len(fit)+len(validation)==len(train) and np.isfinite(x).all()
    assert set(y[train])==set(y[test])=={0,1}
    for name,ids in [('train',train),('test',test),('fit',fit),('validation',validation)]:
        np.save(LOCAL/f'{name}_indices.npy',ids)
    np.save(LOCAL/'X.float32.npy',x);np.save(LOCAL/'y.int8.npy',y)
    metadata=data[['source_pcap','attack_type','row_in_file','window_start_ts','window_end_ts','chunk_id','binary_label']].copy()
    metadata['partition']=np.where(train_mask,'train','test')
    metadata['inner_partition']=np.where(fit_mask,'fit',np.where(train_mask,'validation','test'))
    metadata.to_parquet(LOCAL/'sample_manifest.parquet',index=False,compression='zstd')
    audit=metadata.groupby(['source_pcap','attack_type','binary_label','partition'],observed=True).size().reset_index(name='rows')
    audit.to_csv(OUT/'partition_audit.csv',index=False)
    feature_hashes=pd.util.hash_pandas_object(data[FEATURES],index=False).to_numpy(dtype=np.uint64)
    conflicting=data.groupby(pd.Series(feature_hashes),observed=True).binary_label.nunique()
    conflict_ids=conflicting[conflicting>1].index.to_numpy(dtype=np.uint64)
    overlap=np.isin(feature_hashes[test],np.unique(feature_hashes[train]))
    save_json(OUT/'leakage_audit.json',dict(identifiers_excluded=True,numeric_feature_count=len(FEATURES),
        method='pandas uint64 hashes of all 38 float32 features; collisions theoretically possible',
        train_test_rows_disjoint=not bool(np.intersect1d(train,test).size),
        train_test_exact_feature_overlap_rows=int(overlap.sum()),test_rows=len(test),
        fraction_test_seen_in_full_training_pool=float(overlap.mean()),
        cross_label_feature_groups=len(conflict_ids),rows_in_cross_label_groups=int(np.isin(feature_hashes,conflict_ids).sum()),
        connection_purge=False,split='capture-order within each file, not independent capture holdout'))
    protocol=dict(dataset='Edge-IIoTset PCAP-derived normal versus DDoS capture/scenario baseline',
        label_scope=preparation['label_scope'],source=preparation['source'],features=FEATURES,
        code_hash=code_hash,preparation_code_hash=preparation['code_hash'],
        source_parquet_sha256={p.name:sha256(p) for p in paths},
        settings=dict(n_estimators=100,max_depth=None,min_samples_leaf=1,class_weight='balanced',training_cap=1000000),
        seeds=SEEDS,split='per source_pcap first 70% row_in_file -> training pool, last 30% -> test; no shuffle before partition',
        inner_split='first 56% fit and next 14% validation exported for teammate; fixed RF uses first 70% and does not tune on validation/test',
        partitions={n:dict(rows=len(ids),normal=int((y[ids]==0).sum()),ddos_scenario=int((y[ids]==1).sum()),sha256=digest(ids)) for n,ids in [('train_pool',train),('test',test),('fit',fit),('validation',validation)]},
        inference='single CPU thread RF.predict on fixed at most 100000 test rows, 5-repeat median after warmup; feature extraction excluded',
        environment=dict(python=sys.version,sklearn=sklearn.__version__,numpy=np.__version__,pandas=pd.__version__,platform=platform.platform()),
        limitations=['capture labels do not independently establish every packet is malicious',
            'same-capture split; overlapping connections and identical feature vectors may cross train/test',
            'not a fresh-capture, unseen-attack, device-independent or cross-dataset transfer evaluation',
            'not an official Edge-IIoTset CSV reproduction; uses established CICIoT2023 38-feature extraction',
            'entire supplied 14 PCAPs scanned, not all 14 attack types in Edge-IIoTset',
            'historical CICIoT2023 experiments used first-chunk PCAP subsets; this dataset uses entire supplied files'])
    save_json(protocol_path,protocol)
    records=pd.read_csv(OUT/'runs.csv').to_dict('records') if (OUT/'runs.csv').exists() else []
    for seed in SEEDS:
        if any(int(r['seed'])==seed for r in records):continue
        ids=np.random.default_rng(seed).choice(train,min(1000000,len(train)),replace=False)
        np.save(LOCAL/f'rf_train_seed{seed}.npy',ids)
        np.save(LOCAL/f'rf_fit_seed{seed}.npy',ids[fit_mask[ids]])
        np.save(LOCAL/f'rf_validation_seed{seed}.npy',ids[~fit_mask[ids]])
        save_json(OUT/'status.json',dict(status='training',seed=seed,completed=len(records),elapsed_sec=time.time()-started))
        print('FIT',seed,len(ids),'training windows',flush=True)
        rf=RandomForestClassifier(n_estimators=100,class_weight='balanced',max_depth=None,min_samples_leaf=1,n_jobs=4,random_state=seed)
        t=time.perf_counter();rf.fit(x[ids],y[ids]);training_sec=time.perf_counter()-t
        pd.DataFrame({'feature':FEATURES,'importance':rf.feature_importances_}).sort_values('importance',ascending=False).to_csv(OUT/f'feature_importance_seed{seed}.csv',index=False)
        save_json(OUT/'status.json',dict(status='evaluating',seed=seed,completed=len(records),elapsed_sec=time.time()-started))
        pred=rf.predict(x[test]);cm=confusion_matrix(y[test],pred,labels=[0,1]);m=metrics(cm)
        bench=inference_cost(rf,x[test],seed=42,repeats=5)
        exact_seen=np.isin(feature_hashes[test],np.unique(feature_hashes[ids]))
        sensitivity=[]
        for group,mask in [('all',np.ones(len(test),dtype=bool)),('feature_unseen_in_sampled_training',~exact_seen)]:
            if mask.any(): sensitivity.append(dict(group=group,seed=seed,**metrics(confusion_matrix(y[test][mask],pred[mask],labels=[0,1]))))
        pd.DataFrame(sensitivity).to_csv(OUT/f'sensitivity_seed{seed}.csv',index=False)
        per_source=[]
        for source in sorted(data.source_pcap.unique()):
            mask=data.source_pcap.to_numpy()[test]==source
            details=metrics(confusion_matrix(y[test][mask],pred[mask],labels=[0,1]))
            # Macro F1 is not compared on single-class files; report error rate and counts.
            per_source.append(dict(source_pcap=source,seed=seed,rows=int(mask.sum()),
                binary_label=int(y[test][mask][0]),error_rate=float(np.mean(pred[mask]!=y[test][mask])),
                **{k:details[k] for k in ['tn','fp','fn','tp']}))
        pd.DataFrame(per_source).to_csv(OUT/f'per_source_seed{seed}.csv',index=False)
        local_model=LOCAL/f'rf_baseline_seed{seed}.joblib'
        joblib.dump(dict(model=rf,features=FEATURES,labels={0:'Normal capture',1:'DDoS capture'},protocol=str(protocol_path)),local_model,compress=3)
        loaded=joblib.load(local_model)
        assert loaded['features']==FEATURES
        assert np.array_equal(rf.predict(x[test[:1000]]),loaded['model'].predict(x[test[:1000]]))
        row=dict(seed=seed,n_estimators=100,n_features=len(FEATURES),training_rows=len(ids),training_normal=int((y[ids]==0).sum()),
            training_ddos=int((y[ids]==1).sum()),training_indices_sha256=digest(ids),train_sec=training_sec,
            model_mb=model_size_mb(rf),model_file_mb=local_model.stat().st_size/1e6,**model_stats(rf),**m,**bench,
            feature_seen_test_rows=int(exact_seen.sum()),reload_predictions_match=True)
        assert all(abs(metrics(cm)[k]-row[k])<1e-12 for k in ['f1_macro','accuracy','false_alarm_rate','missed_ddos_rate'])
        records.append(row);pd.DataFrame(records).to_csv(OUT/'runs.csv',index=False)
        print('DONE',seed,'Accuracy',m['accuracy'],'MacroF1',m['f1_macro'],'MB',row['model_mb'],flush=True)
        del rf,loaded,pred;gc.collect()
    df=pd.DataFrame(records)
    columns=['accuracy','f1_macro','benign_precision','benign_recall','recall','false_alarm_rate','missed_ddos_rate','model_mb','infer_us_per_sample','train_sec']
    df[columns].agg(['mean','std']).to_csv(OUT/'summary.csv',index_label='statistic')
    pd.DataFrame({'feature':FEATURES,'train_min':x[train].min(axis=0),'train_max':x[train].max(axis=0)}).to_csv(OUT/'feature_ranges.csv',index=False)
    save_json(OUT/'validation.json',dict(all_input_features_finite=True,train_test_indices_disjoint=True,
        saved_models_reload_predictions_match=True,metrics_recomputed=True,completed_seeds=SEEDS))
    save_json(LOCAL/'MLP_HANDOFF.json',dict(features=FEATURES,X='X.float32.npy',y='y.int8.npy',
        partitions={n:f'{n}_indices.npy' for n in ['train','test','fit','validation']},
        rf_training_indices={str(s):f'rf_train_seed{s}.npy' for s in SEEDS},
        rf_sample_inner_indices={str(s):dict(fit=f'rf_fit_seed{s}.npy',validation=f'rf_validation_seed{s}.npy') for s in SEEDS},
        labels={0:'Normal capture',1:'DDoS capture'},
        rules=['use exactly the same test indices', 'fit scalers/imputation on training only',
               'for equal sample budgets use rf_train_seed42.npy',
               'fit/validation exported for training decisions; a model fitted on fit only has a different budget from final RF training',
               'use this feature order; never include metadata or labels as model input'],
        protocol='results/edge_iiotset_rf/protocol.json'))
    save_json(OUT/'status.json',dict(status='complete',completed_seeds=SEEDS,rows=len(data),elapsed_sec=time.time()-started))
    print('RF_COMPLETE',flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        save_json(OUT/'failure.json',dict(traceback=traceback.format_exc(),stage='RF'))
        raise
