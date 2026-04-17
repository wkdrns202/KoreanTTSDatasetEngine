# -*- coding: utf-8 -*-
"""
A/B Experiment: R6 Envelope Stripping Effectiveness
=====================================================
Compares Whisper transcription accuracy WITH vs WITHOUT envelope stripping.

Hypothesis: Stripping the R6 silence envelope (350ms lead, 700ms tail) before
Whisper transcription reduces first-syllable drops and improves CER similarity.

Usage:
  python src/experiment_envelope_strip.py --tiny       # 50 samples (25 PASS + 25 near-miss)
  python src/experiment_envelope_strip.py --full       # All 4196 samples
"""

import os
import sys
import csv
import json
import re
import unicodedata
import warnings
import argparse
import gc

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

# Use CUDA if available
import torch

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

print("[DIAG] Python started, importing modules...", flush=True)

try:
    print("[DIAG] Importing static_ffmpeg...", flush=True)
    import static_ffmpeg
    static_ffmpeg.add_paths()
    print("[DIAG] Importing whisper...", flush=True)
    import whisper
    print("[DIAG] Whisper imported OK", flush=True)
except ImportError as e:
    print(f"[DIAG] ImportError: {e}", flush=True)
    os.system("pip install openai-whisper static-ffmpeg torch")
    import static_ffmpeg
    static_ffmpeg.add_paths()
    import whisper

from tqdm import tqdm
print("[DIAG] All imports complete", flush=True)

# ============================================================
# CONFIGURATION
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAV_DIR = os.path.join(BASE_DIR, "datasets", "wavs")
METADATA_PATH = os.path.join(BASE_DIR, "datasets", "script.txt")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Stripping parameters (same as evaluate_dataset.py)
EVAL_STRIP_LEAD_MS = 350
EVAL_STRIP_TAIL_MS = 700

MODEL_SIZE = "medium"
LANGUAGE = "ko"


# ============================================================
# TEXT PROCESSING (from evaluate_dataset.py)
# ============================================================

def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def normalize_text(text):
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'[^가-힣a-zA-Z0-9]', '', text)
    return text.lower()


def compute_similarity(gt, pred):
    norm_gt = normalize_text(gt)
    norm_pred = normalize_text(pred)
    if len(norm_gt) == 0 and len(norm_pred) == 0:
        return 1.0
    if len(norm_gt) == 0 or len(norm_pred) == 0:
        return 0.0
    dist = levenshtein_distance(norm_gt, norm_pred)
    max_len = max(len(norm_gt), len(norm_pred))
    return 1.0 - (dist / max_len)


def detect_first_word_drop(gt, pred):
    """Check if the first word of gt is missing from pred."""
    norm_gt = normalize_text(gt)
    norm_pred = normalize_text(pred)
    if len(norm_gt) < 2 or len(norm_pred) < 2:
        return False
    # First 2-4 chars of gt missing from start of pred
    first_chars = norm_gt[:min(4, len(norm_gt))]
    return not norm_pred.startswith(first_chars[:2])


# ============================================================
# AUDIO HELPERS
# ============================================================

def load_and_strip(wav_path, strip_lead_ms, strip_tail_ms):
    """Load WAV and strip specified ms from lead and tail."""
    samples, sr = sf.read(wav_path, dtype='float32')
    lead_samples = int(sr * strip_lead_ms / 1000)
    tail_samples = int(sr * strip_tail_ms / 1000)

    if lead_samples + tail_samples >= len(samples):
        return samples, sr  # Too short to strip, return original

    if strip_lead_ms > 0:
        samples = samples[lead_samples:]
    if strip_tail_ms > 0 and tail_samples > 0:
        samples = samples[:-tail_samples]

    return samples, sr


def transcribe_samples(model, samples, sr, fp16=False):
    """Transcribe audio samples with Whisper."""
    # Whisper expects float32 numpy array
    audio = np.asarray(samples, dtype=np.float32)

    # Whisper expects 16kHz — resample if needed
    if sr != 16000:
        # Simple linear interpolation resample
        duration = len(audio) / sr
        target_len = int(duration * 16000)
        indices = np.linspace(0, len(audio) - 1, target_len).astype(np.float32)
        audio = np.interp(indices, np.arange(len(audio), dtype=np.float32), audio).astype(np.float32)

    result = model.transcribe(
        audio,
        language=LANGUAGE,
        fp16=fp16,
        without_timestamps=True
    )
    return result.get("text", "").strip()


# ============================================================
# SAMPLE SELECTION
# ============================================================

def load_metadata():
    """Load script.txt metadata."""
    entries = {}
    with open(METADATA_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '|' in line:
                parts = line.split('|', 1)
                fname = parts[0].strip()
                text = parts[1].strip()
                entries[fname] = text
    return entries


def load_validation_csv():
    """Load existing validation_results.csv for sample selection."""
    csv_path = os.path.join(BASE_DIR, "datasets", "validation_results.csv")
    results = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            row['similarity'] = float(row['similarity'])
            results.append(row)
    return results


def select_tiny_samples(validation_data):
    """Select 50 samples: 25 PASS (sim >= 0.95) + 25 near-miss (0.80 <= sim < 0.95)."""
    pass_items = [r for r in validation_data if r['similarity'] >= 0.95]
    near_miss = [r for r in validation_data if 0.80 <= r['similarity'] < 0.95]

    # Sort near-miss by similarity ascending (worst first, more interesting)
    near_miss.sort(key=lambda x: x['similarity'])

    # Take 25 of each; if not enough near-miss, take what's available
    selected_pass = pass_items[:25]
    selected_miss = near_miss[:25]

    print(f"Selected {len(selected_pass)} PASS + {len(selected_miss)} near-miss = {len(selected_pass) + len(selected_miss)} total")
    return selected_pass + selected_miss


# ============================================================
# MAIN EXPERIMENT
# ============================================================

def run_experiment(samples_list, metadata, output_path):
    """Run A/B comparison: WITH stripping vs WITHOUT stripping."""

    # --- Robust CUDA setup ---
    device = "cpu"
    use_fp16 = False

    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            gc.collect()
            # Quick CUDA health check
            _t = torch.zeros(1, device="cuda")
            del _t
            torch.cuda.empty_cache()
            device = "cuda"
            use_fp16 = True
            print(f"\n[DIAG] CUDA health check passed", flush=True)
        except Exception as e:
            print(f"\n[DIAG] CUDA health check FAILED ({e}), falling back to CPU", flush=True)
    else:
        print(f"\n[DIAG] CUDA not available, using CPU", flush=True)

    # Load model on CPU first, then move to device (avoids CUDA segfault on direct load)
    print(f"[DIAG] Loading Whisper {MODEL_SIZE} model (CPU first, then {device})...", flush=True)
    model = whisper.load_model(MODEL_SIZE, device="cpu")
    if device == "cuda":
        model = model.cuda()
        torch.cuda.empty_cache()
    print(f"[DIAG] Model loaded on {device}, fp16={use_fp16}", flush=True)

    results = []
    strip_wins = 0
    nostrip_wins = 0
    ties = 0
    strip_first_drops = 0
    nostrip_first_drops = 0

    for item in tqdm(samples_list, desc="A/B Experiment"):
        fname = item['filename']
        wav_path = os.path.join(WAV_DIR, fname)

        if not os.path.exists(wav_path):
            print(f"  SKIP: {fname} not found")
            continue

        gt = metadata.get(fname, '')
        if not gt:
            print(f"  SKIP: {fname} no ground truth")
            continue

        try:
            # --- Condition A: WITH stripping (current pipeline method) ---
            samples_stripped, sr = load_and_strip(wav_path, EVAL_STRIP_LEAD_MS, EVAL_STRIP_TAIL_MS)
            text_stripped = transcribe_samples(model, samples_stripped, sr, fp16=use_fp16)
            sim_stripped = compute_similarity(gt, text_stripped)
            drop_stripped = detect_first_word_drop(gt, text_stripped)

            # --- Condition B: WITHOUT stripping (full R6 envelope retained) ---
            samples_full, sr = sf.read(wav_path, dtype='float32')
            text_full = transcribe_samples(model, samples_full, sr, fp16=use_fp16)
            sim_full = compute_similarity(gt, text_full)
            drop_full = detect_first_word_drop(gt, text_full)
        except Exception as e:
            print(f"  ERROR on {fname}: {e}", flush=True)
            continue

        # --- Compare ---
        delta = sim_stripped - sim_full
        if delta > 0.001:
            strip_wins += 1
            winner = "STRIP"
        elif delta < -0.001:
            nostrip_wins += 1
            winner = "NOSTRIP"
        else:
            ties += 1
            winner = "TIE"

        if drop_stripped:
            strip_first_drops += 1
        if drop_full:
            nostrip_first_drops += 1

        result = {
            "filename": fname,
            "ground_truth": gt,
            "text_stripped": text_stripped,
            "text_full": text_full,
            "sim_stripped": round(sim_stripped, 4),
            "sim_full": round(sim_full, 4),
            "delta": round(delta, 4),
            "winner": winner,
            "first_drop_stripped": drop_stripped,
            "first_drop_full": drop_full,
            "original_sim": item['similarity']
        }
        results.append(result)

    # --- Aggregate ---
    n = len(results)
    if n == 0:
        print("No results!")
        return

    mean_sim_stripped = np.mean([r['sim_stripped'] for r in results])
    mean_sim_full = np.mean([r['sim_full'] for r in results])
    r1_stripped = sum(1 for r in results if r['sim_stripped'] >= 0.95) / n * 100
    r1_full = sum(1 for r in results if r['sim_full'] >= 0.95) / n * 100

    summary = {
        "experiment": "R6 Envelope Stripping A/B Test",
        "sample_size": n,
        "stripping_params": {
            "lead_strip_ms": EVAL_STRIP_LEAD_MS,
            "tail_strip_ms": EVAL_STRIP_TAIL_MS
        },
        "results": {
            "mean_similarity_with_strip": round(float(mean_sim_stripped), 4),
            "mean_similarity_without_strip": round(float(mean_sim_full), 4),
            "delta_mean": round(float(mean_sim_stripped - mean_sim_full), 4),
            "r1_pass_rate_with_strip": round(float(r1_stripped), 2),
            "r1_pass_rate_without_strip": round(float(r1_full), 2),
            "strip_wins": strip_wins,
            "nostrip_wins": nostrip_wins,
            "ties": ties,
            "first_word_drops_with_strip": strip_first_drops,
            "first_word_drops_without_strip": nostrip_first_drops
        },
        "per_item": results
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # --- Print Summary ---
    print("\n" + "=" * 60)
    print("EXPERIMENT RESULTS: R6 Envelope Stripping A/B Test")
    print("=" * 60)
    print(f"Sample size: {n}")
    print(f"\n{'Metric':<40} {'WITH strip':>12} {'WITHOUT strip':>14}")
    print("-" * 66)
    print(f"{'Mean similarity':<40} {mean_sim_stripped:>12.4f} {mean_sim_full:>14.4f}")
    print(f"{'R1 pass rate (sim >= 0.95)':<40} {r1_stripped:>11.1f}% {r1_full:>13.1f}%")
    print(f"{'First-word drops':<40} {strip_first_drops:>12d} {nostrip_first_drops:>14d}")
    print(f"\nPer-item wins: STRIP={strip_wins}  NOSTRIP={nostrip_wins}  TIE={ties}")
    print(f"Mean delta (strip - nostrip): {mean_sim_stripped - mean_sim_full:+.4f}")
    print(f"\nResults saved to: {output_path}")

    # Clean up
    del model
    gc.collect()


def main():
    parser = argparse.ArgumentParser(description="R6 Envelope Stripping A/B Experiment")
    parser.add_argument('--tiny', action='store_true', help='Run tiny experiment (50 samples)')
    parser.add_argument('--full', action='store_true', help='Run full experiment (all samples)')
    args = parser.parse_args()

    if not args.tiny and not args.full:
        print("Usage: python experiment_envelope_strip.py --tiny  OR  --full")
        sys.exit(1)

    print("[DIAG] Loading metadata...", flush=True)
    metadata = load_metadata()
    print(f"[DIAG] Loaded {len(metadata)} metadata entries", flush=True)

    print("[DIAG] Loading validation CSV...", flush=True)
    validation_data = load_validation_csv()
    print(f"[DIAG] Loaded {len(validation_data)} validation results", flush=True)

    if args.tiny:
        samples = select_tiny_samples(validation_data)
        output_path = os.path.join(LOG_DIR, "envelope_strip_ab_tiny.json")
    else:
        samples = validation_data
        output_path = os.path.join(LOG_DIR, "envelope_strip_ab_full.json")

    run_experiment(samples, metadata, output_path)


if __name__ == "__main__":
    main()
