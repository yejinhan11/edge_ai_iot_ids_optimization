"""Single source of truth for MAC -> device mapping (config/devices.csv).

    from devices import load_devices, mac_info, ATTACKER_MACS, CAMERA_MACS
"""
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEVICES_CSV = ROOT / 'config' / 'devices.csv'

ECHO_DOT_1 = '1C:FE:2B:98:16:DD'      # most-attacked device overall (Audio)
AMCREST = '9C:8E:CD:1D:AB:9F'         # most-attacked camera
GATEWAY_CANDIDATE = '3C:18:A0:41:C3:A0'


def norm_mac(mac):
    return str(mac).strip().upper()


@lru_cache(maxsize=1)
def load_devices():
    d = pd.read_csv(DEVICES_CSV)
    d['mac'] = d['mac'].map(norm_mac)
    return d.set_index('mac')


def macs_by(**filters):
    d = load_devices()
    for k, v in filters.items():
        d = d[d[k] == v]
    return frozenset(d.index)


ATTACKER_MACS = macs_by(role='attacker')
CAMERA_MACS = macs_by(category='Camera')
GATEWAY_MACS = macs_by(role='gateway_candidate')
VICTIM_MACS = macs_by(role='victim')


def mac_info(mac):
    """Return (device_name, category, role); unknown MACs -> ('', 'Unknown', 'unknown')."""
    d = load_devices()
    m = norm_mac(mac)
    if m in d.index:
        r = d.loc[m]
        return r['device_name'], r['category'], r['role']
    return '', 'Unknown', 'unknown'


def is_group_mac(mac):
    """Broadcast / multicast (least-significant bit of first octet set)."""
    try:
        return int(norm_mac(mac)[:2], 16) & 1 == 1
    except ValueError:
        return False


if __name__ == '__main__':
    d = load_devices()
    print(d['category'].value_counts().to_dict())
    print('attackers:', sorted(ATTACKER_MACS))
    print('cameras:', len(CAMERA_MACS))
