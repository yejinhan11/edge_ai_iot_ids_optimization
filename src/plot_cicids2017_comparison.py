"""Publication artifacts for the RF comparison; sample units stay in separate panels."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_cache = ROOT / 'data/tmp/matplotlib'
_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(_cache))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = ROOT / 'results/cicids2017_comparison'


def main():
    figures = OUT / 'figures'
    figures.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size': 10, 'axes.grid': True, 'grid.alpha': .25})
    fig, axes = plt.subplots(3, 2, figsize=(13, 12))
    for col, arm in enumerate(['legacy_windows', 'native_flows']):
        data = pd.read_csv(OUT / arm / 'validation_search.csv')
        protocol = json.loads((OUT / arm / 'protocol.json').read_text())
        ranking = json.loads((OUT / arm / 'ranking.json').read_text())
        rank = ranking['mdi_order']
        p = len(protocol['features'])
        standard = data[(data.trees == 100) & (data.depth == 0) & (data.min_leaf == 1) & (data.weight == 'balanced')].copy()
        orders = [('Training MDI', rank)]
        if ranking['permutation_order'] is not None:
            orders.append(('Validation permutation', ranking['permutation_order']))
        for label, order in orders:
            curve = standard[[json.loads(row['columns']) == list(range(p)) or
                              json.loads(row['columns']) == order[:int(row.n_features)]
                              for _, row in standard.iterrows()]].sort_values('n_features')
            axes[0, col].plot(curve.n_features, curve.f1_macro, 'o-', label=label)
        axes[0, col].legend(fontsize=8)
        axes[0, col].set(xlabel='Feature count (ranked subsets)', ylabel='Validation macro F1',
                         title=f'{arm}: fit cap {protocol["screen_cap"]:,}')
        trees = data[(data.n_features == p) & (data.depth == 0) & (data.min_leaf == 1) & (data.weight == 'balanced')].sort_values('trees')
        axes[1, col].plot(trees.trees, trees.f1_macro, 'o-')
        axes[1, col].set(xlabel='Tree count (all active features)', ylabel='Validation macro F1')
        depths = data[(data.n_features == p) & (data.trees == (20 if col == 0 else 50)) & (data.min_leaf == 1) & (data.weight == 'balanced')].copy()
        depths['display_depth'] = depths.depth.replace(0, 999)
        depths = depths.sort_values('display_depth')
        axes[2, col].plot(np.arange(len(depths)), depths.f1_macro, 'o-')
        axes[2, col].set_xticks(np.arange(len(depths)), ['unlimited' if int(d) == 0 else str(int(d)) for d in depths.depth])
        axes[2, col].set(xlabel='Maximum depth', ylabel='Validation macro F1')
    fig.suptitle('Validation sweeps: each panel uses its own sample unit and split', fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, .97))
    fig.savefig(figures / 'validation_sweeps.png', dpi=180)
    plt.close(fig)
    final = pd.read_csv(OUT / 'comparison.csv')
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, arm in zip(axes, ['legacy_windows', 'native_flows']):
        data = final[final.arm == arm].groupby('candidate', sort=False).agg(
            f1=('f1_macro', 'mean'), cost=('infer_us_per_sample', 'mean'), size=('model_mb', 'mean'))
        for name, r in data.iterrows():
            ax.scatter(r.cost, r.f1, s=65)
            offset = (-6, 14) if name == 'baseline' else (6, -14) if name == 'validation_selected' else (6, 7)
            ax.annotate(f'{name} ({r["size"]:.2f} MB)', (r.cost, r.f1), xytext=offset,
                        ha='right' if name == 'baseline' else 'left',
                        va='top' if name == 'validation_selected' else 'bottom',
                        textcoords='offset points', fontsize=8)
        ax.set_xlim(0, data.cost.max() * 1.35)
        ax.margins(y=.18)
        ax.set(title=arm, xlabel='Single-thread RF prediction (microseconds / sample)', ylabel='Test macro F1')
    fig.suptitle('Finalists only; different sample units are not a controlled cross-panel ablation')
    fig.tight_layout(rect=(0, 0, 1, .95))
    fig.savefig(figures / 'final_tradeoff.png', dpi=180)
    plt.close(fig)
    report = OUT / 'REPORT.md'
    text = report.read_text(encoding='utf-8')
    if 'figures/validation_sweeps.png' not in text:
        text += ('\n## 비교 그림\n\n![검증 구간의 변수별 비교](figures/validation_sweeps.png)\n\n'
                 '![최종 후보의 RF 추론 비용과 macro F1](figures/final_tradeoff.png)\n\n'
                 '추론 시간은 RF.predict만 측정했다. 패킷 수집, 특징 추출, flow 종료 대기 비용은 포함하지 않는다. '
                 '따라서 flow 모델의 RF 추론이 빠르다고 전체 온라인 탐지 지연도 짧다는 뜻은 아니다.\n')
        report.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
