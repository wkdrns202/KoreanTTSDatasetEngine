# -*- coding: utf-8 -*-
"""Sweep ONSET_SAFETY_MS across 120/100/80 on Script_1_301-737.
Runs in a single process so Whisper loads only once (transcription cache is
per-call though — each align_and_split call still re-transcribes).
"""
import sys
import os
import shutil

sys.path.insert(0, r'G:\Projects\AI_Research\TTSDataSetCleanser\src')
import align_and_split as aas

BASE_OUT = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets'
AUDIO_DIR = r'G:\Projects\AI_Research\TTSDataSetCleanser\rawdata\audio\_test_trimmed'
RANGE_FILTER = (301, 340)

print(f'Baseline params:')
print(f'  AUDIO_PAD_MS         = {aas.AUDIO_PAD_MS}')
print(f'  SILENCE_THRESHOLD_DB = {aas.SILENCE_THRESHOLD_DB}')
print(f'  FADE_MS (fade-in)    = {aas.FADE_MS}')
print(f'  FADE_OUT_MS          = {aas.FADE_OUT_MS}')
print(f'  (sweeping ONSET_SAFETY_MS over [120, 100, 80])')
print()

for safety in [120, 100, 80]:
    print(f'=' * 60)
    print(f'[SAFETY={safety}ms] starting')
    print(f'=' * 60)
    aas.ONSET_SAFETY_MS = safety
    out_dir = os.path.join(BASE_OUT, f'test_alpha_safety{safety}')
    os.makedirs(out_dir, exist_ok=True)
    # Clear previous wavs if any to keep runs independent
    wavs_dir = os.path.join(out_dir, 'wavs')
    if os.path.exists(wavs_dir):
        shutil.rmtree(wavs_dir, ignore_errors=True)
    os.makedirs(wavs_dir, exist_ok=True)
    aas.align_and_split(
        model_size='medium',
        script_filter=1,
        range_filter=RANGE_FILTER,
        resume=False,
        audio_dir=AUDIO_DIR,
        output_wav_dir=wavs_dir,
        metadata_path=os.path.join(out_dir, 'script.txt'),
    )
    print(f'[SAFETY={safety}ms] done -> {out_dir}\n')

print('Sweep complete.')
