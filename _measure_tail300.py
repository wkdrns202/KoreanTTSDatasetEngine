# -*- coding: utf-8 -*-
"""Verify tail zero-fill implementation (symmetric to _measure_trim100.py).

Checks:
  1. Last N samples of voiced region == exact 0 (target: 300ms)
  2. Fade-out rolls from speech amplitude to 0 just before zero region
  3. Front zero-fill (Step 3.5) still works correctly (regression check)
  4. Duration vs pre-fix (V1 and v3)
"""
import soundfile as sf
import numpy as np
import os
import statistics

DIRS = {
    'V1':    r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_refactored_run\wavs',
    'V3':    r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_final_v3\wavs',
    'TAIL':  r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_tail300\wavs',
}
PRE_MS = 400   # envelope pre-attack
POST_MS = 730  # envelope tail


def load_voiced(p):
    y, sr = sf.read(p)
    if y.ndim > 1:
        y = y[:, 0]
    lead = int(sr * PRE_MS / 1000)
    tail = int(sr * POST_MS / 1000)
    return y[lead:len(y) - tail], sr, len(y)


def probe(p):
    v, sr, total_len = load_voiced(p)
    n = len(v)
    # Front zero region: first nonzero sample from start
    nz_fwd = np.where(np.abs(v) > 1e-12)[0]
    front_zero_ms = (nz_fwd[0] * 1000 / sr) if len(nz_fwd) else n * 1000 / sr
    # Tail zero region: last nonzero sample, measure from end
    nz_bwd = np.where(np.abs(v) > 1e-12)[0]
    if len(nz_bwd):
        last_nz = int(nz_bwd[-1])
        tail_zero_samples = n - (last_nz + 1)
    else:
        tail_zero_samples = n
    tail_zero_ms = tail_zero_samples * 1000 / sr
    # Peak in last 300ms of voiced region (should be exactly 0 if we hit target)
    last300 = v[-int(sr * 0.300):]
    last300_peak = float(np.max(np.abs(last300))) if len(last300) else 0.0
    # Peak in last 600ms of voiced region (outside the 300ms zero target — should have speech)
    last600_except_last300 = v[-int(sr * 0.600):-int(sr * 0.300)] if n > int(sr * 0.600) else np.array([])
    speech_amp = float(np.max(np.abs(last600_except_last300))) if len(last600_except_last300) else 0.0
    dur_ms = int(n * 1000 / sr)
    total_ms = int(total_len * 1000 / sr)
    return {
        'voiced_ms': dur_ms,
        'total_ms': total_ms,
        'front_zero_ms': front_zero_ms,
        'tail_zero_ms': tail_zero_ms,
        'last300_peak': last300_peak,
        'speech_amp_before_tail': speech_amp,
    }


def main():
    print(f'{"Line":>4} | {"V1_dur":>7} {"V3_dur":>7} {"TAIL_dur":>8} | '
          f'{"front0":>7} {"tail0":>7} {"last300_pk":>12} {"speech_pk":>10}')
    print('-' * 100)
    rows = []
    for ln in range(301, 321):
        fn = f'Script_1_{ln:04d}.wav'
        paths = {k: os.path.join(v, fn) for k, v in DIRS.items()}
        if not all(os.path.exists(p) for p in paths.values()):
            continue
        mt = probe(paths['TAIL'])
        # Also get baseline durations
        v1, _, tot1 = load_voiced(paths['V1'])
        v3, sr, tot3 = load_voiced(paths['V3'])
        v1_dur = int(len(v1) * 1000 / sr)
        v3_dur = int(len(v3) * 1000 / sr)
        rows.append((ln, mt, v1_dur, v3_dur))
        print(f'{ln:>4} | {v1_dur:>5}ms {v3_dur:>5}ms {mt["voiced_ms"]:>6}ms | '
              f'{mt["front_zero_ms"]:>5.1f}ms {mt["tail_zero_ms"]:>5.1f}ms '
              f'{mt["last300_peak"]:>12.2e} {mt["speech_amp_before_tail"]:>10.3f}')

    print('-' * 100)
    if not rows:
        print('No matching lines.')
        return

    front = [r[1]['front_zero_ms'] for r in rows]
    tail = [r[1]['tail_zero_ms'] for r in rows]
    last300_pk = [r[1]['last300_peak'] for r in rows]
    tail_dur = [r[1]['voiced_ms'] for r in rows]
    v1_dur = [r[2] for r in rows]
    v3_dur = [r[3] for r in rows]

    print(f'\nN = {len(rows)} lines')
    print(f'\n--- Front zero region (Step 3.5 regression check) ---')
    print(f'  mean: {statistics.mean(front):.2f}ms  target: 100.00ms  (should be unchanged)')

    print(f'\n--- Tail zero region (Step 3.6 new) ---')
    print(f'  mean: {statistics.mean(tail):.2f}ms  target: 300.00ms')
    print(f'  min:  {min(tail):.2f}ms')
    print(f'  max:  {max(tail):.2f}ms')
    at_target = sum(1 for t in tail if abs(t - 300.0) < 5.0)
    print(f'  Lines within 5ms of 300ms target: {at_target}/{len(rows)}')
    print(f'  Peak in last-300ms voiced window: max={max(last300_pk):.3e} '
          f'mean={statistics.mean(last300_pk):.3e}')
    print(f'  (expected: exactly 0 across all lines)')

    print(f'\n--- Duration comparison ---')
    print(f'  V1 voiced  mean: {statistics.mean(v1_dur):.0f}ms')
    print(f'  V3 voiced  mean: {statistics.mean(v3_dur):.0f}ms  (V3 - V1 = {statistics.mean(v3_dur) - statistics.mean(v1_dur):+.0f}ms)')
    print(f'  TAIL voiced mean: {statistics.mean(tail_dur):.0f}ms (TAIL - V3 = {statistics.mean(tail_dur) - statistics.mean(v3_dur):+.0f}ms)')
    print(f'  TAIL - V1 = {statistics.mean(tail_dur) - statistics.mean(v1_dur):+.0f}ms')


if __name__ == '__main__':
    main()
