# -*- coding: utf-8 -*-
"""Re-score test_tail300 batch (18 lines) with new D8 S_continuity.
Reuses existing eval_checkpoint from prior Whisper pass — no Tier 1/2 rerun.

Uses test_L313_only eval was for single-file; we need eval results for all
18 lines. If test_tail300/eval_logs/eval_checkpoint.json doesn't exist yet,
we'll first run Stage 3+4 eval on the 18 files.
"""
import sys
import os

sys.path.insert(0, r'G:\Projects\AI_Research\TTSDataSetCleanser\src')
import evaluate_dataset as ed
import selective_composer as sc

ROOT = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\test_tail300'
LOGS = os.path.join(ROOT, 'eval_logs')
os.makedirs(LOGS, exist_ok=True)

# Run eval only if not already present
eval_ckpt = os.path.join(LOGS, 'eval_checkpoint.json')
if not os.path.exists(eval_ckpt):
    print('[eval_checkpoint missing — running Stage 3+4 first]')
    ed.WAV_DIR = os.path.join(ROOT, 'wavs')
    ed.METADATA_PATH = os.path.join(ROOT, 'script.txt')
    ed.CHECKPOINT_PATH = eval_ckpt
    ed.REPORT_PATH = os.path.join(LOGS, 'evaluation_report.json')
    ed.run_evaluation(script_filter=None, quick_mode=False, reset=True)
else:
    print(f'[using existing eval_checkpoint at {eval_ckpt}]')

# Stage 4.5
sc.WAV_DIR = os.path.join(ROOT, 'wavs')
sc.METADATA_PATH = os.path.join(ROOT, 'script.txt')
sc.EVAL_CHECKPOINT_PATH = eval_ckpt
sc.SCORES_PATH = os.path.join(LOGS, 'composition_scores.json')
sc.COMPOSITION_REPORT_PATH = os.path.join(LOGS, 'composition_report.json')
sc.PENDING_POOL_PATH = os.path.join(LOGS, 'pending_pool.json')
sc.REJECTION_LOG_PATH = os.path.join(LOGS, 'rejection_log.json')
sc.CALIBRATION_PATH = os.path.join(LOGS, 'calibration_report.json')

print('\n[Stage 4.5 rescore with D8 S_continuity]')
sys.argv = ['selective_composer.py', '--compose']
sc.main()
