# -*- coding: utf-8 -*-
"""
Visualize the 9 scoring dimensions (D1-D9) of selective_composer.py.

Reads logs/composition_results.csv and produces three diagnostic views:
  1. Per-dimension histogram grid, split by verdict (ACCEPT / REJECT)
  2. Inter-dimension correlation heatmap
  3. Radar chart of verdict-mean profiles

Outputs PNGs under docs/.
"""
import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE, 'logs', 'composition_results.csv')
OUT_DIR = os.path.join(BASE, 'docs')

DIMS = [
    ('S_unprompted',  'D1 Unprompted sim'),
    ('S_gap',         'D2 Prompt gap'),
    ('S_snr',         'D3 SNR'),
    ('S_duration',    'D4 Duration (AST)'),
    ('S_confidence',  'D6 Confidence'),
    ('S_boundary',    'D7 Boundary'),
    ('S_continuity',  'D8 Continuity'),
    ('S_decay',       'D9 Decay'),
    ('S_composite',   'Composite (geo-mean)'),
]

COLORS = {'ACCEPT': '#2ca02c', 'PENDING': '#ff7f0e', 'REJECT': '#d62728'}


def load():
    df = pd.read_csv(CSV_PATH, encoding='utf-8-sig')
    for col, _ in DIMS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def plot_histograms(df, out_path):
    fig, axes = plt.subplots(3, 3, figsize=(15, 11))
    verdicts = [v for v in ['ACCEPT', 'PENDING', 'REJECT'] if (df['verdict'] == v).any()]
    bins = np.linspace(0, 1, 41)
    for ax, (col, label) in zip(axes.flat, DIMS):
        if col not in df.columns:
            ax.set_visible(False)
            continue
        for v in verdicts:
            vals = df.loc[df['verdict'] == v, col].dropna().values
            if len(vals) == 0:
                continue
            ax.hist(vals, bins=bins, alpha=0.55, color=COLORS[v],
                    label=f'{v} (n={len(vals)})', density=True)
        ax.set_title(label, fontsize=11)
        ax.set_xlim(0, 1)
        ax.grid(alpha=0.2)
        ax.legend(fontsize=7, loc='upper left')
    fig.suptitle(f'Dimension distributions by verdict  —  n={len(df)}',
                 fontsize=14, y=0.995)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    print(f'  saved  {out_path}')


def plot_correlation(df, out_path):
    cols = [c for c, _ in DIMS if c in df.columns and c != 'S_composite']
    labels = [lbl.split()[0] for c, lbl in DIMS if c in df.columns and c != 'S_composite']
    mat = df[cols].corr(method='spearman').values

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(mat, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.set_yticklabels(labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            txt = f'{mat[i, j]:.2f}'
            color = 'white' if abs(mat[i, j]) > 0.5 else 'black'
            ax.text(j, i, txt, ha='center', va='center', fontsize=9, color=color)
    ax.set_title('Spearman correlation between dimensions', fontsize=12)
    fig.colorbar(im, ax=ax, shrink=0.85, label='ρ')
    fig.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    print(f'  saved  {out_path}')


def plot_radar(df, out_path):
    cols = [c for c, _ in DIMS if c in df.columns and c != 'S_composite']
    labels = [lbl.split()[0] for c, lbl in DIMS if c in df.columns and c != 'S_composite']
    n = len(cols)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig = plt.figure(figsize=(9, 8))
    ax = fig.add_subplot(111, polar=True)

    for verdict in ['ACCEPT', 'REJECT', 'PENDING']:
        sub = df[df['verdict'] == verdict]
        if len(sub) == 0:
            continue
        mean_vals = [sub[c].mean() for c in cols]
        p10_vals = [sub[c].quantile(0.10) for c in cols]
        mean_vals += mean_vals[:1]
        p10_vals += p10_vals[:1]
        ax.plot(angles, mean_vals, color=COLORS[verdict], linewidth=2,
                label=f'{verdict} mean (n={len(sub)})')
        ax.fill(angles, mean_vals, color=COLORS[verdict], alpha=0.10)
        ax.plot(angles, p10_vals, color=COLORS[verdict], linewidth=1,
                linestyle='--', alpha=0.7, label=f'{verdict} 10th pct')

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylim(0, 1)
    ax.set_rgrids([0.25, 0.5, 0.75, 1.0], fontsize=8)
    ax.set_title('Per-verdict dimension profile  (mean + 10th percentile)',
                 fontsize=12, pad=20)
    ax.legend(loc='lower right', bbox_to_anchor=(1.25, -0.05), fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    print(f'  saved  {out_path}')


def print_quick_stats(df):
    print('\nVerdict counts:')
    print(df['verdict'].value_counts().to_string())
    print('\nPer-dimension mean by verdict:')
    cols = [c for c, _ in DIMS if c in df.columns]
    stats = df.groupby('verdict')[cols].mean().round(3)
    print(stats.to_string())


def main():
    print(f'Reading {CSV_PATH}')
    df = load()
    print(f'  {len(df)} rows, columns: {list(df.columns)}')
    print_quick_stats(df)
    print('\nGenerating plots...')
    plot_histograms(df, os.path.join(OUT_DIR, 'dimension_histograms.png'))
    plot_correlation(df, os.path.join(OUT_DIR, 'dimension_correlation.png'))
    plot_radar(df, os.path.join(OUT_DIR, 'dimension_radar.png'))
    print('Done.')


if __name__ == '__main__':
    main()
