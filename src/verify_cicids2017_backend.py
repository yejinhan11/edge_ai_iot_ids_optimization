"""Check exact legacy CSV equivalence when unused flow calculations are skipped."""
import hashlib
import json
from pathlib import Path
import tempfile
import time

import dpkt
import pandas as pd

from prepare_cicids2017 import ROOT, Feature_extraction


def main():
    rows = []
    for source in sorted((ROOT / 'data/raw/cicids2017/pcap').glob('*.pcap')):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'sample.pcap'
            with source.open('rb') as f, path.open('wb') as g:
                writer = dpkt.pcap.Writer(g, nano=True)
                accepted = 0
                for ts, buf in dpkt.pcapng.Reader(f):
                    eth = dpkt.ethernet.Ethernet(buf)
                    if eth.type in (0x0800, 0x0806):
                        writer.writepkt(buf, ts)
                        accepted += 1
                    if accepted == 2000:
                        break
            timings = {}
            for option in [True, False]:
                started = time.perf_counter()
                Feature_extraction().pcap_evaluation(str(path), str(Path(work) / str(option)),
                                                     compute_unused_flows=option)
                timings[str(option)] = time.perf_counter() - started
            old = pd.read_csv(Path(work) / 'True.csv')
            new = pd.read_csv(Path(work) / 'False.csv')
            pd.testing.assert_frame_equal(old, new, check_exact=True)
            rows.append(dict(pcap=source.name, packets=accepted, windows=len(old),
                             exact_equal=True, legacy_sec=timings['True'], optimized_sec=timings['False']))
            print(rows[-1], flush=True)
    target = ROOT / 'results/cicids2017_ddos_benign/backend_equivalence.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(results=rows, extractor_sha256=hashlib.sha256(
        (ROOT / 'tools/pcap2csv_metadata_v2/Feature_extraction_fast.py').read_bytes()).hexdigest()),
        indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
