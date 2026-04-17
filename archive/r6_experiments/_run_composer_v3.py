# -*- coding: utf-8 -*-
"""Stage 4.5 Selective Composer on 2026-04-14_final_v3 batch.
Overrides module globals so the composer uses the batch's own eval checkpoint
and writes its artifacts under that batch's eval_logs/ dir.
"""
import sys
import os

sys.path.insert(0, r'G:\Projects\AI_Research\TTSDataSetCleanser\src')
import selective_composer as sc

NEW_ROOT = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-14_final_v3'
eval_logs = os.path.join(NEW_ROOT, 'eval_logs')

# Input paths
sc.WAV_DIR = os.path.join(NEW_ROOT, 'wavs')
sc.METADATA_PATH = os.path.join(NEW_ROOT, 'script.txt')
sc.EVAL_CHECKPOINT_PATH = os.path.join(eval_logs, 'eval_checkpoint.json')

# Output paths (same location for easy collation)
os.makedirs(eval_logs, exist_ok=True)
sc.SCORES_PATH = os.path.join(eval_logs, 'composition_scores.json')
sc.COMPOSITION_REPORT_PATH = os.path.join(eval_logs, 'composition_report.json')
sc.PENDING_POOL_PATH = os.path.join(eval_logs, 'pending_pool.json')
sc.REJECTION_LOG_PATH = os.path.join(eval_logs, 'rejection_log.json')
sc.CALIBRATION_PATH = os.path.join(eval_logs, 'calibration_report.json')

print(f'WAV_DIR        = {sc.WAV_DIR}')
print(f'EVAL_CKPT      = {sc.EVAL_CHECKPOINT_PATH}')
print(f'SCORES_PATH    = {sc.SCORES_PATH}')
print(f'COMP_REPORT    = {sc.COMPOSITION_REPORT_PATH}')
print()

# Replicate what `python selective_composer.py --compose` does
# Build a minimal args namespace and call main
sys.argv = ['selective_composer.py', '--compose']
sc.main()
