# -*- coding: utf-8 -*-
"""Run Stage 3+4 (evaluate) and Stage 4.5 (selective_composer) on L0313 alone
from the test_tail300 (POSTSPEECH_PAD_MS=300) output. Goal: verify whether
the existing composition gate catches the trailing-misalignment issue.
"""
import sys
import os

sys.path.insert(0, r'G:\Projects\AI_Research\TTSDataSetCleanser\src')
import evaluate_dataset as ed
import selective_composer as sc

ROOT = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_L313_only'
LOGS = os.path.join(ROOT, 'eval_logs')
os.makedirs(LOGS, exist_ok=True)

# === Stage 3+4 ===
ed.WAV_DIR = os.path.join(ROOT, 'wavs')
ed.METADATA_PATH = os.path.join(ROOT, 'script.txt')
ed.CHECKPOINT_PATH = os.path.join(LOGS, 'eval_checkpoint.json')
ed.REPORT_PATH = os.path.join(LOGS, 'evaluation_report.json')

print('=== STAGE 3+4 ===')
print(f'WAV_DIR={ed.WAV_DIR}')
print(f'METADATA_PATH={ed.METADATA_PATH}')
ed.run_evaluation(script_filter=None, quick_mode=False, reset=True)

# === Stage 4.5 ===
sc.WAV_DIR = os.path.join(ROOT, 'wavs')
sc.METADATA_PATH = os.path.join(ROOT, 'script.txt')
sc.EVAL_CHECKPOINT_PATH = os.path.join(LOGS, 'eval_checkpoint.json')
sc.SCORES_PATH = os.path.join(LOGS, 'composition_scores.json')
sc.COMPOSITION_REPORT_PATH = os.path.join(LOGS, 'composition_report.json')
sc.PENDING_POOL_PATH = os.path.join(LOGS, 'pending_pool.json')
sc.REJECTION_LOG_PATH = os.path.join(LOGS, 'rejection_log.json')
sc.CALIBRATION_PATH = os.path.join(LOGS, 'calibration_report.json')

print('\n=== STAGE 4.5 ===')
sys.argv = ['selective_composer.py', '--compose']
sc.main()
