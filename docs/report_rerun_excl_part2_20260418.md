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

## Stage 4.5 Results (v1 — HEAD gradient 활성 상태)

| 항목 | 값 |
|------|-----|
| ACCEPT | 4,793 (88.1%) |
| REJECT | 650 |
| PENDING | 0 (calibration 역전으로 소멸) |
| ACCEPT 오디오 | 9.70h |
| tau_accept | 0.6441 |
| tau_reject | 0.8325 (역전) |

### Reject 원인 분석

| 원인 | 건수 |
|------|------|
| hard_reject:S_unprompted | 262 |
| S_decay < 0.5 (기하평균 추락) | 409 |
| - D9만 문제 (다른 차원 OK) | 295 |
| - D9 + 다른 이슈 | 114 |
| AST_anomaly_fast | 209 |
| formal_ending_truncation_risk | 35 |

## Lessons Learned

### 1. D9 HEAD gradient 대량 오탐

**증상**: S_decay=0.0인 409건 중 상당수가 TAIL이 아닌 **HEAD gradient** 때문에 reject.

**원인**: HEAD scan이 first_signal에서 730ms 전방까지 스캔하여, speech 본문 내부의 자연 에너지 변동(단어 간 pause 후 재개)을 cliff truncation으로 오탐. 예: Script_1_0091.wav — 본문 1000ms 지점에서 -120dB→-49.9dB 전환(14.01 dB/ms)이 cliff로 판정됨.

**근본 문제**: 음성 onset은 무음→발화 전환이므로 급격한 positive gradient가 자연스러운 현상. HEAD gradient 검출 자체가 부적합.

**해결**: D9 HEAD gradient 비활성화 (v2). Head 잘림은 Stage 2의 ONSET_SAFETY_MS=320 + PRESPEECH_PAD=100(합계 420ms)이 이미 방지.

### 2. D8 S_continuity 610ms gap 미감지

Script_1_0066.wav: 610ms gap 뒤 이웃 문장 혼입(-25dB speech 재등장). CONTINUITY_GAP_MS=730ms 기준에 미달하여 S_continuity=1.0으로 통과. D9가 부수적으로 감지(body_end≈last_signal → span=0). 향후 gap threshold 하향 검토 필요.

### 3. Calibration 역전 (PENDING 소멸)

tau_accept(0.6441) < tau_reject(0.8325) → PENDING 구간 없음. known_bad의 composite가 높아서(unprompted만 낮고 나머지 OK) 역전 발생. 역전 방지 guard 추가 필요.

### 4. evaluate_dataset 선행 필수

Stage 4.5를 evaluate 없이 돌리면 D1/D6이 기본값 0.5 → calibration 비정상(tau_accept=0.0501) → 사실상 필터 미작동. **반드시 evaluate → composer 순서 준수.**

## Stage 4.5 Results (v2 — HEAD gradient 비활성화)

| 항목 | v1 | v2 | 변화 |
|------|-----|-----|------|
| tau_accept | 0.6441 | **0.7441** | threshold 정상화 |
| tau_reject | 0.8325 | 0.8395 | |
| ACCEPT | 4,793 (88.1%) | **4,786 (87.9%)** | -7 |
| REJECT | 650 | 657 | +7 |
| D9 rejects | 409 | **395** | -14 복구 |
| D9-only rejects | 295 | **285** | -10 복구 |
| ACCEPT 오디오 | 9.70h | 9.69h | |

HEAD 비활성화로 D9 오탐 14건 복구, threshold 0.10 상승으로 일부 상쇄.
핵심 개선: calibration threshold 정상화 (0.6441 → 0.7441).

## Output

- Directory: `datasets/rerun_excl_part2/`
- WAVs: `datasets/rerun_excl_part2/wavs/`
- Metadata: `datasets/rerun_excl_part2/script.txt`
- Pipeline report: `TaskLogs/20260417_230005_pipeline_report.txt`
- Composition v1: `logs/composition_results_v1.csv` (HEAD 활성)
- Composition v2: `logs/composition_results.csv` (HEAD 비활성, 최신)
