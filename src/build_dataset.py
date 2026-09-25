"""Merge the per-pcap feature CSVs into one cleaned, labelled parquet with device metadata.

Input : data/interim/features_meta/<name>_meta.csv (+ .json sidecar)   from extract_features.py
Output: data/processed/dataset_v1.parquet, results/tables/dataset_v1_summary.csv

Cleaning (all counts are logged to the summary):
  - drop windows with < 10 packets (chunk-boundary artefacts of the legacy tcpdump split)
  - drop windows whose mean IAT > 1e5 s (first window of every chunk: the extractor starts
    with last_pac_time = 0, so the first packet gets IAT = its epoch timestamp)
  - Rate = inf (all 10 timestamps equal) -> capped at RATE_CAP; Std/Variance NaN -> 0
  - LLC column dropped (always 1 because of a bug in the official Layered_features.L1)

Metadata (NOT features; used only to pick evaluation subsets):
  has_attacker, n_victim_macs, victim_device (name), victim_mac, victim_category,
  has_camera, has_echo_dot1, has_amcrest, primary_src_mac, primary_dst_mac,
  source_pcap, attack_type, binary_label, window_start_ts, row_in_file
Victim MACs = MACs in the window that are not Raspberry Pis (all 10 NextGen MACs: the 3 the
paper lists as victims also send flood traffic in HTTP_Flood), not the gateway candidate and
not broadcast/multicast.  has_attacker = any Raspberry Pi present.  victim_device prefers primary_dst_mac, then
primary_src_mac, then the first victim MAC (sorted).
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from devices import (AMCREST, CAMERA_MACS, ECHO_DOT_1, GATEWAY_MACS, NEXTGEN_MACS,  # noqa: E402
                     is_group_mac, load_devices)

FEATURES_OFFICIAL = ['Header_Length', 'Protocol Type', 'Time_To_Live', 'Rate', 'fin_flag_number',
                     'syn_flag_number', 'rst_flag_number', 'psh_flag_number', 'ack_flag_number',
                     'ece_flag_number', 'cwr_flag_number', 'ack_count', 'syn_count', 'fin_count',
                     'rst_count', 'HTTP', 'HTTPS', 'DNS', 'Telnet', 'SMTP', 'SSH', 'IRC', 'TCP', 'UDP',
                     'DHCP', 'ARP', 'ICMP', 'IGMP', 'IPv', 'LLC', 'Tot sum', 'Min', 'Max', 'AVG', 'Std',
                     'Tot size', 'IAT', 'Number', 'Variance']
DROP_FEATURES = ['LLC']
FEATURES = [c for c in FEATURES_OFFICIAL if c not in DROP_FEATURES]
RATE_CAP = 1e7          # 10 packets / 1 us
IAT_MAX = 1e5           # seconds; anything larger is the chunk-start artefact
TAG_COLS = ['has_attacker', 'n_victim_macs', 'victim_mac', 'victim_device', 'victim_category',
            'has_camera', 'has_echo_dot1', 'has_amcrest']


class Tagger:
    """all_macs string -> device metadata, memoised (flood windows repeat the same MAC sets)."""

    def __init__(self):
        self.dev = load_devices()
        self.cache = {}

    def __call__(self, all_macs, psrc, pdst):
        key = (all_macs, psrc, pdst)
        if key in self.cache:
            return self.cache[key]
        macs = [m for m in str(all_macs).split(';') if m]
        attackers = [m for m in macs if m in NEXTGEN_MACS]
        victims = sorted(m for m in macs if m not in NEXTGEN_MACS and m not in GATEWAY_MACS
                         and not is_group_mac(m))
        vset = set(victims)
        if pdst in vset:
            vmac = pdst
        elif psrc in vset:
            vmac = psrc
        else:
            vmac = victims[0] if victims else ''
        if vmac in self.dev.index:
            vname, vcat = self.dev.loc[vmac, 'device_name'], self.dev.loc[vmac, 'category']
        elif vmac:
            vname, vcat = 'unknown', 'Unknown'
        else:
            vname, vcat = '', 'None'
        out = (bool(attackers), len(victims), vmac, vname, vcat,
               any(m in CAMERA_MACS for m in victims), ECHO_DOT_1 in vset, AMCREST in vset)
        self.cache[key] = out
        return out


def process_file(csv_path, tagger, chunksize=500_000):
    parts = []
    stats = dict(file=csv_path.name, rows_in=0, drop_short=0, drop_iat=0, rate_inf=0, std_nan=0, rows_out=0)
    offset = 0
    for d in pd.read_csv(csv_path, chunksize=chunksize):
        n = len(d)
        stats['rows_in'] += n
        d['row_in_file'] = np.arange(offset, offset + n)
        offset += n
        short = d['window_packet_count'] < 10
        iat_bad = d['IAT'] > IAT_MAX
        stats['drop_short'] += int(short.sum())
        stats['drop_iat'] += int((iat_bad & ~short).sum())
        d = d[~short & ~iat_bad].copy()
        inf = np.isinf(d['Rate'])
        stats['rate_inf'] += int(inf.sum())
        d.loc[inf, 'Rate'] = RATE_CAP
        d['Rate'] = d['Rate'].clip(upper=RATE_CAP)
        stats['std_nan'] += int(d['Std'].isna().sum())
        d[['Std', 'Variance']] = d[['Std', 'Variance']].fillna(0.0)

        tags = [tagger(a, s, t) for a, s, t in zip(d['all_macs'].fillna(''),
                                                    d['primary_src_mac'].fillna(''),
                                                    d['primary_dst_mac'].fillna(''))]
        tag_df = pd.DataFrame(tags, columns=TAG_COLS, index=d.index)
        out = pd.concat([d[FEATURES].astype(np.float32),
                         d[['window_start_ts', 'row_in_file', 'window_packet_count']],
                         d[['primary_src_mac', 'primary_dst_mac', 'source_pcap', 'attack_type']].astype('category'),
                         d[['binary_label']].astype(np.int8), tag_df], axis=1)
        parts.append(out)
        stats['rows_out'] += len(out)
    return pd.concat(parts, ignore_index=True), stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--in-dir', default=ROOT / 'data/interim/features_meta', type=Path)
    ap.add_argument('--out', default=ROOT / 'data/processed/dataset_v1.parquet', type=Path)
    ap.add_argument('--summary', default=ROOT / 'results/tables/dataset_v1_summary.csv', type=Path)
    ap.add_argument('--only', nargs='*', default=None, help='pcap stems to include')
    a = ap.parse_args()

    csvs = sorted(a.in_dir.glob('*_meta.csv'))
    csvs = [c for c in csvs if c.with_suffix('.json').exists()]
    if a.only:
        csvs = [c for c in csvs if c.name.replace('_meta.csv', '') in set(a.only)]
    if not csvs:
        sys.exit('no finished *_meta.csv (with .json sidecar) found')
    tagger, frames, all_stats = Tagger(), [], []
    for c in csvs:
        t = time.time()
        df, st = process_file(c, tagger)
        st['sec'] = round(time.time() - t, 1)
        st['label'] = int(df['binary_label'].iloc[0]) if len(df) else None
        print(f"{c.name}: in={st['rows_in']:,} out={st['rows_out']:,} short={st['drop_short']} "
              f"iat={st['drop_iat']} rate_inf={st['rate_inf']} ({st['sec']}s)")
        frames.append(df)
        all_stats.append(st)
    data = pd.concat(frames, ignore_index=True)
    for c in ['primary_src_mac', 'primary_dst_mac', 'source_pcap', 'attack_type', 'victim_mac',
              'victim_device', 'victim_category']:
        data[c] = data[c].astype(str).astype('category')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(a.out, index=False)
    a.summary.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_stats).to_csv(a.summary, index=False)

    print(f'\nwrote {a.out} rows={len(data):,} features={len(FEATURES)}')
    print('label counts:', data['binary_label'].value_counts().to_dict())
    print('subset sizes: camera=%d  echo_dot1=%d  amcrest=%d  has_attacker=%d' % (
        data['has_camera'].sum(), data['has_echo_dot1'].sum(), data['has_amcrest'].sum(),
        data['has_attacker'].sum()))
    print(pd.crosstab(data['attack_type'], data['victim_category']).to_string())


if __name__ == '__main__':
    main()
