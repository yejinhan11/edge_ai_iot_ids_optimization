"""Split a PCAP into chunk files of N *accepted* packets (replaces `tcpdump -C 10`).

The official CICIoT2023 extractor only turns IPv4 and ARP frames into feature rows and
then groups every 10 accepted rows into one window.  tcpdump splits by bytes, so the
last window of every chunk had fewer than 10 packets (181 such rows in the SYN_Flood
run).  Here the cut is made after a multiple of 10 accepted packets, so no window is
broken by a chunk boundary.  Frames the extractor would skip (IPv6, LLC, ...) are
copied along untouched so the chunk still is a faithful slice of the capture.

Usage:
    python src/split_pcap.py data/raw/pcap/DDoS-HTTP_Flood-.pcap data/tmp/http --chunk-packets 200000
"""
import argparse
import struct
from pathlib import Path

import dpkt

ETH_TYPE_IP = 0x0800
ETH_TYPE_ARP = 0x0806
ETH_TYPE_8021Q = 0x8100
WINDOW = 10  # official window size


def is_accepted(buf):
    """Same accept rule as Feature_extraction*.py: Ethernet type IPv4 or ARP (VLAN-tagged included)."""
    if len(buf) < 14:
        return False
    et = struct.unpack('!H', buf[12:14])[0]
    if et == ETH_TYPE_8021Q and len(buf) >= 18:
        et = struct.unpack('!H', buf[16:18])[0]
    return et == ETH_TYPE_IP or et == ETH_TYPE_ARP


def split_pcap(pcap_path, out_dir, chunk_packets=200_000, prefix='part'):
    """Write out_dir/part0000.pcap ... ; returns (chunk_paths, packets_read, packets_accepted)."""
    assert chunk_packets % WINDOW == 0, 'chunk_packets must be a multiple of the 10-packet window'
    pcap_path, out_dir = Path(pcap_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks, n_read, n_acc, in_chunk = [], 0, 0, 0
    writer, fh = None, None

    def open_new():
        nonlocal writer, fh
        p = out_dir / f'{prefix}{len(chunks):04d}.pcap'
        fh = open(p, 'wb')
        writer = dpkt.pcap.Writer(fh, linktype=reader.datalink())
        chunks.append(p)

    with open(pcap_path, 'rb') as f:
        reader = dpkt.pcap.Reader(f)
        open_new()
        for ts, buf in reader:
            if in_chunk >= chunk_packets:
                fh.close()
                open_new()
                in_chunk = 0
            writer.writepkt(buf, ts)
            n_read += 1
            if is_accepted(buf):
                n_acc += 1
                in_chunk += 1
    fh.close()
    return chunks, n_read, n_acc


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pcap')
    ap.add_argument('out_dir')
    ap.add_argument('--chunk-packets', type=int, default=200_000)
    a = ap.parse_args()
    chunks, n_read, n_acc = split_pcap(a.pcap, a.out_dir, a.chunk_packets)
    print(f'{len(chunks)} chunks, packets read={n_read:,}, accepted(IPv4/ARP)={n_acc:,}')
