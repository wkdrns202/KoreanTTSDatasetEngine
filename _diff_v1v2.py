# -*- coding: utf-8 -*-
"""Byte-compare V1 vs V2 audio at 5ms resolution across voiced region.
If they match (modulo normalization), Stage 2 is trimming V2's extra Stage 1 padding.
"""
import soundfile as sf
import numpy as np
import os

V1 = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_refactored_run\wavs'
V2 = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_frontfix_v2\wavs'


def rms_profile(y, sr, res_ms=5):
    win = int(sr * res_ms / 1000)
    n = len(y) // win
    a = y[:n * win].reshape(n, win)
    rms = np.sqrt(np.mean(a ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(np.maximum(rms, 1e-10))
    return db


print('Line | V1 voiced dur | V2 voiced dur | V2-V1 dur | V1 voiced first 40ms peaks | V2 voiced first 40ms peaks')
print('-' * 130)
for ln in [301, 302, 303, 310, 317, 318, 324, 325, 326, 330]:
    fn = f'Script_1_{ln:04d}.wav'
    p1 = os.path.join(V1, fn)
    p2 = os.path.join(V2, fn)
    if not (os.path.exists(p1) and os.path.exists(p2)):
        continue
    y1, sr = sf.read(p1)
    y2, _ = sf.read(p2)
    if y1.ndim > 1:
        y1 = y1[:, 0]
    if y2.ndim > 1:
        y2 = y2[:, 0]
    # Voiced region: strip 400ms pre-attack + 730ms tail
    lead = int(sr * 0.400)
    tail = int(sr * 0.730)
    v1 = y1[lead:len(y1) - tail]
    v2 = y2[lead:len(y2) - tail]
    # First 40ms, peak per 5ms
    win = int(sr * 0.005)

    def peaks(arr, n=8):
        out = []
        for i in range(n):
            s = arr[i * win:(i + 1) * win]
            out.append(f'{float(np.max(np.abs(s))):.3f}')
        return ' '.join(out)
    print(f'{ln:>4} | '
          f'{int(len(v1) * 1000 / sr):>8}ms     | '
          f'{int(len(v2) * 1000 / sr):>8}ms     | '
          f'{int((len(v2) - len(v1)) * 1000 / sr):>+5}ms    | '
          f'{peaks(v1)} | {peaks(v2)}')
