"""Collect every results/tables/rf_*.csv into one comparison table (plus the legacy Colab result).

Usage:  python src/compare_results.py            -> results/tables/rf_comparison.csv (and prints it)
"""
import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLS = ['tag', 'split', 'holdout', 'train_subset', 'test_subset', 'train_rows', 'n', 'n_benign', 'n_ddos',
        'accuracy', 'precision', 'recall', 'f1', 'f1_macro', 'majority_baseline_acc',
        'infer_us_per_sample', 'infer_samples_per_sec', 'train_sec', 'model_mb', 'total_nodes', 'peak_rss_mb']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tables', default=ROOT / 'results/tables', type=Path)
    a = ap.parse_args()
    frames = []
    for f in sorted(a.tables.glob('rf_*.csv')):
        if f.name.endswith('_feature_importance.csv') or f.name == 'rf_comparison.csv':
            continue
        d = pd.read_csv(f)
        frames.append(d[[c for c in COLS if c in d.columns]])
    if not frames:
        raise SystemExit('no rf_*.csv found')
    out = pd.concat(frames, ignore_index=True)
    legacy = ROOT / 'data/legacy/rf_full_vs_camera_result.csv'
    if legacy.exists():
        lg = pd.read_csv(legacy, encoding='utf-8-sig')
        lg = pd.DataFrame(dict(tag='legacy_colab', split='time', train_subset=lg.iloc[:, 0], test_subset='',
                               train_rows=lg.iloc[:, 1], n=lg.iloc[:, 2], accuracy=lg.iloc[:, 3],
                               f1_macro=lg.iloc[:, 4], train_sec=lg.iloc[:, 5],
                               infer_us_per_sample=lg.iloc[:, 6] * 1000 / 1000, model_mb=lg.iloc[:, 7]))
        out = pd.concat([out, lg], ignore_index=True)
    out.to_csv(a.tables / 'rf_comparison.csv', index=False)
    pd.set_option('display.width', 200)
    print(out[['tag', 'split', 'train_subset', 'test_subset', 'n', 'accuracy', 'f1', 'f1_macro',
               'majority_baseline_acc', 'infer_us_per_sample', 'model_mb']].to_string(index=False))


if __name__ == '__main__':
    main()
