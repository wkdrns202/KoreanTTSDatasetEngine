# -*- coding: utf-8 -*-
"""Run evaluate_dataset (Tier 1 + Tier 2) on the 2026-04-14_final_v3 batch
by overriding the module-level WAV_DIR / METADATA_PATH / CHECKPOINT_PATH
before calling run_evaluation(). evaluate_dataset.py has no --wav-dir flag.
"""
import sys
import os

sys.path.insert(0, r'G:\Projects\AI_Research\TTSDataSetCleanser\src')
import evaluate_dataset as ed

NEW_ROOT = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_final_v3'

# Override input paths
ed.WAV_DIR = os.path.join(NEW_ROOT, 'wavs')
ed.METADATA_PATH = os.path.join(NEW_ROOT, 'script.txt')

# Override output paths so results co-locate with the batch
eval_logs = os.path.join(NEW_ROOT, 'eval_logs')
os.makedirs(eval_logs, exist_ok=True)
ed.CHECKPOINT_PATH = os.path.join(eval_logs, 'eval_checkpoint.json')
ed.REPORT_PATH = os.path.join(eval_logs, 'evaluation_report.json')

print(f'WAV_DIR         = {ed.WAV_DIR}')
print(f'METADATA_PATH   = {ed.METADATA_PATH}')
print(f'CHECKPOINT_PATH = {ed.CHECKPOINT_PATH}')
print(f'REPORT_PATH     = {ed.REPORT_PATH}')
print()

ed.run_evaluation(script_filter=None, quick_mode=False, reset=True)
