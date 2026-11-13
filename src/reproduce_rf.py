"""Re-run archived RF configurations without overwriting the original results.

Run from the repository root: python -u src/reproduce_rf.py
Equivalent configurations share a fit; feature order is part of the cache key.
"""
import gc
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow
import sklearn
from sklearn.ensemble import RandomForestClassifier

from build_dataset import FEATURES
from metrics import classification_metrics, inference_cost, model_size_mb, model_stats, peak_rss_mb
from train_rf import SUBSETS, time_split

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/reproduction_20261025'
TABLES = ROOT / 'results/tables'
STABLE = ['n', 'n_benign', 'n_ddos', 'train_rows', 'accuracy', 'precision', 'recall',
          'f1', 'f1_macro', 'majority_baseline_acc', 'tn', 'fp', 'fn', 'tp',
          'n_trees', 'total_nodes', 'tree_max_depth']
VARIABLE = ['train_sec', 'infer_us_per_sample', 'model_mb', 'peak_rss_mb']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = [TABLES / 'rf_v1.csv'] + sorted(
        p for p in TABLES.glob('rf_*.csv')
        if p.name not in ['rf_v1.csv', 'rf_comparison.csv']
        and not p.name.endswith('_feature_importance.csv'))
    files += sorted(TABLES.glob('sweep_*.csv'))
    manifest = dict(python=sys.version, platform=platform.platform(), numpy=np.__version__,
                    pandas=pd.__version__, sklearn=sklearn.__version__, pyarrow=pyarrow.__version__,
                    seed=42, train_frac=0.7, class_weight='balanced',
                    limitations=['Original dependency versions and row-level predictions are unavailable.',
                                 'Defaults seed=42/train_frac=0.7 inferred from repository scripts.',
                                 'Matching aggregate metrics does not prove identical predictions.',
                                 'Timing is measured once per unique configuration; equivalent archived runs share it.'],
                    input_sha256={})
    for p in files + [Path(__file__), ROOT / 'src/train_rf.py', ROOT / 'src/sweep_rf.py']:
        manifest['input_sha256'][str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT / 'environment.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    cols = FEATURES + ['source_pcap', 'attack_type', 'binary_label', 'row_in_file'] + [
        c for c in SUBSETS.values() if c]
    print('Loading processed dataset...', flush=True)
    data = pd.read_parquet(ROOT / 'data/processed/dataset_v1_parts', columns=cols)
    base_train = time_split(data, 0.7)
    X = data[FEATURES].to_numpy(np.float32)
    y = data.binary_label.to_numpy().copy()
    attacks = data.attack_type.copy()
    sources = data.source_pcap.copy()
    tags = {s: data[c].to_numpy().copy() for s, c in SUBSETS.items() if c}
    # The early three-file experiment used the same cleaned rows, before other files were added.
    test3_files = pd.read_csv(TABLES / 'dataset_test3_summary.csv')['file'].str.replace(
        '_meta.csv', '.pcap', regex=False)
    test3 = sources.isin(test3_files).to_numpy()
    del data
    gc.collect()
    print(f'Loaded {len(y):,} rows; early test3 subset {test3.sum():,} rows', flush=True)
    rank = pd.read_csv(TABLES / 'rf_v1_feature_importance.csv', index_col=0).importance.sort_values(
        ascending=False).index.tolist()
    cache = {}
    comparisons = []
    counts = []
    for file in files:
        old = pd.read_csv(file)
        records = []
        for _, row in old.iterrows():
            sweep = file.name.startswith('sweep_')
            early = file.stem == 'rf_test3'
            k = int(row.get('top_k', row.get('n_features', len(FEATURES))))
            # train_rf keeps official feature order unless top-k is explicitly requested.
            feats = str(row['features']).split(';') if sweep else (
                [f for f in rank if f in FEATURES][:k] if k < len(FEATURES) else FEATURES)
            depth = row.get('max_depth', np.nan)
            depth = None if pd.isna(depth) or depth == 0 else int(depth)
            leaf = int(row.get('min_leaf', 1))
            split = row.get('split', 'time')
            holdout = row.get('holdout', '')
            holdout = '' if pd.isna(holdout) else str(holdout)
            trsub, tesub = row.train_subset, row.test_subset
            ntrain = int(row.train_rows)
            key = (early, tuple(feats), int(row.n_estimators), depth, leaf, split, holdout, trsub, ntrain)
            digest = hashlib.sha256(repr(key).encode()).hexdigest()[:20]
            cache_path = OUT / f'config_{digest}.json'
            if key not in cache:
                if cache_path.exists():
                    cache[key] = json.loads(cache_path.read_text())
                else:
                    tr = base_train.copy()
                    te = ~base_train
                    if early:
                        tr &= test3
                        te &= test3
                    if split == 'loao':
                        held = (attacks == holdout).to_numpy()
                        benign = y == 0
                        te = held | (~base_train & benign)
                        tr = ~held & (base_train | ~benign)
                    if trsub != 'all':
                        tr &= tags[trsub]
                    idx = np.flatnonzero(tr)
                    if len(idx) > ntrain:
                        idx = np.random.default_rng(42).choice(idx, ntrain, replace=False)
                    indices = [FEATURES.index(f) for f in feats]
                    rf = RandomForestClassifier(n_estimators=int(row.n_estimators), max_depth=depth,
                                                min_samples_leaf=leaf, class_weight='balanced',
                                                random_state=42, n_jobs=-1)
                    print(f'FIT {file.name}: features={len(feats)} trees={row.n_estimators} '
                          f'depth={depth} leaf={leaf} subset={trsub} split={split}/{holdout}', flush=True)
                    start = time.perf_counter()
                    rf.fit(X[idx][:, indices], y[idx])
                    elapsed = time.perf_counter() - start
                    common = dict(train_sec=elapsed, train_rows=len(idx), model_mb=model_size_mb(rf),
                                  **model_stats(rf))
                    evaluations = {}
                    # Include all subsets so equivalent archived runs can reuse the same model.
                    for subset in SUBSETS:
                        mask = te if subset == 'all' else te & tags[subset]
                        test_idx = np.flatnonzero(mask)
                        if not len(test_idx):
                            continue
                        xt = X[test_idx][:, indices]
                        rf.n_jobs = -1
                        met = classification_metrics(y[test_idx], rf.predict(xt))
                        met.update(inference_cost(rf, xt, seed=42))
                        met.update(common)
                        met['peak_rss_mb'] = peak_rss_mb()
                        evaluations[subset] = met
                        del xt
                    cache_path.write_text(json.dumps(evaluations, indent=2), encoding='utf-8')
                    cache[key] = evaluations
                    del rf
                    gc.collect()
            new = cache[key][tesub]
            records.append(dict(row.to_dict(), **new))
            for metric in STABLE + VARIABLE:
                if metric not in row or metric not in new or pd.isna(row[metric]):
                    continue
                before, after = float(row[metric]), float(new[metric])
                comparisons.append(dict(file=file.name, row=int(row.name), test_subset=tesub,
                                        metric=metric, original=before, rerun=after,
                                        delta=after-before, exact_match=before == after,
                                        within_1e_12=abs(after-before) <= 1e-12,
                                        category='stable' if metric in STABLE else 'environment'))
        pd.DataFrame(records).to_csv(OUT / file.name, index=False)
        comp = pd.DataFrame(comparisons)
        comp.to_csv(OUT / 'comparison.csv', index=False)
        counts.append(dict(file=file.name, rows=len(records)))
        stable = comp[(comp.file == file.name) & (comp.category == 'stable')]
        print(f'COMPARED {file.name}: {stable.exact_match.sum()}/{len(stable)} exact, '
              f'{stable.within_1e_12.sum()}/{len(stable)} within 1e-12', flush=True)
    summary = dict(files=counts, unique_fits=len(cache),
                   stable_checks=int((comp.category == 'stable').sum()),
                   exact_matches=int(comp.loc[comp.category == 'stable', 'exact_match'].sum()),
                   within_1e_12=int(comp.loc[comp.category == 'stable', 'within_1e_12'].sum()))
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print('DONE', json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
