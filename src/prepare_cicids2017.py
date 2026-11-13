"""PCAPNG + GeneratedLabelledFlows -> original 38 features, global 10-packet windows.

Labels are interval candidates, not exact packet ground truth: CSV timestamps are
rounded down to seconds/minutes. Only unanimous, fully matched windows are retained.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import zipfile

import dpkt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/pcap2csv_metadata_v2'))
from Feature_extraction_fast import Feature_extraction
from build_dataset import FEATURES, RATE_CAP, IAT_MAX
from cicids2017_checkpoint import load_checkpoint

ALLOWED_LABELS = {'BENIGN', 'DDoS'}
CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def flow_key(src, sport, dst, dport, proto):
    return (int(proto), *sorted(((src, int(sport)), (dst, int(dport)))))


@lru_cache(maxsize=100000)
def label_time(value):
    """Day-first, ADT (UTC-3); missing AM/PM resolved to capture hours 08–17."""
    fmt = '%d/%m/%Y %H:%M:%S' if value.count(':') == 2 else '%d/%m/%Y %H:%M'
    dt = datetime.strptime(value, fmt)
    if dt.hour < 8:
        dt += timedelta(hours=12)
    return dt.replace(tzinfo=timezone(timedelta(hours=-3))).timestamp(), (1 if value.count(':') == 2 else 60)


def load_labels(archive, day):
    index, counts = defaultdict(list), Counter()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if not name.endswith('.csv') or not Path(name).name.lower().startswith(day.lower()):
                continue
            with z.open(name) as f:
                for frame in pd.read_csv(f, encoding='utf-8-sig', encoding_errors='replace', chunksize=100000, low_memory=False):
                    frame.columns = frame.columns.str.strip()
                    cols = ['Source IP', 'Source Port', 'Destination IP', 'Destination Port',
                            'Protocol', 'Timestamp', 'Flow Duration', 'Label']
                    missing = frame[cols].isna().any(axis=1)
                    counts['__missing_fields_excluded__'] += int(missing.sum())
                    frame = frame.loc[~missing]
                    for src, sp, dst, dp, proto, stamp, duration, label in frame[cols].itertuples(index=False, name=None):
                        start, precision = label_time(str(stamp).strip())
                        duration = float(duration) / 1e6
                        if not np.isfinite(duration) or duration < 0:
                            counts['__invalid_duration_excluded__'] += 1
                            continue
                        label = str(label).strip()
                        index[flow_key(src, sp, dst, dp, proto)].append((start, start + precision + duration, label))
                        counts[label] += 1
    if not counts:
        raise ValueError(f'No labels for {day}')
    label_time.cache_clear()
    return index, counts


def packet_label(eth, ts, index):
    ip = eth.data
    if not isinstance(ip, dpkt.ip.IP):
        return 'unsupported', ''
    if ip.offset or ip.mf:
        return 'fragment', ''
    if not isinstance(ip.data, (dpkt.tcp.TCP, dpkt.udp.UDP)):
        return 'unsupported', ''
    key = flow_key(socket.inet_ntoa(ip.src), ip.data.sport,
                   socket.inet_ntoa(ip.dst), ip.data.dport, ip.p)
    labels = {label for start, end, label in index.get(key, ()) if start <= ts <= end}
    if not labels:
        return 'unmatched', ''
    if len(labels) != 1:
        return 'ambiguous', ''
    return 'matched', next(iter(labels))


def window_label(labels):
    if len(labels) != 10:
        return 'short', ''
    if any(status != 'matched' for status, _ in labels):
        return 'incomplete', ''
    if any(label not in ALLOWED_LABELS for _, label in labels):
        return 'excluded_attack', ''
    types = {label for _, label in labels}
    if len(types) != 1:
        return 'mixed', ''
    return 'retained', next(iter(types))


def extract(pcap, archive, out_dir, chunk_packets, max_packets, resume=False):
    started = time.time()
    index, flow_counts = load_labels(archive, pcap.name.split('-')[0])
    print(f'{pcap.name}: label flows={sum(flow_counts.values()):,}', flush=True)
    stats = Counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (pcap.stem + '.parquet')
    if target.exists() or target.with_suffix('.json').exists():
        raise FileExistsError(f'Use a new output directory: {target}')
    checkpoint = load_checkpoint(pcap, target, chunk_packets) if resume else None
    pending = target.with_suffix('.resuming.parquet.part' if checkpoint else '.parquet.part')
    parquet_writer = None
    row_offset = checkpoint['row_offset'] if checkpoint else 0
    if checkpoint:
        stats.update(checkpoint['snapshot']['counts'])
        started -= checkpoint['snapshot']['elapsed_sec']
        print(f'Resuming {pcap.name}: preserved {checkpoint["rows"]:,} rows at byte {checkpoint["bytes_read"]}', flush=True)
    progress_path = target.with_suffix('.progress.json')
    with tempfile.TemporaryDirectory(prefix='cicids_', dir=out_dir) as work:
        chunk = Path(work) / 'chunk.pcap'
        base = Path(work) / 'features'

        def flush(labels):
            nonlocal parquet_writer, row_offset
            Feature_extraction().pcap_evaluation(str(chunk), str(base), compute_unused_flows=False)
            d = pd.read_csv(str(base) + '.csv')
            if len(d) != (len(labels) + 9) // 10:
                raise RuntimeError('Feature/label window alignment mismatch')
            decisions = [window_label(labels[i:i+10]) for i in range(0, len(labels), 10)]
            stats.update('window_' + status for status, _ in decisions)
            d['row_in_file'] = np.arange(row_offset, row_offset + len(d))
            row_offset += len(d)
            d['attack_type'] = [label for _, label in decisions]
            d = d.loc[[status == 'retained' for status, _ in decisions]].copy()
            if d.empty:
                return
            stats['drop_iat'] += int((d.IAT > IAT_MAX).sum())
            d = d[d.IAT <= IAT_MAX].copy()
            d['Rate'] = d.Rate.clip(upper=RATE_CAP)
            d[['Std', 'Variance']] = d[['Std', 'Variance']].fillna(0)
            d[FEATURES] = d[FEATURES].astype(np.float32)
            if not np.isfinite(d[FEATURES].to_numpy()).all():
                raise ValueError('Non-finite features')
            d['source_pcap'] = pcap.name
            if not set(d.attack_type).issubset(ALLOWED_LABELS):
                raise ValueError('Non-DDoS attack passed the label filter')
            d['binary_label'] = (d.attack_type == 'DDoS').astype(np.int8)
            # Device identities from CICIoT2023 do not apply to this dataset.
            for col in ['has_camera', 'has_audio', 'has_echo_dot1', 'has_amcrest']:
                d[col] = False
            cols = FEATURES + ['window_start_ts', 'window_end_ts', 'window_packet_count',
                              'row_in_file', 'source_pcap', 'attack_type', 'binary_label',
                              'has_camera', 'has_audio', 'has_echo_dot1', 'has_amcrest']
            table = pa.Table.from_pandas(d[cols], preserve_index=False)
            if parquet_writer is None:
                parquet_writer = pq.ParquetWriter(pending, table.schema, compression='snappy')
            parquet_writer.write_table(table)
            stats['rows_written'] += len(d)
            stats.update('retained_' + label for label in d.attack_type)

        try:
            if checkpoint:
                prefix = pq.ParquetFile(checkpoint['prefix'])
                parquet_writer = pq.ParquetWriter(pending, prefix.schema_arrow, compression='snappy')
                for batch in prefix.iter_batches(batch_size=100000):
                    parquet_writer.write_batch(batch)
            with pcap.open('rb') as f:
                magic = f.read(4)
                f.seek(0)
                reader = dpkt.pcapng.Reader(f) if magic == b'\x0a\x0d\x0d\x0a' else dpkt.pcap.Reader(f)
                if reader.datalink() != dpkt.pcap.DLT_EN10MB:
                    raise ValueError('Only Ethernet captures supported')
                if checkpoint:
                    if magic != b'\x0a\x0d\x0d\x0a':
                        raise ValueError('Byte-offset recovery currently requires PCAPNG')
                    f.seek(checkpoint['bytes_read'])
                labels = []
                with chunk.open('wb') as cf:
                    writer = dpkt.pcap.Writer(cf, nano=True)
                    for ts, buf in reader:
                        stats['packets_read'] += 1
                        try:
                            eth = dpkt.ethernet.Ethernet(buf)
                        except (dpkt.UnpackError, ValueError):
                            stats['malformed'] += 1
                            continue
                        if eth.type in (dpkt.ethernet.ETH_TYPE_IP, dpkt.ethernet.ETH_TYPE_ARP):
                            writer.writepkt(buf, ts)
                            decision = packet_label(eth, ts, index)
                            labels.append(decision)
                            stats['packet_' + decision[0]] += 1
                            if len(labels) == chunk_packets:
                                cf.flush()
                                flush(labels)
                                labels = []
                                cf.seek(0)
                                cf.truncate()
                                writer = dpkt.pcap.Writer(cf, nano=True)
                                elapsed = time.time() - started
                                fraction = f.tell() / pcap.stat().st_size
                                progress = dict(pcap=pcap.name, fraction=fraction,
                                                bytes_read=f.tell(), pcap_bytes=pcap.stat().st_size,
                                                elapsed_sec=elapsed, eta_sec=elapsed * (1-fraction) / fraction,
                                                counts=dict(stats), updated=time.time(), code_sha256=CODE_SHA256)
                                temp_progress = progress_path.with_suffix('.json.tmp')
                                try:
                                    temp_progress.write_text(json.dumps(progress, indent=2), encoding='utf-8')
                                    temp_progress.replace(progress_path)
                                except PermissionError:
                                    # Windows readers/security scanners can briefly lock a JSON.
                                    # A display-only update must not abort valid feature extraction.
                                    print(f'  progress update temporarily unavailable: {pcap.name}', flush=True)
                                print(f'  {fraction:.2%} packets={stats["packets_read"]:,} '
                                      f'retained={stats["rows_written"]:,} '
                                      f'DDoS={stats["retained_DDoS"]:,} ETA={progress["eta_sec"]/60:.1f}min', flush=True)
                        if max_packets and stats['packets_read'] >= max_packets:
                            break
                    if labels:
                        cf.flush()
                        flush(labels)
        finally:
            if parquet_writer is not None:
                parquet_writer.close()
    report = dict(pcap=str(pcap), pcap_bytes=pcap.stat().st_size, max_packets=max_packets,
                  chunk_packets=chunk_packets, window=10, features=FEATURES,
                  flow_labels=dict(flow_counts), counts=dict(stats), elapsed_sec=time.time()-started,
                  timestamp_policy='day-first; UTC-3; hours 00-07 +12; precision interval 1s/60s',
                  label_policy='BENIGN=0, DDoS=1 only; all 10 packets same exact label; other attacks/conflicts excluded',
                  allowed_labels=sorted(ALLOWED_LABELS), compute_unused_flows=False,
                  resumed_prefix_rows=checkpoint['rows'] if checkpoint else 0,
                  resumed_from_byte=checkpoint['bytes_read'] if checkpoint else 0,
                  labels_archive=str(archive), labels_archive_bytes=archive.stat().st_size,
                  extractor_sha256=hashlib.sha256((ROOT / 'tools/pcap2csv_metadata_v2/Feature_extraction_fast.py').read_bytes()).hexdigest(),
                  code_sha256=CODE_SHA256)
    if pending.exists():
        pending.replace(target)
    target.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report['counts']), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pcap-dir', type=Path, default=ROOT / 'data/raw/cicids2017/pcap')
    ap.add_argument('--labels', type=Path, default=ROOT / 'data/raw/cicids2017/labels/GeneratedLabelledFlows.zip')
    ap.add_argument('--out-dir', type=Path, default=ROOT / 'data/processed/cicids2017')
    ap.add_argument('--only', nargs='+', help='Day names, e.g. Monday Friday')
    ap.add_argument('--chunk-packets', type=int, default=20000)
    ap.add_argument('--max-packets', type=int, default=0, help='0=full capture; use separate directory for smoke runs')
    ap.add_argument('--resume', action='store_true', help='Continue a closed parquet prefix from its last complete chunk')
    a = ap.parse_args()
    if a.chunk_packets <= 0 or a.chunk_packets % 10 or a.max_packets < 0:
        ap.error('chunk-packets must be positive and divisible by 10; max-packets >= 0')
    pcaps = sorted(a.pcap_dir.glob('*.pcap'))
    pcaps = [p for p in pcaps if not a.only or p.name.split('-')[0] in a.only]
    if not pcaps:
        ap.error('No captures selected')
    for pcap in pcaps:
        extract(pcap, a.labels, a.out_dir, a.chunk_packets, a.max_packets, resume=a.resume)


if __name__ == '__main__':
    main()
