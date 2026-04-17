# -*- coding: utf-8 -*-
"""
TTS Dataset: Selective Data Composer (Stage 4.5)
=================================================
SAM-inspired confidence-based dataset admission system.
Multi-dimensional scoring with statistical testing for quality gate.

Scoring Dimensions:
  D1. S_unprompted  — Unbiased Whisper similarity (no GT prompting)
  D2. S_gap         — Prompted vs Unprompted gap (truncation detector)
  D3. S_snr         — Signal-to-noise ratio of speech region
  D4. S_duration    — AST-based duration anomaly (z-test, p<0.05)
  D5. S_stability   — Transcription stability across decode temps (on-demand)
  D6. S_confidence  — Whisper self-reported confidence (avg_logprob)
  D7. S_boundary    — Continuous boundary/envelope quality score
  D8. S_continuity  — Bimodal distribution violation (neighbor leak)
  D9. S_decay       — Tail decay naturalness (cliff cut-off detection)

Usage:
  python selective_composer.py                        # Score all segments
  python selective_composer.py --compose              # Score + compose decisions
  python selective_composer.py --stability-pending    # Run stability on PENDING
  python selective_composer.py --report               # Generate composition report only
"""

import os
import sys
import json
import csv
import argparse
import logging
import datetime
import math
import warnings
import re
import unicodedata
from collections import defaultdict

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from tqdm import tqdm

# ============================================================
# CONFIGURATION
# ============================================================
BASE_DIR = os.getcwd()
WAV_DIR = os.path.join(BASE_DIR, "datasets", "wavs")
METADATA_PATH = os.path.join(BASE_DIR, "datasets", "script.txt")
LOG_DIR = os.path.join(BASE_DIR, "logs")
SCORES_PATH = os.path.join(LOG_DIR, "composition_scores.json")
COMPOSITION_REPORT_PATH = os.path.join(LOG_DIR, "composition_report.json")
PENDING_POOL_PATH = os.path.join(LOG_DIR, "pending_pool.json")
REJECTION_LOG_PATH = os.path.join(LOG_DIR, "rejection_log.json")
CALIBRATION_PATH = os.path.join(LOG_DIR, "calibration_report.json")
COMPOSITION_CSV_PATH = os.path.join(LOG_DIR, "composition_results.csv")
EVAL_CHECKPOINT_PATH = os.path.join(LOG_DIR, "eval_checkpoint.json")

# AST (Average Spoken Time) parameters
AST_SAMPLE_SIZE = 50          # Random sample size for baseline
AST_SIGNIFICANCE = 0.05       # p-value threshold
AST_Z_CAP = 3.0              # z-score cap for score mapping

# SNR reference
SNR_REFERENCE_DB = 40.0       # Score saturates at this SNR

# Boundary scoring
SILENCE_THRESHOLD_DB = -40
SPEECH_DETECT_DB = -40         # (2026-04-15) Loud-body detection for D8 S_continuity.
                                # Matches align_and_split.SPEECH_DETECT_DB intentionally —
                                # both modules use the same threshold for "loud speech body"
                                # detection (different purpose than align_and_split's
                                # SILENCE_THRESHOLD_DB=-68 which is for onset sensitivity).
PREATTACK_TARGET_MS = 400
TAIL_TARGET_MS = 730

# Whisper confidence mapping
CONFIDENCE_LOGPROB_CENTER = -0.4  # sigmoid center
CONFIDENCE_LOGPROB_SCALE = 5.0    # sigmoid steepness

# Composition thresholds (initial — will be calibrated from data)
DEFAULT_TAU_ACCEPT = 0.88
DEFAULT_TAU_REJECT = 0.65

# Hard reject gates
HARD_REJECT_UNPROMPTED = 0.50
HARD_REJECT_GAP = 0.50
HARD_REJECT_SNR = 0.30
HARD_REJECT_CONTINUITY = 0.3   # (2026-04-15) D8 bimodality reject — see compute_continuity_score
CONTINUITY_GAP_MS = 730        # Gap threshold mirrors TAIL_SILENCE_MS in align_and_split

# Formal endings (from detect_ending_truncation.py)
FORMAL_ENDINGS = [
    "습니다", "습니까", "십시오", "십시요",
    "것입니다", "것이었습니다",
    "었습니다", "였습니다", "겠습니다",
    "었습니까", "였습니까", "겠습니까",
    "하십시오", "마십시오",
    "읍시다", "합시다",
    "으세요", "하세요", "으셨어요",
]

# Logging
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(LOG_DIR, "selective_composer.log"),
            encoding='utf-8', mode='a'  # (2026-04-15) 'w'는 import마다 truncate
        )
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# TEXT NORMALIZATION (shared with evaluate_dataset.py)
# ============================================================
def normalize_text(text):
    """Strip punctuation, keep Hangul + alphanumeric, NFC-normalize, lowercase."""
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'[^\w\s\uAC00-\uD7AF\u3130-\u318F]', '', text)
    return text.lower().strip()


def strip_comments(text):
    """Remove inline comments (// ...) from metadata text."""
    idx = text.find('//')
    if idx >= 0:
        text = text[:idx]
    return text.strip()


def count_characters(text):
    """Count meaningful characters in Korean text for AST calculation.

    Korean word length correlates poorly with spoken duration due to
    agglutinative morphology (e.g., honorifics add syllables, not words).
    Character count is a much better proxy for spoken duration.

    Counts Hangul syllables + alphanumeric chars (strips punctuation/spaces).
    Strips inline comments (//) first.
    """
    text = strip_comments(text)
    # Keep only Hangul syllables + alphanumeric
    chars = [c for c in text if ('\uAC00' <= c <= '\uD7AF') or c.isalnum()]
    return len(chars)


# ============================================================
# AUDIO UTILITIES
# ============================================================
def compute_rms_windowed(samples, sr, window_ms=10):
    """Compute RMS in dB for each window."""
    window_size = int(sr * window_ms / 1000)
    if window_size == 0:
        return np.array([-100.0])
    n_windows = len(samples) // window_size
    if n_windows == 0:
        rms_lin = np.sqrt(np.mean(samples ** 2))
        return np.array([20 * np.log10(max(rms_lin, 1e-10))])
    trimmed = samples[:n_windows * window_size].reshape(n_windows, window_size)
    rms_lin = np.sqrt(np.mean(trimmed ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms_lin, 1e-10))


def find_voice_region(samples, sr, threshold_db=-65, window_ms=10):
    """Find voice onset/offset sample indices using RMS.
    Returns (onset_sample, offset_sample)."""
    rms_db = compute_rms_windowed(samples, sr, window_ms)
    window_size = int(sr * window_ms / 1000)
    voiced = np.where(rms_db >= threshold_db)[0]
    if len(voiced) == 0:
        return 0, len(samples)
    onset_sample = voiced[0] * window_size
    offset_sample = min((voiced[-1] + 1) * window_size, len(samples))
    return onset_sample, offset_sample


# ============================================================
# SCORING FUNCTIONS (D1-D7)
# ============================================================

def compute_snr_score(wav_path):
    """D3: Signal-to-Noise Ratio score [0, 1].
    Computes SNR of the speech region vs silence regions."""
    try:
        samples, sr = sf.read(wav_path, dtype='float64')
        if samples.ndim > 1:
            samples = samples[:, 0]

        onset, offset = find_voice_region(samples, sr)

        # Speech region power
        speech = samples[onset:offset]
        if len(speech) == 0:
            return 0.0
        speech_power = np.mean(speech ** 2)

        # Noise region: pre-attack + tail silence
        noise_regions = []
        if onset > 0:
            noise_regions.append(samples[:onset])
        if offset < len(samples):
            noise_regions.append(samples[offset:])

        if not noise_regions or all(len(r) == 0 for r in noise_regions):
            # No silence regions — assume clean
            return 1.0

        noise = np.concatenate(noise_regions)
        noise_power = np.mean(noise ** 2)

        if noise_power < 1e-20:
            return 1.0  # Near-zero noise

        snr_db = 10 * np.log10(speech_power / noise_power)
        return min(1.0, max(0.0, snr_db / SNR_REFERENCE_DB))
    except Exception:
        return 0.0


def discover_sessions(raw_audio_dir):
    """Discover recording sessions from raw audio filenames.

    Each raw audio file (e.g., Script_2_1-162.wav) is one recording session
    where the speaker maintained a consistent tone/pace.

    Returns list of {'script': int, 'start': int, 'end': int, 'session_id': str}.
    """
    sessions = []
    if not os.path.isdir(raw_audio_dir):
        logger.warning(f"Raw audio dir not found: {raw_audio_dir}")
        return sessions
    # (2026-04-16) os.walk for recursive scan — raw audio may live in
    # subdirectories (e.g., rawdata/audio/2026-04-10_additional_lines/).
    # Prior os.listdir missed those, causing 83% ast_not_computed.
    for root, _dirs, files in os.walk(raw_audio_dir):
        for f in sorted(files):
            m = re.match(r'Script_(\d+)_(\d+)-(\d+)\.wav', f)
            if m:
                sessions.append({
                    'script': int(m.group(1)),
                    'start': int(m.group(2)),
                    'end': int(m.group(3)),
                    'session_id': f.replace('.wav', '')
                })
    return sessions


def map_file_to_session(fname, sessions):
    """Map an output WAV filename to its recording session.

    Returns session_id string or None.
    """
    m = re.match(r'Script_(\d+)_(\d+)\.wav', fname)
    if not m:
        return None
    sno, line = int(m.group(1)), int(m.group(2))
    for sess in sessions:
        if sess['script'] == sno and sess['start'] <= line <= sess['end']:
            return sess['session_id']
    return None


def compute_ast_baseline(metadata_entries, wav_dir, sessions):
    """Compute AST (Average Spoken Time) baseline per recording session.

    AST = seconds per character (s/char) — how long the speaker takes to
    speak one character. Higher AST = slower speech. This is more intuitive
    than chars/s because it directly measures the time cost per unit of text.

    Korean character count is a better proxy for spoken duration than word
    count, because Korean is agglutinative (honorifics/endings add syllables,
    not words).

    Each raw audio file = one recording session with consistent speaker pace.

    Returns {session_id: {'mean': float, 'std': float, 'n': int}}.
    """
    # Group entries by session
    by_session = defaultdict(list)
    for entry in metadata_entries:
        sess = map_file_to_session(entry['filename'], sessions)
        if sess:
            by_session[sess].append(entry)

    stats = {}
    for sess_id, entries in by_session.items():
        ast_values = []
        for entry in entries:
            wav_path = os.path.join(wav_dir, entry['filename'])
            if not os.path.exists(wav_path):
                continue
            try:
                duration = _measure_speech_body_duration(wav_path)
                if duration < 0.1:
                    continue
                chars = count_characters(entry['ground_truth'])
                if chars == 0:
                    continue
                ast_values.append(duration / chars)
            except Exception:
                continue

        if len(ast_values) >= 5:
            stats[sess_id] = {
                'mean': float(np.mean(ast_values)),
                'std': float(np.std(ast_values, ddof=1)),
                'n': len(ast_values),
            }
        else:
            logger.warning(f"Session {sess_id}: insufficient AST samples ({len(ast_values)})")

    return stats


def _measure_speech_body_duration(wav_path):
    """Measure the duration of the *speech body* only, excluding all
    envelope silence and designed padding regions.

    Reads the WAV, strips the fixed R6 envelope (PREATTACK + TAIL silence),
    then finds the first and last RMS windows above SPEECH_DETECT_DB (-40dB)
    within the voiced region. Returns the duration in seconds between those
    two points — the actual speaking time, free of any pipeline-added silence.

    This is critical for AST (Average Spoken Time) calculation: using total
    WAV duration inflates AST by 30-50% for short lines because the fixed
    ~1.9s envelope overhead is a larger fraction of shorter recordings.
    See 2026-04-16 L0948 false-REJECT incident.
    """
    samples, sr = sf.read(wav_path, dtype='float64')
    if samples.ndim > 1:
        samples = samples[:, 0]
    # Strip R6 envelope (fixed zeros at both ends)
    lead = int(sr * PREATTACK_TARGET_MS / 1000)
    tail = int(sr * TAIL_TARGET_MS / 1000)
    if lead + tail >= len(samples):
        return 0.0
    voiced = samples[lead:len(samples) - tail]
    # Find speech body via -40dB RMS windows
    win = int(sr * 0.010)  # 10ms
    nw = len(voiced) // win
    if nw < 2:
        return len(voiced) / sr
    trimmed = voiced[:nw * win].reshape(nw, win)
    rms = np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(np.maximum(rms, 1e-10))
    speech_idx = np.where(db >= SPEECH_DETECT_DB)[0]
    if len(speech_idx) == 0:
        return len(voiced) / sr
    body_start = speech_idx[0] * win
    body_end = (speech_idx[-1] + 1) * win
    return (body_end - body_start) / sr


def compute_duration_score(wav_path, gt_text, ast_stats, session_id):
    """D4: AST-based duration anomaly score [0, 1] with p-value.

    AST = seconds per character (s/char). Measures how long the speaker
    takes to speak one character. Higher AST = slower speech.

    z > 0 means segment is slower than session average (more s/char).
    z < 0 means segment is faster than session average (less s/char).

    Truncation risk: z < -1.5 on formal endings = audio may be cut short.

    Returns (score, z_value, p_value, flags).
    """
    from scipy import stats as scipy_stats

    flags = []
    try:
        duration = _measure_speech_body_duration(wav_path)
        if duration < 0.1:
            return 0.0, 0.0, 1.0, ['zero_duration']

        chars = count_characters(gt_text)
        if chars == 0:
            return 0.5, 0.0, 1.0, ['no_chars']

        segment_ast = duration / chars

        if session_id not in ast_stats:
            return 0.5, 0.0, 1.0, ['no_baseline']

        baseline = ast_stats[session_id]
        if baseline['std'] < 1e-6:
            return 0.5, 0.0, 1.0, ['zero_variance']

        z = (segment_ast - baseline['mean']) / baseline['std']
        p = 2.0 * (1.0 - scipy_stats.norm.cdf(abs(z)))  # two-tailed

        score = 1.0 - min(1.0, abs(z) / AST_Z_CAP)

        if p < AST_SIGNIFICANCE:
            # z > 0: slower than average (more time per char)
            # z < 0: faster than average (less time per char)
            direction = "slow" if z > 0 else "fast"
            flags.append('HUMAN_REVIEW_NEEDED')
            flags.append(f"AST_anomaly_{direction}")
            flags.append(f"z={z:.2f},p={p:.4f},AST={segment_ast:.4f}vs{baseline['mean']:.4f}s/char,session={session_id}")

        # Truncation risk: formal ending + unusually fast (low s/char)
        norm_text = normalize_text(gt_text)
        has_formal = any(norm_text.endswith(e) for e in FORMAL_ENDINGS)
        if has_formal and z < -1.5:  # significantly faster = possible truncation
            flags.append('formal_ending_truncation_risk')

        return max(0.0, score), float(z), float(p), flags

    except ImportError:
        logger.warning("scipy not available — AST scoring disabled, returning neutral")
        return 0.5, 0.0, 1.0, ['scipy_missing']
    except Exception as e:
        return 0.0, 0.0, 1.0, [f'error:{e}']


def compute_gap_score(sim_prompted, sim_unprompted):
    """D2: Prompted vs Unprompted gap score [0, 1].
    Large gap = prompt is compensating for audio deficiency."""
    gap = max(0.0, sim_prompted - sim_unprompted)
    return max(0.0, min(1.0, 1.0 - gap))


def compute_confidence_score(avg_logprob, no_speech_prob=0.0, compression_ratio=1.0):
    """D6: Whisper self-reported confidence [0, 1].
    Uses avg_logprob with sigmoid mapping, penalized by no_speech_prob."""
    # Sigmoid mapping
    x = CONFIDENCE_LOGPROB_SCALE * (avg_logprob - CONFIDENCE_LOGPROB_CENTER)
    base_score = 1.0 / (1.0 + math.exp(-x))

    # Penalties
    if no_speech_prob > 0.3:
        base_score *= 0.7
    if compression_ratio > 2.0:
        base_score *= 0.8

    return max(0.0, min(1.0, base_score))


def compute_boundary_score(samples, sr):
    """D7: Continuous boundary/envelope quality score [0, 1].
    Extends binary R2/R6 to continuous scoring."""
    # Boundary silence margin (R2)
    window_50ms = int(sr * 0.05)
    if len(samples) < window_50ms * 2:
        return 0.0

    first_rms = np.sqrt(np.mean(samples[:window_50ms] ** 2))
    last_rms = np.sqrt(np.mean(samples[-window_50ms:] ** 2))
    first_db = 20 * np.log10(max(first_rms, 1e-10))
    last_db = 20 * np.log10(max(last_rms, 1e-10))

    # How far below threshold? More margin = higher score
    margin_first = max(0.0, SILENCE_THRESHOLD_DB - first_db) / 40.0  # -80dB → score 1.0
    margin_last = max(0.0, SILENCE_THRESHOLD_DB - last_db) / 40.0
    silence_score = min(1.0, (margin_first + margin_last) / 2.0)

    # Envelope compliance (R6)
    onset, offset = find_voice_region(samples, sr, threshold_db=SILENCE_THRESHOLD_DB)
    preattack_ms = onset / sr * 1000
    tail_ms = (len(samples) - offset) / sr * 1000

    pre_ratio = min(1.0, preattack_ms / PREATTACK_TARGET_MS)
    tail_ratio = min(1.0, tail_ms / TAIL_TARGET_MS)
    envelope_score = (pre_ratio + tail_ratio) / 2.0

    return 0.4 * silence_score + 0.6 * envelope_score


def compute_stability_score(wav_path, model, temperatures=None):
    """D5: Transcription stability across decode temperatures [0, 1].

    Runs Whisper transcription at multiple temperatures and measures the
    pairwise consistency of the outputs.  High consistency (all temps
    produce the same text) → score ≈ 1.0.  Low consistency (different
    temps produce different text) → score approaches 0.

    Requires a loaded Whisper model (GPU).  Expensive: N_temps × transcribe.
    Intended for PENDING-pool items only, not full-batch scoring.
    """
    if temperatures is None:
        temperatures = [0.0, 0.2, 0.4, 0.6, 0.8]
    import difflib
    transcriptions = []
    for temp in temperatures:
        try:
            result = model.transcribe(
                wav_path, language="ko", verbose=False,
                fp16=True, temperature=temp,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
            )
            transcriptions.append(result.get('text', '').strip())
        except Exception:
            transcriptions.append('')

    if len(transcriptions) < 2:
        return 0.5

    # Pairwise similarity (SequenceMatcher) across all temp pairs
    pairs = []
    for i in range(len(transcriptions)):
        for j in range(i + 1, len(transcriptions)):
            a, b = transcriptions[i], transcriptions[j]
            if not a and not b:
                pairs.append(1.0)
            elif not a or not b:
                pairs.append(0.0)
            else:
                pairs.append(difflib.SequenceMatcher(None, a, b).ratio())

    # Mean pairwise similarity = stability score
    return sum(pairs) / len(pairs) if pairs else 0.5


def compute_continuity_score(samples, sr):
    """D8: Bimodal distribution violation score [0, 1]. (2026-04-15)

    Flags WAVs where a silence gap >= CONTINUITY_GAP_MS is followed by
    speech resumption — breaking the expected unimodal energy envelope of a
    single-sentence utterance (speech → silence → speech is the signature of
    neighbor-sentence leak, e.g. L0313).

    Uses SPEECH_DETECT_DB (-40 dB, loud body threshold) so room ambient does
    not count as speech. Threshold is tied to TAIL_SILENCE_MS design so a
    gap ≥ envelope-tail length is treated as "sentence over"; any speech
    after that is by definition extra content.
    """
    win = int(sr * 0.010)        # 10 ms windows (matches RMS_WINDOW_MS pattern)
    nw = len(samples) // win
    if nw < 10:
        return 1.0
    trimmed = samples[:nw * win].reshape(nw, win)
    rms = np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(np.maximum(rms, 1e-10))
    is_speech = db >= SPEECH_DETECT_DB

    threshold_windows = int(CONTINUITY_GAP_MS / 10)
    worst_severity = 0.0
    i = 0
    while i < nw:
        if not is_speech[i]:
            j = i
            while j < nw and not is_speech[j]:
                j += 1
            gap_len = j - i
            has_speech_after = (j < nw and bool(np.any(is_speech[j:])))
            if gap_len >= threshold_windows and has_speech_after:
                excess_ms = (gap_len - threshold_windows) * 10
                severity = min(1.0, 0.5 + excess_ms / 500.0)
                if severity > worst_severity:
                    worst_severity = severity
            i = j
        else:
            i += 1
    return max(0.0, 1.0 - worst_severity)


def _score_edge(db, anchor, body_ref, scan_windows, direction, window_ms,
                natural_grad, cliff_grad, min_span_ms, good_span_ms):
    """Score one edge (head or tail) of the energy envelope.

    Shared logic for both onset and offset truncation detection.
    Measures gradient steepness and transition span in one direction.

    Args:
        db:            RMS envelope in dB (array of window values).
        anchor:        Window index of the signal boundary (-68dB).
                       For tail: last_signal.  For head: first_signal.
        body_ref:      Window index of the body boundary (-40dB).
                       For tail: body_end (last -40dB window).
                       For head: body_start (first -40dB window).
                       None if no -40dB content exists.
        scan_windows:  How many windows to scan from anchor.
        direction:     'backward' (tail) or 'forward' (head).
        window_ms:     Duration of one RMS window in ms.
        natural_grad:  dB/ms threshold for natural transition (score 1.0).
        cliff_grad:    dB/ms threshold for cliff (score 0.0).
        min_span_ms:   Span below this → score 0.
        good_span_ms:  Span above this → score 1.

    Returns:
        float: score in [0, 1].
    """
    nw = len(db)

    # --- Extract analysis region ---
    if direction == 'backward':
        region_start = max(0, anchor - scan_windows)
        region = db[region_start:anchor + 1]
    else:  # forward
        region_end = min(nw, anchor + scan_windows + 1)
        region = db[anchor:region_end]

    if len(region) < 3:
        return 1.0

    # --- Gradient score ---
    gradient = np.diff(region) / window_ms  # dB/ms

    if direction == 'backward':
        # Tail: look for steepest NEGATIVE gradient (energy drop)
        target_grads = gradient[gradient < 0]
        steepness = abs(np.min(target_grads)) if len(target_grads) > 0 else 0.0
    else:
        # Head: look for steepest POSITIVE gradient (energy rise)
        target_grads = gradient[gradient > 0]
        steepness = np.max(target_grads) if len(target_grads) > 0 else 0.0

    if steepness <= natural_grad:
        grad_score = 1.0
    elif steepness >= cliff_grad:
        grad_score = 0.0
    else:
        grad_score = 1.0 - (steepness - natural_grad) / (cliff_grad - natural_grad)

    # --- Span score ---
    if body_ref is not None:
        if direction == 'backward':
            span_ms = max(0, anchor - body_ref) * window_ms
        else:
            span_ms = max(0, body_ref - anchor) * window_ms
    else:
        span_ms = len(region) * window_ms

    if span_ms >= good_span_ms:
        span_score = 1.0
    elif span_ms <= min_span_ms:
        span_score = 0.0
    else:
        span_score = (span_ms - min_span_ms) / (good_span_ms - min_span_ms)

    return min(grad_score, span_score)


def compute_decay_score(samples, sr):
    """D9: Edge transition naturalness score [0, 1]. (2026-04-17)

    Detects artificial truncation at BOTH edges of the utterance:
      - TAIL: cliff cut-off (energy drops to silence abruptly)
      - HEAD: onset truncation (energy jumps to speech level abruptly,
              consonant attack missing)

    ===== Design: signal-boundary anchors + directional scan =====

    TAIL analysis:
      1. Anchor on last_signal (-68dB) — last detectable signal.
      2. Scan BACKWARD up to 730ms.
      3. Look for steep negative gradient (energy cliff-drop).

    HEAD analysis:
      1. Anchor on first_signal (-68dB) — first detectable signal.
         This skips the PRESPEECH_PAD zero-fill region (-120dB), whose
         transition to speech is an artificial cliff by design.
      2. Scan FORWARD up to 730ms into the speech content.
      3. Look for steep positive gradient (energy cliff-rise).

    ===== Shared gradient thresholds =====

    Empirical basis (2026-04-17, 300-sample measurement):
      HEAD after first_signal: normal max_rise p95=3.8, max=6.0 dB/ms
      TAIL before last_signal: normal max_drop p95=3.6, max=4.4 dB/ms
      Truncated (zero-fill):   gradient 12-15 dB/ms

      <= 4 dB/ms  → 1.0 (natural transition)
      >= 10 dB/ms → 0.0 (cliff = truncation signature)
      4-10 dB/ms  → linear interpolation (protects hard consonants)

    ===== Final score = min(head_score, tail_score) =====

    Both edges must pass. If either edge is truncated, the whole file
    is flagged — a file with perfect tail but clipped onset is still bad.

    Returns score in [0, 1]. Higher = more natural edges.
    """
    # ----- Thresholds (shared for head and tail) -----
    DECAY_SIGNAL_DB = -68           # align_and_split.SILENCE_THRESHOLD_DB
    DECAY_WINDOW_MS = 5             # RMS window resolution
    DECAY_SCAN_MS = 730             # Scan range (= TAIL_SILENCE_MS)
    DECAY_MIN_SPAN_MS = 10          # Below → score 0
    DECAY_GOOD_SPAN_MS = 50         # Above → score 1
    DECAY_NATURAL_GRAD = 4.0        # dB/ms, natural upper bound
    DECAY_CLIFF_GRAD = 10.0         # dB/ms, cliff lower bound

    if samples.ndim > 1:
        samples = samples[:, 0]

    # Step 1: Strip R6 envelope (pipeline-added zeros at both ends).
    lead = int(sr * PREATTACK_TARGET_MS / 1000)
    tail = int(sr * TAIL_TARGET_MS / 1000)
    if lead + tail >= len(samples):
        return 1.0
    voiced = samples[lead:len(samples) - tail]

    # Step 2: RMS envelope in 5ms windows.
    win = int(sr * DECAY_WINDOW_MS / 1000)
    nw = len(voiced) // win
    if nw < 10:
        return 1.0
    trimmed = voiced[:nw * win].reshape(nw, win)
    rms = np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(np.maximum(rms, 1e-10))

    # Step 3: Find signal boundaries and body boundaries.
    signal_idx = np.where(db >= DECAY_SIGNAL_DB)[0]   # -68dB
    body_idx = np.where(db >= SPEECH_DETECT_DB)[0]     # -40dB

    if len(signal_idx) < 5:
        return 1.0

    first_signal = signal_idx[0]
    last_signal = signal_idx[-1]
    body_start = body_idx[0] if len(body_idx) > 0 else None
    body_end = body_idx[-1] if len(body_idx) > 0 else None

    scan_windows = int(DECAY_SCAN_MS / DECAY_WINDOW_MS)
    shared = dict(window_ms=DECAY_WINDOW_MS, natural_grad=DECAY_NATURAL_GRAD,
                  cliff_grad=DECAY_CLIFF_GRAD, min_span_ms=DECAY_MIN_SPAN_MS,
                  good_span_ms=DECAY_GOOD_SPAN_MS)

    # Step 4: TAIL score — backward from last_signal.
    tail_score = _score_edge(db, anchor=last_signal, body_ref=body_end,
                             scan_windows=scan_windows, direction='backward',
                             **shared)

    # Step 5: HEAD score — forward from first_signal.
    #   Skips zero-fill region because first_signal is AFTER the zeros.
    #   HEAD uses span=None to disable span scoring: Korean stops/affricates
    #   naturally jump from silence to -40dB in one window (span=0), which
    #   is normal, not truncation. Only gradient matters for onset quality.
    head_score = _score_edge(db, anchor=first_signal, body_ref=None,
                             scan_windows=scan_windows, direction='forward',
                             **shared)

    # Step 6: Final = min(head, tail). Both edges must be natural.
    return min(head_score, tail_score)


# ============================================================
# COMPOSITE SCORING
# ============================================================
def geometric_mean(values):
    """Geometric mean of a list of [0, 1] values. Handles zeros."""
    values = [max(v, 1e-10) for v in values]
    log_sum = sum(math.log(v) for v in values)
    return math.exp(log_sum / len(values))


def compose_decision(scores, tau_accept=DEFAULT_TAU_ACCEPT, tau_reject=DEFAULT_TAU_REJECT):
    """Make ACCEPT/PENDING/REJECT decision from scores dict.
    Returns (verdict, composite_score, flags)."""
    flags = list(scores.get('flags', []))

    # Hard reject gates
    if scores.get('S_unprompted', 1.0) < HARD_REJECT_UNPROMPTED:
        return 'REJECT', 0.0, flags + ['hard_reject:S_unprompted']
    if scores.get('S_gap', 1.0) < HARD_REJECT_GAP:
        return 'REJECT', 0.0, flags + ['hard_reject:S_gap']
    if scores.get('S_snr', 1.0) < HARD_REJECT_SNR:
        return 'REJECT', 0.0, flags + ['hard_reject:S_snr']
    # (2026-04-15) D8 bimodality gate — catches neighbor-sentence leak
    if scores.get('S_continuity', 1.0) < HARD_REJECT_CONTINUITY:
        return 'REJECT', 0.0, flags + ['hard_reject:S_continuity']

    # Composite: geometric mean of D1-D4, D6-D9 (D5 stability is optional gate)
    core_scores = [
        scores.get('S_unprompted', 0.5),
        scores.get('S_gap', 0.5),
        scores.get('S_snr', 0.5),
        scores.get('S_duration', 0.5),
        scores.get('S_confidence', 0.5),
        scores.get('S_boundary', 0.5),
        scores.get('S_continuity', 0.5),
        scores.get('S_decay', 0.5),
    ]
    S_comp = geometric_mean(core_scores)

    # Stability gate (if available)
    S_stab = scores.get('S_stability')
    if S_stab is not None:
        tau_stab = 0.70
        gate = 1.0 if S_stab >= tau_stab else S_stab / tau_stab
        S_comp *= gate

    if S_comp >= tau_accept:
        return 'ACCEPT', S_comp, flags
    elif S_comp >= tau_reject:
        return 'PENDING', S_comp, flags
    else:
        return 'REJECT', S_comp, flags


# ============================================================
# THRESHOLD CALIBRATION
# ============================================================
def calibrate_thresholds(all_scores, known_good_files=None, known_bad_files=None,
                         n_bootstrap=1000):
    """Data-driven threshold calibration via bootstrap.

    Uses known-good (5th percentile) and known-bad (95th percentile) distributions.
    Returns calibrated (tau_accept, tau_reject) with confidence intervals.
    """
    rng = np.random.RandomState(42)

    # Compute composite for all
    composites = {}
    for fname, scores in all_scores.items():
        core = [
            scores.get('S_unprompted', 0.5),
            scores.get('S_gap', 0.5),
            scores.get('S_snr', 0.5),
            scores.get('S_duration', 0.5),
            scores.get('S_confidence', 0.5),
            scores.get('S_boundary', 0.5),
            scores.get('S_continuity', 0.5),
            scores.get('S_decay', 0.5),
        ]
        composites[fname] = geometric_mean(core)

    # Identify known-good and known-bad
    if known_good_files is None:
        # Heuristic: segments with S_unprompted >= 0.95 and S_gap >= 0.90
        known_good_files = [f for f, s in all_scores.items()
                           if s.get('S_unprompted', 0) >= 0.95
                           and s.get('S_gap', 0) >= 0.90]
    if known_bad_files is None:
        # Heuristic: segments with S_unprompted < 0.60
        known_bad_files = [f for f, s in all_scores.items()
                          if s.get('S_unprompted', 0) < 0.60]

    good_composites = np.array([composites[f] for f in known_good_files if f in composites])
    bad_composites = np.array([composites[f] for f in known_bad_files if f in composites])

    if len(good_composites) < 10:
        logger.warning(f"Only {len(good_composites)} known-good samples — using defaults")
        return DEFAULT_TAU_ACCEPT, DEFAULT_TAU_REJECT, {}

    # Bootstrap calibration
    accept_thresholds = []
    for _ in range(n_bootstrap):
        sample = rng.choice(good_composites, size=len(good_composites), replace=True)
        accept_thresholds.append(np.percentile(sample, 5))

    tau_accept = float(np.median(accept_thresholds))
    accept_ci = (float(np.percentile(accept_thresholds, 2.5)),
                 float(np.percentile(accept_thresholds, 97.5)))

    tau_reject = DEFAULT_TAU_REJECT
    if len(bad_composites) >= 5:
        reject_thresholds = []
        for _ in range(n_bootstrap):
            sample = rng.choice(bad_composites, size=len(bad_composites), replace=True)
            reject_thresholds.append(np.percentile(sample, 95))
        tau_reject = float(np.median(reject_thresholds))

    calibration = {
        'tau_accept': tau_accept,
        'tau_accept_ci_95': accept_ci,
        'tau_reject': tau_reject,
        'n_known_good': len(good_composites),
        'n_known_bad': len(bad_composites),
        'n_bootstrap': n_bootstrap,
        'timestamp': datetime.datetime.now().isoformat()
    }

    logger.info(f"Calibrated thresholds: ACCEPT >= {tau_accept:.4f} "
                f"(95% CI: {accept_ci[0]:.4f}-{accept_ci[1]:.4f}), "
                f"REJECT < {tau_reject:.4f}")

    return tau_accept, tau_reject, calibration


# ============================================================
# MAIN SCORING PIPELINE
# ============================================================
def load_metadata(metadata_path=None):
    """Metadata loader. Resolves METADATA_PATH at call time so module-global
    overrides from orchestrators (pipeline_manager, drivers) take effect —
    see 2026-04-15 default-argument-capture fix."""
    if metadata_path is None:
        metadata_path = METADATA_PATH
    entries = []
    with open(metadata_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|', 1)
            if len(parts) == 2:
                entries.append({'filename': parts[0], 'ground_truth': parts[1]})
    return entries


def load_eval_results(checkpoint_path=None):
    """Load evaluation checkpoint for existing prompted/unprompted scores.
    Resolves path at call time so runtime module-global overrides take effect
    (prior default-argument form captured the value at import time — see
    2026-04-15 selective_composer eval-checkpoint binding bug)."""
    if checkpoint_path is None:
        checkpoint_path = EVAL_CHECKPOINT_PATH
    if not os.path.exists(checkpoint_path):
        return {}
    with open(checkpoint_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # Index by filename
    results = {}
    for r in data.get('results', []):
        results[r['filename']] = r
    return results


def score_all_segments(metadata_entries, wav_dir=None, eval_results=None,
                       ast_stats=None, sessions=None):
    if wav_dir is None:
        wav_dir = WAV_DIR  # resolve at call time (see 2026-04-15 fix)
    """Compute all scoring dimensions for each segment.

    D1 (S_unprompted) and D6 (S_confidence) require eval_results from
    evaluate_dataset.py (must have been run with extended scoring).
    If eval_results not available, these dimensions use neutral defaults.

    Args:
        sessions: list of session dicts from discover_sessions() for
                  session-level AST mapping.
    """
    if eval_results is None:
        eval_results = {}
    if sessions is None:
        sessions = []

    all_scores = {}

    for entry in tqdm(metadata_entries, desc="Scoring segments"):
        fname = entry['filename']
        gt_text = entry['ground_truth']
        wav_path = os.path.join(wav_dir, fname)

        if not os.path.exists(wav_path):
            continue

        scores = {'filename': fname, 'flags': []}

        # Map to recording session
        session_id = map_file_to_session(fname, sessions)
        scores['session_id'] = session_id or 'unknown'

        # --- D1: S_unprompted ---
        eval_r = eval_results.get(fname, {})
        sim_prompted = eval_r.get('similarity_prompted', eval_r.get('similarity', 0.5))
        sim_unprompted = eval_r.get('similarity_unprompted', None)

        if sim_unprompted is not None:
            scores['S_unprompted'] = sim_unprompted
            scores['S_prompted'] = sim_prompted
        else:
            # Fallback: use existing similarity as rough proxy
            scores['S_unprompted'] = eval_r.get('similarity', 0.5)
            scores['S_prompted'] = scores['S_unprompted']
            scores['flags'].append('unprompted_not_available')

        # --- D2: S_gap ---
        scores['S_gap'] = compute_gap_score(scores['S_prompted'], scores['S_unprompted'])

        # --- D3: S_snr ---
        scores['S_snr'] = compute_snr_score(wav_path)

        # --- D4: S_duration (AST, session-level) ---
        if ast_stats and session_id:
            s_dur, z_val, p_val, dur_flags = compute_duration_score(
                wav_path, gt_text, ast_stats, session_id)
            scores['S_duration'] = s_dur
            scores['ast_z'] = z_val
            scores['ast_p'] = p_val
            scores['flags'].extend(dur_flags)
        else:
            scores['S_duration'] = 0.5
            scores['flags'].append('ast_not_computed')

        # --- D5: S_stability (deferred — only for PENDING) ---
        scores['S_stability'] = None

        # --- D6: S_confidence ---
        avg_logprob = eval_r.get('avg_logprob', -0.4)
        no_speech_prob = eval_r.get('no_speech_prob', 0.0)
        compression_ratio = eval_r.get('compression_ratio', 1.0)
        scores['S_confidence'] = compute_confidence_score(
            avg_logprob, no_speech_prob, compression_ratio)

        # --- D7: S_boundary + D8: S_continuity + D9: S_decay ---
        # Narrow the except: only swallow I/O errors. Code bugs (NameError,
        # ValueError in numeric ops) should surface, not silently fallback.
        try:
            samples, sr = sf.read(wav_path, dtype='float64')
            if samples.ndim > 1:
                samples = samples[:, 0]
        except (IOError, OSError, RuntimeError) as e:
            logger.warning(f"Could not read {wav_path} for D7/D8/D9: {e}")
            scores['S_boundary'] = 0.0
            scores['S_continuity'] = 0.5
            scores['S_decay'] = 0.5
        else:
            scores['S_boundary'] = compute_boundary_score(samples, sr)
            scores['S_continuity'] = compute_continuity_score(samples, sr)
            scores['S_decay'] = compute_decay_score(samples, sr)

        all_scores[fname] = scores

    return all_scores


def run_composition(all_scores, tau_accept=None, tau_reject=None):
    """Run composition decisions on all scored segments.

    Returns composition results dict with verdicts and stats.
    """
    # Calibrate if thresholds not provided
    if tau_accept is None or tau_reject is None:
        tau_accept, tau_reject, calibration = calibrate_thresholds(all_scores)
    else:
        calibration = {'tau_accept': tau_accept, 'tau_reject': tau_reject, 'source': 'manual'}

    accept_list = []
    pending_list = []
    reject_list = []

    for fname, scores in all_scores.items():
        verdict, composite, flags = compose_decision(scores, tau_accept, tau_reject)
        scores['S_composite'] = composite
        scores['verdict'] = verdict
        scores['composition_flags'] = flags

        record = {
            'filename': fname,
            'verdict': verdict,
            'S_composite': round(composite, 4),
            'scores': {k: round(v, 4) if isinstance(v, float) else v
                      for k, v in scores.items()
                      if k.startswith('S_') or k in ('ast_z', 'ast_p')},
            'flags': flags
        }

        if verdict == 'ACCEPT':
            accept_list.append(record)
        elif verdict == 'PENDING':
            pending_list.append(record)
        else:
            reject_list.append(record)

    total = len(all_scores)
    composition_rate = len(accept_list) / total * 100 if total > 0 else 0

    # Per-dimension statistics
    dim_stats = {}
    for dim in ['S_unprompted', 'S_gap', 'S_snr', 'S_duration', 'S_confidence', 'S_boundary', 'S_continuity', 'S_decay']:
        values = [s.get(dim, 0.5) for s in all_scores.values() if isinstance(s.get(dim), (int, float))]
        if values:
            dim_stats[dim] = {
                'mean': round(float(np.mean(values)), 4),
                'std': round(float(np.std(values)), 4),
                'p5': round(float(np.percentile(values, 5)), 4),
                'p95': round(float(np.percentile(values, 95)), 4),
                'min': round(float(np.min(values)), 4),
                'max': round(float(np.max(values)), 4),
            }

    # Per-script breakdown
    script_breakdown = defaultdict(lambda: {'accept': 0, 'pending': 0, 'reject': 0, 'total': 0})
    for fname, scores in all_scores.items():
        match = re.match(r'Script_(\d+)_', fname)
        sno = match.group(1) if match else '?'
        script_breakdown[sno]['total'] += 1
        script_breakdown[sno][scores.get('verdict', 'REJECT').lower()] += 1

    # Audio duration tally by verdict
    duration_by_verdict = {'accept': 0.0, 'pending': 0.0, 'reject': 0.0}
    wav_dir = WAV_DIR
    for fname, scores in all_scores.items():
        wav_path = os.path.join(wav_dir, fname)
        if os.path.isfile(wav_path):
            try:
                info = sf.info(wav_path)
                verdict_key = scores.get('verdict', 'REJECT').lower()
                duration_by_verdict[verdict_key] = duration_by_verdict.get(verdict_key, 0.0) + info.duration
            except Exception:
                pass
    total_duration_s = sum(duration_by_verdict.values())

    report = {
        'timestamp': datetime.datetime.now().isoformat(),
        'total_segments': total,
        'accept_count': len(accept_list),
        'pending_count': len(pending_list),
        'reject_count': len(reject_list),
        'composition_rate': round(composition_rate, 2),
        'audio_duration': {
            'total_seconds': round(total_duration_s, 1),
            'total_hours': round(total_duration_s / 3600, 2),
            'accept_seconds': round(duration_by_verdict['accept'], 1),
            'accept_hours': round(duration_by_verdict['accept'] / 3600, 2),
            'pending_seconds': round(duration_by_verdict['pending'], 1),
            'pending_hours': round(duration_by_verdict['pending'] / 3600, 2),
            'reject_seconds': round(duration_by_verdict['reject'], 1),
            'reject_hours': round(duration_by_verdict['reject'] / 3600, 2),
            'accept_pct': round(duration_by_verdict['accept'] / total_duration_s * 100, 1) if total_duration_s > 0 else 0,
        },
        'calibration': calibration,
        'dimension_statistics': dim_stats,
        'per_script_breakdown': dict(script_breakdown),
        'human_review_count': sum(1 for s in all_scores.values()
                                  if 'HUMAN_REVIEW_NEEDED' in s.get('flags', [])),
    }

    # CSV export — always produced alongside JSON so any caller
    # (pipeline_manager, CLI, driver scripts) gets the CSV automatically.
    # Principle 1: composition output logic lives here, not in callers.
    export_composition_csv(all_scores)

    return report, accept_list, pending_list, reject_list


def export_composition_csv(all_scores, csv_path=None):
    """Export composition results to CSV.

    Columns match the 2026-04-04 format with S_continuity added for D8.
    """
    if csv_path is None:
        csv_path = COMPOSITION_CSV_PATH

    fieldnames = [
        'filename', 'session_id', 'verdict', 'S_composite',
        'S_unprompted', 'S_prompted', 'S_gap', 'S_snr',
        'S_duration', 'S_confidence', 'S_boundary', 'S_continuity',
        'S_decay', 'S_stability', 'ast_z', 'ast_p', 'flags', 'composition_flags',
    ]

    rows = []
    for fname in sorted(all_scores.keys()):
        s = all_scores[fname]
        rows.append({
            'filename': fname,
            'session_id': s.get('session_id', ''),
            'verdict': s.get('verdict', ''),
            'S_composite': _fmt(s.get('S_composite')),
            'S_unprompted': _fmt(s.get('S_unprompted')),
            'S_prompted': _fmt(s.get('S_prompted')),
            'S_gap': _fmt(s.get('S_gap')),
            'S_snr': _fmt(s.get('S_snr')),
            'S_duration': _fmt(s.get('S_duration')),
            'S_confidence': _fmt(s.get('S_confidence')),
            'S_boundary': _fmt(s.get('S_boundary')),
            'S_continuity': _fmt(s.get('S_continuity')),
            'S_decay': _fmt(s.get('S_decay')),
            'S_stability': _fmt(s.get('S_stability')),
            'ast_z': _fmt(s.get('ast_z')),
            'ast_p': _fmt(s.get('ast_p')),
            'flags': '|'.join(s.get('flags', [])),
            'composition_flags': '|'.join(s.get('composition_flags', [])),
        })

    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Composition CSV ({len(rows)} rows): {csv_path}")
    return csv_path


def _fmt(v):
    """Format a score value for CSV: round floats to 4dp, pass None as ''."""
    if v is None:
        return ''
    if isinstance(v, float):
        return round(v, 4)
    return v


def run_stability_pending(wav_dir=None, model_size="medium"):
    """Run D5 stability scoring on PENDING pool items only.

    Loads the PENDING pool from pending_pool.json, loads Whisper, transcribes
    each WAV at multiple temperatures, computes S_stability, updates the
    composition scores, and re-runs compose_decision to reclassify PENDING
    items as ACCEPT or REJECT.

    This is the second pass of the two-pass composition:
      Pass 1 (--compose): score D1-D4, D6-D8 → classify → PENDING pool
      Pass 2 (--stability-pending): score D5 on PENDING → reclassify
    """
    import gc
    if wav_dir is None:
        wav_dir = WAV_DIR

    # Load pending pool
    if not os.path.exists(PENDING_POOL_PATH):
        logger.error(f"No pending pool found at {PENDING_POOL_PATH}. "
                     f"Run --compose first.")
        return
    with open(PENDING_POOL_PATH, 'r', encoding='utf-8') as f:
        pending = json.load(f)
    logger.info(f"Loaded {len(pending)} PENDING items for stability scoring")
    if not pending:
        logger.info("Nothing to score.")
        return

    # Load existing composition scores
    if not os.path.exists(SCORES_PATH):
        logger.error(f"No scores found at {SCORES_PATH}. Run --compose first.")
        return
    with open(SCORES_PATH, 'r', encoding='utf-8') as f:
        all_scores = json.load(f)

    # Load Whisper for multi-temp transcription
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"[{device}] Loading Whisper model ({model_size}) for "
                f"stability scoring...")
    import whisper
    model = whisper.load_model(model_size, device=device)

    # Score D5 for each PENDING item
    updated = 0
    for idx, item in enumerate(pending):
        fname = item['filename']
        wav_path = os.path.join(wav_dir, fname)
        if not os.path.exists(wav_path):
            logger.warning(f"WAV not found: {wav_path}")
            continue
        s_stab = compute_stability_score(wav_path, model)
        if fname in all_scores:
            all_scores[fname]['S_stability'] = s_stab
            updated += 1
        if (idx + 1) % 10 == 0:
            logger.info(f"  Stability scored: {idx+1}/{len(pending)}")

    logger.info(f"Stability scored: {updated}/{len(pending)} items")

    # Free model
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Re-run composition decisions with updated S_stability
    # Need calibration thresholds — reload from existing calibration
    tau_accept, tau_reject = DEFAULT_TAU_ACCEPT, DEFAULT_TAU_REJECT
    if os.path.exists(CALIBRATION_PATH):
        with open(CALIBRATION_PATH, 'r', encoding='utf-8') as f:
            cal = json.load(f)
        tau_accept = cal.get('tau_accept', DEFAULT_TAU_ACCEPT)
        tau_reject = cal.get('tau_reject', DEFAULT_TAU_REJECT)

    # Reclassify
    reclassified = {'ACCEPT': 0, 'PENDING': 0, 'REJECT': 0}
    new_accept, new_pending, new_reject = [], [], []
    for item in pending:
        fname = item['filename']
        scores = all_scores.get(fname, {})
        verdict, composite, flags = compose_decision(scores, tau_accept, tau_reject)
        scores['S_composite'] = composite
        reclassified[verdict] += 1
        entry = {'filename': fname, 'verdict': verdict,
                 'S_composite': composite, 'scores': scores, 'flags': flags}
        if verdict == 'ACCEPT':
            new_accept.append(entry)
        elif verdict == 'PENDING':
            new_pending.append(entry)
        else:
            new_reject.append(entry)

    # Update scores file + CSV
    with open(SCORES_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_scores, f, indent=2, ensure_ascii=False)
    export_composition_csv(all_scores)

    # Update pending pool (only items that stayed PENDING)
    with open(PENDING_POOL_PATH, 'w', encoding='utf-8') as f:
        json.dump(new_pending, f, indent=2, ensure_ascii=False)

    # Append new rejects to rejection log
    if new_reject:
        existing_rejects = []
        if os.path.exists(REJECTION_LOG_PATH):
            with open(REJECTION_LOG_PATH, 'r', encoding='utf-8') as f:
                existing_rejects = json.load(f)
        existing_rejects.extend(new_reject)
        with open(REJECTION_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing_rejects, f, indent=2, ensure_ascii=False)

    logger.info(f"\nStability reclassification:")
    logger.info(f"  {reclassified['ACCEPT']} PENDING → ACCEPT")
    logger.info(f"  {reclassified['PENDING']} remained PENDING")
    logger.info(f"  {reclassified['REJECT']} PENDING → REJECT")


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Selective Data Composer (Stage 4.5)")
    parser.add_argument('--score', action='store_true', default=True,
                        help='Compute all scoring dimensions (default)')
    parser.add_argument('--compose', action='store_true',
                        help='Run composition decisions after scoring')
    parser.add_argument('--stability-pending', action='store_true',
                        help='Run D5 stability scoring on PENDING pool '
                             '(requires Whisper GPU, second pass after --compose)')
    parser.add_argument('--report', action='store_true',
                        help='Generate report from existing scores')
    parser.add_argument('--wav-dir', default=WAV_DIR,
                        help='WAV directory to score')
    parser.add_argument('--metadata', default=METADATA_PATH,
                        help='Metadata file path')
    parser.add_argument('--model', default='medium',
                        choices=['tiny', 'base', 'small', 'medium', 'large'],
                        help='Whisper model for stability scoring (default: medium)')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Selective Data Composer — Stage 4.5")
    logger.info("=" * 60)

    # D5 stability: separate execution path (GPU-heavy, PENDING-only)
    if args.stability_pending:
        run_stability_pending(wav_dir=args.wav_dir, model_size=args.model)
        return

    # Load metadata
    entries = load_metadata(args.metadata)
    logger.info(f"Loaded {len(entries)} metadata entries")

    # Load existing eval results (if available)
    eval_results = load_eval_results()
    if eval_results:
        logger.info(f"Loaded {len(eval_results)} evaluation results")
        # Check if extended scoring is available
        sample = next(iter(eval_results.values()), {})
        has_extended = 'similarity_unprompted' in sample
        if not has_extended:
            logger.warning("Evaluation results lack unprompted scores — "
                          "run evaluate_dataset.py with extended scoring first")
    else:
        logger.warning("No evaluation results found — D1/D6 will use defaults")

    # Discover recording sessions (each raw audio file = one session)
    raw_audio_dir = os.path.join(BASE_DIR, "rawdata", "audio")
    sessions = discover_sessions(raw_audio_dir)
    logger.info(f"Discovered {len(sessions)} recording sessions")

    if args.report and os.path.exists(SCORES_PATH):
        # Report-only mode: load existing scores
        with open(SCORES_PATH, 'r', encoding='utf-8') as f:
            all_scores = json.load(f)
        logger.info(f"Loaded {len(all_scores)} existing scores")
    else:
        # Compute AST baseline per recording session
        logger.info("Computing AST baseline (per-session)...")
        ast_stats = compute_ast_baseline(entries, args.wav_dir, sessions)
        for sess_id, stats in sorted(ast_stats.items()):
            logger.info(f"  {sess_id}: AST mean={stats['mean']:.4f} s/char, "
                       f"std={stats['std']:.4f}, n={stats['n']}")

        # Score all segments
        logger.info("Scoring all segments (D1-D4, D6-D7)...")
        all_scores = score_all_segments(entries, args.wav_dir, eval_results,
                                        ast_stats, sessions)
        logger.info(f"Scored {len(all_scores)} segments")

        # Save scores
        with open(SCORES_PATH, 'w', encoding='utf-8') as f:
            json.dump(all_scores, f, ensure_ascii=False, indent=2)
        logger.info(f"Scores saved to {SCORES_PATH}")

    if args.compose or args.report:
        # Run composition
        logger.info("Running composition decisions...")
        report, accept_list, pending_list, reject_list = run_composition(all_scores)

        # Save reports
        with open(COMPOSITION_REPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"Composition report: {COMPOSITION_REPORT_PATH}")

        with open(PENDING_POOL_PATH, 'w', encoding='utf-8') as f:
            json.dump(pending_list, f, ensure_ascii=False, indent=2)
        logger.info(f"Pending pool ({len(pending_list)} items): {PENDING_POOL_PATH}")

        with open(REJECTION_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(reject_list, f, ensure_ascii=False, indent=2)
        logger.info(f"Rejection log ({len(reject_list)} items): {REJECTION_LOG_PATH}")

        # Summary
        ad = report['audio_duration']
        logger.info(f"\n{'=' * 60}")
        logger.info(f"COMPOSITION COMPLETE")
        logger.info(f"  Total segments: {report['total_segments']}")
        logger.info(f"  ACCEPT: {report['accept_count']} ({report['composition_rate']:.1f}%)")
        logger.info(f"  PENDING: {report['pending_count']}")
        logger.info(f"  REJECT: {report['reject_count']}")
        logger.info(f"  Human review needed: {report['human_review_count']}")
        logger.info(f"  ─── Audio Duration ───")
        logger.info(f"  Total audio:  {ad['total_hours']:.2f}h ({ad['total_seconds']:.0f}s)")
        logger.info(f"  ACCEPT audio: {ad['accept_hours']:.2f}h ({ad['accept_pct']:.1f}%)")
        logger.info(f"  PENDING audio: {ad['pending_hours']:.2f}h")
        logger.info(f"  REJECT audio: {ad['reject_hours']:.2f}h")
        logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
