# -*- coding: utf-8 -*-
"""Comprehensive check of safety=320 test:
  1. Voiced region duration & onset shift
  2. Clamp frequency (pullback hitting chunk index 0)
  3. Bleed: head-20ms peak anomaly
  4. Adjacent-WAV overlap (sample-level cross-correlation at boundary)
  5. Overall distribution vs V1 and S80
"""
import soundfile as sf
import numpy as np
import os
import statistics

DIRS = {
    'V1':   r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_refactored_run\wavs',
    'S80':  r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_alpha_safety80\wavs',
    'S320': r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_alpha_safety320\wavs',
}


def load_voiced(p):
    y, sr = sf.read(p)
    if y.ndim > 1:
        y = y[:, 0]
    lead = int(sr * 0.400)
    tail = int(sr * 0.730)
    v = y[lead:len(y) - tail]
    return v, sr, y


def probe(p):
    v, sr, y = load_voiced(p)
    dur_ms = int(len(v) * 1000 / sr)
    win = int(sr * 0.001)
    nw = len(v) // win
    rms = np.array([np.sqrt(np.mean(v[i*win:(i+1)*win]**2) + 1e-12)
                    for i in range(nw)])
    db = 20 * np.log10(rms + 1e-12)
    above = np.where(db > -40)[0]
    onset_ms = int(above[0]) if len(above) else -1
    head20 = v[:int(sr * 0.020)]
    head_peak = float(np.max(np.abs(head20))) if len(head20) else 0.0
    return {
        'dur_ms': dur_ms,
        'onset_ms': onset_ms,
        'head20_peak': head_peak,
        'voiced': v,
        'sr': sr,
    }


def cross_corr_tail_head(tail_samples, head_samples, max_lag_ms=300, sr=48000):
    """Find peak normalized cross-correlation between tail of segment N
    and head of segment N+1. High peak indicates audio overlap (bleed)."""
    n = min(int(sr * max_lag_ms / 1000), len(tail_samples), len(head_samples))
    if n < 1000:
        return 0.0
    t = tail_samples[-n:].astype(np.float64)
    h = head_samples[:n].astype(np.float64)
    if np.std(t) < 1e-6 or np.std(h) < 1e-6:
        return 0.0
    # normalized cross-correlation, return peak value
    t = (t - t.mean()) / (t.std() * len(t))
    h = (h - h.mean()) / h.std()
    corr = np.correlate(h, t, mode='valid')
    return float(np.max(np.abs(corr)))


def main():
    print('=== Per-line 3-way comparison (L0301-0320) ===')
    print(f'{"Line":>4} | {"V1_dur":>7} {"S80_dur":>8} {"S320_dur":>9} | '
          f'{"V1_on":>6} {"S80_on":>7} {"S320_on":>8} | '
          f'{"V1_p20":>7} {"S80_p20":>8} {"S320_p20":>9}')
    print('-' * 110)

    rows = []
    for ln in range(301, 321):
        fn = f'Script_1_{ln:04d}.wav'
        paths = {k: os.path.join(v, fn) for k, v in DIRS.items()}
        if not all(os.path.exists(p) for p in paths.values()):
            continue
        m = {k: probe(p) for k, p in paths.items()}
        rows.append((ln, m))
        print(f'{ln:>4} | '
              f'{m["V1"]["dur_ms"]:>5}ms {m["S80"]["dur_ms"]:>6}ms {m["S320"]["dur_ms"]:>7}ms | '
              f'{m["V1"]["onset_ms"]:>4}ms {m["S80"]["onset_ms"]:>5}ms {m["S320"]["onset_ms"]:>6}ms | '
              f'{m["V1"]["head20_peak"]:>7.3f} {m["S80"]["head20_peak"]:>8.3f} {m["S320"]["head20_peak"]:>9.3f}')

    print('-' * 110)

    # --- Aggregate ---
    if not rows:
        print('No matching lines found.')
        return

    s80_dur_delta = [m['S80']['dur_ms'] - m['V1']['dur_ms'] for _, m in rows]
    s320_dur_delta = [m['S320']['dur_ms'] - m['V1']['dur_ms'] for _, m in rows]
    s320_vs_s80_delta = [m['S320']['dur_ms'] - m['S80']['dur_ms'] for _, m in rows]
    s320_onset_delta = [m['S320']['onset_ms'] - m['V1']['onset_ms'] for _, m in rows]
    s320_head = [m['S320']['head20_peak'] for _, m in rows]
    v1_head = [m['V1']['head20_peak'] for _, m in rows]

    print(f'\nN = {len(rows)} lines')
    print(f'{"":<30} {"S80 vs V1":>12} {"S320 vs V1":>13} {"S320 vs S80":>14}')
    print(f'{"dur delta mean (ms)":<30} {statistics.mean(s80_dur_delta):>+12.1f} '
          f'{statistics.mean(s320_dur_delta):>+13.1f} '
          f'{statistics.mean(s320_vs_s80_delta):>+14.1f}')
    print(f'{"dur delta max (ms)":<30} {max(s80_dur_delta):>+12d} '
          f'{max(s320_dur_delta):>+13d} {max(s320_vs_s80_delta):>+14d}')
    print(f'{"dur delta min (ms)":<30} {min(s80_dur_delta):>+12d} '
          f'{min(s320_dur_delta):>+13d} {min(s320_vs_s80_delta):>+14d}')

    print(f'\nS320 onset shift vs V1: mean={statistics.mean(s320_onset_delta):+.1f}ms '
          f'median={statistics.median(s320_onset_delta):+.1f}ms '
          f'min={min(s320_onset_delta):+d}ms max={max(s320_onset_delta):+d}ms')

    # --- Bleed heuristic ---
    print(f'\n=== Bleed / head20 anomaly check ===')
    print(f'V1  head20 peak mean = {statistics.mean(v1_head):.3f}, max = {max(v1_head):.3f}')
    print(f'S320 head20 peak mean = {statistics.mean(s320_head):.3f}, max = {max(s320_head):.3f}')
    # Lines where S320 has head20 > 0.3 (real amplitude near start)
    suspicious = []
    for ln, m in rows:
        if m['S320']['head20_peak'] > 0.2:
            suspicious.append((ln, m['V1']['head20_peak'], m['S320']['head20_peak']))
    if suspicious:
        print('Lines with S320 head20 > 0.2 (potential bleed or close-pack):')
        for ln, v1p, s320p in suspicious:
            ratio = s320p / max(v1p, 0.001)
            print(f'  L{ln}: V1={v1p:.3f}, S320={s320p:.3f}, ratio={ratio:.2f}x')

    # --- Adjacent WAV overlap check (cross-corr) ---
    print(f'\n=== Adjacent WAV overlap (cross-corr at boundary, S320) ===')
    print('(Peak value > 0.5 is strong overlap signal)')
    for i in range(len(rows) - 1):
        ln_a, m_a = rows[i]
        ln_b, m_b = rows[i + 1]
        if ln_b != ln_a + 1:
            continue
        tail_a = m_a['S320']['voiced'][-int(m_a['S320']['sr'] * 0.2):]
        head_b = m_b['S320']['voiced'][:int(m_b['S320']['sr'] * 0.3)]
        corr = cross_corr_tail_head(tail_a, head_b, max_lag_ms=200,
                                     sr=m_a['S320']['sr'])
        flag = ' <-- OVERLAP' if corr > 0.5 else ''
        print(f'  L{ln_a}→L{ln_b}: peak corr = {corr:.3f}{flag}')


if __name__ == '__main__':
    main()
