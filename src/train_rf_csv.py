"""Random Forest on a CICIoT2023 *CSV* dataset (official CIC CSV or a Kaggle re-upload), for cross-checking
against a teammate's MLP that was trained on the same CSV.  Independent of the PCAP pipeline.

What it does
  1. loads every CSV under --data-dir (train/validation/test files if present, otherwise one random split),
     auto-detects the label column and reports class counts per file
  2. leakage checks: exact-duplicate rows inside each file and test rows that also appear in train
  3. trains one RF per task with the same settings as train_rf.py (100 trees, 1M train rows, class_weight=balanced)
       binary  : Benign (0) vs everything else (1)        [--target attack: Benign vs DDoS-only rows]
       category: Benign + 7 attack categories of the paper (8 classes)
       full    : every raw label (34 classes)
  4. writes results/tables/rf_csv_<tag>.csv (one row per task) and per-class reports to
     results/tables/rf_csv_<tag>_<task>_classes.csv

Usage
  python src/train_rf_csv.py --data-dir data/raw/kaggle_himadri07 --tag kaggle
  python src/train_rf_csv.py --data-dir data/raw/kaggle_himadri07 --tag kaggle --tasks binary category
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from metrics import inference_cost, model_size_mb, model_stats, peak_rss_mb  # noqa: E402

LABEL_CANDIDATES = ['label', 'Label', 'attack', 'Attack', 'class', 'Class', 'category', 'Category']
# paper (Neto et al. 2023) grouping of the 33 attacks + Benign into 8 classes
CATEGORY_PREFIX = {'DDoS': 'DDoS', 'DoS': 'DoS', 'Mirai': 'Mirai', 'Recon': 'Recon',
                   'MITM': 'Spoofing', 'DNS_Spoofing': 'Spoofing', 'DictionaryBruteForce': 'BruteForce',
                   'Backdoor_Malware': 'Web', 'BrowserHijacking': 'Web', 'CommandInjection': 'Web',
                   'SqlInjection': 'Web', 'Uploading_Attack': 'Web', 'VulnerabilityScan': 'Web', 'XSS': 'Web',
                   'Benign': 'Benign'}


def to_category(label):
    for prefix, cat in CATEGORY_PREFIX.items():
        if str(label).startswith(prefix):
            return cat
    return 'Other'


def find_label_column(df):
    for c in LABEL_CANDIDATES:
        if c in df.columns:
            return c
    obj = [c for c in df.columns if df[c].dtype == object]
    if len(obj) == 1:
        return obj[0]
    sys.exit(f'cannot find label column; columns = {list(df.columns)}')


def load_dir(data_dir, nrows):
    files = sorted(p for p in Path(data_dir).glob('**/*.csv'))
    if not files:
        sys.exit(f'no csv under {data_dir}')
    parts = {}
    for p in files:
        t = time.time()
        d = pd.read_csv(p, nrows=nrows, low_memory=False)
        d.columns = [c.strip() for c in d.columns]
        role = next((r for r in ['train', 'val', 'test'] if r in p.name.lower()), p.stem)
        parts[role] = d
        print(f'  {p.name}: {d.shape[0]:,} rows x {d.shape[1]} cols ({time.time() - t:.0f}s) -> role={role}')
    return parts


def split_frames(parts, seed):
    """Use train/test files when present (val is merged into train); otherwise random 70/30."""
    if 'train' in parts and 'test' in parts:
        tr = pd.concat([parts['train']] + [parts[k] for k in parts if k == 'val'], ignore_index=True)
        return tr, parts['test'], 'files (train+val / test)'
    d = pd.concat(parts.values(), ignore_index=True)
    rng = np.random.default_rng(seed)
    m = rng.random(len(d)) < 0.7
    return d[m].reset_index(drop=True), d[~m].reset_index(drop=True), 'random 70/30'


def leakage_report(tr, te, label):
    feats = [c for c in tr.columns if c != label]
    out = {}
    for name, d in [('train', tr), ('test', te)]:
        dup = d.duplicated(subset=feats).mean()
        out[f'{name}_dup_rows_frac'] = float(dup)
        print(f'  {name}: exact-duplicate rows (features only) = {dup:.1%}')
    # test rows whose feature vector also occurs in train (hash of the row)
    h_tr = pd.util.hash_pandas_object(tr[feats], index=False)
    h_te = pd.util.hash_pandas_object(te[feats], index=False)
    overlap = h_te.isin(set(h_tr.values)).mean()
    out['test_rows_also_in_train_frac'] = float(overlap)
    print(f'  test rows whose feature vector also appears in train = {overlap:.1%}')
    const = [c for c in feats if tr[c].nunique(dropna=False) <= 1]
    out['constant_features'] = ';'.join(const)
    print(f'  constant features in train: {const}')
    return out


def run_task(task, tr, te, label, a):
    if task == 'binary':
        ytr, yte = (tr[label] != 'BenignTraffic').astype(int), (te[label] != 'BenignTraffic').astype(int)
        names = ['Benign', 'Attack']
    elif task == 'attack':
        m_tr = (tr[label] == 'BenignTraffic') | tr[label].str.startswith('DDoS')
        m_te = (te[label] == 'BenignTraffic') | te[label].str.startswith('DDoS')
        tr, te = tr[m_tr], te[m_te]
        ytr, yte = (tr[label] != 'BenignTraffic').astype(int), (te[label] != 'BenignTraffic').astype(int)
        names = ['Benign', 'DDoS']
    elif task == 'category':
        ytr, yte = tr[label].map(to_category), te[label].map(to_category)
        names = sorted(set(ytr) | set(yte))
    else:
        ytr, yte = tr[label], te[label]
        names = sorted(set(ytr) | set(yte))
    feats = [c for c in tr.columns if c != label]
    Xtr = tr[feats].to_numpy(np.float32)
    Xte = te[feats].to_numpy(np.float32)
    Xtr, Xte = np.nan_to_num(Xtr, nan=0, posinf=np.finfo(np.float32).max, neginf=0), \
        np.nan_to_num(Xte, nan=0, posinf=np.finfo(np.float32).max, neginf=0)
    ytr, yte = np.asarray(ytr), np.asarray(yte)

    rng = np.random.default_rng(a.seed)
    idx = np.arange(len(Xtr))
    if len(idx) > a.max_train:
        idx = rng.choice(idx, a.max_train, replace=False)
    rf = RandomForestClassifier(n_estimators=a.n_estimators, class_weight='balanced', n_jobs=-1, random_state=a.seed)
    t = time.time()
    rf.fit(Xtr[idx], ytr[idx])
    train_sec = time.time() - t
    pred = rf.predict(Xte)

    rep = classification_report(yte, pred, output_dict=True, zero_division=0)
    cls = pd.DataFrame({k: v for k, v in rep.items() if isinstance(v, dict) and k not in ('macro avg', 'weighted avg')}).T
    cls.index.name = 'class'
    cls.to_csv(a.out_dir / f'rf_csv_{a.tag}_{task}_classes.csv')
    row = dict(tag=a.tag, task=task, n_classes=len(set(ytr)), train_rows=len(idx), test_rows=len(yte),
               accuracy=accuracy_score(yte, pred), f1_macro=f1_score(yte, pred, average='macro', zero_division=0),
               f1_weighted=f1_score(yte, pred, average='weighted', zero_division=0),
               majority_baseline_acc=float(pd.Series(yte).value_counts(normalize=True).iloc[0]),
               n_features=len(feats), n_estimators=a.n_estimators, train_sec=train_sec,
               model_mb=model_size_mb(rf), peak_rss_mb=peak_rss_mb(), **model_stats(rf))
    if task in ('binary', 'attack'):
        pos = 1
        row.update(precision=rep['1']['precision'], recall=rep['1']['recall'], f1=rep['1']['f1-score'],
                   benign_recall=rep['0']['recall'])
    row.update(inference_cost(rf, Xte, seed=a.seed))
    imp = pd.Series(rf.feature_importances_, index=feats).sort_values(ascending=False)
    imp.to_csv(a.out_dir / f'rf_csv_{a.tag}_{task}_feature_importance.csv', header=['importance'])
    print(f"  {task:9s} classes={row['n_classes']:>2} acc={row['accuracy']:.4f} f1_macro={row['f1_macro']:.4f} "
          f"baseline={row['majority_baseline_acc']:.4f} train={train_sec:.0f}s model={row['model_mb']:.1f}MB "
          f"infer={row['infer_us_per_sample']:.1f}us")
    print('    weakest classes (F1):', cls['f1-score'].sort_values().head(3).round(3).to_dict())
    print('    top features:', ', '.join(imp.head(8).index))
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data-dir', required=True, type=Path)
    ap.add_argument('--tag', default='csv')
    ap.add_argument('--tasks', nargs='+', default=['binary', 'attack', 'category', 'full'],
                    choices=['binary', 'attack', 'category', 'full'])
    ap.add_argument('--max-train', type=int, default=1_000_000)
    ap.add_argument('--n-estimators', type=int, default=100)
    ap.add_argument('--nrows', type=int, default=None, help='read only the first N rows of each file (smoke test)')
    ap.add_argument('--drop-test-overlap', action='store_true',
                    help='evaluate only on test rows whose feature vector does not occur in train')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out-dir', default=ROOT / 'results/tables', type=Path)
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)

    print('loading')
    parts = load_dir(a.data_dir, a.nrows)
    label = find_label_column(next(iter(parts.values())))
    print(f'label column = {label!r}')
    for role, d in parts.items():
        vc = d[label].value_counts()
        print(f'  {role}: {len(vc)} classes; Benign={vc.get("BenignTraffic", 0):,} '
              f'({vc.get("BenignTraffic", 0) / len(d):.2%}); top: {vc.head(5).to_dict()}')
    tr, te, how = split_frames(parts, a.seed)
    print(f'split = {how}: train {len(tr):,} / test {len(te):,}')
    feats = [c for c in tr.columns if c != label]
    print(f'{len(feats)} features: {feats}')

    print('leakage checks')
    leak = leakage_report(tr, te, label)
    if a.drop_test_overlap:
        h_tr = set(pd.util.hash_pandas_object(tr[feats], index=False).values)
        keep = ~pd.util.hash_pandas_object(te[feats], index=False).isin(h_tr).to_numpy()
        te = te[keep].reset_index(drop=True)
        print(f'  dropped overlapping test rows -> test {len(te):,}')

    rows = [run_task(t, tr, te, label, a) for t in a.tasks]
    out = pd.DataFrame(rows)
    for k, v in leak.items():
        out[k] = v
    out['split'] = how
    out.to_csv(a.out_dir / f'rf_csv_{a.tag}.csv', index=False)
    (a.out_dir / f'rf_csv_{a.tag}.json').write_text(json.dumps(dict(vars(a), label=label, features=feats, **leak),
                                                               default=str, indent=2))
    print(f'\nwrote {a.out_dir / f"rf_csv_{a.tag}.csv"}')


if __name__ == '__main__':
    main()
