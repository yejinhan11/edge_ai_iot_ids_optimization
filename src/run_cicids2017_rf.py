"""Run the authorized full BENIGN/DDoS preparation, audit, and existing RF baseline."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from build_dataset import FEATURES
from prepare_cicids2017 import ALLOWED_LABELS, ROOT, extract
from train_rf import time_split


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-dir', type=Path, default=ROOT / 'data/processed/cicids2017_ddos_benign')
    ap.add_argument('--results-dir', type=Path, default=ROOT / 'results/cicids2017_ddos_benign')
    ap.add_argument('--workers', type=int, default=3, help='Concurrent daily captures; same per-file window order')
    ap.add_argument('--compatible-preparer-sha256', action='append', default=[],
                    help='Explicitly reuse completed outputs of a reviewed, numerically compatible preparer')
    ap.add_argument('--resume-partial', action='store_true')
    a = ap.parse_args()
    a.data_dir.mkdir(parents=True, exist_ok=True)
    a.results_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    previous_path = a.results_dir / 'status.json'
    previous = json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else {}
    first_started = previous.get('first_started_utc', previous.get('started_utc', datetime.now(timezone.utc).isoformat()))
    state = dict(started_utc=datetime.now(timezone.utc).isoformat(), status='running',
                 first_started_utc=first_started, allowed_labels=sorted(ALLOWED_LABELS), data_dir=str(a.data_dir))

    def save_state(**changes):
        state.update(changes)
        state['updated_utc'] = datetime.now(timezone.utc).isoformat()
        temp = a.results_dir / 'status.json.tmp'
        temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
        for attempt in range(20):
            try:
                temp.replace(a.results_dir / 'status.json')
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)

    save_state(stage='extract')
    try:
        pcaps = sorted((ROOT / 'data/raw/cicids2017/pcap').glob('*.pcap'))
        # Validate the actual DDoS capture first, then collect benign controls.
        pcaps.sort(key=lambda p: (not p.name.startswith('Friday'), p.name))
        if len(pcaps) != 5:
            raise ValueError(f'Expected 5 daily captures, got {len(pcaps)}')
        archive = ROOT / 'data/raw/cicids2017/labels/GeneratedLabelledFlows.zip'
        code_hash = hashlib.sha256((ROOT / 'src/prepare_cicids2017.py').read_bytes()).hexdigest()
        pending = []
        for pcap in pcaps:
            metadata = a.data_dir / f'{pcap.stem}.json'
            if metadata.exists():
                old = json.loads(metadata.read_text(encoding='utf-8'))
                if (old.get('code_sha256') not in {code_hash, *a.compatible_preparer_sha256} or old.get('max_packets') != 0
                        or old.get('allowed_labels') != sorted(ALLOWED_LABELS)
                        or old.get('extractor_sha256') != hashlib.sha256((ROOT / 'tools/pcap2csv_metadata_v2/Feature_extraction_fast.py').read_bytes()).hexdigest()
                        or old.get('pcap_bytes') != pcap.stat().st_size
                        or not metadata.with_suffix('.parquet').exists()):
                    raise ValueError(f'Cannot resume incompatible output: {metadata}')
                print(f'Resume: completed {pcap.name}', flush=True)
                continue
            pending.append(pcap)
        save_state(current_pcaps=[p.name for p in pending], workers=a.workers)
        with ProcessPoolExecutor(max_workers=max(1, min(a.workers, len(pending) or 1))) as pool:
            futures = {pool.submit(extract, p, archive, a.data_dir, 20000, 0,
                                   a.resume_partial and (a.data_dir / f'{p.stem}.parquet.part').exists()): p for p in pending}
            for future in as_completed(futures):
                try:
                    future.result()
                except BaseException:
                    traceback.print_exc()
                    raise
                save_state(current_pcaps=[p.name for f, p in futures.items() if not f.done()])
        save_state(stage='audit', current_pcap=None)
        audit = []
        for path in sorted(a.data_dir.glob('*.parquet')):
            # Batch validation keeps the audit memory independent of capture size.
            for batch in pq.ParquetFile(path).iter_batches(batch_size=200000):
                d = batch.to_pandas()
                if not set(d.attack_type).issubset(ALLOWED_LABELS):
                    raise ValueError(f'Unexpected attack type in {path}')
                if not (d.binary_label.to_numpy() == (d.attack_type == 'DDoS').to_numpy()).all():
                    raise ValueError(f'Binary label mismatch in {path}')
                if not (d.window_packet_count == 10).all() or not np.isfinite(d[FEATURES]).all().all():
                    raise ValueError(f'Invalid features or window size in {path}')
            meta = pd.read_parquet(path, columns=['source_pcap', 'row_in_file', 'attack_type', 'binary_label'])
            train = time_split(meta, 0.7)
            for name, mask in [('train_before_cap', train), ('test', ~train)]:
                for label, count in meta.loc[mask, 'attack_type'].value_counts().items():
                    audit.append(dict(source_pcap=path.stem, split=name, label=label, rows=int(count)))
        audit_frame = pd.DataFrame(audit)
        audit_frame.to_csv(a.results_dir / 'strict_time_label_audit.csv', index=False)
        time_group = 'source'
        if any(set(audit_frame.loc[audit_frame.split == name, 'label']) != ALLOWED_LABELS
               for name in ['train_before_cap', 'test']):
            time_group = 'source-label'
            print('Strict per-file time split lacks a class; using chronological 70/30 within source and label. '
                  'There is no common chronological cutoff across labels.', flush=True)
            audit = []
            for path in sorted(a.data_dir.glob('*.parquet')):
                meta = pd.read_parquet(path, columns=['source_pcap', 'row_in_file', 'attack_type', 'binary_label'])
                train = time_split(meta, 0.7, group_label=True)
                for name, mask in [('train_before_cap', train), ('test', ~train)]:
                    for label, count in meta.loc[mask, 'attack_type'].value_counts().items():
                        audit.append(dict(source_pcap=path.stem, split=name, label=label, rows=int(count)))
            audit_frame = pd.DataFrame(audit)
        audit_frame.to_csv(a.results_dir / 'label_audit.csv', index=False)
        for name in ['train_before_cap', 'test']:
            if set(audit_frame.loc[audit_frame.split == name, 'label']) != ALLOWED_LABELS:
                raise ValueError(f'Both BENIGN and DDoS required in {name}')
        save_state(stage='train', time_group=time_group)
        command = [sys.executable, '-u', str(ROOT / 'src/train_rf.py'), '--data', str(a.data_dir),
                   '--tag', 'cicids2017_ddos_benign', '--out-dir', str(a.results_dir / 'tables'),
                   '--time-group', time_group,
                   '--model-dir', str(a.results_dir / 'models')]
        subprocess.run(command, check=True)
        result = pd.read_csv(a.results_dir / 'tables/rf_cicids2017_ddos_benign.csv').iloc[0]
        report = ['# CICIDS2017 BENIGN / DDoS RF', '',
                  'Full five-day PCAPNG extraction. Other attacks, unmatched, ambiguous and mixed windows excluded.', '',
                  f'38 features; non-overlapping 10-packet windows; 70/30 time split, grouping={time_group}; training cap 1,000,000; '
                  '100 trees; balanced; seed 42.', '',
                  f'- Train rows: {int(result.train_rows):,}', f'- Test rows: {int(result.n):,}',
                  f'- Accuracy: {result.accuracy:.8f}', f'- F1 macro: {result.f1_macro:.8f}',
                  f'- DDoS precision: {result.precision:.8f}', f'- DDoS recall: {result.recall:.8f}',
                  f'- DDoS F1: {result.f1:.8f}', f'- Train seconds: {result.train_sec:.2f}',
                  f'- Inference us/sample: {result.infer_us_per_sample:.3f}',
                  f'- Model MB (uncompressed estimate): {result.model_mb:.2f}', '',
                  f'- Wall minutes since initial extraction start: {(time.time()-datetime.fromisoformat(first_started).timestamp())/60:.2f}', '',
                  'Label matching uses time intervals reflecting CSV timestamp precision. '
                  'This does not guarantee exact packet ground truth. Flows may cross the time split boundary.', '',
                  'If grouping=source-label, the strict per-file split lacked a class and was replaced with '
                  'chronological splitting within each file and label. This is not a common chronological holdout; '
                  'see strict_time_label_audit.csv for the unmodified split.', '',
                  'See label_audit.csv, data JSON sidecars, tables/, models/ and run.log for details.']
        (a.results_dir / 'REPORT.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
        save_state(status='complete', stage='complete', elapsed_sec=time.time()-started,
                   wall_elapsed_sec=time.time()-datetime.fromisoformat(first_started).timestamp())
    except BaseException as error:
        save_state(status='failed', error=str(error), elapsed_sec=time.time()-started)
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main()
