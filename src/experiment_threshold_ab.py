# -*- coding: utf-8 -*-
"""
A/B Experiment: Silence Threshold -40dB vs -65dB — [FROZEN EXPERIMENT]
==================================================
WARNING: Parameters (AUDIO_PAD_MS=100, OFFSET_SAFETY=20/100) are frozen from
the original experiment. Current pipeline uses align_and_split.py (50/120).
Do NOT treat output as current-quality evidence.
==================================================
Tests the effect of SILENCE_THRESHOLD_DB on R6 envelope trimming accuracy.

Uses pre-aligned time ranges from envelope_raw_ab.json to avoid re-running alignment.
Extracts each segment from the raw audio, applies post-processing with both thresholds,
then runs Whisper eval on both versions.

Conditions:
  A: -40dB threshold + OFFSET_SAFETY=20ms  (old params)
  B: -65dB threshold + OFFSET_SAFETY=100ms (new params)
"""

import os
import sys
import json
import gc
import warnings
import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

import torch

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

print("[DIAG] Importing modules...", flush=True)

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    import whisper
except ImportError:
    os.system("pip install openai-whisper static-ffmpeg torch")
    import static_ffmpeg
    static_ffmpeg.add_paths()
    import whisper

from tqdm import tqdm
import re
import unicodedata

print("[DIAG] All imports complete", flush=True)

# ============================================================
# CONFIGURATION
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
RAW_AUDIO_PATH = os.path.join(BASE_DIR, "rawdata", "audio", "Script_1_221-300.wav")
ALIGNMENT_DATA = os.path.join(LOG_DIR, "envelope_raw_ab.json")
OUTPUT_PATH = os.path.join(LOG_DIR, "threshold_ab_results.json")

MODEL_SIZE = "medium"
LANGUAGE = "ko"
SR_TARGET = 48000

# Shared params
PREATTACK_SILENCE_MS = 400
TAIL_SILENCE_MS = 730
FADE_MS = 10
PEAK_NORMALIZE_DB = -1.0
ONSET_SAFETY_MS = 30
RMS_WINDOW_MS = 10
AUDIO_PAD_MS = 100  # extraction padding from raw

# Condition A: old params
THRESHOLD_A_DB = -40
OFFSET_SAFETY_A_MS = 20

# Condition B: new params
THRESHOLD_B_DB = -65
OFFSET_SAFETY_B_MS = 100


# ============================================================
# DSP FUNCTIONS (from align_and_split.py)
# ============================================================

def compute_rms_windowed(samples, sr=48000, window_ms=RMS_WINDOW_MS):
    window_size = int(sr * window_ms / 1000)
    if window_size < 1:
        window_size = 1
    n_windows = len(samples) // window_size
    if n_windows == 0:
        rms_lin = np.sqrt(np.mean(samples ** 2))
        return np.array([20 * np.log10(max(rms_lin, 1e-10))])
    trimmed = samples[:n_windows * window_size].reshape(n_windows, window_size)
    rms_lin = np.sqrt(np.mean(trimmed ** 2, axis=1))
    rms_db = 20 * np.log10(np.maximum(rms_lin, 1e-10))
    return rms_db


def find_voice_onset_offset(samples, sr=48000, threshold_db=-40, window_ms=RMS_WINDOW_MS):
    window_size = int(sr * window_ms / 1000)
    rms_db = compute_rms_windowed(samples, sr, window_ms)
    voiced = np.where(rms_db >= threshold_db)[0]
    if len(voiced) == 0:
        return 0, len(samples)
    onset_sample = voiced[0] * window_size
    offset_sample = min((voiced[-1] + 1) * window_size, len(samples))
    return onset_sample, offset_sample


def find_nearest_zero_crossing(samples, center_idx, sr=48000, search_ms=10):
    search_radius = int(sr * search_ms / 1000)
    start = max(0, center_idx - search_radius)
    end = min(len(samples) - 1, center_idx + search_radius)
    if end - start < 2:
        return center_idx
    signs = np.sign(samples[start:end])
    signs[signs == 0] = 1
    crossings = np.where(np.diff(signs))[0] + start
    if len(crossings) == 0:
        return center_idx
    distances = np.abs(crossings - center_idx)
    return int(crossings[np.argmin(distances)])


def make_raised_cosine_fade(length):
    if length <= 0:
        return np.array([], dtype=np.float64)
    return 0.5 * (1 - np.cos(np.pi * np.arange(length) / length))


def post_process_segment(samples, sr, threshold_db, offset_safety_ms):
    """Apply full Stage 2 post-processing with given threshold and offset safety."""
    sr_target = SR_TARGET
    preattack_samples = int(sr_target * PREATTACK_SILENCE_MS / 1000)
    tail_samples = int(sr_target * TAIL_SILENCE_MS / 1000)
    fade_samples = int(sr_target * FADE_MS / 1000)
    onset_safety = int(sr * ONSET_SAFETY_MS / 1000)
    offset_safety = int(sr * offset_safety_ms / 1000)

    # Ensure float64 for precision
    samples = np.asarray(samples, dtype=np.float64)

    # Step 1: Zero-crossing snap
    if len(samples) > 960:
        new_start = find_nearest_zero_crossing(samples, 0, sr)
        new_end = find_nearest_zero_crossing(samples, len(samples) - 1, sr)
        if new_end > new_start:
            samples = samples[new_start:new_end + 1]

    # Step 2-3: Voice onset/offset + trim
    onset, offset = find_voice_onset_offset(samples, sr, threshold_db=threshold_db)
    onset = max(0, onset - onset_safety)
    offset = min(len(samples), offset + offset_safety)

    if onset >= offset:
        voiced = samples.copy()
    else:
        voiced = samples[onset:offset].copy()

    if len(voiced) == 0:
        return None

    # Step 4: Fade
    actual_fade_in = min(fade_samples, len(voiced) // 4)
    actual_fade_out = min(fade_samples, len(voiced) // 4)
    if actual_fade_in > 0:
        voiced[:actual_fade_in] *= make_raised_cosine_fade(actual_fade_in)
    if actual_fade_out > 0:
        voiced[-actual_fade_out:] *= make_raised_cosine_fade(actual_fade_out)[::-1]

    # Step 5: Peak normalize to -1dB
    peak = np.max(np.abs(voiced))
    if peak > 0:
        target_peak = 10 ** (PEAK_NORMALIZE_DB / 20)
        voiced = voiced * (target_peak / peak)

    # Step 6: R6 Envelope
    pre_silence = np.zeros(preattack_samples, dtype=np.float64)
    tail_silence = np.zeros(tail_samples, dtype=np.float64)
    final = np.concatenate([pre_silence, voiced, tail_silence])
    final = np.clip(final, -1.0, 1.0)

    return final


# ============================================================
# TEXT PROCESSING
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
    norm_gt = normalize_text(gt)
    norm_pred = normalize_text(pred)
    if len(norm_gt) < 2 or len(norm_pred) < 2:
        return False
    first_chars = norm_gt[:min(4, len(norm_gt))]
    return not norm_pred.startswith(first_chars[:2])


# ============================================================
# WHISPER TRANSCRIPTION
# ============================================================

def transcribe_audio(model, samples, sr, fp16=False):
    """Transcribe audio samples with Whisper."""
    audio = np.asarray(samples, dtype=np.float32)

    # Whisper expects 16kHz
    if sr != 16000:
        duration = len(audio) / sr
        target_len = int(duration * 16000)
        if target_len < 1:
            return ""
        indices = np.linspace(0, len(audio) - 1, target_len).astype(np.float32)
        audio = np.interp(indices, np.arange(len(audio), dtype=np.float32), audio).astype(np.float32)

    result = model.transcribe(audio, language=LANGUAGE, fp16=fp16, without_timestamps=True)
    return result.get("text", "").strip()


def transcribe_stripped(model, samples, sr, fp16=False):
    """Transcribe after stripping the R6 envelope."""
    lead_strip = int(sr * 350 / 1000)
    tail_strip = int(sr * 700 / 1000)

    if lead_strip + tail_strip >= len(samples):
        return transcribe_audio(model, samples, sr, fp16)

    stripped = samples[lead_strip:]
    if tail_strip > 0:
        stripped = stripped[:-tail_strip]

    return transcribe_audio(model, stripped, sr, fp16)


# ============================================================
# MAIN EXPERIMENT
# ============================================================

def main():
    # Load alignment data
    print("[DIAG] Loading alignment data...", flush=True)
    with open(ALIGNMENT_DATA, 'r', encoding='utf-8') as f:
        ab_data = json.load(f)

    items = ab_data['per_item']
    print(f"[DIAG] Loaded {len(items)} aligned segments", flush=True)

    # Load raw audio
    print(f"[DIAG] Loading raw audio: {RAW_AUDIO_PATH}", flush=True)
    raw_samples, raw_sr = sf.read(RAW_AUDIO_PATH, dtype='float64')
    if raw_samples.ndim > 1:
        raw_samples = raw_samples[:, 0]
    print(f"[DIAG] Raw audio: {len(raw_samples)} samples, {raw_sr}Hz, {len(raw_samples)/raw_sr:.1f}s", flush=True)

    # Setup CUDA
    device = "cpu"
    use_fp16 = False
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            gc.collect()
            _t = torch.zeros(1, device="cuda")
            del _t
            torch.cuda.empty_cache()
            device = "cuda"
            use_fp16 = True
            print("[DIAG] CUDA health check passed", flush=True)
        except Exception as e:
            print(f"[DIAG] CUDA failed ({e}), using CPU", flush=True)

    # Load model (CPU first, then move)
    print(f"[DIAG] Loading Whisper {MODEL_SIZE} model (CPU first, then {device})...", flush=True)
    model = whisper.load_model(MODEL_SIZE, device="cpu")
    if device == "cuda":
        model = model.cuda()
        torch.cuda.empty_cache()
    print(f"[DIAG] Model loaded on {device}, fp16={use_fp16}", flush=True)

    # Padding in samples
    pad_samples = int(raw_sr * AUDIO_PAD_MS / 1000)

    results = []
    a_wins = 0
    b_wins = 0
    ties = 0
    a_first_drops = 0
    b_first_drops = 0

    for item in tqdm(items, desc="Threshold A/B"):
        gt = item['ground_truth']
        time_range = item['time_range']  # e.g., "0.00-4.84s"

        # Parse time range
        match = re.match(r'([\d.]+)-([\d.]+)s', time_range)
        if not match:
            print(f"  SKIP: bad time_range {time_range}")
            continue

        start_sec = float(match.group(1))
        end_sec = float(match.group(2))
        start_sample = int(start_sec * raw_sr)
        end_sample = int(end_sec * raw_sr)

        # Extract with padding (same as pipeline)
        extract_start = max(0, start_sample - pad_samples)
        extract_end = min(len(raw_samples), end_sample + pad_samples)
        segment_raw = raw_samples[extract_start:extract_end]

        if len(segment_raw) < 480:
            print(f"  SKIP: too short ({len(segment_raw)} samples)")
            continue

        try:
            # Condition A: -40dB + OFFSET_SAFETY=20ms (old)
            processed_a = post_process_segment(segment_raw.copy(), raw_sr,
                                                THRESHOLD_A_DB, OFFSET_SAFETY_A_MS)

            # Condition B: -65dB + OFFSET_SAFETY=100ms (new)
            processed_b = post_process_segment(segment_raw.copy(), raw_sr,
                                                THRESHOLD_B_DB, OFFSET_SAFETY_B_MS)

            if processed_a is None or processed_b is None:
                print(f"  SKIP: empty processed for line {item['line_no']}")
                continue

            # Transcribe both (with envelope stripping for fair eval)
            text_a = transcribe_stripped(model, processed_a, raw_sr, fp16=use_fp16)
            text_b = transcribe_stripped(model, processed_b, raw_sr, fp16=use_fp16)

            sim_a = compute_similarity(gt, text_a)
            sim_b = compute_similarity(gt, text_b)
            drop_a = detect_first_word_drop(gt, text_a)
            drop_b = detect_first_word_drop(gt, text_b)

        except Exception as e:
            print(f"  ERROR line {item['line_no']}: {e}", flush=True)
            continue

        delta = sim_b - sim_a
        if delta > 0.001:
            b_wins += 1
            winner = "NEW_65dB"
        elif delta < -0.001:
            a_wins += 1
            winner = "OLD_40dB"
        else:
            ties += 1
            winner = "TIE"

        if drop_a:
            a_first_drops += 1
        if drop_b:
            b_first_drops += 1

        # Also measure onset/offset differences
        onset_a, offset_a = find_voice_onset_offset(segment_raw, raw_sr, THRESHOLD_A_DB)
        onset_b, offset_b = find_voice_onset_offset(segment_raw, raw_sr, THRESHOLD_B_DB)

        result = {
            "line_no": item['line_no'],
            "ground_truth": gt,
            "text_40dB": text_a,
            "text_65dB": text_b,
            "sim_40dB": round(sim_a, 4),
            "sim_65dB": round(sim_b, 4),
            "delta": round(delta, 4),
            "winner": winner,
            "first_drop_40dB": drop_a,
            "first_drop_65dB": drop_b,
            "onset_40dB_ms": round(onset_a / raw_sr * 1000, 1),
            "onset_65dB_ms": round(onset_b / raw_sr * 1000, 1),
            "offset_40dB_ms": round(offset_a / raw_sr * 1000, 1),
            "offset_65dB_ms": round(offset_b / raw_sr * 1000, 1),
            "duration_40dB_ms": round((offset_a - onset_a) / raw_sr * 1000, 1),
            "duration_65dB_ms": round((offset_b - onset_b) / raw_sr * 1000, 1),
            "align_score": item.get('align_score', None),
            "time_range": time_range,
        }
        results.append(result)

    # --- Aggregate ---
    n = len(results)
    if n == 0:
        print("No results!")
        del model
        gc.collect()
        return

    mean_sim_a = np.mean([r['sim_40dB'] for r in results])
    mean_sim_b = np.mean([r['sim_65dB'] for r in results])
    r1_a = sum(1 for r in results if r['sim_40dB'] >= 0.95) / n * 100
    r1_b = sum(1 for r in results if r['sim_65dB'] >= 0.95) / n * 100

    # Onset/offset analysis
    onset_diffs = [r['onset_65dB_ms'] - r['onset_40dB_ms'] for r in results]
    offset_diffs = [r['offset_65dB_ms'] - r['offset_40dB_ms'] for r in results]
    dur_diffs = [r['duration_65dB_ms'] - r['duration_40dB_ms'] for r in results]

    summary = {
        "experiment": "Silence Threshold A/B: -40dB vs -65dB",
        "raw_file": os.path.basename(RAW_AUDIO_PATH),
        "sample_size": n,
        "conditions": {
            "A_old": {"threshold_db": THRESHOLD_A_DB, "offset_safety_ms": OFFSET_SAFETY_A_MS},
            "B_new": {"threshold_db": THRESHOLD_B_DB, "offset_safety_ms": OFFSET_SAFETY_B_MS},
        },
        "results": {
            "mean_sim_40dB": round(float(mean_sim_a), 4),
            "mean_sim_65dB": round(float(mean_sim_b), 4),
            "delta_mean": round(float(mean_sim_b - mean_sim_a), 4),
            "r1_pass_40dB": round(float(r1_a), 2),
            "r1_pass_65dB": round(float(r1_b), 2),
            "old_40dB_wins": a_wins,
            "new_65dB_wins": b_wins,
            "ties": ties,
            "first_drops_40dB": a_first_drops,
            "first_drops_65dB": b_first_drops,
        },
        "onset_offset_analysis": {
            "mean_onset_shift_ms": round(float(np.mean(onset_diffs)), 1),
            "mean_offset_shift_ms": round(float(np.mean(offset_diffs)), 1),
            "mean_duration_diff_ms": round(float(np.mean(dur_diffs)), 1),
            "onset_shifted_count": sum(1 for d in onset_diffs if abs(d) > 0.5),
            "offset_shifted_count": sum(1 for d in offset_diffs if abs(d) > 0.5),
        },
        "per_item": results
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("EXPERIMENT: Silence Threshold -40dB vs -65dB")
    print("=" * 70)
    print(f"Raw audio: {os.path.basename(RAW_AUDIO_PATH)}")
    print(f"Sample size: {n}")
    print(f"\n{'Metric':<35} {'OLD -40dB':>12} {'NEW -65dB':>12}")
    print("-" * 60)
    print(f"{'Mean similarity':<35} {mean_sim_a:>12.4f} {mean_sim_b:>12.4f}")
    print(f"{'R1 pass rate (sim >= 0.95)':<35} {r1_a:>11.1f}% {r1_b:>11.1f}%")
    print(f"{'First-word drops':<35} {a_first_drops:>12d} {b_first_drops:>12d}")
    print(f"\nPer-item wins: OLD_40dB={a_wins}  NEW_65dB={b_wins}  TIE={ties}")
    print(f"Mean delta (new - old): {mean_sim_b - mean_sim_a:+.4f}")
    print(f"\n--- Onset/Offset Detection Shift ---")
    print(f"Mean onset shift:  {np.mean(onset_diffs):+.1f}ms (negative = earlier detection)")
    print(f"Mean offset shift: {np.mean(offset_diffs):+.1f}ms (positive = later detection)")
    print(f"Mean duration diff: {np.mean(dur_diffs):+.1f}ms")
    print(f"Files with onset change:  {sum(1 for d in onset_diffs if abs(d) > 0.5)}/{n}")
    print(f"Files with offset change: {sum(1 for d in offset_diffs if abs(d) > 0.5)}/{n}")
    print(f"\nResults saved to: {OUTPUT_PATH}")

    # Clean up
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
