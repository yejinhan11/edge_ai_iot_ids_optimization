"""Report figures for the lightweighting sweeps (F1 vs inference cost, F1 vs model size).

Reads results/tables/sweep_*.csv (test_subset == all by default) and writes
results/figures/sweep_tradeoff.png plus per-sweep line charts.

Usage:  python src/plot_sweeps.py [--test-subset all|camera|audio]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLES, FIGS = ROOT / 'results/tables', ROOT / 'results/figures'
# categorical palette (validated, see dataviz reference): blue, orange, aqua, yellow
SERIES = {'features': '#2a78d6', 'trees': '#eb6834', 'depth': '#1baf7a', 'baseline': '#eda100'}
INK, INK2, GRID = '#1a1a19', '#5d5c55', '#e3e2dc'


def load(test_subset):
    frames = []
    for f in sorted(TABLES.glob('sweep_*.csv')):
        d = pd.read_csv(f)
        d['sweep'] = f.stem.replace('sweep_', '')
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d = d[(d.test_subset == test_subset) & (d.train_subset == 'all')].copy()
    d['max_depth'] = d['max_depth'].fillna(0).astype(int)
    d['min_leaf'] = d.get('min_leaf', 1)
    d['label'] = d.apply(lambda r: f"k{r.top_k} t{r.n_estimators}" + (f" d{r.max_depth}" if r.max_depth else '')
                         + (f" l{r.min_leaf}" if r.min_leaf > 1 else ''), axis=1)
    return d


def style(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel, color=INK2)
    ax.set_ylabel(ylabel, color=INK2)
    ax.grid(True, color=GRID, linewidth=0.8)
    for s in ['top', 'right']:
        ax.spines[s].set_visible(False)
    for s in ['left', 'bottom']:
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2)


def tradeoff(d, test_subset):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, xcol, xlabel in [(axes[0], 'infer_us_per_sample', 'inference time (µs / sample, single thread)'),
                             (axes[1], 'model_mb', 'model size (MB)')]:
        for sweep, color in SERIES.items():
            s = d[d.sweep == sweep]
            if s.empty:
                continue
            ax.scatter(s[xcol], s.f1_macro, s=42, color=color, edgecolor='white', linewidth=1.5, label=sweep, zorder=3)
        # direct labels for the Pareto-front points (best F1 for a given cost or better)
        front = d.sort_values(xcol)
        best = -1
        for _, r in front.iterrows():
            if r.f1_macro > best:
                best = r.f1_macro
                ax.annotate(r.label, (r[xcol], r.f1_macro), xytext=(5, 4), textcoords='offset points',
                            fontsize=8, color=INK)
        ax.set_xscale('log')
        style(ax, xlabel, 'F1 (macro)')
        ax.legend(frameon=False, fontsize=9, labelcolor=INK2)
    fig.suptitle(f'RF lightweighting trade-off (test subset: {test_subset})', color=INK)
    fig.tight_layout()
    fig.savefig(FIGS / f'sweep_tradeoff_{test_subset}.png', dpi=160)
    plt.close(fig)


def lines(d, test_subset):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    f = d[d.sweep == 'features'].sort_values('top_k')
    axes[0].plot(f.top_k, f.f1_macro, marker='o', color=SERIES['features'], linewidth=2)
    style(axes[0], 'number of features (top-k by importance)', 'F1 (macro)')
    t = d[d.sweep == 'trees']
    for k, g in t.groupby('top_k'):
        g = g.sort_values('n_estimators')
        axes[1].plot(g.n_estimators, g.f1_macro, marker='o', linewidth=2, label=f'{k} features',
                     color=SERIES['trees'] if k == 38 else SERIES['features'])
    style(axes[1], 'number of trees', 'F1 (macro)')
    axes[1].legend(frameon=False, fontsize=9)
    t2 = d[d.sweep == 'trees']
    for k, g in t2.groupby('top_k'):
        g = g.sort_values('n_estimators')
        axes[2].plot(g.n_estimators, g.infer_us_per_sample, marker='o', linewidth=2, label=f'{k} features',
                     color=SERIES['trees'] if k == 38 else SERIES['features'])
    style(axes[2], 'number of trees', 'inference time (µs / sample)')
    axes[2].legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGS / f'sweep_lines_{test_subset}.png', dpi=160)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--test-subset', default='all', choices=['all', 'camera', 'audio'])
    a = ap.parse_args()
    FIGS.mkdir(parents=True, exist_ok=True)
    d = load(a.test_subset)
    tradeoff(d, a.test_subset)
    lines(d, a.test_subset)
    print('wrote', FIGS / f'sweep_tradeoff_{a.test_subset}.png', 'and', FIGS / f'sweep_lines_{a.test_subset}.png')


if __name__ == '__main__':
    main()
