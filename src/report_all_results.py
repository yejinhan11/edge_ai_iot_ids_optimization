"""Build the all-results report: every RF / sweep / final-candidate row as markdown tables + PNG figures.

Reads results/tables/*.csv (nothing is re-trained) and writes
  docs/RESULTS_ALL.md
  results/figures/report/*.png

Usage:  python src/report_all_results.py
"""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLES, FIGS, OUT = ROOT / 'results/tables', ROOT / 'results/figures/report', ROOT / 'docs/RESULTS_ALL.md'

# categorical palette (dataviz reference, light mode): blue, orange, aqua, yellow, magenta
C = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4']
INK, INK2, MUTED, GRID, AXIS, SURFACE = '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7', '#fcfcfb'

if any(f.name == 'Malgun Gothic' for f in font_manager.fontManager.ttflist):
    plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams.update({'axes.unicode_minus': False, 'font.size': 10, 'figure.facecolor': SURFACE,
                     'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE, 'text.color': INK,
                     'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2})

SUB_KO = {'all': '전체', 'camera': '카메라', 'audio': '오디오', 'echo_dot1': 'Echo Dot 1', 'amcrest': 'AMCREST'}


# ---------------------------------------------------------------- helpers
def style(ax, xlabel='', ylabel=''):
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ['top', 'right']:
        ax.spines[s].set_visible(False)
    for s in ['left', 'bottom']:
        ax.spines[s].set_color(AXIS)
    ax.tick_params(length=0)


def legend(ax, **kw):
    ax.legend(frameon=False, labelcolor=INK2, **kw)


def line(ax, x, y, color, label=None):
    ax.plot(x, y, color=color, linewidth=2, marker='o', markersize=7, markeredgecolor=SURFACE,
            markeredgewidth=2, label=label, solid_capstyle='round')


def depth_str(v):
    return '∞' if (pd.isna(v) or int(v) == 0) else str(int(v))


def md_table(df, cols, fmt=None):
    """df -> markdown table; cols = [(column, header)], fmt = {column: format-string or callable}."""
    fmt = fmt or {}
    lines = ['| ' + ' | '.join(h for _, h in cols) + ' |',
             '|' + '|'.join('---:' if pd.api.types.is_numeric_dtype(df[c]) else '---' for c, _ in cols) + '|']
    for _, r in df.iterrows():
        cells = []
        for c, _ in cols:
            v = r[c]
            f = fmt.get(c)
            if callable(f):
                cells.append(f(v))
            elif f:
                cells.append(f.format(v))
            elif isinstance(v, float):
                cells.append(f'{v:.4f}')
            else:
                cells.append(str(v))
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


F4, F1D, INT = '{:.4f}', '{:.1f}', lambda v: f'{int(v):,}'
K = lambda v: f'{v / 1000:.0f}k'  # noqa: E731


def fig_path(name):
    return f'../results/figures/report/{name}.png'


# ---------------------------------------------------------------- load
def load_sweep(name):
    d = pd.read_csv(TABLES / f'sweep_{name}.csv')
    d['depth'] = d['max_depth'].fillna(0).astype(int)
    return d


sw_f, sw_t, sw_d = load_sweep('features'), load_sweep('trees'), load_sweep('depth')
fin = pd.read_csv(TABLES / 'final_candidates.csv')
fin['depth'] = fin['max_depth'].fillna(0).astype(int)
comp = pd.read_csv(TABLES / 'rf_comparison.csv')

FIGS.mkdir(parents=True, exist_ok=True)
md = []


def section(title):
    md.append(f'\n## {title}\n')


# ---------------------------------------------------------------- 0. design
md.append('# RF 실험 결과 전체 정리\n')
md.append('모든 결과는 각 PCAP 캡처의 **첫 2 GB 청크**(HTTP_Flood, SlowLoris, BenignTraffic3는 원본 전체)에서 추출한 '
          '20,990,150개 윈도우 기준. 학습은 무작위 100만 행, 평가는 테스트 전체. '
          '표의 값은 `results/tables/*.csv`를 그대로 옮긴 것이며 생략한 실험은 없다. '
          '이 문서와 그림은 `python src/report_all_results.py`로 다시 만들 수 있다.\n')

section('0. 실험 설계 요약')
md.append('**조합 수.** feature 5종 × 트리 4종 × 깊이 4종 × min_leaf 3종을 모두 조합한 240개 설정 전체를 학습한 적은 없다. '
          '한 번에 한 변수씩 바꾸는 방식으로 아래 **47개 설정만** 학습했고, 마지막에 후보 5개를 평가 3종으로 재학습(15회)했다. '
          '이 문서의 모든 표는 그 결과에서 나온 것이다.\n')
md.append(md_table(pd.DataFrame([
    ['1단계 feature', 'feature 5/10/15/20/38 × 학습 데이터(전체/카메라/오디오)', '트리 100, 깊이 ∞, leaf 1', 15],
    ['2단계 트리', '트리 10/20/50/100 × feature 15/38', '깊이 ∞, leaf 1, 전체 학습', 8],
    ['3단계 깊이', '깊이 8/12/16/∞ × min_leaf 1/10/100 × feature 15/38', '트리 20, 전체 학습', 24],
    ['4단계 최종', '후보 5개 × (time split, LOAO-SYN, LOAO-SlowLoris)', '', 15],
], columns=['단계', '바꾼 변수', '고정', '모델 수']),
    [('단계', '단계'), ('바꾼 변수', '바꾼 변수'), ('고정', '고정'), ('모델 수', '학습 모델 수')]))
md.append('\n**변수 값을 정한 기준.** 설계 당시 기준이며 `docs/LOG.md`에는 값만 기록돼 있다.\n')
md.append(md_table(pd.DataFrame([
    ['feature 수', '5 / 10 / 15 / 20 / 38', '`rf_v1` 중요도 순위 상위 k개. 38 = 전체.'],
    ['트리 수', '10 / 20 / 50 / 100', '100 = scikit-learn 기본값이자 기준 모델. 추론시간·모델 크기가 트리 수에 정비례하므로 '
     '100에서 절반씩 줄여 10배 범위를 4점으로 봄. 10 미만은 앙상블이라 보기 어려워 제외.'],
    ['깊이', '∞ / 16 / 12 / 8', '∞ = 기본값(실제 트리 깊이 77~85). 트리당 리프 수 상한이 2^깊이(8→256, 12→4k, 16→65k)라 '
     '노드 수가 수십 배 줄어드는 구간을 4 간격으로 잡음. 20 이상은 ∞와 노드 수 차이가 작을 것으로 보고 제외(추정).'],
    ['min_leaf', '1 / 10 / 100', '1 = 기본값. 10배 간격 2점. 깊이와 같은 "트리 크기 제한" 변수라 3단계에서 깊이와 함께 격자로 봄.'],
    ['2·3단계의 feature', '15, 38', '1단계에서 F1 손실 0.5%p 이내인 최소값(15)과 전체(38).'],
    ['3단계의 트리', '20', '2단계에서 F1 손실 없이 가장 적은 트리 수.'],
    ['학습 행 수', '100만 (무작위)', '학습 가능 행 1,469만 중 메모리·시간 제약으로 상한. 1단계 카메라 학습 모델이 650 MB까지 커진 원인이기도 함.'],
    ['class_weight', 'balanced', 'DDoS : Benign = 18 : 1 불균형 보정.'],
    ['split', '파일별 시간순 70/30', '같은 파일의 앞뒤를 섞어 평가하는 시간 누수 방지.'],
    ['LOAO 공격', 'SYN_Flood, SlowLoris', '대량 flood 대표 1종 + 저속 공격 대표 1종을 학습에서 빼고 평가.'],
    ['평가 subset', 'all / camera / audio (+ echo_dot1, amcrest)', '카메라 = 정상 트래픽 최다 기기 종류, 오디오 = DDoS 피해 최다. '
     'sweep은 앞 3개, 단일 학습(`train_rf.py`)은 5개 모두 평가.'],
    ['seed', '42, 설정당 1회', '반복 없음. 같은 설정(k38 t20)이 2단계 0.9618, 4단계 0.9608로 실행 간 약 0.001 차이.'],
    ['지표', 'F1(macro) 우선', 'Accuracy는 DDoS 95%인 데이터에서 아무것도 안 해도 0.95라 의미가 약함.'],
], columns=['변수', '값', '기준']), [('변수', '변수'), ('값', '값'), ('기준', '기준')]))

# ---------------------------------------------------------------- 0-1. one-variable slices
md.append('\n### 0-1. 한 변수씩만 바꾼 결과 (§2~§4에서 발췌)\n')
md.append('전체 학습 모델. 각 표는 해당 변수 외 나머지를 고정한 행만 모은 것이며, 원본 행은 괄호 안 절에 있다. '
          '고정값이 표마다 다르다(feature 실험은 트리 100, 깊이·min_leaf 실험은 트리 20).\n')
ONE_COLS = [('값', '값'), ('f1m_all', 'F1m 전체'), ('f1m_camera', 'F1m 카메라'), ('f1m_audio', 'F1m 오디오'),
            ('acc_all', 'Acc 전체'), ('recall_all', 'Recall 전체'), ('infer_us_per_sample', '추론 µs'),
            ('model_mb', '모델 MB'), ('total_nodes', '노드')]
ONE_FMT = {'total_nodes': INT, 'infer_us_per_sample': F1D, 'model_mb': F1D}


def one_var(d, mask, var, label):
    s = d[mask & (d.train_subset == 'all')]
    rows = []
    for v, g in s.groupby(var, sort=True):
        g = g.set_index('test_subset')
        rows.append(dict(값=label(v), f1m_all=g.f1_macro['all'], f1m_camera=g.f1_macro['camera'], f1m_audio=g.f1_macro['audio'],
                         acc_all=g.accuracy['all'], recall_all=g.recall['all'], infer_us_per_sample=g.infer_us_per_sample['all'],
                         model_mb=g.model_mb['all'], total_nodes=g.total_nodes['all'], _k=v))
    return pd.DataFrame(rows).sort_values('_k', key=lambda s: s.replace({0: 999}))


md.append('\n**feature 수만** (트리 100, 깊이 ∞, leaf 1 고정 — §2)\n')
md.append(md_table(one_var(sw_f, sw_f.n_estimators == 100, 'top_k', str), ONE_COLS, ONE_FMT))
md.append('\n**트리 수만** (feature 38, 깊이 ∞, leaf 1 고정 — §3)\n')
md.append(md_table(one_var(sw_t, sw_t.top_k == 38, 'n_estimators', str), ONE_COLS, ONE_FMT))
md.append('\n**깊이만** (feature 38, 트리 20, leaf 1 고정 — §4)\n')
md.append(md_table(one_var(sw_d, (sw_d.top_k == 38) & (sw_d.min_leaf == 1), 'depth', depth_str), ONE_COLS, ONE_FMT))
md.append('\n**min_leaf만** (feature 38, 트리 20, 깊이 ∞ 고정 — §4)\n')
md.append(md_table(one_var(sw_d, (sw_d.top_k == 38) & (sw_d.depth == 0), 'min_leaf', str), ONE_COLS, ONE_FMT))
md.append('\n같은 네 묶음을 feature 15로 고정한 경우(트리·깊이·min_leaf)도 §3·§4 원본 표에 있다.\n')

# ---------------------------------------------------------------- 1. baseline experiments
section('1. 기준 실험 (9/25~26): 전체 vs 기기별 학습, LOAO')
base_tags = {'v1': '전체 학습', 'v1_cam': '카메라 학습', 'v1_audio': '오디오 학습',
             'loao_syn': 'LOAO SYN 제외', 'loao_slowloris': 'LOAO SlowLoris 제외'}
b = comp[comp.tag.isin(base_tags)].copy()
b['실험'] = b.tag.map(base_tags)
b['테스트'] = b.test_subset.map(SUB_KO)
b['order'] = b.tag.map({t: i for i, t in enumerate(base_tags)})
b['so'] = b.test_subset.map({'all': 0, 'camera': 1, 'audio': 2, 'echo_dot1': 3, 'amcrest': 4})
b = b.sort_values(['order', 'so'])
md.append('트리 100, feature 38, 깊이 ∞. `rf_v1.csv`, `rf_v1_cam.csv`, `rf_v1_audio.csv`, `rf_loao_syn.csv`, `rf_loao_slowloris.csv`.\n')
md.append(md_table(b, [('실험', '실험'), ('테스트', '테스트 subset'), ('n', '테스트 행'), ('accuracy', 'Acc'),
                       ('precision', 'Prec'), ('recall', 'Recall'), ('f1', 'F1'), ('f1_macro', 'F1m'),
                       ('majority_baseline_acc', '다수결 Acc'), ('infer_us_per_sample', '추론 µs'),
                       ('model_mb', '모델 MB'), ('total_nodes', '노드')],
                   {'n': INT, 'total_nodes': INT, 'infer_us_per_sample': F1D, 'model_mb': F1D}))

fig, ax = plt.subplots(figsize=(9, 4.8))
bb = b[b.test_subset.isin(['all', 'camera', 'audio'])].copy()
bb['label'] = bb['실험'] + ' → ' + bb['테스트']
bb = bb.iloc[::-1]
ypos = np.arange(len(bb))
ax.barh(ypos, bb.f1_macro, height=0.55, color=C[0])
ax.set_yticks(ypos, bb.label)
for y, v in zip(ypos, bb.f1_macro):
    ax.text(v + 0.004, y, f'{v:.3f}', va='center', color=INK2, fontsize=9)
ax.set_xlim(0, 1.08)
style(ax, 'F1 (macro)')
ax.grid(True, axis='x', color=GRID, linewidth=0.8)
ax.grid(False, axis='y')
ax.set_title('기준 실험 F1(macro) — 학습 데이터 → 테스트 subset', loc='left', color=INK)
fig.tight_layout()
fig.savefig(FIGS / 'fig1_baseline.png', dpi=150)
plt.close(fig)
md.append(f'\n![기준 실험 F1m]({fig_path("fig1_baseline")})\n')

# ---------------------------------------------------------------- 2. features
section('2. 1단계 feature 수 (sweep_features.csv, 45행)')
md.append('트리 100, 깊이 ∞, leaf 1. 학습 데이터 3종 × feature 5종 = 15개 모델, 각각 전체/카메라/오디오 테스트.\n')

# feature ranking used for top-k selection
imp = pd.read_csv(TABLES / 'rf_v1_feature_importance.csv', index_col=0)['importance'].sort_values(ascending=False)
rank = pd.DataFrame({'순위': range(1, len(imp) + 1), 'feature': imp.index, '중요도': imp.values})
rank['포함 k'] = ['5, 10, 15, 20, 38' if i < 5 else '10, 15, 20, 38' if i < 10 else '15, 20, 38' if i < 15
                 else '20, 38' if i < 20 else '38' for i in range(len(imp))]
md.append('**feature 순위.** 기준 모델 `rf_v1`(38 feature, 트리 100)의 Gini 중요도(`rf_v1_feature_importance.csv`). '
          '상위 k개를 쓰므로 k=15는 1~15위, k=20은 1~20위다. `Number`는 중요도 0(모든 윈도우가 10패킷이라 상수).\n')
md.append(md_table(rank, [('순위', '순위'), ('feature', 'feature'), ('중요도', '중요도'), ('포함 k', '포함되는 k')],
                   {'중요도': '{:.4f}', '순위': INT}))
fig, ax = plt.subplots(figsize=(9, 9))
ypos = np.arange(len(imp))[::-1]
ax.barh(ypos, imp.values, height=0.6, color=[C[0] if i < 15 else '#9ec5f4' for i in range(len(imp))])
ax.set_yticks(ypos, imp.index, fontsize=8.5)
for y, v in zip(ypos, imp.values):
    if v >= 0.005:
        ax.text(v + 0.002, y, f'{v:.3f}', va='center', color=INK2, fontsize=8)
for k in [5, 10, 15, 20]:
    ax.axhline(len(imp) - k - 0.5, color=AXIS, linewidth=0.8)
    ax.text(0.148, len(imp) - k - 0.3, f'k = {k}', color=MUTED, fontsize=8, ha='right')
style(ax, 'Gini 중요도 (rf_v1, 38 feature)')
ax.grid(True, axis='x', color=GRID, linewidth=0.8)
ax.grid(False, axis='y')
ax.set_xlim(0, 0.16)
ax.set_title('feature 중요도 순위 — 진한 색 = 상위 15 (C3 후보의 feature)', loc='left', color=INK)
fig.tight_layout()
fig.savefig(FIGS / 'fig2_feature_importance.png', dpi=150)
plt.close(fig)
md.append(f'\n![feature 중요도]({fig_path("fig2_feature_importance")})\n')
md.append('**sweep 결과.**\n')
sw_f['학습'] = sw_f.train_subset.map(SUB_KO)
sw_f['테스트'] = sw_f.test_subset.map(SUB_KO)
sw_f = sw_f.sort_values(['top_k', 'train_subset', 'test_subset'],
                        key=lambda s: s.map({'all': 0, 'camera': 1, 'audio': 2}) if s.name != 'top_k' else s)
SWEEP_COLS = [('top_k', 'feature'), ('n_estimators', '트리'), ('depth', '깊이'), ('min_leaf', 'leaf'), ('학습', '학습'),
              ('테스트', '테스트'), ('n', '테스트 행'), ('accuracy', 'Acc'), ('precision', 'Prec'), ('recall', 'Recall'),
              ('f1', 'F1'), ('f1_macro', 'F1m'), ('infer_us_per_sample', '추론 µs'), ('infer_samples_per_sec', 'samples/s'),
              ('model_mb', '모델 MB'), ('total_nodes', '노드'), ('train_sec', '학습 s')]
SWEEP_FMT = {'depth': depth_str, 'n': INT, 'total_nodes': INT, 'infer_us_per_sample': F1D, 'model_mb': F1D,
             'infer_samples_per_sec': K, 'train_sec': F1D}
md.append(md_table(sw_f, SWEEP_COLS, SWEEP_FMT))

fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
ax = axes[0]
for i, ts in enumerate(['all', 'camera', 'audio']):
    s = sw_f[(sw_f.train_subset == 'all') & (sw_f.test_subset == ts)].sort_values('top_k')
    line(ax, s.top_k, s.f1_macro, C[i], f'전체 → {SUB_KO[ts]}')
style(ax, 'feature 수 (중요도 상위 k)', 'F1 (macro)')
ax.set_title('전체 학습 모델, 테스트 subset별', loc='left', color=INK)
legend(ax, loc='lower right')
ax = axes[1]
pairs = [('all', 'camera', C[0], '전체 → 카메라'), ('camera', 'camera', C[1], '카메라 → 카메라'),
         ('all', 'audio', C[2], '전체 → 오디오'), ('audio', 'audio', C[3], '오디오 → 오디오')]
for tr, ts, col, lab in pairs:
    s = sw_f[(sw_f.train_subset == tr) & (sw_f.test_subset == ts)].sort_values('top_k')
    line(ax, s.top_k, s.f1_macro, col, lab)
style(ax, 'feature 수 (중요도 상위 k)')
ax.set_title('기기별 학습 vs 전체 학습', loc='left', color=INK)
legend(ax, loc='lower right')
for ax in axes:
    ax.set_xticks([5, 10, 15, 20, 38])
fig.tight_layout()
fig.savefig(FIGS / 'fig2_features_f1.png', dpi=150)
plt.close(fig)
md.append(f'\n![feature 수 vs F1m]({fig_path("fig2_features_f1")})\n')

fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
s = sw_f[(sw_f.train_subset == 'all') & (sw_f.test_subset == 'all')].sort_values('top_k')
line(axes[0], s.top_k, s.model_mb, C[0])
style(axes[0], 'feature 수', '모델 크기 (MB)')
axes[0].set_ylim(0, 130)
line(axes[1], s.top_k, s.infer_us_per_sample, C[0])
style(axes[1], 'feature 수', '추론 시간 (µs / 샘플)')
axes[1].set_ylim(0, 18)
for ax in axes:
    ax.set_xticks([5, 10, 15, 20, 38])
axes[0].set_title('전체 학습 모델: feature 수 vs 모델 크기 · 추론 시간', loc='left', color=INK)
fig.tight_layout()
fig.savefig(FIGS / 'fig2_features_cost.png', dpi=150)
plt.close(fig)
md.append(f'![feature 수 vs 모델 크기·추론 시간]({fig_path("fig2_features_cost")})\n')
md.append('추론 µs 절대값은 실행 시점 PC 부하에 따라 같은 설정이 5~15 µs로 흔들린다(LOG 9/27). 같은 표 안의 상대 비교만 의미가 있다.\n')

# ---------------------------------------------------------------- 3. trees
section('3. 2단계 트리 수 (sweep_trees.csv, 24행)')
md.append('깊이 ∞, leaf 1, 전체 학습. feature 15/38 × 트리 4종 = 8개 모델.\n')
sw_t['학습'] = sw_t.train_subset.map(SUB_KO)
sw_t['테스트'] = sw_t.test_subset.map(SUB_KO)
sw_t = sw_t.sort_values(['top_k', 'n_estimators', 'test_subset'],
                        key=lambda s: s.map({'all': 0, 'camera': 1, 'audio': 2}) if s.name == 'test_subset' else s)
md.append(md_table(sw_t, SWEEP_COLS, SWEEP_FMT))

fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
for i, k in enumerate([38, 15]):
    s = sw_t[(sw_t.top_k == k) & (sw_t.test_subset == 'all')].sort_values('n_estimators')
    line(axes[0], s.n_estimators, s.f1_macro, C[i], f'feature {k}')
    line(axes[1], s.n_estimators, s.model_mb, C[i], f'feature {k}')
    line(axes[2], s.n_estimators, s.infer_us_per_sample, C[i], f'feature {k}')
style(axes[0], '트리 수', 'F1 (macro)')
axes[0].set_ylim(0.950, 0.965)
style(axes[1], '트리 수', '모델 크기 (MB)')
axes[1].set_ylim(0, 110)
style(axes[2], '트리 수', '추론 시간 (µs / 샘플)')
axes[2].set_ylim(0, 17)
for ax in axes:
    ax.set_xticks([10, 20, 50, 100])
    legend(ax, loc='best')
axes[0].set_title('전체 테스트 기준. 크기·시간은 트리 수에 비례', loc='left', color=INK)
fig.tight_layout()
fig.savefig(FIGS / 'fig3_trees.png', dpi=150)
plt.close(fig)
md.append(f'\n![트리 수 sweep]({fig_path("fig3_trees")})\n')

# ---------------------------------------------------------------- 4. depth
section('4. 3단계 깊이 · min_samples_leaf (sweep_depth.csv, 72행)')
md.append('트리 20, 전체 학습. feature 15/38 × 깊이 4종 × leaf 3종 = 24개 모델.\n')
sw_d['학습'] = sw_d.train_subset.map(SUB_KO)
sw_d['테스트'] = sw_d.test_subset.map(SUB_KO)
sw_d['dorder'] = sw_d.depth.replace({0: 99})
sw_d = sw_d.sort_values(['top_k', 'dorder', 'min_leaf', 'test_subset'],
                        key=lambda s: s.map({'all': 0, 'camera': 1, 'audio': 2}) if s.name == 'test_subset' else s)
md.append(md_table(sw_d, SWEEP_COLS, SWEEP_FMT))

fig, axes = plt.subplots(2, 2, figsize=(11, 8))
xt = [8, 12, 16, 20]
for col_i, k in enumerate([38, 15]):
    for row_i, (ycol, ylab, ylim) in enumerate([('f1_macro', 'F1 (macro)', (0.925, 0.965)), ('model_mb', '모델 크기 (MB)', (0, 28))]):
        ax = axes[row_i][col_i]
        for j, leaf in enumerate([1, 10, 100]):
            s = sw_d[(sw_d.top_k == k) & (sw_d.min_leaf == leaf) & (sw_d.test_subset == 'all')].copy()
            s['x'] = s.depth.replace({0: 20})
            s = s.sort_values('x')
            line(ax, s.x, s[ycol], C[j], f'min_leaf {leaf}')
        ax.set_xticks(xt, ['8', '12', '16', '∞'])
        style(ax, 'max_depth', ylab)
        ax.set_ylim(*ylim)
        ax.set_title(f'feature {k}', loc='left', color=INK)
        legend(ax, loc='lower right' if ycol == 'f1_macro' else 'upper left')
fig.suptitle('깊이·min_leaf sweep (트리 20, 전체 테스트)', x=0.03, ha='left', color=INK)
fig.tight_layout(rect=[0, 0, 1, 0.97])
fig.savefig(FIGS / 'fig4_depth.png', dpi=150)
plt.close(fig)
md.append(f'\n![깊이·min_leaf sweep]({fig_path("fig4_depth")})\n')

# ---------------------------------------------------------------- 5. tradeoff (all 47 configs)
section('5. sweep 전체 trade-off (47개 설정, 전체 학습·전체 테스트)')
allcfg = []
for name, d in [('features', sw_f), ('trees', sw_t), ('depth', sw_d)]:
    s = d[(d.train_subset == 'all') & (d.test_subset == 'all')].copy()
    s['sweep'] = name
    allcfg.append(s)
allcfg = pd.concat(allcfg, ignore_index=True)
allcfg['설정'] = allcfg.apply(lambda r: f'k{r.top_k} t{r.n_estimators} d{depth_str(r.depth)} l{r.min_leaf}', axis=1)
md.append('1~3단계의 전체-학습 모델을 한 그림에 모은 것. 같은 설정(k38 t20 d∞ l1, k15 t20 d∞ l1, k38 t100, k15 t100)이 '
          '두 단계에 중복으로 들어 있어 점은 47개보다 적어 보일 수 있다.\n')
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
names = {'features': '1단계 feature', 'trees': '2단계 트리', 'depth': '3단계 깊이·leaf'}
for ax, xcol, xlab in [(axes[0], 'model_mb', '모델 크기 (MB)'), (axes[1], 'infer_us_per_sample', '추론 시간 (µs / 샘플)')]:
    for i, sw in enumerate(['features', 'trees', 'depth']):
        s = allcfg[allcfg.sweep == sw]
        ax.scatter(s[xcol], s.f1_macro, s=55, color=C[i], edgecolor=SURFACE, linewidth=1.5, label=names[sw], zorder=3)
    base = allcfg[(allcfg.top_k == 38) & (allcfg.n_estimators == 100) & (allcfg.sweep == 'features')].iloc[0]
    ax.annotate('기준 k38 t100', (base[xcol], base.f1_macro), xytext=(6, -12), textcoords='offset points',
                color=INK2, fontsize=9)
    for lab, cond, off in [('k38 t20', (allcfg.top_k == 38) & (allcfg.n_estimators == 20) & (allcfg.depth == 0) & (allcfg.min_leaf == 1), (8, 4)),
                           ('k38 t10', (allcfg.top_k == 38) & (allcfg.n_estimators == 10), (6, -13)),
                           ('k38 t20 d16', (allcfg.top_k == 38) & (allcfg.depth == 16) & (allcfg.min_leaf == 1), (6, 4)),
                           ('k38 t20 d8', (allcfg.top_k == 38) & (allcfg.depth == 8) & (allcfg.min_leaf == 1), (6, 4)),
                           ('k5 t100', (allcfg.top_k == 5), (6, 4))]:
        p = allcfg[cond].iloc[0]
        ax.annotate(lab, (p[xcol], p.f1_macro), xytext=off, textcoords='offset points', color=INK2, fontsize=9)
    style(ax, xlab, 'F1 (macro)')
    ax.grid(True, axis='x', color=GRID, linewidth=0.8)
    legend(ax, loc='center right')
axes[0].set_title('F1(macro) vs 모델 크기', loc='left', color=INK)
axes[1].set_title('F1(macro) vs 추론 시간', loc='left', color=INK)
fig.tight_layout()
fig.savefig(FIGS / 'fig5_tradeoff.png', dpi=150)
plt.close(fig)
md.append(f'![trade-off]({fig_path("fig5_tradeoff")})\n')

# ---------------------------------------------------------------- 6. final candidates
section('6. 4단계 최종 후보 재검증 (final_candidates.csv, 75행)')
md.append('후보 5개를 time split(5 subset) + LOAO-SYN(5 subset) + LOAO-SlowLoris(5 subset)로 재학습·평가. '
          '같은 실행 묶음에서 측정했으므로 추론 µs는 이 표 안에서만 비교.\n')
cand_name = {'base': 'baseline', 'c1': 'C1', 'c2': 'C2', 'c3': 'C3', 'c4': 'C4'}
eval_name = {'time': 'time split', 'LOAO-SYN': 'LOAO SYN', 'LOAO-SlowLoris': 'LOAO SlowLoris'}
fin['후보'] = fin.cand.map(cand_name)
fin['평가'] = fin['eval'].map(eval_name)
fin['테스트'] = fin.test_subset.map(SUB_KO)
fin['eo'] = fin['eval'].map({'time': 0, 'LOAO-SYN': 1, 'LOAO-SlowLoris': 2})
fin['so'] = fin.test_subset.map({'all': 0, 'camera': 1, 'audio': 2, 'echo_dot1': 3, 'amcrest': 4})
fin = fin.sort_values(['cand', 'eo', 'so'])
md.append(md_table(fin, [('후보', '후보'), ('평가', '평가'), ('테스트', '테스트'), ('top_k', 'feature'), ('n_estimators', '트리'),
                         ('depth', '깊이'), ('n', '테스트 행'), ('accuracy', 'Acc'), ('precision', 'Prec'),
                         ('recall', 'Recall'), ('f1', 'F1'), ('f1_macro', 'F1m'), ('infer_us_per_sample', '추론 µs'),
                         ('infer_samples_per_sec', 'samples/s'), ('model_mb', '모델 MB'), ('total_nodes', '노드'),
                         ('train_sec', '학습 s')],
                   {'depth': depth_str, 'n': INT, 'total_nodes': INT, 'infer_us_per_sample': F1D, 'model_mb': F1D,
                    'infer_samples_per_sec': K, 'train_sec': F1D}))

cands = ['base', 'c1', 'c2', 'c3', 'c4']
xlabels = ['baseline\nk38 t100', 'C1\nk38 t20', 'C2\nk38 t10', 'C3\nk15 t20', 'C4\nk38 t20 d16']
panels = [('time', 'all', 'f1_macro', 'time split · 전체 F1m', (0.95, 0.965)),
          ('time', 'camera', 'f1_macro', 'time split · 카메라 F1m', (0.945, 0.96)),
          ('time', 'audio', 'f1_macro', 'time split · 오디오 F1m', (0.94, 0.955)),
          ('LOAO-SYN', 'all', 'f1_macro', 'LOAO SYN · 전체 F1m', (0.99, 1.0)),
          ('LOAO-SlowLoris', 'all', 'f1_macro', 'LOAO SlowLoris · 전체 F1m', (0.72, 0.80)),
          ('LOAO-SlowLoris', 'all', 'recall', 'LOAO SlowLoris · 전체 Recall', (0.44, 0.56))]
fig, axes = plt.subplots(2, 3, figsize=(13, 7.5))
for ax, (ev, ts, m, title, ylim) in zip(axes.ravel(), panels):
    s = fin[(fin['eval'] == ev) & (fin.test_subset == ts)].set_index('cand').loc[cands]
    x = np.arange(5)
    ax.vlines(x, ylim[0], s[m], color=GRID, linewidth=1.5, zorder=2)
    ax.scatter(x, s[m], s=80, color=C[0], edgecolor=SURFACE, linewidth=2, zorder=3)
    for xi, v in zip(x, s[m]):
        ax.text(xi, v + (ylim[1] - ylim[0]) * 0.05, f'{v:.4f}', ha='center', color=INK2, fontsize=8.5)
    ax.set_xticks(x, xlabels, fontsize=8.5)
    ax.set_ylim(*ylim)
    style(ax)
    ax.set_title(title, loc='left', color=INK, fontsize=10)
fig.suptitle('최종 후보 5개 · 정확도 지표 (y축은 구간 확대)', x=0.01, ha='left', color=INK)
fig.tight_layout()
fig.savefig(FIGS / 'fig6_final_scores.png', dpi=150)
plt.close(fig)
md.append(f'\n![최종 후보 정확도]({fig_path("fig6_final_scores")})\n')

fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
s = fin[(fin['eval'] == 'time') & (fin.test_subset == 'all')].set_index('cand').loc[cands]
for ax, m, ylab, f in zip(axes, ['model_mb', 'infer_us_per_sample', 'total_nodes'],
                          ['모델 크기 (MB)', '추론 시간 (µs / 샘플)', '트리 노드 수 (천 개)'],
                          [lambda v: f'{v:.1f}', lambda v: f'{v:.1f}', lambda v: f'{v / 1000:.0f}k']):
    vals = s[m] / (1000 if m == 'total_nodes' else 1)
    ax.bar(np.arange(5), vals, width=0.55, color=C[0])
    for xi, v in enumerate(vals):
        ax.text(xi, v + vals.max() * 0.02, f(s[m].iloc[xi]), ha='center', color=INK2, fontsize=9)
    ax.set_xticks(np.arange(5), xlabels, fontsize=8.5)
    ax.set_ylim(0, vals.max() * 1.15)
    style(ax, '', ylab)
axes[0].set_title('최종 후보 5개 · 비용 (time split 모델)', loc='left', color=INK)
fig.tight_layout()
fig.savefig(FIGS / 'fig6_final_cost.png', dpi=150)
plt.close(fig)
md.append(f'![최종 후보 비용]({fig_path("fig6_final_cost")})\n')

# ---------------------------------------------------------------- 7. preliminary / legacy
section('7. 사전 점검 및 Colab 1차 (참고용)')
t3 = comp[comp.tag == 'test3'].copy()
t3['테스트'] = t3.test_subset.map(SUB_KO)
md.append('**`rf_test3.csv`** — 파이프라인 점검용. 소규모 데이터셋(`dataset_test3.parquet`, 파일 3개)으로 학습 50만 행. '
          '본 실험과 데이터가 달라 비교 대상이 아님.\n')
md.append(md_table(t3, [('테스트', '테스트'), ('n', '테스트 행'), ('accuracy', 'Acc'), ('recall', 'Recall'), ('f1', 'F1'),
                        ('f1_macro', 'F1m'), ('infer_us_per_sample', '추론 µs'), ('model_mb', '모델 MB')],
                   {'n': INT, 'infer_us_per_sample': F1D, 'model_mb': F1D}))
lg = pd.read_csv(ROOT / 'data/legacy/rf_full_vs_camera_result.csv', encoding='utf-8-sig')
md.append('\n**Colab 1차 (`data/legacy/rf_full_vs_camera_result.csv`)** — 자체 numpy feature, Benign 파일 1개, '
          '파일당 앞 200만 패킷만 사용. 공식 feature로 바꾸기 전 결과라 본 실험과 직접 비교 불가.\n')
md.append(md_table(lg, [(c, c) for c in lg.columns], {'학습 window 수': INT, '테스트 window 수': INT}))

# ---------------------------------------------------------------- write
OUT.write_text('\n'.join(md) + '\n', encoding='utf-8')
print(f'wrote {OUT} and {len(list(FIGS.glob("*.png")))} figures in {FIGS}')
