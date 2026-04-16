# -*- coding: utf-8 -*-
"""Phase A measurement — tail preserve (700ms + 30ms fade) vs optionB (120 safety + 5ms fade)."""
import soundfile as sf
import numpy as np
import os
import statistics

OLD = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_optionB\wavs'
NEW = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_tail_preserve\wavs'


def load_voiced(p):
    y, sr = sf.read(p)
    if y.ndim > 1:
        y = y[:, 0]
    lead = int(sr * 0.400)
    tail = int(sr * 0.730)
    return y[lead:len(y) - tail], sr


def probe(p):
    v, sr = load_voiced(p)
    n = len(v)
    dur_ms = int(n * 1000 / sr)
    # Peak in last 300ms
    last300 = v[-int(sr * 0.300):]
    last300_pk = float(np.max(np.abs(last300))) if len(last300) else 0.0
    # Peak in last 30ms (fade region)
    last30 = v[-int(sr * 0.030):]
    last30_pk = float(np.max(np.abs(last30))) if len(last30) else 0.0
    # Check fade ramp: abs amplitudes should be monotonically decreasing
    # across the last 30ms. Sample peak at 5ms intervals inside the last 30ms.
    win5 = int(sr * 0.005)
    fade_samples = []
    for i in range(6):  # 6 x 5ms = 30ms
        start = n - int(sr * 0.030) + i * win5
        end = start + win5
        if 0 <= start < n and end <= n:
            fade_samples.append(float(np.max(np.abs(v[start:end]))))
    # Longest silent gap (sanity)
    win = int(sr * 0.020)
    nw = n // win
    if nw >= 5:
        rms = np.array([np.sqrt(np.mean(v[i*win:(i+1)*win]**2) + 1e-12) for i in range(nw)])
        db = 20 * np.log10(np.maximum(rms, 1e-10))
        is_speech = db >= -40
        longest = 0
        cur = 0
        for b in is_speech:
            if not b:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 0
        gap_ms = longest * 20
    else:
        gap_ms = 0
    return {
        'dur_ms': dur_ms,
        'last300_pk': last300_pk,
        'last30_pk': last30_pk,
        'fade_profile_5ms': fade_samples,
        'gap_ms': gap_ms,
    }


def main():
    print(f'{"Line":>4} | {"OLD_dur":>8} {"NEW_dur":>8} {"delta":>7} | '
          f'{"OLD_l300":>9} {"NEW_l300":>9} {"NEW_l30":>8} | {"gap":>6} | fade profile (5ms bins)')
    print('-' * 135)
    durs_old, durs_new, gaps, l300s, l30s = [], [], [], [], []
    for ln in range(301, 321):
        fn = f'Script_1_{ln:04d}.wav'
        op = os.path.join(OLD, fn)
        np2 = os.path.join(NEW, fn)
        if not (os.path.exists(op) and os.path.exists(np2)):
            continue
        mo = probe(op)
        mn = probe(np2)
        durs_old.append(mo['dur_ms'])
        durs_new.append(mn['dur_ms'])
        gaps.append(mn['gap_ms'])
        l300s.append(mn['last300_pk'])
        l30s.append(mn['last30_pk'])
        profile = ' '.join(f'{x:.3f}' for x in mn['fade_profile_5ms'])
        flag = ' <== L0313' if ln == 313 else ''
        print(f'{ln:>4} | {mo["dur_ms"]:>6}ms {mn["dur_ms"]:>6}ms '
              f'{mn["dur_ms"] - mo["dur_ms"]:>+5}ms | '
              f'{mo["last300_pk"]:>9.3f} {mn["last300_pk"]:>9.3f} {mn["last30_pk"]:>8.3f} | '
              f'{mn["gap_ms"]:>4}ms | {profile}{flag}')

    print('-' * 135)
    if not durs_new:
        print('No matching lines.')
        return

    n = len(durs_new)
    d_deltas = [durs_new[i] - durs_old[i] for i in range(n)]
    print(f'\nN = {n}')
    print(f'Duration delta (NEW - OLD):')
    print(f'  mean: {statistics.mean(d_deltas):+.0f}ms')
    print(f'  min:  {min(d_deltas):+d}ms  max: {max(d_deltas):+d}ms')
    print(f'  (expected ≈ +570ms if 700ms preserve - 120ms optionB safety - tiny normalize variance)')
    print()
    print(f'Last 300ms peak (NEW):')
    print(f'  mean: {statistics.mean(l300s):.4f}')
    print(f'  max:  {max(l300s):.4f}')
    print(f'  (expected > 0 — natural audio present, not zero-filled)')
    print()
    print(f'Last 30ms peak (NEW, fade region):')
    print(f'  mean: {statistics.mean(l30s):.4f}')
    print(f'  max:  {max(l30s):.4f}')
    print(f'  (should be < last300_pk since fade tapers to 0)')
    print()
    print(f'Longest silent gap (NEW):')
    print(f'  mean: {statistics.mean(gaps):.0f}ms  max: {max(gaps)}ms')
    print(f'  (L0313 should still be ≤ ~120ms from Option B bimodality fix)')


if __name__ == '__main__':
    main()
