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
EVAL_CHECKPOINT_PATH = os.path.join(LOG_DIR, "eval_checkpoint.json")

# AST (Average Spoken Time) parameters
AST_SAMPLE_SIZE = 50          # Random sample size for baseline
AST_SIGNIFICANCE = 0.05       # p-value threshold
AST_Z_CAP = 3.0              # z-score cap for score mapping

# SNR reference
SNR_REFERENCE_DB = 40.0       # Score saturates at this SNR

# Boundary scoring
SILENCE_THRESHOLD_DB = -40
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
            encoding='utf-8', mode='w'
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
    for f in sorted(os.listdir(raw_audio_dir)):
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
                info = sf.info(wav_path)
                duration = info.duration
                if duration < 0.1:
                    continue
                chars = count_characters(entry['ground_truth'])
                if chars == 0:
                    continue
                ast_values.append(duration / chars)  # seconds per character
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
        info = sf.info(wav_path)
        duration = info.duration
        if duration < 0.1:
            return 0.0, 0.0, 1.0, ['zero_duration']

        chars = count_characters(gt_text)
        if chars == 0:
            return 0.5, 0.0, 1.0, ['no_chars']

        segment_ast = duration / chars  # seconds per character

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

    # Composite: geometric mean of D1-D4, D6-D7 (D5 stability is optional gate)
    core_scores = [
        scores.get('S_unprompted', 0.5),
        scores.get('S_gap', 0.5),
        scores.get('S_snr', 0.5),
        scores.get('S_duration', 0.5),
        scores.get('S_confidence', 0.5),
        scores.get('S_boundary', 0.5),
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
def load_metadata(metadata_path=METADATA_PATH):
    """Load script.txt → list of {filename, ground_truth}."""
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


def load_eval_results(checkpoint_path=EVAL_CHECKPOINT_PATH):
    """Load evaluation checkpoint for existing prompted/unprompted scores."""
    if not os.path.exists(checkpoint_path):
        return {}
    with open(checkpoint_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # Index by filename
    results = {}
    for r in data.get('results', []):
        results[r['filename']] = r
    return results


def score_all_segments(metadata_entries, wav_dir=WAV_DIR, eval_results=None,
                       ast_stats=None, sessions=None):
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

        # --- D7: S_boundary ---
        try:
            samples, sr = sf.read(wav_path, dtype='float64')
            if samples.ndim > 1:
                samples = samples[:, 0]
            scores['S_boundary'] = compute_boundary_score(samples, sr)
        except Exception:
            scores['S_boundary'] = 0.0

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
    for dim in ['S_unprompted', 'S_gap', 'S_snr', 'S_duration', 'S_confidence', 'S_boundary']:
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

    report = {
        'timestamp': datetime.datetime.now().isoformat(),
        'total_segments': total,
        'accept_count': len(accept_list),
        'pending_count': len(pending_list),
        'reject_count': len(reject_list),
        'composition_rate': round(composition_rate, 2),
        'calibration': calibration,
        'dimension_statistics': dim_stats,
        'per_script_breakdown': dict(script_breakdown),
        'human_review_count': sum(1 for s in all_scores.values()
                                  if 'HUMAN_REVIEW_NEEDED' in s.get('flags', [])),
    }

    return report, accept_list, pending_list, reject_list


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Selective Data Composer (Stage 4.5)")
    parser.add_argument('--score', action='store_true', default=True,
                        help='Compute all scoring dimensions (default)')
    parser.add_argument('--compose', action='store_true',
                        help='Run composition decisions after scoring')
    parser.add_argument('--report', action='store_true',
                        help='Generate report from existing scores')
    parser.add_argument('--wav-dir', default=WAV_DIR,
                        help='WAV directory to score')
    parser.add_argument('--metadata', default=METADATA_PATH,
                        help='Metadata file path')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Selective Data Composer — Stage 4.5")
    logger.info("=" * 60)

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
        logger.info(f"\n{'=' * 60}")
        logger.info(f"COMPOSITION COMPLETE")
        logger.info(f"  Total segments: {report['total_segments']}")
        logger.info(f"  ACCEPT: {report['accept_count']} ({report['composition_rate']:.1f}%)")
        logger.info(f"  PENDING: {report['pending_count']}")
        logger.info(f"  REJECT: {report['reject_count']}")
        logger.info(f"  Human review needed: {report['human_review_count']}")
        logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
