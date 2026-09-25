"""Re-create the per-attack device summary tables from the saved EDA CSV (no pcap re-scan),
using the single device table config/devices.csv.

Input : data/interim/device_summary/all_devices_summary.csv   (mac, sent/received packets, ... , file)
Output: results/tables/eda_attack_top_devices.csv     attack x (top senders / receivers / victim / top camera)
        results/tables/eda_camera_by_attack.csv       one row per (attack, camera)
        results/tables/eda_device_totals.csv          per-device totals over the 12 DDoS pcaps
        results/tables/eda_category_totals.csv        per-category totals
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from devices import is_group_mac, load_devices, norm_mac  # noqa: E402


def fmt_top(df, col, k=5):
    top = df.nlargest(k, col)
    return ' | '.join(f"{r.device_name or r.mac} ({int(getattr(r, col)):,})" for r in top.itertuples())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--summary', default=ROOT / 'data/interim/device_summary/all_devices_summary.csv', type=Path)
    ap.add_argument('--out-dir', default=ROOT / 'results/tables', type=Path)
    a = ap.parse_args()

    dev = load_devices()
    d = pd.read_csv(a.summary)
    d['mac'] = d['mac'].map(norm_mac)
    d['top_peer'] = d['top_peer'].map(norm_mac)
    d['attack'] = d['file'].str.replace(r'\.pcap$', '', regex=True).str.rstrip('-')
    d = d[~d['mac'].map(is_group_mac)].copy()
    d['device_name'] = d['mac'].map(dev['device_name']).fillna('')
    d['category'] = d['mac'].map(dev['category']).fillna('Unknown')
    d['role'] = d['mac'].map(dev['role']).fillna('unknown')
    d['top_peer_name'] = d['top_peer'].map(dev['device_name']).fillna(d['top_peer'])
    d['top_peer_role'] = d['top_peer'].map(dev['role']).fillna('unknown')
    d['recv_to_sent'] = d['received_packets'] / d['sent_packets'].clip(lower=1)

    rows = []
    for attack, g in d.groupby('attack'):
        victims = g[(g['role'] != 'attacker') & (g['role'] != 'gateway_candidate')]
        cams = victims[victims['category'] == 'Camera']
        v = victims.nlargest(1, 'received_packets').iloc[0]
        c = cams.nlargest(1, 'received_packets').iloc[0] if len(cams) else None
        rows.append(dict(attack=attack,
                         sent_top5=fmt_top(g, 'sent_packets'), received_top5=fmt_top(g, 'received_packets'),
                         total_top5=fmt_top(g, 'total_packets'),
                         main_victim=v['device_name'] or v['mac'], main_victim_category=v['category'],
                         main_victim_received=int(v['received_packets']),
                         top_camera=c['device_name'] if c is not None else '',
                         camera_received=int(c['received_packets']) if c is not None else 0,
                         camera_sent=int(c['sent_packets']) if c is not None else 0,
                         camera_top_peer=c['top_peer_name'] if c is not None else '',
                         camera_top_peer_role=c['top_peer_role'] if c is not None else ''))
    a.out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(a.out_dir / 'eda_attack_top_devices.csv', index=False)

    cams = d[d['category'] == 'Camera'].sort_values(['attack', 'received_packets'], ascending=[True, False])
    cams[['attack', 'device_name', 'mac', 'sent_packets', 'received_packets', 'total_packets', 'recv_to_sent',
          'top_peer_name', 'top_peer_role', 'top_peer_packets']].to_csv(a.out_dir / 'eda_camera_by_attack.csv',
                                                                       index=False)

    tot = (d.groupby(['mac', 'device_name', 'category', 'role'])[['sent_packets', 'received_packets', 'total_packets']]
           .sum().reset_index().sort_values('received_packets', ascending=False))
    peak = d.loc[d.groupby('mac')['received_packets'].idxmax(), ['mac', 'attack', 'received_packets']]
    tot = tot.merge(peak.rename(columns={'attack': 'peak_attack', 'received_packets': 'peak_received'}), on='mac')
    tot.to_csv(a.out_dir / 'eda_device_totals.csv', index=False)

    cat = (d[d['role'] != 'attacker'].groupby('category')[['sent_packets', 'received_packets', 'total_packets']]
           .sum().assign(n_devices=d[d['role'] != 'attacker'].groupby('category')['mac'].nunique())
           .sort_values('received_packets', ascending=False))
    cat.to_csv(a.out_dir / 'eda_category_totals.csv')

    print(pd.DataFrame(rows)[['attack', 'main_victim', 'main_victim_received', 'top_camera', 'camera_received']]
          .to_string(index=False))
    print('\n', cat.to_string())
    print('\nunknown MACs with > 10k packets:')
    print(d[(d['category'] == 'Unknown') & (d['total_packets'] > 10_000)][['attack', 'mac', 'ips', 'sent_packets',
                                                                            'received_packets']].to_string(index=False))


if __name__ == '__main__':
    main()
