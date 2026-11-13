"""Validation-selected, resumable RF compression on the archived CICIoT2023 data."""
import gc
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

from build_dataset import FEATURES
from metrics import inference_cost, model_size_mb, model_stats
from run_ciciot2023_balanced_rf import metrics, digest
from train_rf import time_split

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/ciciot2023_rf_further'
LOCAL = ROOT / 'data/processed/ciciot2023_rf_further'
SEEDS = [42, 43, 44]
LIMITS = dict(f1_macro_drop=0.005, fpr_increase=0.001, fnr_increase=0.001)


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def config(trees, depth=0, leaf=1):
    return dict(candidate=f't{trees}_d{depth}_l{leaf}', trees=trees, depth=depth, leaf=leaf)


def passes(row, base):
    return (row['f1_macro'] >= base['f1_macro'] - LIMITS['f1_macro_drop']
            and row['false_alarm_rate'] <= base['false_alarm_rate'] + LIMITS['fpr_increase']
            and row['missed_ddos_rate'] <= base['missed_ddos_rate'] + LIMITS['fnr_increase'])


def main():
    start = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if (OUT/'protocol.json').exists():
        old = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
        if old['code_hash'] != code_hash:
            raise RuntimeError('Code hash changed; use a new output directory or review checkpoint compatibility.')
    write_json(OUT/'status.json', dict(status='loading'))
    meta = pd.read_parquet(ROOT/'data/processed/dataset_v1_parts',
                           columns=['source_pcap', 'row_in_file', 'binary_label'])
    y = meta.binary_label.to_numpy(copy=True)
    outer = time_split(meta, .7)
    fit_mask = time_split(meta, .56)
    fit_pool = np.flatnonzero(fit_mask)
    val = np.flatnonzero(outer & ~fit_mask)
    test = np.flatnonzero(~outer)
    full_pool = np.flatnonzero(outer)
    assert len(meta) == 20_990_150 and len(test) == 6_297_039
    assert not np.any(fit_mask & ~outer)
    assert len(fit_pool)+len(val)+len(test) == len(meta)
    cache = ROOT/'data/processed/ciciot2023_balanced_rf/features.float32'
    archived = json.loads((ROOT/'results/ciciot2023_balanced_rf/protocol.json').read_text(encoding='utf-8'))
    assert digest(test) == archived['test_sha256'] and FEATURES == archived['features']
    assert cache.stat().st_size == len(y)*len(FEATURES)*4
    x = np.memmap(cache, dtype='float32', mode='r', shape=(len(y), len(FEATURES)))
    protocol = dict(code_hash=code_hash, dataset='CICIoT2023 archived PCAP-derived dataset_v1_parts',
        limitations=['first 2GB chunks except HTTP_Flood, SlowLoris, BenignTraffic3',
                     'historically observed test; not a fresh independent holdout',
                     'same-capture temporal split; no connection-level purge or external validation',
                     'serialized model MB is not RAM; feature extraction excluded from inference'],
        features=FEATURES, class_weight='balanced', training_cap=1000000,
        split='per-source first 56% fit, next 14% validation, last 30% historical test; final refit first 70%',
        selection='seed42 baseline and tree sweep 5/10/15/20; two smallest passing tree counts (fallback highest macro F1); depths 16/20/24/unlimited and leaves 1/5/10; top three passing configurations by size then latency; 3-seed validation, then freeze selection before test',
        acceptance='each seed must pass its matching 100-tree baseline on validation; final test does not change selection',
        limits=LIMITS, targets=dict(primary_mb=15, stretch_mb=10, latency_ratio_to_c1=.7),
        benchmark='single-thread predict, fixed 100000 rows per partition, 5-repeat median after warmup; batch amortized us/row',
        seeds=SEEDS, python=sys.version, sklearn=sklearn.__version__, platform=platform.platform(),
        cache_origin='existing balanced-rf cache; shape, feature order and test index hash checked; per-file feature probe checked',
        partitions={name:dict(rows=len(ids),benign=int((y[ids]==0).sum()),ddos=int((y[ids]==1).sum()),sha256=digest(ids))
                    for name,ids in [('fit_pool',fit_pool),('validation',val),('test',test),('refit_pool',full_pool)]})
    # Validate cache ordering against each parquet file, without rebuilding the cache.
    import pyarrow.parquet as pq
    offset = 0
    for path in sorted((ROOT/'data/processed/dataset_v1_parts').glob('*.parquet')):
        pf = pq.ParquetFile(path)
        batch = next(pf.iter_batches(batch_size=8, columns=FEATURES))
        probe = np.column_stack([c.to_numpy(zero_copy_only=False) for c in batch.columns]).astype('float32')
        assert np.array_equal(x[offset:offset+len(probe)],probe), path
        offset += pf.metadata.num_rows
    assert offset == len(y)
    write_json(OUT/'protocol.json', protocol)
    audit=[]
    for source, group in meta.groupby('source_pcap', observed=True):
        ids=group.index.to_numpy()
        for name,mask in [('fit',fit_mask),('validation',outer & ~fit_mask),('test',~outer)]:
            labels=y[ids[mask[ids]]]
            audit.append(dict(source=source,partition=name,rows=len(labels),benign=int((labels==0).sum()),ddos=int((labels==1).sum())))
    pd.DataFrame(audit).to_csv(OUT/'partition_audit.csv',index=False)
    del meta,fit_mask,outer
    gc.collect()
    records = pd.read_csv(OUT/'runs.csv').to_dict('records') if (OUT/'runs.csv').exists() else []
    samples={}

    def run(stage, cfg, seed):
        for r in records:
            if r['stage']==stage and r['candidate']==cfg['candidate'] and int(r['seed'])==seed:
                return r
        pool, evaluation = (fit_pool,val) if stage=='validation' else (full_pool,test)
        key=(stage,seed)
        if key not in samples:
            ids=np.random.default_rng(seed).choice(pool,1000000,replace=False)
            np.save(LOCAL/f'{stage}_train_seed{seed}.npy',ids)
            samples[key]=(ids,np.ascontiguousarray(x[ids]))
        ids,xt=samples[key]
        write_json(OUT/'status.json',dict(status='running',stage=stage,candidate=cfg['candidate'],seed=seed,completed=len(records),elapsed_sec=time.time()-start))
        print('FIT',stage,cfg['candidate'],seed,flush=True)
        rf=RandomForestClassifier(n_estimators=cfg['trees'],max_depth=cfg['depth'] or None,
            min_samples_leaf=cfg['leaf'],class_weight='balanced',n_jobs=4,random_state=seed)
        t=time.perf_counter(); rf.fit(xt,y[ids]); train_sec=time.perf_counter()-t
        cm=np.zeros((2,2),dtype=np.int64)
        for pos in range(0,len(evaluation),200000):
            ei=evaluation[pos:pos+200000]
            cm+=confusion_matrix(y[ei],rf.predict(x[ei]),labels=[0,1])
        bi=np.random.default_rng(42).choice(evaluation,100000,replace=False)
        bench=inference_cost(rf,np.ascontiguousarray(x[bi]),n_samples=100000,repeats=5,seed=42)
        row=dict(stage=stage,seed=seed,**cfg,train_sec=train_sec,train_rows=len(ids),
                 train_indices_sha256=digest(ids),model_mb=model_size_mb(rf),**metrics(cm),**model_stats(rf),**bench)
        if stage=='test':
            path=LOCAL/f'{cfg["candidate"]}_seed{seed}.joblib'
            joblib.dump(dict(model=rf,features=FEATURES,protocol=str(OUT/'protocol.json')),path,compress=3)
            loaded=joblib.load(path)['model']
            assert np.array_equal(rf.predict(x[bi[:1000]]),loaded.predict(x[bi[:1000]]))
            row.update(model_file_mb=path.stat().st_size/1e6,reload_verified=True)
            del loaded
        records.append(row)
        pd.DataFrame(records).to_csv(OUT/'runs.csv',index=False)
        print('DONE',stage,cfg['candidate'],seed,'F1',round(row['f1_macro'],6),'MB',round(row['model_mb'],3),'us',round(row['infer_us_per_sample'],3),flush=True)
        del rf; gc.collect()
        return row

    baseline=config(100)
    c1=config(20)
    base=run('validation',baseline,42)
    tree_rows=[run('validation',config(t),42) for t in [5,10,15,20]]
    good=[r for r in tree_rows if passes(r,base)]
    chosen=sorted(good,key=lambda r:r['trees'])[:2]
    if len(chosen)<2:
        chosen += [r for r in sorted(tree_rows,key=lambda r:-r['f1_macro']) if r not in chosen][:2-len(chosen)]
    for t in [r['trees'] for r in chosen]:
        for depth in [0,16,20,24]:
            for leaf in [1,5,10]:
                run('validation',config(t,depth,leaf),42)
    eligible=[r for r in records if r['stage']=='validation' and int(r['seed'])==42
              and r['candidate']!=baseline['candidate'] and passes(r,base)]
    finalists=sorted(eligible,key=lambda r:(r['model_mb'],r['infer_us_per_sample']))[:3]
    configs=[{k:r[k] for k in ['candidate','trees','depth','leaf']} for r in finalists]
    for cfg in configs:
        cfg.update({k:int(cfg[k]) for k in ['trees','depth','leaf']})
    # Release per-seed training matrices between stages to bound memory use.
    samples.clear(); gc.collect()
    validation=[]
    for seed in SEEDS:
        b=run('validation',baseline,seed)
        run('validation',c1,seed)
        for cfg in configs:
            r=run('validation',cfg,seed)
            validation.append(dict(candidate=cfg['candidate'],seed=seed,passes=passes(r,b)))
        samples.clear(); gc.collect()
    valid_names=[c['candidate'] for c in configs if all(r['passes'] for r in validation if r['candidate']==c['candidate'])]
    if (OUT/'selection.json').exists():
        prior=json.loads((OUT/'selection.json').read_text(encoding='utf-8'))
        assert prior['valid_names']==valid_names
    selected=next((c for c in configs if c['candidate'] in valid_names),c1)
    write_json(OUT/'selection.json',dict(selected=selected,finalists=configs,valid_names=valid_names,
        per_seed_checks=validation,fallback_to_c1=not bool(valid_names),frozen_before_test=True))
    final_configs={c['candidate']:c for c in [baseline,c1]+configs}
    for seed in SEEDS:
        for cfg in final_configs.values():
            run('test',cfg,seed)
        samples.clear(); gc.collect()
    df=pd.DataFrame(records)
    measures=['accuracy','f1_macro','false_alarm_rate','missed_ddos_rate','model_mb','infer_us_per_sample','train_sec','total_nodes']
    summary=df.groupby(['stage','candidate'])[measures].agg(['mean','std'])
    summary.columns=['_'.join(c) for c in summary.columns]
    summary.reset_index().to_csv(OUT/'summary.csv',index=False)
    comparisons=[]
    for seed in SEEDS:
        rows=df[(df.stage=='test') & (df.seed==seed)].set_index('candidate')
        b=rows.loc[baseline['candidate']]; control=rows.loc[c1['candidate']]
        for name,r in rows.iterrows():
            comparisons.append(dict(seed=seed,candidate=name,performance_pass=passes(r,b),
                f1_drop=b.f1_macro-r.f1_macro,fpr_increase=r.false_alarm_rate-b.false_alarm_rate,
                fnr_increase=r.missed_ddos_rate-b.missed_ddos_rate,
                size_ratio_to_baseline=r.model_mb/b.model_mb,size_ratio_to_c1=r.model_mb/control.model_mb,
                latency_ratio_to_c1=r.infer_us_per_sample/control.infer_us_per_sample,
                primary_size_met=r.model_mb<=15,stretch_size_met=r.model_mb<=10,
                speed_target_met=r.infer_us_per_sample<=.7*control.infer_us_per_sample))
    pd.DataFrame(comparisons).to_csv(OUT/'comparisons.csv',index=False)
    write_json(OUT/'validation.json',dict(partitions_disjoint=True,cache_file_probes_match=True,
        test_hash_matches_archive=True,test_rows=len(test),all_test_models_reload_verified=True,
        selection_frozen_before_test=True,limits=LIMITS))
    write_json(OUT/'status.json',dict(status='complete',completed=len(records),selected=selected,elapsed_sec=time.time()-start))
    print('COMPLETE',selected,flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception:
        import traceback
        OUT.mkdir(parents=True,exist_ok=True)
        write_json(OUT/'failure.json',dict(traceback=traceback.format_exc()))
        raise
