# -*- coding: utf-8 -*-
"""
A/B Experiment v2: R6 Envelope Effect on RAW Audio — [FROZEN EXPERIMENT]
====================================================
WARNING: Parameters (AUDIO_PAD_MS=100, MATCH_THRESHOLD=0.50) are frozen from
the original experiment and may lag align_and_split.py's current values.
Do NOT use this script as a current-quality check — it's for reproducing
the historical A/B only.
====================================================
Extracts raw segments directly from the source recording, then compares
Whisper transcription accuracy on:
  - Condition A (RAW):  raw extracted segment, no processing
  - Condition B (ENV):  same raw segment + R6 silence envelope (400ms + 730ms)

This isolates the envelope effect using genuinely raw audio.

Usage:
  python src/experiment_raw_envelope.py
"""

import os
import sys
import json
import re
import unicodedata
import warnings
import gc

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

import torch

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

print("[DIAG] Python started, importing modules...", flush=True)

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
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
LOG_DIR = os.path.join(BASE_DIR, "logs")
METADATA_PATH = os.path.join(BASE_DIR, "datasets", "script.txt")
os.makedirs(LOG_DIR, exist_ok=True)

# Raw audio file to use
RAW_AUDIO_PATH = os.path.join(
    BASE_DIR, "rawdata", "audio", "Script_1_221-300.wav")
SCRIPT_NO = 1
LINE_START = 221
LINE_END = 300

# R6 envelope parameters (from align_and_split.py)
PREATTACK_SILENCE_MS = 400
TAIL_SILENCE_MS = 730

# Segment extraction padding
AUDIO_PAD_MS = 100

# Whisper config
MODEL_SIZE = "medium"
LANGUAGE = "ko"

# Alignment
MATCH_THRESHOLD = 0.50
SEG_SEARCH_WINDOW = 25
MAX_MERGE = 5


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
# AUDIO HELPERS
# ============================================================

def resample_for_whisper(audio, sr):
    """Resample to 16kHz float32 for Whisper."""
    audio = np.asarray(audio, dtype=np.float32)
    if sr == 16000:
        return audio
    duration = len(audio) / sr
    target_len = int(duration * 16000)
    indices = np.linspace(0, len(audio) - 1, target_len).astype(np.float32)
    return np.interp(
        indices,
        np.arange(len(audio), dtype=np.float32),
        audio
    ).astype(np.float32)


def add_r6_envelope(audio, sr):
    """Add R6 silence envelope: 400ms pre-attack + 730ms tail."""
    pre_samples = int(sr * PREATTACK_SILENCE_MS / 1000)
    tail_samples = int(sr * TAIL_SILENCE_MS / 1000)
    pre_silence = np.zeros(pre_samples, dtype=audio.dtype)
    tail_silence = np.zeros(tail_samples, dtype=audio.dtype)
    return np.concatenate([pre_silence, audio, tail_silence])


# ============================================================
# ALIGNMENT (simplified from align_and_split.py)
# ============================================================

def align_segments_to_lines(segments, script_lines):
    """Forward-only alignment of Whisper segments to script lines.

    Returns list of dicts: {line_no, gt_text, start_sec, end_sec, whisper_text, align_score}
    """
    matches = []
    current_line_idx = 0
    seg_idx = 0

    while seg_idx < len(segments) and current_line_idx < len(script_lines):
        best_score = -1
        best_line_idx = -1
        best_merge = 1
        best_text = ""

        # Try merging 1..MAX_MERGE consecutive segments
        for merge_count in range(1, MAX_MERGE + 1):
            if seg_idx + merge_count > len(segments):
                break
            merged_text = " ".join(
                segments[seg_idx + k]['text'].strip()
                for k in range(merge_count)
            )

            # Search forward in script lines (within window)
            search_end = min(current_line_idx + SEG_SEARCH_WINDOW,
                             len(script_lines))
            for line_idx in range(current_line_idx, search_end):
                line_no, gt_text = script_lines[line_idx]
                score = compute_similarity(gt_text, merged_text)
                if score > best_score:
                    best_score = score
                    best_line_idx = line_idx
                    best_merge = merge_count
                    best_text = merged_text

        if best_score >= MATCH_THRESHOLD and best_line_idx >= 0:
            line_no, gt_text = script_lines[best_line_idx]
            merged_segs = segments[seg_idx:seg_idx + best_merge]
            start_sec = merged_segs[0]['start']
            end_sec = merged_segs[-1]['end']

            matches.append({
                'line_no': line_no,
                'gt_text': gt_text,
                'start_sec': start_sec,
                'end_sec': end_sec,
                'whisper_text': best_text,
                'align_score': round(best_score, 4),
                'merge_count': best_merge
            })

            current_line_idx = best_line_idx + 1
            seg_idx += best_merge
        else:
            seg_idx += 1

    return matches


# ============================================================
# MAIN EXPERIMENT
# ============================================================

def run_experiment():
    output_path = os.path.join(LOG_DIR, "envelope_raw_ab.json")

    # --- Load ground truth lines ---
    print("[DIAG] Loading ground truth lines...", flush=True)
    script_lines = []  # list of (line_no, text)
    with open(METADATA_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '|' not in line:
                continue
            fname, text = line.split('|', 1)
            # Parse Script_1_NNNN.wav
            if not fname.startswith(f"Script_{SCRIPT_NO}_"):
                continue
            num_str = fname.replace(f"Script_{SCRIPT_NO}_", '').replace('.wav', '')
            try:
                line_no = int(num_str)
            except ValueError:
                continue
            if LINE_START <= line_no <= LINE_END:
                script_lines.append((line_no, text.strip()))

    script_lines.sort(key=lambda x: x[0])
    print(f"[DIAG] Loaded {len(script_lines)} ground truth lines "
          f"({LINE_START}-{LINE_END})", flush=True)

    if not script_lines:
        print("ERROR: No ground truth lines found!")
        return

    # --- Robust CUDA setup ---
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
            print(f"[DIAG] CUDA health check passed", flush=True)
        except Exception as e:
            print(f"[DIAG] CUDA health check FAILED ({e}), using CPU", flush=True)
    else:
        print(f"[DIAG] CUDA not available, using CPU", flush=True)

    # Load model on CPU first, then move to device
    print(f"[DIAG] Loading Whisper {MODEL_SIZE} model "
          f"(CPU first, then {device})...", flush=True)
    model = whisper.load_model(MODEL_SIZE, device="cpu")
    if device == "cuda":
        model = model.cuda()
        torch.cuda.empty_cache()
    print(f"[DIAG] Model loaded on {device}, fp16={use_fp16}", flush=True)

    # --- Step 1: Transcribe full raw file for alignment ---
    print(f"\n[STEP 1] Transcribing raw file for alignment...", flush=True)
    print(f"  File: {RAW_AUDIO_PATH}", flush=True)

    raw_audio, sr = sf.read(RAW_AUDIO_PATH, dtype='float32')
    print(f"  SR={sr}, Duration={len(raw_audio)/sr:.1f}s, "
          f"Samples={len(raw_audio)}", flush=True)

    # Resample full file for Whisper alignment pass
    audio_16k = resample_for_whisper(raw_audio, sr)

    result = model.transcribe(
        audio_16k,
        language=LANGUAGE,
        fp16=use_fp16,
        word_timestamps=True  # need word-level for precise boundaries
    )
    segments = result.get('segments', [])
    print(f"  Got {len(segments)} Whisper segments", flush=True)

    if not segments:
        print("ERROR: No segments from Whisper!")
        del model
        gc.collect()
        return

    # --- Step 2: Align segments to script lines ---
    print(f"\n[STEP 2] Aligning segments to script lines...", flush=True)
    matches = align_segments_to_lines(segments, script_lines)
    print(f"  Matched {len(matches)}/{len(script_lines)} lines", flush=True)

    if not matches:
        print("ERROR: No matches found!")
        del model
        gc.collect()
        return

    # --- Step 3: A/B comparison ---
    print(f"\n[STEP 3] Running A/B experiment on {len(matches)} matched "
          f"segments...", flush=True)

    results = []
    raw_wins = 0
    env_wins = 0
    ties = 0
    raw_first_drops = 0
    env_first_drops = 0

    for match in tqdm(matches, desc="A/B Raw vs Envelope"):
        gt = match['gt_text']
        start_sec = match['start_sec']
        end_sec = match['end_sec']

        # Extract raw segment with padding
        pad_sec = AUDIO_PAD_MS / 1000.0
        extract_start = max(0, start_sec - pad_sec)
        extract_end = min(len(raw_audio) / sr, end_sec + pad_sec)

        start_sample = int(extract_start * sr)
        end_sample = int(extract_end * sr)
        raw_segment = raw_audio[start_sample:end_sample]

        if len(raw_segment) == 0:
            print(f"  SKIP line {match['line_no']}: empty segment")
            continue

        try:
            # --- Condition A: RAW segment (no processing) ---
            audio_a = resample_for_whisper(raw_segment, sr)
            result_a = model.transcribe(
                audio_a, language=LANGUAGE, fp16=use_fp16,
                without_timestamps=True
            )
            text_raw = result_a.get("text", "").strip()
            sim_raw = compute_similarity(gt, text_raw)
            drop_raw = detect_first_word_drop(gt, text_raw)

            # --- Condition B: RAW segment + R6 envelope ---
            enveloped = add_r6_envelope(raw_segment, sr)
            audio_b = resample_for_whisper(enveloped, sr)
            result_b = model.transcribe(
                audio_b, language=LANGUAGE, fp16=use_fp16,
                without_timestamps=True
            )
            text_env = result_b.get("text", "").strip()
            sim_env = compute_similarity(gt, text_env)
            drop_env = detect_first_word_drop(gt, text_env)

        except Exception as e:
            print(f"  ERROR line {match['line_no']}: {e}", flush=True)
            continue

        # --- Compare ---
        delta = sim_raw - sim_env  # positive = raw better
        if delta > 0.001:
            raw_wins += 1
            winner = "RAW"
        elif delta < -0.001:
            env_wins += 1
            winner = "ENV"
        else:
            ties += 1
            winner = "TIE"

        if drop_raw:
            raw_first_drops += 1
        if drop_env:
            env_first_drops += 1

        results.append({
            "line_no": match['line_no'],
            "ground_truth": gt,
            "text_raw": text_raw,
            "text_enveloped": text_env,
            "sim_raw": round(sim_raw, 4),
            "sim_enveloped": round(sim_env, 4),
            "delta": round(delta, 4),
            "winner": winner,
            "first_drop_raw": drop_raw,
            "first_drop_enveloped": drop_env,
            "align_score": match['align_score'],
            "time_range": f"{start_sec:.2f}-{end_sec:.2f}s"
        })

    # --- Aggregate ---
    n = len(results)
    if n == 0:
        print("No results!")
        del model
        gc.collect()
        return

    mean_sim_raw = np.mean([r['sim_raw'] for r in results])
    mean_sim_env = np.mean([r['sim_enveloped'] for r in results])
    r1_raw = sum(1 for r in results if r['sim_raw'] >= 0.95) / n * 100
    r1_env = sum(1 for r in results if r['sim_enveloped'] >= 0.95) / n * 100

    summary = {
        "experiment": "R6 Envelope Effect on RAW Audio — A/B Test v2",
        "raw_file": os.path.basename(RAW_AUDIO_PATH),
        "script_range": f"Script_{SCRIPT_NO} lines {LINE_START}-{LINE_END}",
        "sample_size": n,
        "envelope_params": {
            "preattack_silence_ms": PREATTACK_SILENCE_MS,
            "tail_silence_ms": TAIL_SILENCE_MS
        },
        "results": {
            "mean_similarity_raw": round(float(mean_sim_raw), 4),
            "mean_similarity_enveloped": round(float(mean_sim_env), 4),
            "delta_mean": round(float(mean_sim_raw - mean_sim_env), 4),
            "r1_pass_rate_raw": round(float(r1_raw), 2),
            "r1_pass_rate_enveloped": round(float(r1_env), 2),
            "raw_wins": raw_wins,
            "env_wins": env_wins,
            "ties": ties,
            "first_word_drops_raw": raw_first_drops,
            "first_word_drops_enveloped": env_first_drops
        },
        "per_item": results
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # --- Print Summary ---
    print("\n" + "=" * 60)
    print("EXPERIMENT v2: R6 Envelope Effect on RAW Audio")
    print("=" * 60)
    print(f"Raw file: {os.path.basename(RAW_AUDIO_PATH)}")
    print(f"Lines: {LINE_START}-{LINE_END} | Matched: {n}")
    print(f"\n{'Metric':<40} {'RAW':>12} {'+ ENVELOPE':>14}")
    print("-" * 66)
    print(f"{'Mean similarity':<40} {mean_sim_raw:>12.4f} {mean_sim_env:>14.4f}")
    print(f"{'R1 pass rate (sim >= 0.95)':<40} {r1_raw:>11.1f}% {r1_env:>13.1f}%")
    print(f"{'First-word drops':<40} {raw_first_drops:>12d} {env_first_drops:>14d}")
    print(f"\nPer-item wins: RAW={raw_wins}  ENVELOPE={env_wins}  TIE={ties}")
    print(f"Mean delta (raw - envelope): {mean_sim_raw - mean_sim_env:+.4f}")
    print(f"\nResults saved to: {output_path}")

    # Clean up
    del model
    gc.collect()


if __name__ == "__main__":
    run_experiment()
