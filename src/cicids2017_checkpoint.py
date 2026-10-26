"""Validate a closed parquet prefix at an accepted-packet chunk boundary."""
import json
from pathlib import Path

import pyarrow.parquet as pq

from build_dataset import FEATURES


def load_checkpoint(pcap, target, chunk_packets):
    prefix = target.with_suffix('.parquet.part')
    parquet = pq.ParquetFile(prefix)  # An actively written/incomplete footer is rejected.
    if parquet.schema_arrow.names[:len(FEATURES)] != FEATURES:
        raise ValueError('Checkpoint features do not match the 38-feature schema')
    candidates = []
    for path in [target.with_suffix('.progress.json'), target.with_suffix('.progress.json.tmp')]:
        if not path.exists():
            continue
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        if snapshot['pcap'] != pcap.name:
            continue
        counts = snapshot['counts']
        accepted = sum(counts.get('packet_' + name, 0)
                       for name in ['matched', 'unsupported', 'fragment', 'unmatched', 'ambiguous'])
        if counts['rows_written'] != parquet.metadata.num_rows or accepted % chunk_packets:
            continue
        offset = snapshot.get('bytes_read', round(snapshot['fraction'] * pcap.stat().st_size))
        if not 0 < offset < pcap.stat().st_size:
            raise ValueError('Invalid raw checkpoint byte offset')
        candidates.append(dict(snapshot=snapshot, prefix=prefix, bytes_read=offset,
                               row_offset=accepted // 10, rows=parquet.metadata.num_rows))
    if not candidates:
        raise ValueError('Closed parquet prefix does not match a complete-chunk checkpoint')
    return max(candidates, key=lambda item: item['bytes_read'])
