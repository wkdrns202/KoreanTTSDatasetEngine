# -*- coding: utf-8 -*-
"""4-way comparison: V1 vs safety=80 vs safety=100 vs safety=120.
Measures:
  - Voiced region duration
  - Onset position (first -40dB peak past 390ms-stripped pre-attack)
  - First 40ms voiced energy profile (to detect bleed or over-extension)
  - Peak amplitude at voiced start (bleed signal)
"""
import soundfile as sf
import numpy as np
import os
import statistics

DIRS = {
    'V1':  r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_refactored_run\wavs',
    'S80': r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_alpha_safety80\wavs',
    'S100': r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_alpha_safety100\wavs',
    'S120': r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_alpha_safety120\wavs',
}


def load_voiced(p):
    y, sr = sf.read(p)
    if y.ndim > 1:
        y = y[:, 0]
    lead = int(sr * 0.400)
    tail = int(sr * 0.730)
    v = y[lead:len(y) - tail]
    return v, sr


def probe(p):
    """Return dict with key metrics."""
    v, sr = load_voiced(p)
    dur_ms = int(len(v) * 1000 / sr)
    # Onset relative to voiced start: first 1ms window with peak above -40dB
    win = int(sr * 0.001)
    nw = len(v) // win
    rms = np.array([np.sqrt(np.mean(v[i*win:(i+1)*win]**2) + 1e-12)
                    for i in range(nw)])
    db = 20 * np.log10(rms + 1e-12)
    above = np.where(db > -40)[0]
    onset_ms = int(above[0]) if len(above) else -1
    # First 20ms peak (to detect bleed — if high amplitude immediately, suspicious)
    head20 = v[:int(sr * 0.020)]
    head_peak = float(np.max(np.abs(head20))) if len(head20) else 0.0
    # First 40ms peaks in 5ms windows
    win5 = int(sr * 0.005)
    peaks5 = [float(np.max(np.abs(v[i*win5:(i+1)*win5]))) for i in range(8)]
    return {
        'dur_ms': dur_ms,
        'onset_ms': onset_ms,
        'head20_peak': head_peak,
        'peaks5': peaks5,
    }


def main():
    print(f'{"Line":>4} | {"V1_dur":>7} {"S80_dur":>8} {"S100_dur":>9} {"S120_dur":>9} | '
          f'{"V1_ons":>6} {"S80":>5} {"S100":>5} {"S120":>5} | '
          f'{"V1_p20":>7} {"S80":>6} {"S100":>6} {"S120":>6}')
    print('-' * 120)

    d_rows = {'S80': [], 'S100': [], 'S120': []}
    o_rows = {'S80': [], 'S100': [], 'S120': []}
    head_rows = {'V1': [], 'S80': [], 'S100': [], 'S120': []}
    bleed_flags = {'S80': 0, 'S100': 0, 'S120': 0}

    for ln in range(301, 331):
        fn = f'Script_1_{ln:04d}.wav'
        paths = {k: os.path.join(v, fn) for k, v in DIRS.items()}
        if not all(os.path.exists(p) for p in paths.values()):
            continue
        m = {k: probe(p) for k, p in paths.items()}
        print(f'{ln:>4} | '
              f'{m["V1"]["dur_ms"]:>5}ms {m["S80"]["dur_ms"]:>6}ms '
              f'{m["S100"]["dur_ms"]:>7}ms {m["S120"]["dur_ms"]:>7}ms | '
              f'{m["V1"]["onset_ms"]:>4}ms {m["S80"]["onset_ms"]:>3}ms '
              f'{m["S100"]["onset_ms"]:>3}ms {m["S120"]["onset_ms"]:>3}ms | '
              f'{m["V1"]["head20_peak"]:>7.3f} {m["S80"]["head20_peak"]:>6.3f} '
              f'{m["S100"]["head20_peak"]:>6.3f} {m["S120"]["head20_peak"]:>6.3f}')
        for k in ['S80', 'S100', 'S120']:
            d_rows[k].append(m[k]['dur_ms'] - m['V1']['dur_ms'])
            o_rows[k].append(m[k]['onset_ms'] - m['V1']['onset_ms'])
            head_rows[k].append(m[k]['head20_peak'])
            # Bleed heuristic: head20 peak > 0.3 AND much higher than V1's head20
            if m[k]['head20_peak'] > 0.3 and \
               m[k]['head20_peak'] > m['V1']['head20_peak'] * 2.0:
                bleed_flags[k] += 1
        head_rows['V1'].append(m['V1']['head20_peak'])

    print('-' * 120)
    print(f'\nSummary (N={len(d_rows["S80"])} lines, 301-330):')
    print(f'{"metric":<25}  {"S80":>12} {"S100":>12} {"S120":>12}')
    for k in ['S80', 'S100', 'S120']:
        print(f'{"dur delta (ms) mean":<25}: ', end='')
    print()
    for label in ['dur delta mean (ms)',
                  'dur delta max (ms)',
                  'onset delta mean (ms)',
                  'onset delta median (ms)',
                  'onset delta min (ms)',
                  'onset delta max (ms)',
                  'head20 peak mean',
                  'head20 peak max',
                  'bleed-flag count']:
        vals = {}
        for k in ['S80', 'S100', 'S120']:
            if label == 'dur delta mean (ms)':
                vals[k] = f'{statistics.mean(d_rows[k]):+.1f}'
            elif label == 'dur delta max (ms)':
                vals[k] = f'{max(d_rows[k]):+d}'
            elif label == 'onset delta mean (ms)':
                vals[k] = f'{statistics.mean(o_rows[k]):+.1f}'
            elif label == 'onset delta median (ms)':
                vals[k] = f'{statistics.median(o_rows[k]):+.1f}'
            elif label == 'onset delta min (ms)':
                vals[k] = f'{min(o_rows[k]):+d}'
            elif label == 'onset delta max (ms)':
                vals[k] = f'{max(o_rows[k]):+d}'
            elif label == 'head20 peak mean':
                vals[k] = f'{statistics.mean(head_rows[k]):.3f}'
            elif label == 'head20 peak max':
                vals[k] = f'{max(head_rows[k]):.3f}'
            elif label == 'bleed-flag count':
                vals[k] = f'{bleed_flags[k]}'
        print(f'{label:<25}: {vals["S80"]:>12} {vals["S100"]:>12} {vals["S120"]:>12}')

    print(f'\nV1 baseline head20 peak mean: {statistics.mean(head_rows["V1"]):.3f}, max: {max(head_rows["V1"]):.3f}')


if __name__ == '__main__':
    main()
