"""Meaningful boundary tests for packet/flow alignment and conservative labels."""
from datetime import datetime, timezone
import socket
import csv
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

import dpkt
import numpy as np
import pandas as pd

from prepare_cicids2017 import extract, flow_key, label_time, packet_label, window_label
from build_dataset import FEATURES
from train_rf import time_split
from Feature_extraction_fast import Feature_extraction


class LabelTests(unittest.TestCase):
    def packet(self, reverse=False):
        a, b = ('192.168.10.1', 1234), ('192.168.10.2', 80)
        if reverse:
            a, b = b, a
        tcp = dpkt.tcp.TCP(sport=a[1], dport=b[1])
        ip = dpkt.ip.IP(src=socket.inet_aton(a[0]), dst=socket.inet_aton(b[0]), p=6, data=tcp)
        return dpkt.ethernet.Ethernet(type=0x0800, data=ip)

    def test_bidirectional_and_time_interval(self):
        key = flow_key('192.168.10.1', 1234, '192.168.10.2', 80, 6)
        index = {key: [(100, 110, 'BENIGN'), (200, 210, 'DDoS')]}
        self.assertEqual(packet_label(self.packet(), 105, index), ('matched', 'BENIGN'))
        self.assertEqual(packet_label(self.packet(True), 205, index), ('matched', 'DDoS'))
        self.assertEqual(packet_label(self.packet(), 150, index)[0], 'unmatched')
        index[key].append((200, 210, 'BENIGN'))
        self.assertEqual(packet_label(self.packet(), 205, index)[0], 'ambiguous')

    def test_windows_do_not_turn_unknown_into_benign(self):
        benign = [('matched', 'BENIGN')] * 10
        self.assertEqual(window_label(benign), ('retained', 'BENIGN'))
        self.assertEqual(window_label([('matched', 'DDoS')] * 10), ('retained', 'DDoS'))
        self.assertEqual(window_label(benign[:9])[0], 'short')
        self.assertEqual(window_label(benign[:9] + [('unmatched', '')])[0], 'incomplete')
        self.assertEqual(window_label(benign[:9] + [('matched', 'DDoS')])[0], 'mixed')
        for label in ['DoS Hulk', 'DoS GoldenEye', 'PortScan', 'Bot', 'SSH-Patator']:
            self.assertEqual(window_label([('matched', label)] * 10)[0], 'excluded_attack')
            self.assertEqual(window_label(benign[:9] + [('matched', label)])[0], 'excluded_attack')

    def test_day_first_afternoon_and_precision(self):
        stamp, precision = label_time('7/7/2017 3:30')
        self.assertEqual(datetime.fromtimestamp(stamp, timezone.utc).hour, 18)
        self.assertEqual(precision, 60)
        stamp, precision = label_time('03/07/2017 08:55:58')
        self.assertEqual(datetime.fromtimestamp(stamp, timezone.utc).isoformat(), '2017-07-03T11:55:58+00:00')
        self.assertEqual(precision, 1)

    def test_late_ddos_split_is_explicit(self):
        d = pd.DataFrame({'source_pcap': ['Friday'] * 100, 'row_in_file': range(100),
                          'binary_label': [0] * 90 + [1] * 10})
        strict = time_split(d, 0.7)
        self.assertEqual(set(d.loc[strict, 'binary_label']), {0})
        grouped = time_split(d, 0.7, group_label=True)
        self.assertEqual(d.loc[grouped, 'binary_label'].value_counts().to_dict(), {0: 63, 1: 7})
        self.assertEqual(d.loc[~grouped, 'binary_label'].value_counts().to_dict(), {0: 27, 1: 3})

    def test_pcapng_end_to_end_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pcap = root / 'Monday-fixture.pcap'
            archive = root / 'labels.zip'
            start, _ = label_time('03/07/2017 08:55:58')
            with pcap.open('wb') as f:
                writer = dpkt.pcapng.Writer(f)
                for i in range(120):
                    eth = self.packet(reverse=bool(i % 2))
                    eth.data.data.sport = 80 if i % 2 else 1000 + i // 10
                    eth.data.data.dport = 1000 + i // 10 if i % 2 else 80
                    writer.writepkt(bytes(eth), start + i / 100)
            text = io.StringIO()
            writer = csv.writer(text)
            writer.writerow(['Source IP', 'Source Port', 'Destination IP', 'Destination Port',
                             'Protocol', 'Timestamp', 'Flow Duration', 'Label'])
            for w in range(12):
                writer.writerow(['192.168.10.1', 1000+w, '192.168.10.2', 80, 6,
                                 '03/07/2017 08:55:58', 1000000,
                                 ('BENIGN' if w % 2 == 0 else 'DDoS') if w < 10 else 'DoS Hulk'])
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('Monday-fixture.csv', text.getvalue())
            # The original extractor reads classic PCAP. Compare the same serialized
            # packets with/without unused flow statistics before using the fast path.
            classic = root / 'classic.pcap'
            with pcap.open('rb') as f, classic.open('wb') as g:
                out = dpkt.pcap.Writer(g, nano=True)
                for ts, buf in dpkt.pcapng.Reader(f):
                    out.writepkt(buf, ts)
            for option in [True, False]:
                Feature_extraction().pcap_evaluation(str(classic), str(root / str(option)),
                                                     compute_unused_flows=option)
            pd.testing.assert_frame_equal(pd.read_csv(root / 'True.csv'), pd.read_csv(root / 'False.csv'),
                                          check_exact=True)
            extract(pcap, archive, root / 'out', 20, 0)
            d = pd.read_parquet(root / 'out/Monday-fixture.parquet')
            self.assertEqual(len(d), 10)
            self.assertEqual(d.binary_label.tolist(), [0, 1] * 5)
            self.assertTrue((d.window_packet_count == 10).all())
            self.assertTrue(np.isfinite(d[FEATURES]).all().all())
            self.assertEqual(len(FEATURES), 38)
            tr = time_split(d, 0.7)
            self.assertEqual(set(d.loc[tr, 'binary_label']), {0, 1})
            self.assertEqual(set(d.loc[~tr, 'binary_label']), {0, 1})
            report = json.loads((root / 'out/Monday-fixture.json').read_text())
            self.assertEqual(report['counts']['packet_matched'], 120)
            self.assertEqual(report['counts']['window_excluded_attack'], 2)
            # Recover a closed prefix without losing/repeating packets at its boundary.
            resumed_dir = root / 'recovered'
            extract(pcap, archive, resumed_dir, 20, 40)
            resumed_file = resumed_dir / 'Monday-fixture.parquet'
            resumed_file.rename(resumed_file.with_suffix('.parquet.part'))
            resumed_file.with_suffix('.json').rename(root / 'prefix-report.json')
            extract(pcap, archive, resumed_dir, 20, 0, resume=True)
            pd.testing.assert_frame_equal(d, pd.read_parquet(resumed_file), check_exact=True)
            # Display-only progress failures must not abort valid extraction on Windows.
            original_replace = Path.replace

            def locked_progress(path, destination):
                if path.name.endswith('.progress.json.tmp'):
                    raise PermissionError('simulated Windows progress lock')
                return original_replace(path, destination)

            with mock.patch.object(Path, 'replace', locked_progress):
                extract(pcap, archive, root / 'locked_progress', 20, 0)
            pd.testing.assert_frame_equal(d, pd.read_parquet(root / 'locked_progress/Monday-fixture.parquet'),
                                          check_exact=True)
            subprocess.run([sys.executable, str(Path(__file__).with_name('train_rf.py')),
                            '--data', str(root / 'out'), '--tag', 'fixture',
                            '--out-dir', str(root / 'tables'), '--model-dir', str(root / 'models')],
                           check=True, capture_output=True, text=True)
            result = pd.read_csv(root / 'tables/rf_fixture.csv')
            self.assertEqual(result.n_features.tolist(), [38])
            self.assertEqual(result.n_estimators.tolist(), [100])


if __name__ == '__main__':
    unittest.main()
