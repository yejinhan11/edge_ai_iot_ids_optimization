"""Build a complete Markdown report and matplotlib figures from saved results."""
from pathlib import Path
import itertools
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / 'results/tables'
OUT = ROOT / 'results/reports'
FIG = OUT / 'figures'


def table(frame):
    def cell(v):
        if pd.isna(v):
            return '—'
        if isinstance(v, (float, np.floating)):
            return f'{v:.6f}'
        return str(v).replace('|', '\\|').replace('\n', '<br>')
    return '\n'.join(['| ' + ' | '.join(map(str, frame.columns)) + ' |',
                      '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |'] +
                     ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in frame.itertuples(index=False, name=None)])


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    parts = []
    def add(rows, columns):
        parts.append(table(pd.DataFrame(rows, columns=columns)))
    sweeps = []
    sources = []
    for p in sorted(TABLES.glob('*.csv')):
        if p.name.startswith('sweep_') or (p.name.startswith('rf_') and 'importance' not in p.name and p.name != 'rf_comparison.csv'):
            d = pd.read_csv(p)
            sources.append((p, d))
            if p.name.startswith('sweep_'):
                sweeps.append(d.assign(source_file=p.name))
    s = pd.concat(sweeps, ignore_index=True)
    s['max_depth'] = s.max_depth.fillna(0).astype(int)
    keys = ['top_k', 'n_estimators', 'max_depth', 'min_leaf']
    measured = set(map(tuple, s[s.train_subset == 'all'][keys].drop_duplicates().to_numpy()))
    add([['보고서', '저장된 전체 실험 결과 · 순위 필터 없음'],
         ['범위', f'개별 결과 CSV {len(sources)}개, 평가 행 {sum(len(d) for _, d in sources)}개 + 이전 Colab 결과'],
         ['요청 조합', 'feature 5·10·15·20·38 × 트리 10·20·50·100 × 깊이 ∞·8·12·16 × min_leaf 1·10·100 = 240개'],
         ['전체 학습 sweep 실행 범위', f'{len(measured)}개 조합 결과 있음 / {240-len(measured)}개 조합 저장 결과 없음'],
         ['실험 방식', 'feature sweep 15개 모델; trees sweep 8개 모델; depth sweep 24개 모델. 단계 간 동일 설정의 재측정도 보존'],
         ['자료 한계', '로컬 PCAP은 각 캡처 첫 2 GB 청크 중심(HTTP_Flood·SlowLoris·BenignTraffic3 제외). 전체 원본 548 GB 실험이 아님'],
         ['비교 주의', '추론시간은 PC 부하·실행 시점 영향. 동일 실행 묶음에서 비교; 서로 다른 데이터셋(test3·Colab)은 별도 비교'],
         ['표 정밀도', '소수 6자리 표시; 전체 원시 열·정밀도는 all_experiment_results.csv 및 원본 CSV 보존']], ['항목', '내용'])
    add([
        ['트리 수', '10·20·50·100', '확인: 100개 기준 모델과 경량 모델의 정확도·속도·크기 비교', '해석: 기준선의 10%·20%·50%·100% 수준을 탐색. 10/20은 큰 절감, 50은 중간, 100은 기준. 정확히 이 숫자를 고른 사전 근거는 기록 없음'],
        ['최대 깊이', '∞·8·12·16', '확인: 트리 성장 제한에 따른 성능·노드 수·크기 비교', '해석: ∞는 깊이 제한 없는 대조군; 8/12/16은 강한·중간·완화된 제한을 4단계 간격으로 탐색. 특정 논문이나 최적값에서 유도한 기록 없음'],
        ['깊이 값 간격', '8 → 12 → 16', '이진 트리의 깊이 d에서 최대 노드 수는 2^(d+1)−1', '이론상 상한 511 → 8,191 → 131,071개/트리. 실제 노드 수는 데이터·다른 제한에 따라 더 작음; ∞도 유한 데이터에서는 유한 트리'],
        ['min_samples_leaf', '1·10·100', '확인: 말단 노드에 필요한 최소 학습 표본 수를 증가시키는 실험', '해석: 1은 최소 제약 기준선, 10/100은 10배 간격의 중간/강한 제약. 작은 가지를 줄여 크기·과적합을 완화할 수 있으나 세부 공격 탐지를 잃을 수 있음. 정확한 숫자의 선정 근거 기록 없음'],
        ['후속 sweep 고정값', 'feature 15·38; depth sweep 트리 20', '확인: 단계별 결과를 보고 탐색 범위를 축소', '로그: 15개는 성능 손실 약 0.5%p의 후보, 38개는 전체 입력; 20트리는 성능을 유지하며 경량화한 후보'],
        ['기타 공통 설정', 'seed=42; class_weight=balanced; 학습 최대 100만', '확인: sweep 코드와 결과의 공통 설정', '목적 해석: 난수 고정으로 재현, 클래스 불균형 보정, 학습 비용 제한. 시간순 70/30은 후반 트래픽 평가; LOAO는 미학습 공격 평가'],
        ['근거 파일', '[sweep_rf.py](../../src/sweep_rf.py) · [train_rf.py](../../src/train_rf.py) · [LOG.md](../../docs/LOG.md)', '실행 값·목적은 저장소에서 확인', '수치 선정 해석은 당시 의사결정의 확정적 증거가 아님'],
    ], ['변수', '설정', '확인된 목적·사실', '선정 기준 설명·기록 한계'])
    add([['accuracy', '전체 정답 비율'], ['precision / recall / f1', 'DDoS를 양성으로 계산'], ['f1_macro', 'Benign·DDoS F1의 단순 평균'], ['∞', 'sweep 원본 0 또는 RF 원본 빈 max_depth: 깊이 제한 없음'], ['—', '미기록 값; min_leaf 미기록 값은 임의 보충하지 않음'], ['모델 MB', '비압축 joblib 파일 크기, 1 MB=10⁶ bytes; 실행 메모리와 다름'], ['추론 µs', '단일 스레드, 최대 10만 표본, 워밍업 후 5회 중앙값; feature 추출 시간 제외'], ['평가 subset', 'all·camera·audio·echo_dot1·amcrest는 중첩 가능, 행 수 합산 금지']], ['표기', '의미'])
    inventory = [[p.name, len(d), d.train_subset.iloc[0] if 'train_subset' in d else '—', ', '.join(d.test_subset.unique())] for p, d in sources]
    parts.append(table(pd.DataFrame(inventory, columns=['원본', '전체 평가 행 수', '첫 행 학습 subset', '평가 subset'])))
    grid = []
    for k, n, dep, leaf in itertools.product([5,10,15,20,38], [10,20,50,100], [0,8,12,16], [1,10,100]):
        match = s[(s.train_subset == 'all') & (s.top_k == k) & (s.n_estimators == n) & (s.max_depth == dep) & (s.min_leaf == leaf)]
        grid.append([k,n,'∞' if dep == 0 else dep,leaf,'있음' if len(match) else '저장 결과 없음', ', '.join(match.source_file.unique()) or '—'])
    parts.append(table(pd.DataFrame(grid, columns=['feature', '트리', '깊이', 'min_leaf', '전체 학습 결과', '출처'])))
    # Every recorded sweep point appears in both cost plots, including all train/test subsets.
    fig, axes = plt.subplots(1, 2, figsize=(12,5))
    for name, g in s.groupby('sweep'):
        for ax, x, label in zip(axes, ['infer_us_per_sample','model_mb'], ['Inference (us/sample)', 'Model size (MB)']):
            ax.scatter(g[x], g.f1_macro, label=f'{name} ({len(g)} rows)', alpha=.65, s=25)
            ax.set(xlabel=label, ylabel='Macro F1', xscale='log')
            ax.grid(alpha=.25)
            ax.legend()
    fig.suptitle('All sweep evaluations (no ranking filter)')
    fig.tight_layout()
    fig.savefig(FIG / 'all_sweep_tradeoffs.png', dpi=180)
    plt.close(fig)
    parts.append('![전체 sweep 평가 행의 성능·비용 비교](figures/all_sweep_tradeoffs.png)')
    for subset in ['all','camera','audio']:
        d = s[(s.train_subset == 'all') & (s.test_subset == subset)]
        fig, axes = plt.subplots(2, 3, figsize=(15,8))
        for col, name in enumerate(['features','trees','depth']):
            g = d[d.sweep == name]
            x = {'features':'top_k','trees':'n_estimators','depth':'max_depth'}[name]
            groups = [((),g)] if name == 'features' else list(g.groupby('top_k' if name == 'trees' else ['top_k','min_leaf']))
            for key, h in groups:
                h = h.assign(plot_x=h[x].replace(0,20) if name == 'depth' else h[x]).sort_values('plot_x')
                for row, metric in enumerate(['f1_macro','model_mb']):
                    axes[row,col].plot(h.plot_x, h[metric], marker='o', label=str(key))
            for row in range(2):
                ax = axes[row,col]
                ax.set(xlabel=x, ylabel=['Macro F1','Model size (MB)'][row])
                ax.grid(alpha=.25)
                if name == 'depth':
                    ax.set_xticks([8,12,16,20], ['8','12','16','Unlimited'])
                if name != 'features':
                    ax.legend(title='features' if name == 'trees' else '(features, min_leaf)', fontsize=8)
        fig.suptitle(f'All recorded configurations | train=all | test={subset}')
        fig.tight_layout()
        fig.savefig(FIG / f'sweeps_{subset}.png', dpi=180)
        plt.close(fig)
        parts.append(f'![전체 학습 / {subset} 평가의 변수별 비교](figures/sweeps_{subset}.png)')
    raw = []
    for p, d in sources:
        raw.append(d.assign(source_file=p.name))
        add([[p.name, len(d), f'[원본 CSV](../tables/{p.name})']], ['전체 결과 표', '평가 행 수', '원시 데이터'])
        display = d.copy()
        display.insert(0, 'row_id', range(1,len(d)+1))
        display['max_depth'] = display.max_depth.map(lambda v: '∞' if pd.isna(v) or v == 0 else str(int(v)))
        identifiers = [c for c in ['row_id','tag','sweep','split','holdout','train_subset','test_subset','top_k','n_features','n_estimators','max_depth','min_leaf'] if c in display]
        metrics = ['n','accuracy','precision','recall','f1','f1_macro','infer_us_per_sample','model_mb']
        parts.append(table(display[identifiers + metrics]))
        other = [c for c in display if c not in identifiers + metrics]
        # Split wide auxiliary tables without omitting any original column.
        for start in range(0,len(other),8):
            parts.append(table(display[['row_id'] + other[start:start+8]]))
    legacy = ROOT / 'data/legacy/rf_full_vs_camera_result.csv'
    if legacy.exists():
        add([['이전 Colab 결과', '공식 feature 적용 전; 현행 RF·sweep와 직접 비교 불가']], ['별도 실험', '조건'])
        parts.append(table(pd.read_csv(legacy)))
    for p in sorted(TABLES.glob('*feature_importance.csv')):
        add([[p.name, '전체 feature 중요도; 순위 필터 없음']], ['부록', '범위'])
        parts.append(table(pd.read_csv(p)))
    add([['재생성 명령', '.venv\\Scripts\\python.exe src/report_all_results.py'], ['그래프 구현', 'Python matplotlib; PNG 삽입 문법: `![설명](figures/파일명.png)`'], ['공유 방법', 'reports 폴더 전체를 공유하면 Markdown과 그래프 상대 경로가 유지됨'], ['중복 집계', 'rf_comparison.csv와 final_candidates.csv는 개별 RF 결과의 요약본이므로 추가 실험으로 중복 집계하지 않음']], ['사용 방법', '내용'])
    combined = pd.concat(raw, ignore_index=True, sort=False)
    combined.to_csv(OUT / 'all_experiment_results.csv', index=False, encoding='utf-8-sig')
    (OUT / 'all_experiment_results.md').write_text('\n\n'.join(parts)+'\n', encoding='utf-8')
    assert len(grid) == 240
    assert len(combined) == sum(len(d) for _,d in sources)
    print(f'Wrote {len(combined)} evaluation rows; {len(measured)}/240 sweep combinations; {len(s)} plotted sweep rows.')


if __name__ == '__main__':
    main()
