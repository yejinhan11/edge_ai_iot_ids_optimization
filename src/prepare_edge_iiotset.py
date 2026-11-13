"""Extract the established 38 numeric features from Edge-IIoTset PCAP scenarios."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

import dpkt
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/pcap2csv_metadata_v2'))
from build_dataset import FEATURES, RATE_CAP, IAT_MAX
from split_pcap import split_pcap

OUT=ROOT/'results/edge_iiotset_rf'
LOCAL=ROOT/'data/processed/edge_iiotset'
WORK=ROOT/'data/tmp/edge_iiotset'


def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''): h.update(block)
    return h.hexdigest()


def scenario(path):
    if path.parent.name=='Normal traffic': return 'Normal',0
    names={'DDoS HTTP Flood Attacks':'DDoS_HTTP','DDoS ICMP Flood Attacks':'DDoS_ICMP',
           'DDoS TCP SYN Flood Attacks':'DDoS_TCP_SYN','DDoS UDP Flood Attacks':'DDoS_UDP'}
    if path.parent.name=='Attack traffic' and path.stem in names: return names[path.stem],1
    raise ValueError(f'Unknown capture scenario: {path}')


def extract_chunk(chunk, output, code_hash):
    import warnings
    warnings.filterwarnings('ignore')
    from Feature_extraction_fast import Feature_extraction
    chunk,output=Path(chunk),Path(output)
    sidecar=output.with_suffix('.json')
    if output.exists() and sidecar.exists():
        info=json.loads(sidecar.read_text(encoding='utf-8'))
        assert info['code_hash']==code_hash
        return info
    base=output.with_suffix('')
    with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
        Feature_extraction().pcap_evaluation(str(chunk),str(base),compute_unused_flows=False)
    csv=base.with_suffix('.csv')
    frame=pd.read_csv(csv)
    frame.to_parquet(output,index=False)
    csv.unlink()
    info=dict(chunk=chunk.name,rows=len(frame),code_hash=code_hash)
    save_json(sidecar,info)
    return info


def equivalence_probe(source,folder):
    from Feature_extraction_fast import Feature_extraction
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'probe.pcap'
    with source.open('rb') as stream,path.open('wb') as target:
        reader=dpkt.pcap.Reader(stream)
        assert reader.datalink()==1
        writer=dpkt.pcap.Writer(target)
        for i,(ts,buf) in enumerate(reader):
            writer.writepkt(buf,ts)
            if i>=1999:break
    for option in [True,False]:
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            Feature_extraction().pcap_evaluation(str(path),str(folder/str(option)),compute_unused_flows=option)
    a=pd.read_csv(folder/'True.csv'); b=pd.read_csv(folder/'False.csv')
    pd.testing.assert_frame_equal(a,b,check_exact=True)
    assert len(a)>0
    return dict(source=source.name,probe_packets=i+1,windows=len(a),exact_original_backend_match=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workers',type=int,default=4)
    args=ap.parse_args()
    for folder in [OUT,LOCAL/'parts',WORK]: folder.mkdir(parents=True,exist_ok=True)
    code_files=[Path(__file__),ROOT/'src/split_pcap.py',ROOT/'src/build_dataset.py']+sorted((ROOT/'tools/pcap2csv_metadata_v2').glob('*.py'))
    code_hash=hashlib.sha256(b''.join(p.read_bytes() for p in code_files)).hexdigest()
    files=sorted((ROOT/'data/raw/edge_iiotset').rglob('*.pcap'),key=lambda p:(scenario(p)[1],p.name))
    assert len(files)==14 and sum(scenario(p)[1]==0 for p in files)==10
    audit=[]; probes=[]; started=time.time()
    for number,source in enumerate(files,1):
        name=source.stem.replace(' ','_')
        target=LOCAL/'parts'/f'{name}.parquet'
        done=OUT/'extraction_metadata'/f'{name}.json'
        fingerprint=dict(bytes=source.stat().st_size,sha256=sha256(source))
        if target.exists() and done.exists():
            info=json.loads(done.read_text(encoding='utf-8'))
            assert info['code_hash']==code_hash and info['input']==fingerprint
            audit.append(info)
            print('RESUME',source.name,info['rows_out'],flush=True)
            continue
        save_json(OUT/'status.json',dict(status='extracting',file=source.name,file_number=number,total_files=len(files),stage='probe_and_split',elapsed_sec=time.time()-started))
        print('FILE',number,'/',len(files),source.name,flush=True)
        work=WORK/name;work.mkdir(parents=True,exist_ok=True)
        probes.append(equivalence_probe(source,work/'probe'))
        save_json(OUT/'backend_equivalence.json',dict(probes=probes))
        split_cache=work/'split.json'
        if split_cache.exists():
            split=json.loads(split_cache.read_text(encoding='utf-8'))
            assert split['input']==fingerprint and split['chunk_packets']==20000
            chunks=[work/'pcap'/n for n in split['chunks']]
            assert all(p.exists() for p in chunks)
            n_read,n_acc=split['packets_read'],split['packets_accepted']
        else:
            chunks,n_read,n_acc=split_pcap(source,work/'pcap',20000)
            save_json(split_cache,dict(input=fingerprint,chunk_packets=20000,chunks=[p.name for p in chunks],packets_read=n_read,packets_accepted=n_acc))
        outputs=[work/f'{p.stem}.parquet' for p in chunks]
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            jobs={executor.submit(extract_chunk,str(p),str(out),code_hash):p for p,out in zip(chunks,outputs)}
            for finished,future in enumerate(as_completed(jobs),1):
                future.result()
                if finished%10==0 or finished==len(jobs):
                    print('CHUNKS',name,finished,'/',len(jobs),flush=True)
                    save_json(OUT/'status.json',dict(status='extracting',file=source.name,file_number=number,total_files=len(files),chunks_completed=finished,chunks_total=len(jobs),elapsed_sec=time.time()-started))
        frames=[];row_offset=0;stats=dict(rows_in=0,drop_short=0,drop_iat=0,rate_capped=0)
        label,binary=scenario(source)
        for part_index,path in enumerate(outputs):
            frame=pd.read_parquet(path)
            frame['row_in_file']=np.arange(row_offset,row_offset+len(frame),dtype=np.int64)
            row_offset+=len(frame)
            short=frame.window_packet_count!=10; bad_iat=frame.IAT>IAT_MAX
            stats['rows_in']+=len(frame);stats['drop_short']+=int(short.sum());stats['drop_iat']+=int((bad_iat & ~short).sum())
            frame=frame[~short & ~bad_iat].copy()
            stats['rate_capped']+=int((np.isinf(frame.Rate) | (frame.Rate>RATE_CAP)).sum())
            frame['Rate']=frame.Rate.clip(upper=RATE_CAP)
            frame[['Std','Variance']]=frame[['Std','Variance']].fillna(0.)
            frame[FEATURES]=frame[FEATURES].astype(np.float32)
            assert np.isfinite(frame[FEATURES].to_numpy()).all(), source
            frame['source_pcap']=source.name;frame['attack_type']=label;frame['binary_label']=np.int8(binary)
            frame['chunk_id']=np.int32(part_index)
            frames.append(frame[FEATURES+['source_pcap','attack_type','binary_label','row_in_file','chunk_id','window_start_ts','window_end_ts','window_packet_count']])
        merged=pd.concat(frames,ignore_index=True)
        assert len(merged)>0
        temp=target.with_suffix('.tmp.parquet');merged.to_parquet(temp,index=False,compression='zstd');temp.replace(target)
        info=dict(source=source.name,input=fingerprint,code_hash=code_hash,scenario_label=label,binary_label=binary,
                  rows_out=len(merged),packets_read=n_read,packets_accepted=n_acc,chunks=len(chunks),
                  accepted_packet_tail=n_acc%10,timestamp_backwards=int((merged.window_start_ts.diff()<0).sum()),**stats,
                  label_scope='capture/scenario label; not independently matched per-packet ground truth')
        save_json(done,info);audit.append(info)
        pd.DataFrame(audit).to_csv(OUT/'extraction_summary.csv',index=False)
        print('EXTRACTED',source.name,len(merged),'windows',flush=True)
    pd.DataFrame(audit).to_csv(OUT/'extraction_summary.csv',index=False)
    save_json(OUT/'preparation.json',dict(status='complete',files=len(audit),rows=sum(r['rows_out'] for r in audit),
        features=FEATURES,window=10,chunk_accepted_packets=20000,code_hash=code_hash,
        label_scope='normal versus DDoS capture/scenario; mixed benign packets in attack captures not separately resolved',
        source='https://doi.org/10.1109/ACCESS.2022.3165809',elapsed_sec=time.time()-started))
    save_json(OUT/'status.json',dict(status='features_ready',files=len(audit),elapsed_sec=time.time()-started))
    print('PREPARATION_COMPLETE',sum(r['rows_out'] for r in audit),'windows',flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        save_json(OUT/'failure.json',dict(traceback=traceback.format_exc(),stage='preparation'))
        raise
