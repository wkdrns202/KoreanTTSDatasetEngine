# -*- coding: utf-8 -*-
"""
One-shot recovery script for 2026-04-14 refactored pipeline run.

Context:
  pipeline_manager called align_and_split 3x (once per script). Each call
  overwrote datasets/2026-04-14_refactored_run/script.txt with only its own
  entries. Only the last call (S6) survived. Step 4 then misclassified the
  valid S1+S5 WAVs as orphans and moved them to rawdata/missed audios/.

Recovery (no re-alignment needed):
  1. Move Script_1/Script_5 WAVs back from missed audios/ to the output wavs/
  2. Reconstruct metadata entries from filename line numbers + original
     Scripts/Script_N_A0.txt text, APPEND to existing S6-only script.txt
"""
import os
import re
import shutil
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = r"G:\Projects\AI_Research\TTSDataSetCleanser"
MISSED_DIR = os.path.join(BASE, "rawdata", "missed audios and script")
OUT_DIR = os.path.join(BASE, "datasets", "2026-04-14_refactored_run")
OUT_WAVS = os.path.join(OUT_DIR, "wavs")
OUT_META = os.path.join(OUT_DIR, "script.txt")
SCRIPTS_DIR = os.path.join(BASE, "rawdata", "Scripts")

PATTERN = re.compile(r'^Script_([1-9]\d*)_(\d+)\.wav$')


def load_script(script_no):
    """Load rawdata/Scripts/Script_N_A0.txt into {line_num: text}."""
    path = os.path.join(SCRIPTS_DIR, f"Script_{script_no}_A0.txt")
    for enc in ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr'):
        try:
            with open(path, 'r', encoding=enc) as f:
                lines = [ln.rstrip('\n').strip() for ln in f]
            out = {}
            n = 0
            for ln in lines:
                if not ln:
                    continue
                n += 1
                out[n] = ln
            return out
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Cannot decode {path}")


def main():
    # Collect Script_1 / Script_5 WAVs from missed audios
    to_recover = []  # list of (filename, script_no, line_no)
    for fname in sorted(os.listdir(MISSED_DIR)):
        m = PATTERN.match(fname)
        if not m:
            continue
        sno = int(m.group(1))
        if sno not in (1, 5):
            continue
        ln = int(m.group(2))
        to_recover.append((fname, sno, ln))
    print(f"Found {len(to_recover)} WAVs to recover")

    # Load scripts
    scripts = {1: load_script(1), 5: load_script(5)}
    for sno, d in scripts.items():
        print(f"  Script_{sno}: {len(d)} lines loaded")

    # Move WAVs back + collect metadata entries
    os.makedirs(OUT_WAVS, exist_ok=True)
    new_entries = []
    moved = 0
    missing_line = []
    dup_collision = []
    for fname, sno, ln in to_recover:
        src = os.path.join(MISSED_DIR, fname)
        dst = os.path.join(OUT_WAVS, fname)
        if os.path.exists(dst):
            dup_collision.append(fname)
            continue
        text = scripts[sno].get(ln)
        if text is None:
            missing_line.append((fname, sno, ln))
            continue
        shutil.move(src, dst)
        new_entries.append(f"{fname}|{text}")
        moved += 1

    print(f"\nMoved: {moved}")
    print(f"Collisions (already in wavs/): {len(dup_collision)}")
    print(f"Missing line in script: {len(missing_line)}")
    if missing_line[:5]:
        for x in missing_line[:5]:
            print(f"  {x}")

    # Read existing script.txt (S6 entries) and append
    existing_keys = set()
    existing_lines = []
    if os.path.exists(OUT_META):
        with open(OUT_META, 'r', encoding='utf-8') as f:
            for ln in f:
                ln = ln.rstrip('\n')
                if '|' in ln:
                    existing_lines.append(ln)
                    existing_keys.add(ln.split('|', 1)[0])
    print(f"\nExisting metadata entries (S6): {len(existing_lines)}")

    # Merge + dedupe
    added = 0
    for entry in new_entries:
        k = entry.split('|', 1)[0]
        if k in existing_keys:
            continue
        existing_lines.append(entry)
        existing_keys.add(k)
        added += 1

    # Sort for reproducibility
    existing_lines.sort()

    # Write back
    with open(OUT_META, 'w', encoding='utf-8') as f:
        for ln in existing_lines:
            f.write(ln + "\n")

    print(f"Appended: {added}")
    print(f"Final metadata entries: {len(existing_lines)}")
    print(f"\nFinal state:")
    print(f"  {OUT_WAVS}: {len(os.listdir(OUT_WAVS))} WAVs")
    print(f"  {OUT_META}: {len(existing_lines)} entries")


if __name__ == "__main__":
    main()
