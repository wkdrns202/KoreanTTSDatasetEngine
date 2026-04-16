# -*- coding: utf-8 -*-
"""Stage 3+4 on 2026-04-16_tail_preserve batch."""
import sys, os
sys.path.insert(0, r'G:\Projects\AI_Research\TTSDataSetCleanser\src')
import evaluate_dataset as ed
ROOT = r'G:\Projects\AI_Research\TTSDataSetCleanser\datasets\2026-04-16_tail_preserve'
LOGS = os.path.join(ROOT, 'eval_logs')
os.makedirs(LOGS, exist_ok=True)
ed.WAV_DIR = os.path.join(ROOT, 'wavs')
ed.METADATA_PATH = os.path.join(ROOT, 'script.txt')
ed.CHECKPOINT_PATH = os.path.join(LOGS, 'eval_checkpoint.json')
ed.REPORT_PATH = os.path.join(LOGS, 'evaluation_report.json')
ed.run_evaluation(script_filter=None, quick_mode=False, reset=True)
