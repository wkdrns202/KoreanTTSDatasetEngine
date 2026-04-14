# -*- coding: utf-8 -*-
"""
TTS Dataset Pipeline Manager
=============================
End-to-end workflow for Korean TTS dataset preparation.

Pipeline Steps:
  1. DISCOVER - Find raw audio files and matching scripts (orchestrator)
  2. ALIGN    - Delegated entirely to align_and_split.align_and_split().
                That function performs Whisper load, transcription, forward-
                only alignment, WAV slicing, AND Stage 2 post-processing
                (R6 envelope, asymmetric fade, sustained-silence voice offset,
                peak normalization).  pipeline_manager MUST NOT duplicate any
                of this logic — see logs/engineering_note_2026-04-14.md.
  3. VALIDATE - Verify dataset integrity (WAVs <-> metadata)
  4. ORPHANS  - Collect unmatched WAVs -> rawdata/missed audios and script/
  5. REPORT   - Generate timestamped report -> TaskLogs/

Usage:
  python pipeline_manager.py                          # Process all scripts
  python pipeline_manager.py --script 2               # Process Script_2 only
  python pipeline_manager.py --script 2 5             # Process Script_2 and Script_5
  python pipeline_manager.py --reset                  # Clear checkpoints, start fresh
  python pipeline_manager.py --validate-only          # Skip alignment, just validate
  python pipeline_manager.py --collect-orphans        # Validate + move orphan WAVs
  python pipeline_manager.py --model large            # Use larger Whisper model
  python pipeline_manager.py --start-line 201         # Start matching from line 201
"""

import os
import sys
import re
import json
import shutil
import warnings
import datetime
import torch
from pathlib import Path

# Force UTF-8 for stdout/stderr on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

warnings.filterwarnings("ignore")

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except ImportError:
    print("Installing requirements...")
    os.system("pip install openai-whisper pydub static-ffmpeg torch")
    import static_ffmpeg
    static_ffmpeg.add_paths()

# All alignment / splitting / post-processing is implemented in
# align_and_split.py. pipeline_manager is a pure orchestrator — NEVER
# reimplement Stage 1 or Stage 2 logic here. See 2026-04-14 engineering
# note for the incident that made this rule non-negotiable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from align_and_split import align_and_split as _run_align_and_split


# NOTE: Alignment parameters (SEG_SEARCH_WINDOW, SKIP_PENALTY, MATCH_THRESHOLD,
# CONSEC_FAIL_LIMIT, AUDIO_PAD_MS, etc.) live in align_and_split.py. Do NOT
# redeclare them here — the orchestrator must not fork parameter state.


# NOTE: Script parsing lives exclusively in align_and_split.load_script().
# The orchestrator does not read script files — it only checks existence and
# forwards start_line through _run_align_and_split(start_line=...). Any local
# copy of encoding-sniffing logic would fork knowledge and silently drift.


class PipelineManager:
    """Orchestrates the full TTS dataset alignment pipeline."""

    def __init__(self, base_dir, model_size="medium",
                 audio_dir=None, output_dir=None):
        self.base_dir = Path(base_dir)
        self.model_size = model_size
        self.run_timestamp = datetime.datetime.now()

        # Directory structure (supports override for isolated runs)
        self.audio_dir = Path(audio_dir) if audio_dir else (
            self.base_dir / "rawdata" / "audio")
        self.scripts_dir = self.base_dir / "rawdata" / "Scripts"
        self.output_dir = Path(output_dir) if output_dir else (
            self.base_dir / "datasets")
        self.wavs_dir = self.output_dir / "wavs"
        self.script_txt = self.output_dir / "script.txt"
        self.missed_dir = self.base_dir / "rawdata" / "missed audios and script"
        self.missed_targets_dir = self.missed_dir / "TargetScripts"
        self.tasklogs_dir = self.base_dir / "TaskLogs"
        # Checkpoints co-locate with output_dir so independent runs don't collide
        self.checkpoint_dir = self.output_dir

        # Runtime state (no model — align_and_split owns Whisper lifecycle)
        self.all_results = {}       # {script_id: result_dict}
        self.all_skipped = []       # List of skipped line log entries
                                     # (align_and_split writes its own log;
                                     # kept for CLI compat, usually empty)

    # ============================================================
    # STEP 1: DISCOVER
    # ============================================================
    def discover(self, script_ids=None):
        """Find all raw audio files grouped by script ID, with matching scripts.
        Returns (audio_groups, script_files) dicts keyed by script_id (int)."""
        pattern = re.compile(r'Script_(\d+)_(\d+)-(\d+)\.wav')
        audio_groups = {}

        if not self.audio_dir.exists():
            print(f"  [ERROR] Audio directory not found: {self.audio_dir}")
            return {}, {}

        for f in sorted(os.listdir(str(self.audio_dir))):
            match = pattern.match(f)
            if match:
                sid = int(match.group(1))
                if script_ids and sid not in script_ids:
                    continue
                start_line = int(match.group(2))
                end_line = int(match.group(3))
                if sid not in audio_groups:
                    audio_groups[sid] = []
                audio_groups[sid].append((start_line, end_line, self.audio_dir / f))

        # Sort each group by start line
        for sid in audio_groups:
            audio_groups[sid].sort(key=lambda x: x[0])

        # Find matching script text files
        script_files = {}
        if self.scripts_dir.exists():
            for script_file in sorted(os.listdir(str(self.scripts_dir))):
                match = re.match(r'Script_(\d+)_A0\.txt', script_file)
                if match:
                    sid = int(match.group(1))
                    if script_ids and sid not in script_ids:
                        continue
                    script_files[sid] = self.scripts_dir / script_file

        return audio_groups, script_files

    # ============================================================
    # STEP 2: DELEGATED TO align_and_split.align_and_split()
    # ============================================================
    # Whisper loading, transcription, alignment, WAV slicing, and Stage 2
    # post-processing (R6 envelope, asymmetric fade, sustained-silence voice
    # offset, peak normalization) are all implemented inside
    # align_and_split.align_and_split(). The orchestrator simply calls it
    # with the appropriate audio_dir / output_wav_dir overrides and lets the
    # single source of truth handle the actual work.
    #
    # DO NOT add a local Whisper load, alignment loop, or WAV extractor here.
    # If you need to change alignment behavior, edit align_and_split.py.

    # ============================================================
    # STEP 3: ALIGN & SPLIT (core algorithm)
    # ============================================================
    def align_script(self, script_id, audio_files,
                     start_line=1, reset=False):
        """Delegate alignment + split + Stage 2 post-processing to
        align_and_split.align_and_split().

        Returns (matched_count, skipped_entries_list, total_script_lines).

        DEPRECATED PER-SCRIPT ENTRY POINT — kept for test compat but
        pipeline_manager.run() now calls align_and_split ONCE with a full
        list of script_ids via _run_align_and_split_batch(). See the
        2026-04-14 metadata-overwrite incident: per-script iteration caused
        script.txt to be rewritten on each call, discarding prior scripts'
        entries. Only use this method for isolated single-script runs.
        """
        print(f"  Script_{script_id}: delegating to align_and_split "
              f"(audio_dir={self.audio_dir}, output_wav_dir={self.wavs_dir}, "
              f"start_line={start_line})")

        try:
            matched, _, total = _run_align_and_split(
                model_size=self.model_size,
                script_filter=script_id,
                resume=not reset,
                audio_dir=str(self.audio_dir),
                output_wav_dir=str(self.wavs_dir),
                metadata_path=str(self.script_txt),
                start_line=start_line,
            )
        except Exception as e:
            print(f"  [ERROR] align_and_split failed for Script_{script_id}: {e}")
            return 0, [], 0

        rate = (matched / total * 100) if total else 0
        print(f"  Script_{script_id} done: {matched}/{total} ({rate:.1f}%)")
        return matched, [], total

    def _run_align_and_split_batch(self, script_ids, start_line, reset):
        """Single-call delegation covering ALL scripts in this batch.

        This is the correct orchestration: align_and_split is designed to
        process multiple scripts in one run, accumulating metadata into
        script.txt as it goes. Looping per-script and calling it n times
        triggers the metadata-overwrite bug.
        """
        filt = None
        if script_ids:
            filt = script_ids if len(script_ids) > 1 else script_ids[0]
        print(f"  Batch delegation: script_filter={filt}, "
              f"audio_dir={self.audio_dir}, output_wav_dir={self.wavs_dir}")
        try:
            matched, skipped, total = _run_align_and_split(
                model_size=self.model_size,
                script_filter=filt,
                resume=not reset,
                audio_dir=str(self.audio_dir),
                output_wav_dir=str(self.wavs_dir),
                metadata_path=str(self.script_txt),
                start_line=start_line,
            )
        except Exception as e:
            print(f"  [ERROR] align_and_split failed: {e}")
            return 0, 0, 0
        print(f"  Batch done: matched={matched}, skipped={skipped}, "
              f"target_lines={total}")
        return matched, skipped, total

    def _compute_per_script_stats(self, audio_groups):
        """Build self.all_results by parsing script.txt (truth) + audio
        coverage ranges from filenames. Replaces the per-script bookkeeping
        that used to happen in the now-removed alignment loop.

        total_lines is computed from audio coverage (max_audio_line -
        min_audio_line + 1) rather than full script length, so the reported
        rate reflects what was actually reachable given the audio.
        """
        per_script_matched = {}
        if self.script_txt.exists():
            with open(self.script_txt, 'r', encoding='utf-8') as f:
                for line in f:
                    m = re.match(r'Script_(\d+)_', line)
                    if m:
                        sid = int(m.group(1))
                        per_script_matched[sid] = per_script_matched.get(sid, 0) + 1
        for sid, files in audio_groups.items():
            min_line = min(af[0] for af in files)
            max_line = max(af[1] for af in files)
            covered = max_line - min_line + 1
            self.all_results[sid] = {
                'matched': per_script_matched.get(sid, 0),
                'skipped': 0,
                'total_lines': covered,
                'audio_files': len(files),
            }

    # ============================================================
    # (2026-04-14 refactor) The 240-line inline alignment block that
    # previously lived here is gone. It duplicated align_and_split.py
    # without the Stage 2 post-processing, which caused a catastrophic
    # envelope regression on the 2026-04-13 batch. Never reintroduce.
    # ============================================================

    # ============================================================
    # STEP 4: VALIDATE
    # ============================================================
    def validate(self):
        """Check dataset integrity: WAV files <-> metadata entries in script.txt.
        Returns a validation result dict."""
        print("\n" + "=" * 60)
        print("VALIDATION")
        print("=" * 60)

        # Load all metadata entries from script.txt
        meta_files = {}
        if self.script_txt.exists():
            with open(self.script_txt, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if '|' in line:
                        parts = line.split('|', 1)
                        meta_files[parts[0]] = parts[1]

        # Get actual WAV files
        wav_files = set()
        if self.wavs_dir.exists():
            wav_files = {f for f in os.listdir(str(self.wavs_dir))
                         if f.endswith('.wav')}

        meta_set = set(meta_files.keys())
        missing_wav = sorted(meta_set - wav_files)
        orphan_wav = sorted(wav_files - meta_set)

        # Stats by script ID
        script_stats = {}
        for fname in meta_set | wav_files:
            match = re.match(r'Script_(\d+)_', fname)
            if match:
                sid = int(match.group(1))
                if sid not in script_stats:
                    script_stats[sid] = {
                        'meta': 0, 'wav': 0, 'orphan': 0, 'missing': 0
                    }
                if fname in meta_set:
                    script_stats[sid]['meta'] += 1
                if fname in wav_files:
                    script_stats[sid]['wav'] += 1
                if fname in set(orphan_wav):
                    script_stats[sid]['orphan'] += 1
                if fname in set(missing_wav):
                    script_stats[sid]['missing'] += 1

        print(f"\n  Metadata entries:  {len(meta_set)}")
        print(f"  WAV files:         {len(wav_files)}")
        print(f"  Missing WAVs:      {len(missing_wav)}")
        print(f"  Orphan WAVs:       {len(orphan_wav)}")

        print(f"\n  By Script:")
        for sid in sorted(script_stats.keys()):
            s = script_stats[sid]
            status = ""
            if s['orphan'] > 0:
                status += f" ({s['orphan']} orphans)"
            if s['missing'] > 0:
                status += f" ({s['missing']} missing)"
            print(f"    Script_{sid}: {s['meta']} entries, "
                  f"{s['wav']} wavs{status}")

        integrity = ("PASS" if not missing_wav and not orphan_wav
                     else "NEEDS ATTENTION")
        print(f"\n  Integrity: {integrity}")

        return {
            'meta_count': len(meta_set),
            'wav_count': len(wav_files),
            'missing_wav': missing_wav,
            'orphan_wav': orphan_wav,
            'script_stats': script_stats,
            'integrity': integrity
        }

    # ============================================================
    # STEP 5: COLLECT ORPHANS
    # ============================================================
    def collect_orphans(self, orphan_wavs):
        """Move orphan WAVs from datasets/wavs/ to rawdata/missed audios and script/.
        Returns number of files moved."""
        if not orphan_wavs:
            print("\n  No orphan WAVs to collect.")
            return 0

        print(f"\n{'='*60}")
        print(f"COLLECTING ORPHANS -> {self.missed_dir.name}/")
        print(f"{'='*60}")

        self.missed_dir.mkdir(parents=True, exist_ok=True)

        moved = 0
        for wav_name in sorted(orphan_wavs):
            src = self.wavs_dir / wav_name
            dst = self.missed_dir / wav_name
            if src.exists():
                try:
                    shutil.move(str(src), str(dst))
                    moved += 1
                except Exception as e:
                    print(f"  [WARN] Cannot move {wav_name}: {e}")

        print(f"  Moved {moved}/{len(orphan_wavs)} orphan WAVs")
        return moved

    def write_missed_lines(self, skipped_entries):
        """Write missed/skipped script line numbers to a report file
        in rawdata/missed audios and script/ for future recovery."""
        if not skipped_entries:
            return

        self.missed_dir.mkdir(parents=True, exist_ok=True)

        # Group by script ID
        by_script = {}
        for entry in skipped_entries:
            parts = entry.split('|')
            if len(parts) >= 4:
                match = re.match(r'Script_(\d+)_', parts[0])
                if match:
                    sid = int(match.group(1))
                    line_num = int(parts[1])
                    reason = parts[2]
                    text = parts[3]
                    if sid not in by_script:
                        by_script[sid] = []
                    by_script[sid].append((line_num, reason, text))

        for sid, lines in sorted(by_script.items()):
            report_path = (self.missed_dir /
                           f"missed_lines_Script_{sid}.txt")
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(f"# Missed lines from Script_{sid} alignment\n")
                f.write(f"# Generated: {self.run_timestamp:%Y-%m-%d %H:%M}\n")
                f.write(f"# Format: LineNumber|Reason|Text\n")
                f.write(f"# Total: {len(lines)} lines\n\n")
                for line_num, reason, text in sorted(lines, key=lambda x: x[0]):
                    f.write(f"{line_num}|{reason}|{text}\n")
            print(f"  Script_{sid}: {len(lines)} missed lines -> "
                  f"{report_path.name}")

    # ============================================================
    # STEP 6: REPORT
    # ============================================================
    def generate_report(self, validation):
        """Generate a timestamped pipeline report to TaskLogs/."""
        self.tasklogs_dir.mkdir(parents=True, exist_ok=True)

        ts = self.run_timestamp.strftime("%Y%m%d_%H%M%S")
        report_path = self.tasklogs_dir / f"{ts}_pipeline_report.txt"

        lines = []
        lines.append("=" * 80)
        lines.append("TTS DATASET PIPELINE REPORT")
        lines.append("=" * 80)
        lines.append(f"Date: {self.run_timestamp:%Y-%m-%d %H:%M:%S}")
        lines.append(f"Tool: Whisper ASR ({self.model_size} model, CUDA"
                      f" - {torch.cuda.get_device_name(0)})")
        # Pull current alignment config from the authoritative module
        # so the report always reflects align_and_split.py, not a stale copy.
        try:
            import align_and_split as _aas
            lines.append(
                f"Config: window={_aas.SEG_SEARCH_WINDOW}, "
                f"threshold={_aas.MATCH_THRESHOLD}, "
                f"penalty={_aas.SKIP_PENALTY}, "
                f"pad={_aas.AUDIO_PAD_MS}ms, "
                f"preattack={_aas.PREATTACK_SILENCE_MS}ms, "
                f"tail={_aas.TAIL_SILENCE_MS}ms, "
                f"offset_safety={_aas.OFFSET_SAFETY_MS}ms")
        except Exception as e:
            lines.append(f"Config: (unavailable — {e})")
        lines.append("")

        # Alignment results
        if self.all_results:
            lines.append("=" * 80)
            lines.append("ALIGNMENT RESULTS")
            lines.append("=" * 80)

            total_matched = 0
            total_skipped = 0
            total_lines = 0

            for sid in sorted(self.all_results.keys()):
                r = self.all_results[sid]
                total_matched += r['matched']
                total_skipped += r['skipped']
                total_lines += r['total_lines']
                rate = (r['matched'] / r['total_lines'] * 100
                        if r['total_lines'] > 0 else 0)
                lines.append(f"  Script_{sid}:")
                lines.append(f"    Script lines: {r['total_lines']}")
                lines.append(f"    Matched:      {r['matched']}  ({rate:.1f}%)")
                lines.append(f"    Skipped:      {r['skipped']}")
                lines.append(f"    Audio files:  {r['audio_files']}")
                lines.append("")

            overall = (total_matched / total_lines * 100
                       if total_lines > 0 else 0)
            lines.append(f"  TOTAL: {total_matched}/{total_lines} "
                         f"matched ({overall:.1f}%)")
            lines.append(f"         {total_skipped} lines skipped")
            lines.append("")

        # Validation results
        if validation:
            lines.append("=" * 80)
            lines.append("DATASET VALIDATION")
            lines.append("=" * 80)
            lines.append(f"  Metadata entries:  {validation['meta_count']}")
            lines.append(f"  WAV files:         {validation['wav_count']}")
            lines.append(f"  Missing WAVs:      {len(validation['missing_wav'])}")
            lines.append(f"  Orphan WAVs:       {len(validation['orphan_wav'])}")
            lines.append(f"  Integrity:         {validation['integrity']}")

            if validation['orphan_wav']:
                lines.append(f"\n  Orphan WAVs (moved to missed audios):")
                for wav in validation['orphan_wav'][:20]:
                    lines.append(f"    - {wav}")
                if len(validation['orphan_wav']) > 20:
                    lines.append(f"    ... and {len(validation['orphan_wav'])-20} more")

            lines.append("")

        lines.append("=" * 80)

        report_text = "\n".join(lines)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_text)

        print(f"\n  Report: {report_path}")
        return report_path

    # ============================================================
    # PIPELINE ORCHESTRATOR
    # ============================================================
    def run(self, script_ids=None, start_line=1, reset=False,
            validate_only=False, collect_orphans_only=False):
        """Run the full pipeline end-to-end."""
        print("=" * 60)
        print("TTS Dataset Pipeline Manager")
        print("=" * 60)
        print(f"  Base: {self.base_dir}")
        print(f"  Time: {self.run_timestamp:%Y-%m-%d %H:%M:%S}")

        # --validate-only / --collect-orphans: skip alignment
        if validate_only or collect_orphans_only:
            validation = self.validate()
            if collect_orphans_only and validation['orphan_wav']:
                self.collect_orphans(validation['orphan_wav'])
            self.generate_report(validation)
            return

        # Step 1: Discover
        print(f"\n[Step 1/5] Discovering audio files and scripts...")
        audio_groups, script_files = self.discover(script_ids)

        if not audio_groups:
            print("  No audio files found to process.")
            if script_ids:
                print(f"  (Filtered for script IDs: {script_ids})")
            return

        for sid in sorted(audio_groups.keys()):
            files = audio_groups[sid]
            has_script = "OK" if sid in script_files else "MISSING"
            print(f"  Script_{sid}: {len(files)} audio files "
                  f"(script: {has_script})")
            for start, end, path in files:
                print(f"    {path.name}  (lines {start}-{end})")

        # Step 2: SINGLE delegated call to align_and_split covering ALL
        # scripts in this batch. Whisper load, alignment, WAV slicing, and
        # Stage 2 post-processing all happen inside that one call, with
        # metadata accumulated across scripts into a single script.txt.
        #
        # DO NOT iterate per-script here — doing so made align_and_split
        # write script.txt once per call, overwriting each previous
        # script's entries. Incident: 2026-04-14.
        print(f"\n[Step 2/5] Delegating full alignment + Stage 2 post-"
              f"processing to align_and_split (single call)...")

        batch_script_ids = sorted(
            sid for sid in audio_groups.keys() if sid in script_files)
        missing = sorted(set(audio_groups.keys()) - set(batch_script_ids))
        for sid in missing:
            print(f"  [SKIP] Script_{sid}: no script file found")

        if not batch_script_ids:
            print("  No processable scripts in batch.")
            return

        self._run_align_and_split_batch(
            script_ids=batch_script_ids,
            start_line=start_line,
            reset=reset,
        )
        # Rebuild per-script bookkeeping from script.txt (truth after batch)
        self._compute_per_script_stats(
            {sid: audio_groups[sid] for sid in batch_script_ids})

        # Step 3: Validate
        print(f"\n[Step 3/5] Validating dataset...")
        validation = self.validate()

        # Step 4: Collect orphans
        print(f"\n[Step 4/5] Collecting orphan WAVs...")
        if validation['orphan_wav']:
            self.collect_orphans(validation['orphan_wav'])
            self.write_missed_lines(self.all_skipped)
        else:
            print("  No orphans found. Dataset is clean.")

        # Step 5: Report
        print(f"\n[Step 5/5] Generating report...")
        self.generate_report(validation)

        # Final summary
        print("\n" + "=" * 60)
        print("PIPELINE COMPLETE")
        print("=" * 60)
        for sid in sorted(self.all_results.keys()):
            r = self.all_results[sid]
            rate = (r['matched'] / r['total_lines'] * 100
                    if r['total_lines'] > 0 else 0)
            print(f"  Script_{sid}: {r['matched']}/{r['total_lines']} "
                  f"({rate:.1f}%)")

        total_m = sum(r['matched'] for r in self.all_results.values())
        total_l = sum(r['total_lines'] for r in self.all_results.values())
        if total_l > 0:
            print(f"\n  Overall: {total_m}/{total_l} "
                  f"({total_m/total_l*100:.1f}%)")
        print(f"  Orphans collected: {len(validation.get('orphan_wav', []))}")
        print(f"  Skipped lines report: "
              f"{'written' if self.all_skipped else 'none'}")
        print("=" * 60)


# ============================================================
# CLI ENTRY POINT
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="TTS Dataset Pipeline Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline_manager.py                    Process all scripts
  python pipeline_manager.py --script 2         Process Script_2 only
  python pipeline_manager.py --script 2 5       Process Script_2 and 5
  python pipeline_manager.py --reset            Clear checkpoints, fresh start
  python pipeline_manager.py --validate-only    Just validate dataset
  python pipeline_manager.py --collect-orphans  Validate + move orphan WAVs
  python pipeline_manager.py --model large      Use larger Whisper model
  python pipeline_manager.py --start-line 201   Start matching from line 201
        """
    )
    parser.add_argument(
        "--script", nargs="+", type=int, default=None,
        help="Script IDs to process (default: all)")
    parser.add_argument(
        "--model", default="medium",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: medium)")
    parser.add_argument(
        "--start-line", type=int, default=1,
        help="Start matching from this script line (default: 1)")
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear checkpoints and start fresh")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Skip alignment, just validate dataset integrity")
    parser.add_argument(
        "--collect-orphans", action="store_true",
        help="Validate and collect orphan WAVs to missed audios folder")
    parser.add_argument(
        "--audio-dir", default=None,
        help="Override audio input directory (default: rawdata/audio)")
    parser.add_argument(
        "--output-dir", default=None,
        help="Override output directory (default: datasets). "
             "Use this to write to a versioned subdir without touching base datasets/")

    args = parser.parse_args()

    base_dir = Path(__file__).parent.parent
    manager = PipelineManager(
        base_dir, model_size=args.model,
        audio_dir=args.audio_dir, output_dir=args.output_dir,
    )
    manager.run(
        script_ids=args.script,
        start_line=args.start_line,
        reset=args.reset,
        validate_only=args.validate_only,
        collect_orphans_only=args.collect_orphans
    )
