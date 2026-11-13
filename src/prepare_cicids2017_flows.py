"""Prepare native CICFlowMeter statistics for BENIGN/DDoS RF, excluding identifiers.

Whole-day 5-tuple groups stay in one partition. Feature-identical duplicates are
removed globally before partitioning; conflicting labels for identical features
are excluded. Non-finite numeric values are left missing for fit-only imputation.
"""
from collections import Counter
import gc
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import pandas as pd

from prepare_cicids2017 import ROOT, label_time

EXCLUDE = {'Flow ID', 'Source IP', 'Source Port', 'Destination IP', 'Destination Port',
           'Timestamp', 'Label', 'Fwd Header Length.1'}


def prepare(out_dir=None):
    out_dir = Path(out_dir or ROOT / 'data/processed/cicids2017_native_flows')
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / 'flows.parquet'
    if target.exists():
        return target
    started = time.time()
    stats, frames, features = Counter(), [], None
    archive = ROOT / 'data/raw/cicids2017/labels/GeneratedLabelledFlows.zip'
    with zipfile.ZipFile(archive) as z:
        for name in sorted(n for n in z.namelist() if n.endswith('.csv')):
            print(f'Native flows: {name}', flush=True)
            offset = 0
            with z.open(name) as f:
                for d in pd.read_csv(f, chunksize=100000, low_memory=False, encoding_errors='replace'):
                    d.columns = d.columns.str.strip()
                    stats['raw_rows'] += len(d)
                    d['raw_row'] = np.arange(offset, offset + len(d))
                    offset += len(d)
                    labels = d.Label.astype('string').str.strip()
                    keep = labels.isin(['BENIGN', 'DDoS'])
                    stats['other_or_missing_label'] += int((~keep).sum())
                    d = d.loc[keep].copy()
                    d['binary_label'] = (labels.loc[keep] == 'DDoS').astype(np.int8)
                    if d.empty:
                        continue
                    current = [c for c in d.columns if c not in EXCLUDE | {'raw_row', 'binary_label'}]
                    if features is None:
                        features = current
                    if current != features:
                        raise ValueError(f'Inconsistent feature schema: {name}')
                    missing = d[['Source IP', 'Source Port', 'Destination IP', 'Destination Port',
                                 'Protocol', 'Timestamp', 'Flow Duration']].isna().any(axis=1)
                    stats['missing_identity_or_time'] += int(missing.sum())
                    d = d.loc[~missing].copy()
                    numeric = d[features].apply(pd.to_numeric, errors='coerce')
                    invalid_duration = ~np.isfinite(numeric['Flow Duration']) | (numeric['Flow Duration'] < 0)
                    stats['invalid_duration'] += int(invalid_duration.sum())
                    d, numeric = d.loc[~invalid_duration].copy(), numeric.loc[~invalid_duration].copy()
                    numeric = numeric.replace([np.inf, -np.inf], np.nan)
                    stats['numeric_missing_cells'] += int(numeric.isna().sum().sum())
                    numeric = numeric.astype(np.float32)
                    numeric['binary_label'] = d.binary_label
                    numeric['source_pcap'] = Path(name).name.split('-')[0] + '-WorkingHours.pcap'
                    numeric['row_in_file'] = d.raw_row
                    stamps = d.Timestamp.astype(str).str.strip()
                    lookup = {s: label_time(s)[0] for s in stamps.unique()}
                    numeric['window_start_ts'] = stamps.map(lookup).astype(float)
                    a = d['Source IP'].astype(str) + ':' + d['Source Port'].astype(int).astype(str)
                    b = d['Destination IP'].astype(str) + ':' + d['Destination Port'].astype(int).astype(str)
                    pair = pd.Series(np.where(a <= b, a + '|' + b, b + '|' + a), index=d.index)
                    identity = numeric.source_pcap + '|' + pair + '|' + d.Protocol.astype(int).astype(str)
                    numeric['split_group'] = pd.util.hash_pandas_object(identity, index=False).to_numpy()
                    frames.append(numeric)
    data = pd.concat(frames, ignore_index=True)
    del frames
    gc.collect()
    data = data.sort_values(['window_start_ts', 'source_pcap', 'row_in_file'], kind='stable').reset_index(drop=True)
    fingerprint = pd.util.hash_pandas_object(data[features], index=False)
    conflict_table = pd.DataFrame({'hash': fingerprint, 'y': data.binary_label})
    conflict_hashes = conflict_table.groupby('hash', sort=False).y.nunique()
    conflict_hashes = conflict_hashes.index[conflict_hashes > 1]
    conflict = fingerprint.isin(conflict_hashes)
    stats['feature_identical_conflicting_label_rows'] = int(conflict.sum())
    duplicate = fingerprint.duplicated(keep='first') & ~conflict
    stats['feature_identical_duplicate_rows'] = int(duplicate.sum())
    data = data.loc[~conflict & ~duplicate].reset_index(drop=True)
    stats['rows_written'] = len(data)
    stats['benign_written'] = int((data.binary_label == 0).sum())
    stats['ddos_written'] = int((data.binary_label == 1).sum())
    data.to_parquet(target, index=False)
    manifest = dict(features=features, n_features=len(features), excluded_columns=sorted(EXCLUDE),
                    counts=dict(stats), elapsed_sec=time.time() - started,
                    grouping='whole-day bidirectional 5-tuple, including both labels in same group',
                    deduplication='global numeric-feature hashes; conflicting labels excluded; earliest duplicate kept',
                    imputation='not performed here; median fitted on training partition only',
                    source='https://www.unb.ca/cic/datasets/ids-2017.html')
    target.with_suffix('.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest['counts']), flush=True)
    return target


if __name__ == '__main__':
    prepare()
