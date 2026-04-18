# -*- coding: utf-8 -*-
"""
Diagnose why D9 S_decay is low across the board.

Splits the D9 score into HEAD vs TAIL, reports gradient vs span separately,
and measures the actual R6 envelope of a sample of the current dataset.
"""
import os
import sys
import json
import random
import numpy as np
import soundfile as sf
import pandas as pd
import matplotlib.pyplot as plt

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'src'))

from selective_composer import (
    _score_edge,
    PREATTACK_TARGET_MS, TAIL_TARGET_MS,
    SPEECH_DETECT_DB,
)

WAV_DIR = os.path.join(BASE, 'datasets', 'wavs')
CSV_PATH = os.path.join(BASE, 'logs', 'composition_results.csv')
OUT_DIR = os.path.join(BASE, 'docs')

DECAY_SIGNAL_DB = -68
DECAY_WINDOW_MS = 5
DECAY_SCAN_MS = 730
DECAY_MIN_SPAN_MS = 10
DECAY_GOOD_SPAN_MS = 50
DECAY_NATURAL_GRAD = 4.0
DECAY_CLIFF_GRAD = 10.0


def analyze_file(wav_path):
    """Return dict with split head/tail diagnostics."""
    samples, sr = sf.read(wav_path, dtype='float64')
    if samples.ndim > 1:
        samples = samples[:, 0]

    total_ms = len(samples) / sr * 1000

    lead_n = int(sr * PREATTACK_TARGET_MS / 1000)
    tail_n = int(sr * TAIL_TARGET_MS / 1000)
    if lead_n + tail_n >= len(samples):
        return None
    voiced = samples[lead_n:len(samples) - tail_n]

    win = int(sr * DECAY_WINDOW_MS / 1000)
    nw = len(voiced) // win
    if nw < 10:
        return None
    trimmed = voiced[:nw * win].reshape(nw, win)
    rms = np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(np.maximum(rms, 1e-10))

    signal_idx = np.where(db >= DECAY_SIGNAL_DB)[0]
    body_idx = np.where(db >= SPEECH_DETECT_DB)[0]
    if len(signal_idx) < 5:
        return None

    first_signal = signal_idx[0]
    last_signal = signal_idx[-1]
    body_start = body_idx[0] if len(body_idx) > 0 else None
    body_end = body_idx[-1] if len(body_idx) > 0 else None

    scan_windows = int(DECAY_SCAN_MS / DECAY_WINDOW_MS)

    def edge_components(anchor, body_ref, direction):
        """Recompute _score_edge but also break out grad and span individually."""
        if direction == 'backward':
            region_start = max(0, anchor - scan_windows)
            region = db[region_start:anchor + 1]
        else:
            region_end = min(len(db), anchor + scan_windows + 1)
            region = db[anchor:region_end]
        if len(region) < 3:
            return dict(grad=None, grad_score=1.0, span_ms=None, span_score=1.0, total=1.0)
        gradient = np.diff(region) / DECAY_WINDOW_MS
        if direction == 'backward':
            neg = gradient[gradient < 0]
            steep = abs(np.min(neg)) if len(neg) else 0.0
        else:
            pos = gradient[gradient > 0]
            steep = np.max(pos) if len(pos) else 0.0
        if steep <= DECAY_NATURAL_GRAD:
            grad_score = 1.0
        elif steep >= DECAY_CLIFF_GRAD:
            grad_score = 0.0
        else:
            grad_score = 1.0 - (steep - DECAY_NATURAL_GRAD) / (DECAY_CLIFF_GRAD - DECAY_NATURAL_GRAD)
        if body_ref is not None:
            if direction == 'backward':
                span_ms = max(0, anchor - body_ref) * DECAY_WINDOW_MS
            else:
                span_ms = max(0, body_ref - anchor) * DECAY_WINDOW_MS
        else:
            span_ms = len(region) * DECAY_WINDOW_MS
        if span_ms >= DECAY_GOOD_SPAN_MS:
            span_score = 1.0
        elif span_ms <= DECAY_MIN_SPAN_MS:
            span_score = 0.0
        else:
            span_score = (span_ms - DECAY_MIN_SPAN_MS) / (DECAY_GOOD_SPAN_MS - DECAY_MIN_SPAN_MS)
        return dict(grad=float(steep), grad_score=float(grad_score),
                    span_ms=float(span_ms), span_score=float(span_score),
                    total=float(min(grad_score, span_score)))

    head = edge_components(first_signal, body_ref=None, direction='forward')
    tail = edge_components(last_signal, body_ref=body_end, direction='backward')

    return dict(
        path=wav_path,
        total_ms=total_ms,
        lead_strip_ms=lead_n / sr * 1000,
        tail_strip_ms=tail_n / sr * 1000,
        voiced_ms=len(voiced) / sr * 1000,
        first_signal_ms=first_signal * DECAY_WINDOW_MS,
        last_signal_ms=last_signal * DECAY_WINDOW_MS,
        body_start_ms=body_start * DECAY_WINDOW_MS if body_start is not None else None,
        body_end_ms=body_end * DECAY_WINDOW_MS if body_end is not None else None,
        head=head, tail=tail,
        final_score=min(head['total'], tail['total']),
    )


def measure_actual_envelope(wav_path):
    """How much leading/trailing silence actually exists in this file?
    Useful to check if the file was made with different envelope params."""
    samples, sr = sf.read(wav_path, dtype='float64')
    if samples.ndim > 1:
        samples = samples[:, 0]
    win = int(sr * 0.005)
    nw = len(samples) // win
    if nw < 10:
        return None, None
    trimmed = samples[:nw * win].reshape(nw, win)
    rms = np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(np.maximum(rms, 1e-10))
    sig = np.where(db >= DECAY_SIGNAL_DB)[0]
    if len(sig) == 0:
        return None, None
    lead_ms = sig[0] * 5
    tail_ms = (nw - 1 - sig[-1]) * 5
    return lead_ms, tail_ms


def main():
    df = pd.read_csv(CSV_PATH, encoding='utf-8-sig')
    df['S_decay'] = pd.to_numeric(df['S_decay'], errors='coerce')

    print('=== D9 S_decay distribution ===')
    s = df['S_decay'].dropna()
    pcts = [0, 5, 25, 50, 75, 95, 100]
    for p in pcts:
        print(f'  p{p:>3}: {np.percentile(s, p):.3f}')
    print(f'  mean: {s.mean():.3f}   std: {s.std():.3f}')
    print(f'  near 0 (<0.05): {(s < 0.05).sum()}   '
          f'mid (0.05-0.5): {((s >= 0.05) & (s < 0.5)).sum()}   '
          f'high (>=0.5): {(s >= 0.5).sum()}')

    print('\n=== Measuring actual R6 envelope on 30 random files ===')
    random.seed(42)
    sample_files = random.sample(df['filename'].tolist(), 30)
    leads, tails = [], []
    for fn in sample_files:
        p = os.path.join(WAV_DIR, fn)
        if not os.path.exists(p):
            continue
        l, t = measure_actual_envelope(p)
        if l is not None:
            leads.append(l); tails.append(t)
    print(f'  lead silence ms — mean={np.mean(leads):.0f}  '
          f'p5={np.percentile(leads,5):.0f}  p95={np.percentile(leads,95):.0f}  '
          f'min={min(leads):.0f}  max={max(leads):.0f}')
    print(f'  tail silence ms — mean={np.mean(tails):.0f}  '
          f'p5={np.percentile(tails,5):.0f}  p95={np.percentile(tails,95):.0f}  '
          f'min={min(tails):.0f}  max={max(tails):.0f}')
    print(f'  (D9 strips {PREATTACK_TARGET_MS}ms lead, {TAIL_TARGET_MS}ms tail — should match)')

    print('\n=== Splitting HEAD vs TAIL on 200-file sample ===')
    random.seed(1)
    sample_files = random.sample(df['filename'].tolist(), 200)
    head_totals, tail_totals = [], []
    head_grads, tail_grads = [], []
    head_grad_scores, tail_grad_scores = [], []
    tail_spans, tail_span_scores = [], []

    for fn in sample_files:
        p = os.path.join(WAV_DIR, fn)
        if not os.path.exists(p):
            continue
        r = analyze_file(p)
        if r is None:
            continue
        head_totals.append(r['head']['total'])
        tail_totals.append(r['tail']['total'])
        head_grads.append(r['head']['grad'])
        tail_grads.append(r['tail']['grad'])
        head_grad_scores.append(r['head']['grad_score'])
        tail_grad_scores.append(r['tail']['grad_score'])
        tail_spans.append(r['tail']['span_ms'])
        tail_span_scores.append(r['tail']['span_score'])

    def summary(name, arr):
        a = np.array([x for x in arr if x is not None])
        print(f'  {name:<22} mean={a.mean():.3f}  '
              f'p5={np.percentile(a,5):.3f}  p50={np.percentile(a,50):.3f}  '
              f'p95={np.percentile(a,95):.3f}')
    summary('head_total',      head_totals)
    summary('tail_total',      tail_totals)
    summary('head_grad (dB/ms)', head_grads)
    summary('tail_grad (dB/ms)', tail_grads)
    summary('head_grad_score', head_grad_scores)
    summary('tail_grad_score', tail_grad_scores)
    summary('tail_span_ms',    tail_spans)
    summary('tail_span_score', tail_span_scores)

    bottleneck = ['HEAD' if h < t else 'TAIL' for h, t in zip(head_totals, tail_totals)]
    print(f'  bottleneck: HEAD={bottleneck.count("HEAD")}  TAIL={bottleneck.count("TAIL")}')

    # Plot components
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    axes[0, 0].hist(head_totals, bins=30, color='#1f77b4', alpha=0.7); axes[0, 0].set_title('HEAD total')
    axes[0, 1].hist(head_grads, bins=30, color='#1f77b4', alpha=0.7); axes[0, 1].set_title('HEAD gradient (dB/ms)')
    axes[0, 1].axvline(DECAY_NATURAL_GRAD, color='g', linestyle='--', label='natural(4)')
    axes[0, 1].axvline(DECAY_CLIFF_GRAD, color='r', linestyle='--', label='cliff(10)')
    axes[0, 1].legend()
    axes[0, 2].hist(head_grad_scores, bins=30, color='#1f77b4', alpha=0.7); axes[0, 2].set_title('HEAD grad_score')

    axes[1, 0].hist(tail_totals, bins=30, color='#d62728', alpha=0.7); axes[1, 0].set_title('TAIL total')
    axes[1, 1].hist(tail_grads, bins=30, color='#d62728', alpha=0.7); axes[1, 1].set_title('TAIL gradient (dB/ms)')
    axes[1, 1].axvline(DECAY_NATURAL_GRAD, color='g', linestyle='--')
    axes[1, 1].axvline(DECAY_CLIFF_GRAD, color='r', linestyle='--')
    axes[1, 2].hist(tail_spans, bins=30, color='#d62728', alpha=0.7); axes[1, 2].set_title('TAIL span_ms')
    axes[1, 2].axvline(DECAY_MIN_SPAN_MS, color='r', linestyle='--', label='min(10)')
    axes[1, 2].axvline(DECAY_GOOD_SPAN_MS, color='g', linestyle='--', label='good(50)')
    axes[1, 2].legend()
    for ax in axes.flat: ax.grid(alpha=0.2)
    fig.suptitle(f'D9 component breakdown  (n={len(head_totals)})', fontsize=13)
    fig.tight_layout()
    out = os.path.join(OUT_DIR, 'd9_diagnostic.png')
    fig.savefig(out, dpi=130, bbox_inches='tight')
    print(f'\n  saved {out}')

    print('\n=== Lowest-D9 and highest-D9 example files ===')
    df_sorted = df.dropna(subset=['S_decay']).sort_values('S_decay')
    print('\n  5 lowest:')
    for _, row in df_sorted.head(5).iterrows():
        r = analyze_file(os.path.join(WAV_DIR, row['filename']))
        if r:
            print(f"    {row['filename']}  S_decay={row['S_decay']:.3f}  "
                  f"HEAD total={r['head']['total']:.2f} (grad={r['head']['grad']:.1f})  "
                  f"TAIL total={r['tail']['total']:.2f} "
                  f"(grad={r['tail']['grad']:.1f}, span={r['tail']['span_ms']:.0f}ms)")
    print('\n  5 highest:')
    for _, row in df_sorted.tail(5).iterrows():
        r = analyze_file(os.path.join(WAV_DIR, row['filename']))
        if r:
            print(f"    {row['filename']}  S_decay={row['S_decay']:.3f}  "
                  f"HEAD total={r['head']['total']:.2f} (grad={r['head']['grad']:.1f})  "
                  f"TAIL total={r['tail']['total']:.2f} "
                  f"(grad={r['tail']['grad']:.1f}, span={r['tail']['span_ms']:.0f}ms)")


if __name__ == '__main__':
    main()
