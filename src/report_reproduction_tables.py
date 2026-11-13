"""Create Korean tables grouped by experiment from this laptop's RF rerun."""
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'results/reproduction_20261025'
OUT = SOURCE / 'tables_by_experiment'
NAMES = {'all': '전체', 'camera': '카메라', 'audio': '오디오',
         'echo_dot1': 'Echo Dot 1', 'amcrest': 'AMCREST'}


def md(frame):
    def fmt(v):
        if pd.isna(v):
            return '—'
        if isinstance(v, float):
            return f'{v:.4f}'
        return str(v).replace('|', '\\|')
    return '\n'.join(['| ' + ' | '.join(frame.columns) + ' |',
                      '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |'] +
                     ['| ' + ' | '.join(map(fmt, row)) + ' |'
                      for row in frame.itertuples(index=False, name=None)])


def display(d):
    out = pd.DataFrame(index=d.index)
    if 'candidate' in d:
        out['후보'] = d.candidate
    if 'holdout' in d and d.holdout.notna().any():
        out['학습 제외 공격'] = d.holdout.fillna('').str.replace('DDoS-', '', regex=False)
    out['학습 대상'] = d.train_subset.map(NAMES)
    out['평가 대상'] = d.test_subset.map(NAMES)
    out['특징 수'] = d['n_features'] if 'n_features' in d else d.top_k
    out['트리 수'] = d.n_estimators.astype(int)
    out['최대 깊이'] = d.max_depth.map(lambda v: '제한 없음' if pd.isna(v) or v == 0 else str(int(v)))
    out['최소 말단 표본'] = d.get('min_leaf', pd.Series(1, index=d.index)).fillna(1).astype(int)
    out['학습 행 수'] = d.train_rows.astype(int)
    out['평가 행 수'] = d.n.astype(int)
    out['정확도(%)'] = d.accuracy * 100
    out['F1-macro'] = d.f1_macro
    out['DDoS 재현율(%)'] = d.recall * 100
    out['학습 시간(초)'] = d.train_sec
    out['추론(µs/행)'] = d.infer_us_per_sample
    out['모델(MB)'] = d.model_mb
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    OUT.mkdir(parents=True, exist_ok=True)
    def load(name):
        return pd.read_csv(SOURCE / name).assign(source_file=name)
    basic = pd.concat([load(f'rf_{tag}.csv') for tag in ['v1', 'v1_cam', 'v1_audio']], ignore_index=True)
    final, loao = [], []
    for tag, name in [('base', '기준선'), ('c1', 'C1'), ('c2', 'C2'), ('c3', 'C3'), ('c4', 'C4')]:
        final.append(load(f'rf_final_{tag}.csv').assign(candidate=name))
        for attack in ['syn', 'slowloris']:
            loao.append(load(f'rf_final_{tag}_loao_{attack}.csv').assign(candidate=name))
    loao += [load(f'rf_loao_{attack}.csv').assign(candidate='초기 LOAO') for attack in ['syn', 'slowloris']]
    groups = [
        ('01_basic', '기본·기기별 학습 비교', basic),
        ('02_final', '최종 경량화 후보 — 시간순 분할', pd.concat(final, ignore_index=True)),
        ('03_loao', '처음 보는 공격 평가 — 해당 공격을 학습에서 제외', pd.concat(loao, ignore_index=True)),
        ('04_features', '특징 수 탐색', load('sweep_features.csv')),
        ('05_trees', '트리 수 탐색', load('sweep_trees.csv')),
        ('06_depth', '깊이·최소 말단 표본 수 탐색', load('sweep_depth.csv')),
        ('07_test3', '초기 3개 파일 실험 — 전체 데이터 실험과 별도 비교', load('rf_test3.csv')),
    ]
    parts = ['# 현재 노트북 RF 결과 — 실험 종류별 전체 표',
             '기존 결과를 재현한 **이번 노트북의 측정값**이다. 평가 242행을 모두 포함한다. '
             '기존 성능과의 일치 여부는 [재현 검증 보고서](../REPORT.md)를 참고한다.',
             '정확도·재현율은 %, F1-macro는 0~1이다. 추론은 단일 CPU 스레드의 µs/행이며 특징 추출 시간은 제외한다. '
             '학습은 최대 100만 행(초기 3파일 실험은 50만 행), 시간순 70/30 분할, 시드 42를 사용했다. '
             'LOAO는 지정 공격을 학습에서 제외하는 별도 분할이다.',
             '모델 크기는 비압축 직렬화 MB이며 RAM 사용량과 다르다. 평가 대상은 서로 겹칠 수 있다. '
             '동일 학습 설정은 재학습 결과를 공유하므로 표의 같은 시간이 독립 반복 측정값을 의미하지 않는다. '
             '최소 말단 표본 수가 원본에 없던 초기 RF는 코드 기본값 1을 표시했다.',
             '현재 PCAP은 공격 캡처의 첫 2GB 청크 중심이다(HTTP_Flood·SlowLoris·BenignTraffic3 제외). '
             'CICIoT2023 전체 원본을 사용한 실험은 아니다. 초기 Colab의 별도 특징 실험은 제외했다.']
    total = 0
    for key, title, raw in groups:
        total += len(raw)
        raw.to_csv(OUT / f'{key}_raw.csv', index=False, encoding='utf-8-sig')
        shown = display(raw)
        shown.to_csv(OUT / f'{key}.csv', index=False, encoding='utf-8-sig')
        parts += [f'## {title} ({len(raw)}행)', f'[엑셀에서 여는 CSV]({key}.csv) · [원시 지표 전체]({key}_raw.csv)', md(shown)]
    assert total == 242, total
    (OUT / 'ALL_TABLES.md').write_text('\n\n'.join(parts) + '\n', encoding='utf-8')
    print('Wrote 7 categories, 242 rows:', OUT / 'ALL_TABLES.md')
    print('\nBASIC\n' + md(display(basic).loc[:, ['학습 대상','평가 대상','정확도(%)','F1-macro','추론(µs/행)','모델(MB)']]))
    fin = pd.concat(final, ignore_index=True)
    print('\nFINAL\n' + md(display(fin[fin.test_subset=='all']).loc[:, ['후보','특징 수','트리 수','최대 깊이','정확도(%)','F1-macro','추론(µs/행)','모델(MB)']]))
    for name in ['features','trees','depth']:
        d = load(f'sweep_{name}.csv')
        d = d[(d.train_subset=='all') & (d.test_subset=='all')]
        print('\n'+name.upper()+'\n'+md(display(d).loc[:, ['특징 수','트리 수','최대 깊이','최소 말단 표본','정확도(%)','F1-macro','추론(µs/행)','모델(MB)']]))
    l = pd.concat(loao, ignore_index=True)
    l = l[(l.test_subset=='all') & (l.candidate!='초기 LOAO')]
    print('\nLOAO\n'+md(display(l).loc[:,['후보','학습 제외 공격','정확도(%)','F1-macro','DDoS 재현율(%)']]))


if __name__ == '__main__':
    main()
