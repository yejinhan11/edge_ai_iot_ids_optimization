"""PCAP -> official CICIoT2023 39 features + window MAC metadata, one CSV per pcap.

Pipeline per pcap (resumable: a finished pcap has a .json sidecar and is skipped):
  1. split_pcap.split_pcap()      pcap -> data/tmp/<name>/partNNNN.pcap  (N accepted packets each,
                                  cut on a 10-packet boundary so no window straddles a chunk)
  2. Feature_extraction_fast      each chunk -> CSV in parallel (ProcessPool)
  3. merge in natural chunk order, append source_pcap / attack_type / binary_label
  4. write <name>_meta.csv + <name>_meta.json (code hash, counts, timing); delete chunks

Usage (from project root, venv active):
  python src/extract_features.py                       # all pcaps in data/raw/pcap
  python src/extract_features.py --only DDoS-HTTP_Flood- BenignTraffic
  python src/extract_features.py --workers 6 --chunk-packets 100000 --force
"""
import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools' / 'pcap2csv_metadata_v2'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))

logging.getLogger('scapy.runtime').setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

import pandas as pd  # noqa: E402
from tqdm import tqdm  # noqa: E402

from split_pcap import split_pcap  # noqa: E402

WINDOW = 10
META_COLS = ['window_start_ts', 'window_end_ts', 'window_packet_count', 'primary_src_mac',
             'primary_dst_mac', 'src_macs', 'dst_macs', 'all_macs', 'unique_mac_count']

# Extraction order: benign first (needed for label 0), then attacks with the largest camera impact.
PRIORITY = ['BenignTraffic', 'DDoS-SynonymousIP_Flood', 'DDoS-PSHACK_Flood', 'DDoS-ACK_Fragmentation',
            'DDoS-HTTP_Flood-', 'DDoS-UDP_Fragmentation', 'DDoS-SYN_Flood']


def label_for(pcap_name):
    """('Benign', 0) or ('DDoS-SYN_Flood', 1) from the file name (trailing digits / '-' removed)."""
    if 'benign' in pcap_name.lower():
        return 'Benign', 0
    return re.sub(r'\d*\.pcap$', '', pcap_name).rstrip('-'), 1


def code_hash():
    h = hashlib.sha1()
    for p in [TOOLS / 'Feature_extraction_fast.py', ROOT / 'src' / 'split_pcap.py', Path(__file__)]:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def natural_key(p):
    return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', Path(p).name)]


def _worker(chunk_path, csv_base):
    """Runs in a subprocess: one chunk pcap -> one CSV."""
    import Feature_extraction_fast as FE
    FE.Feature_extraction().pcap_evaluation(str(chunk_path), str(csv_base))
    return str(csv_base) + '.csv'


def extract_one(pcap, out_dir, tmp_dir, workers, chunk_packets, keep_chunks=False):
    stem = pcap.stem
    out_csv = out_dir / f'{stem}_meta.csv'
    sidecar = out_dir / f'{stem}_meta.json'
    attack_type, binary_label = label_for(pcap.name)
    work = tmp_dir / stem
    if work.exists():
        shutil.rmtree(work)
    t0 = time.time()

    chunks, n_read, n_acc = split_pcap(pcap, work / 'split', chunk_packets)
    t_split = time.time() - t0
    print(f'  split: {len(chunks)} chunks, packets read={n_read:,} accepted={n_acc:,} ({t_split:.0f}s)')

    csv_dir = work / 'csv'
    csv_dir.mkdir()
    jobs = [(c, csv_dir / c.stem) for c in chunks]
    produced = []
    with ProcessPoolExecutor(max_workers=max(1, min(workers, len(jobs)))) as ex:
        futs = [ex.submit(_worker, c, b) for c, b in jobs]
        for fut in tqdm(as_completed(futs), total=len(futs), desc=f'  {stem}', unit='chunk'):
            produced.append(fut.result())
    produced.sort(key=natural_key)

    first, rows, tmp_out = True, 0, out_csv.with_suffix('.csv.part')
    for c in produced:
        d = pd.read_csv(c)
        if d.empty:
            continue
        d['source_pcap'] = pcap.name
        d['attack_type'] = attack_type
        d['binary_label'] = binary_label
        d.to_csv(tmp_out, mode='w' if first else 'a', header=first, index=False)
        first, rows = False, rows + len(d)
    tmp_out.replace(out_csv)

    if not keep_chunks:
        shutil.rmtree(work)
    elapsed = time.time() - t0
    meta = dict(pcap=pcap.name, pcap_bytes=pcap.stat().st_size, attack_type=attack_type,
                binary_label=binary_label, window=WINDOW, chunk_packets=chunk_packets,
                chunks=len(chunks), packets_read=n_read, packets_accepted=n_acc, rows=rows,
                code_hash=code_hash(), extractor='Feature_extraction_fast', workers=workers,
                elapsed_sec=round(elapsed, 1), finished=time.strftime('%Y-%m-%d %H:%M:%S'))
    sidecar.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print(f'  done: {out_csv.name} rows={rows:,} ({elapsed/60:.1f} min)')
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pcap-dir', default=ROOT / 'data/raw/pcap', type=Path)
    ap.add_argument('--out-dir', default=ROOT / 'data/interim/features_meta', type=Path)
    ap.add_argument('--tmp-dir', default=ROOT / 'data/tmp', type=Path)
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--chunk-packets', type=int, default=20_000,
                    help='accepted packets per chunk (multiple of 10); official tcpdump split was ~10 MB')
    ap.add_argument('--only', nargs='*', default=None, help='pcap stems to process (default: all)')
    ap.add_argument('--force', action='store_true', help='re-extract even if a sidecar exists')
    ap.add_argument('--keep-chunks', action='store_true')
    a = ap.parse_args()

    pcaps = sorted(a.pcap_dir.glob('*.pcap'),
                   key=lambda p: (PRIORITY.index(p.stem) if p.stem in PRIORITY else len(PRIORITY), p.name))
    if a.only:
        pcaps = [p for p in pcaps if p.stem in set(a.only)]
    a.out_dir.mkdir(parents=True, exist_ok=True)
    print(f'{len(pcaps)} pcap(s), workers={a.workers}, chunk={a.chunk_packets:,}, code={code_hash()}')

    for i, pcap in enumerate(pcaps, 1):
        sidecar = a.out_dir / f'{pcap.stem}_meta.json'
        print(f'[{i}/{len(pcaps)}] {pcap.name} ({pcap.stat().st_size/1e9:.2f} GB)')
        if sidecar.exists() and not a.force:
            old = json.loads(sidecar.read_text(encoding='utf-8'))
            note = '' if old.get('code_hash') == code_hash() else f"  (WARNING: made with code {old.get('code_hash')}, current {code_hash()}; use --force to redo)"
            print(f"  skip: sidecar exists, rows={old.get('rows'):,}{note}")
            continue
        extract_one(pcap, a.out_dir, a.tmp_dir, a.workers, a.chunk_packets, a.keep_chunks)


if __name__ == '__main__':
    main()
