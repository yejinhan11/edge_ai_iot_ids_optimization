"""Package existing Edge-IIoTset arrays and fixed partitions for a teammate."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'data/processed/edge_iiotset'
OUT=ROOT/'results/edge_iiotset_rf'


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    assert json.loads((OUT/'status.json').read_text(encoding='utf-8'))['status']=='complete'
    files=[LOCAL/'MLP_HANDOFF.json',LOCAL/'sample_manifest.parquet']+sorted(LOCAL.glob('*.npy'))
    assert all(p.is_file() for p in files)
    assert len(list(LOCAL.glob('rf_train_seed*.npy')))==3
    guide=ROOT/'docs/EDGE_IIOTSET_MLP_GUIDE.md'
    manifest=dict(dataset='Edge-IIoTset PCAP-derived 38-feature capture/scenario baseline',
        rows=1935894,features=38,labels={'0':'Normal capture','1':'DDoS capture'},
        files=[dict(name=p.name,bytes=p.stat().st_size,sha256=sha256(p)) for p in files],
        guide_sha256=sha256(guide),
        extract='copy edge_iiotset/ into data/processed/edge_iiotset/ in a clone of the repository',
        excluded=['PCAPs','RF joblib models','extraction cache','raw feature parts'])
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'MLP_HANDOFF.json').write_bytes((LOCAL/'MLP_HANDOFF.json').read_bytes())
    (OUT/'MLP_PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    target=ROOT/'data/exports/edge_iiotset_mlp_handoff.zip'
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix('.zip.part')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for path in files:archive.write(path,'edge_iiotset/'+path.name)
        archive.write(guide,'EDGE_IIOTSET_MLP_GUIDE.md')
        archive.writestr('edge_iiotset/PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(temp) as archive:
        assert archive.testzip() is None
        for record in manifest['files']:
            h=hashlib.sha256()
            with archive.open('edge_iiotset/'+record['name']) as stream:
                for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
            assert h.hexdigest()==record['sha256'],record['name']
    temp.replace(target)
    print(json.dumps(dict(package=str(target),bytes=target.stat().st_size,files=len(files),all_member_hashes_verified=True),ensure_ascii=False))


if __name__=='__main__':main()
