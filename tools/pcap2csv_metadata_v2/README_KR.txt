CICIoT2023 pcap2csv + MAC metadata (modified helper)
=========================================================

Purpose
-------
Preserve the official CICIoT2023 39-feature extraction logic while appending
window-level metadata that is NOT intended to be used as RF input features.

What was changed
----------------
1. Feature_extraction.py is preserved untouched.
2. Feature_extraction_metadata.py is a minimally modified copy.
3. The official extractor summarizes every 10 accepted packets into one output row.
4. For each same 10-packet window, metadata is appended:
   - window_start_ts / window_end_ts
   - window_packet_count
   - primary_src_mac / primary_dst_mac
   - src_macs / dst_macs / all_macs
   - unique_mac_count
5. Generating_dataset_metadata.py provides a Colab-friendly CLI and preserves
   the official 10 MB tcpdump splitting behavior by default.

IMPORTANT
---------
Do NOT feed the metadata columns into Random Forest.
Use only the original 39 feature columns for X.
Use all_macs / primary_* only for selecting evaluation subsets such as
Camera, Echo Dot 1, or AMCREST windows.

Example
-------
python Generating_dataset_metadata.py   --pcap /content/drive/MyDrive/CICIoT2023/DDoS-SYN_Flood.pcap   --output /content/drive/MyDrive/CICIoT2023/features_meta/DDoS-SYN_Flood_meta.csv   --attack-type DDoS-SYN_Flood   --binary-label 1   --workers 2
