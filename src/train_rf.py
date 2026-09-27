"""Train one Random Forest (DDoS vs Benign) and evaluate it on the full test set and on
device subsets (Camera / Audio / Echo Dot 1 / AMCREST).  Metadata columns are never used as features.

Splits
  time   : per source_pcap, first 70% of windows (by row order) -> train, last 30% -> test
  loao   : leave-one-attack-out; --holdout DDoS-SYN_Flood -> that attack is test-only
           (benign is still split 70/30 in time so both classes appear in the test set)

Usage
  python src/train_rf.py --tag v1
  python src/train_rf.py --tag v1_cam --train-subset camera        # train only on camera windows
  python src/train_rf.py --tag loao_syn --split loao --holdout DDoS-SYN_Flood
"""
import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_dataset import FEATURES  # noqa: E402
from metrics import (classification_metrics, inference_cost, model_size_mb, model_stats,  # noqa: E402
                     peak_rss_mb)

SUBSETS = {'all': None, 'camera': 'has_camera', 'audio': 'has_audio', 'echo_dot1': 'has_echo_dot1',
           'amcrest': 'has_amcrest'}


def time_split(data, train_frac):
    """is_train = row within the first `train_frac` of its source file (row_in_file order)."""
    n_in_file = data.groupby('source_pcap', observed=True)['row_in_file'].transform('max') + 1
    return (data['row_in_file'] < n_in_file * train_frac).to_numpy()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default=ROOT / 'data/processed/dataset_v1.parquet', type=Path)
    ap.add_argument('--tag', default='v1')
    ap.add_argument('--split', choices=['time', 'loao'], default='time')
    ap.add_argument('--holdout', default=None, help='attack_type held out for --split loao')
    ap.add_argument('--train-frac', type=float, default=0.7)
    ap.add_argument('--train-subset', choices=list(SUBSETS), default='all')
    ap.add_argument('--max-train', type=int, default=1_000_000, help='random cap on training rows')
    ap.add_argument('--n-estimators', type=int, default=100)
    ap.add_argument('--max-depth', type=int, default=None)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out-dir', default=ROOT / 'results/tables', type=Path)
    ap.add_argument('--model-dir', default=ROOT / 'results/models', type=Path)
    a = ap.parse_args()

    if not a.data.exists() and a.data.with_name('dataset_v1_parts').exists():
        a.data = a.data.with_name('dataset_v1_parts')   # split copy committed to git (parts < 100 MB)
    data = pd.read_parquet(a.data)
    print(f'rows={len(data):,} features={len(FEATURES)} labels={data.binary_label.value_counts().to_dict()}')
    is_train = time_split(data, a.train_frac)
    if a.split == 'loao':
        if not a.holdout:
            sys.exit('--holdout required for loao')
        held = (data['attack_type'] == a.holdout).to_numpy()
        benign = (data['binary_label'] == 0).to_numpy()
        is_test = held | (~is_train & benign)
        is_train = ~held & (is_train | ~benign)
    else:
        is_test = ~is_train
    if SUBSETS[a.train_subset]:
        is_train = is_train & data[SUBSETS[a.train_subset]].to_numpy()

    rng = np.random.default_rng(a.seed)
    tr_idx = np.flatnonzero(is_train)
    if len(tr_idx) > a.max_train:
        tr_idx = rng.choice(tr_idx, a.max_train, replace=False)
    X = data[FEATURES].to_numpy(np.float32)
    y = data['binary_label'].to_numpy()
    print(f'train rows={len(tr_idx):,} (benign {int((y[tr_idx] == 0).sum()):,}) test rows={int(is_test.sum()):,}')

    rf = RandomForestClassifier(n_estimators=a.n_estimators, max_depth=a.max_depth, class_weight='balanced',
                                n_jobs=-1, random_state=a.seed)
    t = time.time()
    rf.fit(X[tr_idx], y[tr_idx])
    train_sec = time.time() - t
    size_mb = model_size_mb(rf)
    mstats = model_stats(rf)
    print(f'trained in {train_sec:.1f}s, model {size_mb:.1f} MB, {mstats}')

    rows = []
    for name, col in SUBSETS.items():
        mask = is_test if col is None else (is_test & data[col].to_numpy())
        if mask.sum() == 0:
            print(f'  {name}: empty test subset, skipped')
            continue
        idx = np.flatnonzero(mask)
        rf.n_jobs = -1
        pred = rf.predict(X[idx])
        m = classification_metrics(y[idx], pred)
        m.update(inference_cost(rf, X[idx], seed=a.seed))
        m.update(dict(tag=a.tag, split=a.split, holdout=a.holdout or '', train_subset=a.train_subset,
                      test_subset=name, train_rows=len(tr_idx), train_sec=train_sec, model_mb=size_mb,
                      n_features=len(FEATURES), n_estimators=a.n_estimators, max_depth=a.max_depth,
                      peak_rss_mb=peak_rss_mb(), **mstats))
        rows.append(m)
        print(f"  {name:10s} n={m['n']:>9,} acc={m['accuracy']:.4f} f1={m['f1']:.4f} "
              f"f1_macro={m['f1_macro']:.4f} recall={m['recall']:.4f} prec={m['precision']:.4f} "
              f"baseline={m['majority_baseline_acc']:.4f} infer={m['infer_us_per_sample']:.2f} us/sample")

    a.out_dir.mkdir(parents=True, exist_ok=True)
    out = a.out_dir / f'rf_{a.tag}.csv'
    pd.DataFrame(rows).to_csv(out, index=False)
    imp = pd.Series(rf.feature_importances_, index=FEATURES).sort_values(ascending=False)
    imp.to_csv(a.out_dir / f'rf_{a.tag}_feature_importance.csv', header=['importance'])
    a.model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, a.model_dir / f'rf_{a.tag}.joblib', compress=3)
    (a.model_dir / f'rf_{a.tag}.json').write_text(json.dumps(vars(a), default=str, indent=2))
    print(f'\nwrote {out}\ntop features:\n{imp.head(10).to_string()}')


if __name__ == '__main__':
    main()
