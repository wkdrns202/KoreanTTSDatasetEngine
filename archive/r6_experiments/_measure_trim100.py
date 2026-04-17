# -*- coding: utf-8 -*-
"""Verify 320+trim100+zerofill implementation:
  1. Exact-zero pre-speech region (peak = 0.000000)
  2. Speech starts at exactly 100ms into voiced region (or less if clamped)
  3. Transition smoothness (fade-in at speech boundary)
  4. Duration vs V1 / S320 / S80
"""
import soundfile as sf
import numpy as np
import os
import statistics

DIRS = {
    'V1':    r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_refactored_run\wavs',
    'S80':   r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_alpha_safety80\wavs',
    'S320':  r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_alpha_safety320\wavs',
    'TRIM':  r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_safety320_trim100_v2\wavs',
}


def load_voiced(p):
    y, sr = sf.read(p)
    if y.ndim > 1:
        y = y[:, 0]
    lead = int(sr * 0.400)
    tail = int(sr * 0.730)
    v = y[lead:len(y) - tail]
    return v, sr


def probe_trim(p):
    v, sr = load_voiced(p)
    # Find first nonzero sample — this is where "complete silence" ends
    nonzero = np.where(np.abs(v) > 1e-12)[0]
    first_nz_sample = int(nonzero[0]) if len(nonzero) else len(v)
    first_nz_ms = first_nz_sample * 1000 / sr
    # Peak in the zeroed region (should be exactly 0)
    if first_nz_sample > 0:
        zeroed_peak = float(np.max(np.abs(v[:first_nz_sample])))
    else:
        zeroed_peak = 0.0
    # Speech peak in first 20ms after the zero region
    after_win = v[first_nz_sample:first_nz_sample + int(sr * 0.020)]
    first20_peak = float(np.max(np.abs(after_win))) if len(after_win) else 0.0
    # Check smoothness: first few samples after zero region
    n_samples_after = min(int(sr * 0.010), len(v) - first_nz_sample)
    ramp_samples = v[first_nz_sample:first_nz_sample + n_samples_after]
    dur_ms = int(len(v) * 1000 / sr)
    return {
        'dur_ms': dur_ms,
        'zero_region_ms': first_nz_ms,
        'zeroed_peak': zeroed_peak,  # should be exactly 0
        'first20_peak_after_zero': first20_peak,
        'ramp_first_10ms': ramp_samples[:10].tolist() if len(ramp_samples) else [],
    }


def main():
    print('=== Trim+ZeroFill Verification (L301-320) ===')
    print(f'{"Line":>4} | {"TRIM_dur":>9} {"S320_dur":>9} {"delta":>6} | '
          f'{"zero_ms":>8} {"zeroed_pk":>10} {"post20pk":>9}')
    print('-' * 80)

    rows = []
    for ln in range(301, 321):
        fn = f'Script_1_{ln:04d}.wav'
        paths = {k: os.path.join(v, fn) for k, v in DIRS.items()}
        if not all(os.path.exists(p) for p in paths.values()):
            continue
        m_trim = probe_trim(paths['TRIM'])
        # Durations for context
        v320, sr = load_voiced(paths['S320'])
        v1, _ = load_voiced(paths['V1'])
        s320_dur = int(len(v320) * 1000 / sr)
        v1_dur = int(len(v1) * 1000 / sr)
        rows.append((ln, m_trim, s320_dur, v1_dur))
        print(f'{ln:>4} | '
              f'{m_trim["dur_ms"]:>7}ms {s320_dur:>7}ms '
              f'{m_trim["dur_ms"] - s320_dur:>+4}ms | '
              f'{m_trim["zero_region_ms"]:>6.2f}ms '
              f'{m_trim["zeroed_peak"]:>10.2e} '
              f'{m_trim["first20_peak_after_zero"]:>9.3f}')

    print('-' * 80)

    # Aggregate
    zeros = [r[1]['zero_region_ms'] for r in rows]
    zero_peaks = [r[1]['zeroed_peak'] for r in rows]
    trim_durs = [r[1]['dur_ms'] for r in rows]
    s320_durs = [r[2] for r in rows]
    v1_durs = [r[3] for r in rows]

    print(f'\nN = {len(rows)} lines')
    print(f'\n--- Zero-fill region ---')
    print(f'  Length mean: {statistics.mean(zeros):6.2f}ms (target: 100ms)')
    print(f'  Length min : {min(zeros):6.2f}ms')
    print(f'  Length max : {max(zeros):6.2f}ms')
    print(f'  Peak in zeroed region: max={max(zero_peaks):.3e}, mean={statistics.mean(zero_peaks):.3e}')
    print(f'  (expected: exactly 0; any nonzero = leak)')

    print(f'\n--- Duration comparison ---')
    print(f'  TRIM mean: {statistics.mean(trim_durs):.0f}ms')
    print(f'  S320 mean: {statistics.mean(s320_durs):.0f}ms  (TRIM-S320 = {statistics.mean(trim_durs) - statistics.mean(s320_durs):+.1f}ms)')
    print(f'  V1  mean : {statistics.mean(v1_durs):.0f}ms  (TRIM-V1  = {statistics.mean(trim_durs) - statistics.mean(v1_durs):+.1f}ms)')

    # Check how many lines hit the 100ms target exactly vs shorter (clamp)
    at_target = sum(1 for z in zeros if abs(z - 100.0) < 1.0)
    shorter = sum(1 for z in zeros if z < 99.0)
    print(f'\n  Lines with zero-region ~100ms (exact): {at_target}/{len(rows)}')
    print(f'  Lines with zero-region <100ms (clamp) : {shorter}/{len(rows)}')

    # Show first 10 samples of ramp for first 3 lines to verify no click
    print(f'\n--- Ramp at speech boundary (first 10 samples after zeros) ---')
    for ln, m, _, _ in rows[:3]:
        ramp = m['ramp_first_10ms']
        print(f'  L{ln}: {[f"{x:+.4f}" for x in ramp]}')


if __name__ == '__main__':
    main()
