"""Lightweighting sweep: feature count / n_estimators / max_depth / min_samples_leaf.

Each config trains one RF and evaluates it on the test subsets (all / camera / audio / ...),
appending one row per (config, test_subset) to results/tables/sweep_<name>.csv.
Finished configs are skipped (resumable).  Feature ranking comes from a feature-importance CSV
(default: results/tables/rf_v1_feature_importance.csv, the 38-feature baseline).

Usage
  python src/sweep_rf.py --name features --top-k 5 10 15 20 38 --train-subsets all camera audio
  python src/sweep_rf.py --name trees    --top-k 15 --n-estimators 10 20 50 100
  python src/sweep_rf.py --name depth    --top-k 15 --n-estimators 20 --max-depth 8 12 16 0 --min-leaf 1 10 100
(max_depth 0 = unlimited)
"""
import argparse
import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_dataset import FEATURES  # noqa: E402
from metrics import classification_metrics, inference_cost, model_size_mb, model_stats  # noqa: E402
from train_rf import SUBSETS, time_split  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--name', required=True, help='output: results/tables/sweep_<name>.csv')
    ap.add_argument('--data', default=ROOT / 'data/processed/dataset_v1.parquet', type=Path)
    ap.add_argument('--importance', default=ROOT / 'results/tables/rf_v1_feature_importance.csv', type=Path)
    ap.add_argument('--top-k', type=int, nargs='+', default=[38])
    ap.add_argument('--n-estimators', type=int, nargs='+', default=[100])
    ap.add_argument('--max-depth', type=int, nargs='+', default=[0], help='0 = unlimited')
    ap.add_argument('--min-leaf', type=int, nargs='+', default=[1])
    ap.add_argument('--train-subsets', nargs='+', default=['all'], choices=list(SUBSETS))
    ap.add_argument('--test-subsets', nargs='+', default=['all', 'camera', 'audio'], choices=list(SUBSETS))
    ap.add_argument('--train-frac', type=float, default=0.7)
    ap.add_argument('--max-train', type=int, default=1_000_000)
    ap.add_argument('--seed', type=int, default=42)
    a = ap.parse_args()

    out = ROOT / 'results/tables' / f'sweep_{a.name}.csv'
    done = set()
    if out.exists():
        prev = pd.read_csv(out)
        done = set(zip(prev.top_k, prev.n_estimators, prev.max_depth.fillna(0).astype(int), prev.min_leaf,
                       prev.train_subset))
    rank = pd.read_csv(a.importance, index_col=0)['importance'].sort_values(ascending=False)
    rank = [f for f in rank.index if f in FEATURES]

    if not a.data.exists() and a.data.with_name('dataset_v1_parts').exists():
        a.data = a.data.with_name('dataset_v1_parts')
    data = pd.read_parquet(a.data)
    is_train_all = time_split(data, a.train_frac)
    is_test = ~is_train_all
    y = data['binary_label'].to_numpy()
    X_all = data[FEATURES].to_numpy(np.float32)
    feat_idx = {f: i for i, f in enumerate(FEATURES)}
    test_masks = {s: (is_test if SUBSETS[s] is None else is_test & data[SUBSETS[s]].to_numpy())
                  for s in a.test_subsets}
    train_masks = {s: (is_train_all if SUBSETS[s] is None else is_train_all & data[SUBSETS[s]].to_numpy())
                   for s in a.train_subsets}
    del data

    grid = list(itertools.product(a.top_k, a.n_estimators, a.max_depth, a.min_leaf, a.train_subsets))
    print(f'{len(grid)} configs, {len(done)} already done -> {out.name}')
    for k, n_est, depth, leaf, tr_sub in grid:
        key = (k, n_est, depth, leaf, tr_sub)
        if key in done:
            continue
        feats = rank[:k]
        cols = [feat_idx[f] for f in feats]
        rng = np.random.default_rng(a.seed)
        tr_idx = np.flatnonzero(train_masks[tr_sub])
        if len(tr_idx) > a.max_train:
            tr_idx = rng.choice(tr_idx, a.max_train, replace=False)
        rf = RandomForestClassifier(n_estimators=n_est, max_depth=None if depth == 0 else depth,
                                    min_samples_leaf=leaf, class_weight='balanced', n_jobs=-1, random_state=a.seed)
        t = time.time()
        rf.fit(X_all[tr_idx][:, cols], y[tr_idx])
        train_sec = time.time() - t
        size_mb = model_size_mb(rf)
        st = model_stats(rf)
        rows = []
        for ts_sub in a.test_subsets:
            idx = np.flatnonzero(test_masks[ts_sub])
            Xt = X_all[idx][:, cols]
            rf.n_jobs = -1
            m = classification_metrics(y[idx], rf.predict(Xt))
            m.update(inference_cost(rf, Xt, seed=a.seed))
            m.update(dict(sweep=a.name, top_k=k, n_estimators=n_est, max_depth=depth, min_leaf=leaf,
                          train_subset=tr_sub, test_subset=ts_sub, train_rows=len(tr_idx), train_sec=train_sec,
                          model_mb=size_mb, features=';'.join(feats), **st))
            rows.append(m)
            print(f"k={k:2d} trees={n_est:3d} depth={depth:2d} leaf={leaf:3d} train={tr_sub:6s} test={ts_sub:6s} "
                  f"acc={m['accuracy']:.4f} f1m={m['f1_macro']:.4f} rec={m['recall']:.4f} "
                  f"{m['infer_us_per_sample']:.2f}us {size_mb:.1f}MB", flush=True)
        pd.DataFrame(rows).to_csv(out, mode='a', header=not out.exists(), index=False)
        done.add(key)
    print('done:', out)


if __name__ == '__main__':
    main()
