import argparse
import os
import re
import shutil
import subprocess
import tempfile
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from Feature_extraction_metadata import Feature_extraction


def natural_key(path):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)', Path(path).name)]


def process_one(args):
    split_pcap, out_base = args
    fe = Feature_extraction()
    fe.pcap_evaluation(str(split_pcap), str(out_base))
    return str(out_base) + '.csv'


def main():
    parser = argparse.ArgumentParser(
        description='CICIoT2023 official pcap2csv features + window-level MAC metadata'
    )
    parser.add_argument('--pcap', required=True, help='Input PCAP path')
    parser.add_argument('--output', required=True, help='Merged output CSV path')
    parser.add_argument('--attack-type', default='', help='e.g. DDoS-SYN_Flood or Benign')
    parser.add_argument('--binary-label', type=int, choices=[0, 1], default=None,
                        help='0=Benign, 1=DDoS. Optional metadata only.')
    parser.add_argument('--split-mb', type=int, default=10,
                        help='tcpdump split size in MB; official code uses 10')
    parser.add_argument('--workers', type=int, default=1,
                        help='Parallel workers. Start with 1 for Colab compatibility.')
    args = parser.parse_args()

    pcap = Path(args.pcap).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if not pcap.exists():
        raise FileNotFoundError(pcap)
    if shutil.which('tcpdump') is None:
        raise RuntimeError('tcpdump is not installed. In Colab: !apt-get -qq install tcpdump')

    with tempfile.TemporaryDirectory(prefix='ciciot2023_') as td:
        td = Path(td)
        split_dir = td / 'split'
        csv_dir = td / 'csv'
        split_dir.mkdir()
        csv_dir.mkdir()
        prefix = split_dir / 'part'

        print('[1/3] Splitting PCAP...')
        split_proc = subprocess.run(
            ['tcpdump', '-r', str(pcap), '-w', str(prefix), '-C', str(args.split_mb)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if split_proc.returncode != 0:
            raise RuntimeError(
                "tcpdump split failed:\n" + (split_proc.stderr or split_proc.stdout)
            )
        split_files = sorted([p for p in split_dir.iterdir() if p.is_file()], key=natural_key)
        if not split_files:
            raise RuntimeError('No split PCAP files were produced')
        print(f'      {len(split_files)} split files')

        print('[2/3] Extracting official features + MAC metadata...')
        jobs = [(p, csv_dir / p.name) for p in split_files]
        produced = []
        max_workers = max(1, min(args.workers, len(jobs)))
        if max_workers == 1:
            for job in jobs:
                produced.append(process_one(job))
        else:
            with ProcessPoolExecutor(max_workers=max_workers) as ex:
                futs = [ex.submit(process_one, job) for job in jobs]
                for fut in as_completed(futs):
                    produced.append(fut.result())

        # Restore deterministic split order for the merge.
        produced = sorted([Path(x) for x in produced], key=natural_key)

        print('[3/3] Merging split CSVs...')
        first = True
        total_rows = 0
        for csv_file in produced:
            d = pd.read_csv(csv_file)
            if d.empty:
                continue
            d['source_pcap'] = pcap.name
            if args.attack_type:
                d['attack_type'] = args.attack_type
            if args.binary_label is not None:
                d['binary_label'] = args.binary_label
            d.to_csv(output, mode='w' if first else 'a', header=first, index=False)
            first = False
            total_rows += len(d)

        print(f'Done: {output}')
        print(f'Rows: {total_rows:,}')
        print('RF feature columns remain the original 39 columns; metadata columns are appended at the end.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print("\n===== REAL ERROR INSIDE PCAP2CSV =====")
        traceback.print_exc()
        raise
