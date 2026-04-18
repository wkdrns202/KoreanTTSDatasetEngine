# Rerun Pipeline Report — Part2 Exclusion

**Date**: 2026-04-18
**Pipeline start**: 2026-04-17 22:58
**Pipeline end**: 2026-04-18 00:54 (Stage 2 complete)
**Total wall time**: ~116min (1h 56m)

## Objective

Part1(3,805 WAVs, 7.49h)에서 끝음절 truncation 발생 → Part2 ACCEPT 1,410라인을 제외하고 raw audio부터 전체 재처리. D9 S_decay(변화율 기반 절삭 검출) 포함 최신 9차원 파이프라인 적용.

## Exclusion Summary

| Script | Total Lines | Part2 Excluded | Audio Cover | Target Lines |
|--------|-------------|----------------|-------------|--------------|
| S1     | 984         | 642 (301-984)  | 1-984       | 342          |
| S2     | 1,416       | 0              | 1-1416      | 1,416        |
| S3     | 878         | 0              | 1-878       | 878          |
| S4     | 1,005       | 0              | 1-1005      | 1,005        |
| S5     | 1,019       | 447 (542-1019) | 1-1019      | 572          |
| S6     | 1,000       | 321 (1-329)    | 1-330       | 9            |
| **Sum**| **6,302**   | **1,410**      | —           | **4,222**    |

## Pipeline Results (Stage 1+2)

| Script | Matched | Target | Rate   |
|--------|---------|--------|--------|
| S1     | 309     | 342    | 90.4%  |
| S2     | 1,308   | 1,416  | 92.4%  |
| S3     | 873     | 878    | 99.4%  |
| S4     | 998     | 1,005  | 99.3%  |
| S5     | 544     | 572    | 95.1%  |
| S6     | 1       | 9      | 11.1%  |
| **Sum**| **4,033** | **4,222** | **95.5%** |

- Skipped: 189 lines
- Stage 2 errors: 0
- Orphan WAVs: 0
- Integrity: PASS

## Part2 Merge

- Part2 WAVs copied: 1,410
- Part2 metadata appended: 1,410 entries
- script.txt sorted by Script_N_LLLL order

## Integrated Dataset

| Metric        | Value          |
|---------------|----------------|
| WAV files     | 5,443          |
| Script lines  | 5,443          |
| Orphans       | 0              |
| Total audio   | 10.71h (38,560s) |
| 10h target    | 107.1% reached |

## Configuration

```
Model: Whisper medium (CUDA, RTX 3060 Ti)
SEG_SEARCH_WINDOW = 25
MATCH_THRESHOLD = 0.50
AUDIO_PAD_MS = 320
ONSET_SAFETY_MS = 320
OFFSET_SAFETY_MS = 120
SUSTAINED_SILENCE_MS = 730
PREATTACK_SILENCE_MS = 400
TAIL_SILENCE_MS = 730
FADE_MS = 3 (in) / 30 (out)
PRESPEECH_PAD_MS = 100
POSTSPEECH_PAD_MS = 700
```

## Output

- Directory: `datasets/rerun_excl_part2/`
- WAVs: `datasets/rerun_excl_part2/wavs/`
- Metadata: `datasets/rerun_excl_part2/script.txt`
- Pipeline report: `TaskLogs/20260417_230005_pipeline_report.txt`

## Next Step

Stage 4.5 (selective_composer) — D1-D9 9-dimension quality scoring on the integrated 5,443 WAVs.
