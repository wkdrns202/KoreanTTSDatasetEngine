# -*- coding: utf-8 -*-
"""
R6 Envelope Ablation Study — [FROZEN EXPERIMENT, 2026-02]
============================
WARNING: Parameters in this script (OFFSET_SAFETY_MS=80, AUDIO_PAD_MS=100)
are frozen at the values used during the original ablation. Current pipeline
uses OFFSET_SAFETY_MS=120, AUDIO_PAD_MS=50 — see align_and_split.py.
Do NOT re-run this script and treat the output as current-quality evidence.
It exists for reproducing the ablation report, not for production validation.
============================
Quantifies the effect of R6 audio envelope on TTS dataset quality.

Compares 4 envelope conditions on the same extracted segments:
  A. NO_ENV    — tight trim only (0ms/0ms silence)
  B. MINIMAL   — 50ms pre-attack + 100ms tail
  C. MODERATE  — 200ms pre-attack + 400ms tail
  D. FULL_R6   — 400ms pre-attack + 730ms tail (current pipeline)

Measures:
  - Whisper transcription accuracy (CER similarity)
  - First-word / last-word drops
  - R1 pass rate (sim >= 0.95)
  - Audio duration statistics
  - Boundary artifact analysis

Uses pre-aligned time ranges from envelope_raw_ab.json (80 segments).
Also saves WAV files for manual listening comparison.
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
OUTPUT_PATH = os.path.join(LOG_DIR, "r6_ablation_results.json")
SAMPLE_WAV_DIR = os.path.join(BASE_DIR, "logs", "r6_ablation_samples")

MODEL_SIZE = "medium"
LANGUAGE = "ko"
SR_TARGET = 48000

# Shared DSP params
FADE_MS = 10
PEAK_NORMALIZE_DB = -1.0
ONSET_SAFETY_MS = 30
OFFSET_SAFETY_MS = 80
SILENCE_THRESHOLD_DB = -40
RMS_WINDOW_MS = 10
AUDIO_PAD_MS = 100

# 4 envelope conditions
CONDITIONS = {
    "A_NO_ENV": {"preattack_ms": 0, "tail_ms": 0, "label": "No envelope (tight trim)"},
    "B_MINIMAL": {"preattack_ms": 50, "tail_ms": 100, "label": "Minimal (50/100ms)"},
    "C_MODERATE": {"preattack_ms": 200, "tail_ms": 400, "label": "Moderate (200/400ms)"},
    "D_FULL_R6": {"preattack_ms": 400, "tail_ms": 730, "label": "Full R6 (400/730ms)"},
}

# How many sample WAVs to save for listening
SAVE_SAMPLE_COUNT = 10


# ============================================================
# DSP FUNCTIONS
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


def find_voice_onset_offset(samples, sr=48000, threshold_db=SILENCE_THRESHOLD_DB):
    window_size = int(sr * RMS_WINDOW_MS / 1000)
    rms_db = compute_rms_windowed(samples, sr, RMS_WINDOW_MS)
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


def post_process_segment(samples, sr, preattack_ms, tail_ms):
    """Apply full post-processing with given envelope parameters."""
    preattack_samples = int(sr * preattack_ms / 1000)
    tail_samples = int(sr * tail_ms / 1000)
    fade_samples = int(sr * FADE_MS / 1000)
    onset_safety = int(sr * ONSET_SAFETY_MS / 1000)
    offset_safety = int(sr * OFFSET_SAFETY_MS / 1000)

    samples = np.asarray(samples, dtype=np.float64)

    # Zero-crossing snap
    if len(samples) > 960:
        new_start = find_nearest_zero_crossing(samples, 0, sr)
        new_end = find_nearest_zero_crossing(samples, len(samples) - 1, sr)
        if new_end > new_start:
            samples = samples[new_start:new_end + 1]

    # Voice onset/offset + trim
    onset, offset = find_voice_onset_offset(samples, sr)
    onset = max(0, onset - onset_safety)
    offset = min(len(samples), offset + offset_safety)

    if onset >= offset:
        voiced = samples.copy()
    else:
        voiced = samples[onset:offset].copy()

    if len(voiced) == 0:
        return None

    # Fade
    actual_fade_in = min(fade_samples, len(voiced) // 4)
    actual_fade_out = min(fade_samples, len(voiced) // 4)
    if actual_fade_in > 0:
        voiced[:actual_fade_in] *= make_raised_cosine_fade(actual_fade_in)
    if actual_fade_out > 0:
        voiced[-actual_fade_out:] *= make_raised_cosine_fade(actual_fade_out)[::-1]

    # Peak normalize
    peak = np.max(np.abs(voiced))
    if peak > 0:
        target_peak = 10 ** (PEAK_NORMALIZE_DB / 20)
        voiced = voiced * (target_peak / peak)

    # Envelope
    if preattack_ms > 0 or tail_ms > 0:
        parts = []
        if preattack_samples > 0:
            parts.append(np.zeros(preattack_samples, dtype=np.float64))
        parts.append(voiced)
        if tail_samples > 0:
            parts.append(np.zeros(tail_samples, dtype=np.float64))
        final = np.concatenate(parts)
    else:
        final = voiced

    return np.clip(final, -1.0, 1.0)


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
    return not norm_pred.startswith(norm_gt[:2])


def detect_last_word_drop(gt, pred):
    """Check if the last few chars of gt are missing from pred."""
    norm_gt = normalize_text(gt)
    norm_pred = normalize_text(pred)
    if len(norm_gt) < 2 or len(norm_pred) < 2:
        return False
    return not norm_pred.endswith(norm_gt[-2:])


# ============================================================
# WHISPER
# ============================================================

def transcribe_audio(model, samples, sr, fp16=False):
    audio = np.asarray(samples, dtype=np.float32)
    if sr != 16000:
        duration = len(audio) / sr
        target_len = int(duration * 16000)
        if target_len < 1:
            return ""
        indices = np.linspace(0, len(audio) - 1, target_len).astype(np.float32)
        audio = np.interp(indices, np.arange(len(audio), dtype=np.float32), audio).astype(np.float32)
    result = model.transcribe(audio, language=LANGUAGE, fp16=fp16, without_timestamps=True)
    return result.get("text", "").strip()


# ============================================================
# MAIN
# ============================================================

def main():
    print("[DIAG] Loading alignment data...", flush=True)
    with open(ALIGNMENT_DATA, 'r', encoding='utf-8') as f:
        ab_data = json.load(f)
    items = ab_data['per_item']
    print(f"[DIAG] {len(items)} aligned segments", flush=True)

    print(f"[DIAG] Loading raw audio...", flush=True)
    raw_samples, raw_sr = sf.read(RAW_AUDIO_PATH, dtype='float64')
    if raw_samples.ndim > 1:
        raw_samples = raw_samples[:, 0]
    print(f"[DIAG] Raw: {len(raw_samples)} samples, {raw_sr}Hz, {len(raw_samples)/raw_sr:.1f}s", flush=True)

    # Create sample dir
    os.makedirs(SAMPLE_WAV_DIR, exist_ok=True)

    # CUDA setup
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
            print("[DIAG] CUDA OK", flush=True)
        except Exception as e:
            print(f"[DIAG] CUDA failed: {e}", flush=True)

    print(f"[DIAG] Loading Whisper {MODEL_SIZE} (CPU → {device})...", flush=True)
    model = whisper.load_model(MODEL_SIZE, device="cpu")
    if device == "cuda":
        model = model.cuda()
        torch.cuda.empty_cache()
    print(f"[DIAG] Model ready, fp16={use_fp16}", flush=True)

    pad_samples = int(raw_sr * AUDIO_PAD_MS / 1000)

    # Per-condition accumulators
    cond_results = {k: [] for k in CONDITIONS}
    per_item_results = []
    saved_count = 0

    for item in tqdm(items, desc="R6 Ablation"):
        gt = item['ground_truth']
        time_range = item['time_range']
        line_no = item['line_no']

        match = re.match(r'([\d.]+)-([\d.]+)s', time_range)
        if not match:
            continue

        start_sec = float(match.group(1))
        end_sec = float(match.group(2))
        start_sample = int(start_sec * raw_sr)
        end_sample = int(end_sec * raw_sr)

        extract_start = max(0, start_sample - pad_samples)
        extract_end = min(len(raw_samples), end_sample + pad_samples)
        segment_raw = raw_samples[extract_start:extract_end]

        if len(segment_raw) < 480:
            continue

        item_result = {
            "line_no": line_no,
            "ground_truth": gt,
            "time_range": time_range,
        }

        all_ok = True
        for cond_key, cond_params in CONDITIONS.items():
            try:
                processed = post_process_segment(
                    segment_raw.copy(), raw_sr,
                    cond_params['preattack_ms'], cond_params['tail_ms']
                )
                if processed is None:
                    all_ok = False
                    break

                # Transcribe the FULL audio (with envelope) — this tests how
                # Whisper handles the silence padding, which is the whole point
                text = transcribe_audio(model, processed, raw_sr, fp16=use_fp16)
                sim = compute_similarity(gt, text)
                first_drop = detect_first_word_drop(gt, text)
                last_drop = detect_last_word_drop(gt, text)

                duration_ms = len(processed) / raw_sr * 1000

                item_result[f"{cond_key}_text"] = text
                item_result[f"{cond_key}_sim"] = round(sim, 4)
                item_result[f"{cond_key}_first_drop"] = first_drop
                item_result[f"{cond_key}_last_drop"] = last_drop
                item_result[f"{cond_key}_duration_ms"] = round(duration_ms, 1)

                cond_results[cond_key].append({
                    "sim": sim,
                    "first_drop": first_drop,
                    "last_drop": last_drop,
                    "duration_ms": duration_ms,
                })

                # Save sample WAVs for manual listening
                if saved_count < SAVE_SAMPLE_COUNT:
                    wav_path = os.path.join(SAMPLE_WAV_DIR, f"line{line_no}_{cond_key}.wav")
                    sf.write(wav_path, processed.astype(np.float32), raw_sr, subtype='PCM_24')

            except Exception as e:
                print(f"  ERROR line {line_no} {cond_key}: {e}", flush=True)
                all_ok = False
                break

        if all_ok:
            per_item_results.append(item_result)
            if saved_count < SAVE_SAMPLE_COUNT:
                saved_count += 1

    # ============================================================
    # AGGREGATE
    # ============================================================
    n = len(per_item_results)
    if n == 0:
        print("No results!")
        del model; gc.collect()
        return

    summary_table = {}
    for cond_key, cond_params in CONDITIONS.items():
        data = cond_results[cond_key]
        if not data:
            continue
        sims = [d['sim'] for d in data]
        summary_table[cond_key] = {
            "label": cond_params['label'],
            "preattack_ms": cond_params['preattack_ms'],
            "tail_ms": cond_params['tail_ms'],
            "mean_sim": round(float(np.mean(sims)), 4),
            "median_sim": round(float(np.median(sims)), 4),
            "r1_pass_rate": round(sum(1 for s in sims if s >= 0.95) / len(sims) * 100, 2),
            "first_word_drops": sum(1 for d in data if d['first_drop']),
            "last_word_drops": sum(1 for d in data if d['last_drop']),
            "mean_duration_ms": round(float(np.mean([d['duration_ms'] for d in data])), 1),
        }

    output = {
        "experiment": "R6 Audio Envelope Ablation Study",
        "description": "Effect of R6 silence envelope on Whisper transcription quality",
        "note": "Whisper transcribes FULL audio including envelope — tests how silence padding affects ASR accuracy",
        "raw_file": os.path.basename(RAW_AUDIO_PATH),
        "sample_size": n,
        "shared_params": {
            "silence_threshold_db": SILENCE_THRESHOLD_DB,
            "onset_safety_ms": ONSET_SAFETY_MS,
            "offset_safety_ms": OFFSET_SAFETY_MS,
            "fade_ms": FADE_MS,
            "normalize_db": PEAK_NORMALIZE_DB,
        },
        "conditions": summary_table,
        "sample_wavs_dir": SAMPLE_WAV_DIR,
        "sample_wavs_count": saved_count,
        "per_item": per_item_results,
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ============================================================
    # PRINT SUMMARY
    # ============================================================
    print("\n" + "=" * 85)
    print("R6 AUDIO ENVELOPE ABLATION STUDY")
    print("=" * 85)
    print(f"Sample size: {n} segments from {os.path.basename(RAW_AUDIO_PATH)}")
    print(f"NOTE: Whisper transcribes FULL audio (with envelope) — not stripped\n")

    header = f"{'Condition':<28} {'Pre/Tail':>10} {'Mean Sim':>10} {'R1 Pass%':>10} {'1st Drop':>9} {'Last Drop':>10} {'Duration':>10}"
    print(header)
    print("-" * 85)
    for cond_key in CONDITIONS:
        s = summary_table.get(cond_key, {})
        if not s:
            continue
        env_str = f"{s['preattack_ms']}/{s['tail_ms']}ms"
        print(f"{s['label']:<28} {env_str:>10} {s['mean_sim']:>10.4f} {s['r1_pass_rate']:>9.1f}% {s['first_word_drops']:>9d} {s['last_word_drops']:>10d} {s['mean_duration_ms']:>9.0f}ms")

    # Pairwise deltas vs NO_ENV
    print(f"\n--- Delta vs No Envelope (Condition A) ---")
    base = summary_table.get("A_NO_ENV", {})
    if base:
        for cond_key in ["B_MINIMAL", "C_MODERATE", "D_FULL_R6"]:
            s = summary_table.get(cond_key, {})
            if not s:
                continue
            d_sim = s['mean_sim'] - base['mean_sim']
            d_r1 = s['r1_pass_rate'] - base['r1_pass_rate']
            d_fd = s['first_word_drops'] - base['first_word_drops']
            print(f"  {s['label']:<25} sim: {d_sim:+.4f}  R1: {d_r1:+.1f}pp  1st-drops: {d_fd:+d}")

    print(f"\nSample WAVs saved: {saved_count} segments × 4 conditions = {saved_count*4} files")
    print(f"  → {SAMPLE_WAV_DIR}")
    print(f"\nFull results: {OUTPUT_PATH}")

    del model; gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
