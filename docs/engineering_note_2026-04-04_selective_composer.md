# Engineering Note — 2026-04-04 (2/2)

## Selective Data Composer: SAM-inspired Confidence-based Dataset Admission

---

## 1. Motivation

파이프라인이 R1-R6를 충족(95.4%)했지만 두 가지 근본 한계가 존재:
1. **평가 신뢰도**: GT-prompted Whisper가 truncation을 마스킹 (similarity=1.0인데 실제로 끝음절 잘림)
2. **최적화 천장**: 잔존 실패 95%가 Whisper 한국어 인식 한계 (Type D)

SAM(Segment Anything Model, Meta AI)의 핵심 인사이트를 차용:
- SAM의 99.1%는 모델 정확도가 아니라 **dataset composition rate**
- 많이 생성 → 신뢰도 높은 것만 편입 → 신뢰할 수 있는 학습 데이터

---

## 2. Architecture: 7-Dimension Scoring

`src/selective_composer.py` — Stage 4.5로 파이프라인에 삽입

### Textual Fidelity
- **D1 (S_unprompted)**: GT prompt 없이 Whisper transcribe → 편향 없는 유사도
- **D2 (S_gap)**: prompted vs unprompted 격차 → truncation 마스킹 탐지
- **D6 (S_confidence)**: Whisper avg_logprob → 모델 자체 불확실성

### Acoustic Integrity
- **D3 (S_snr)**: 음성 구간 vs 무음 구간 SNR
- **D7 (S_boundary)**: R2/R6 이진 판정을 [0,1] 연속 점수로 확장

### Structural Consistency
- **D4 (S_duration)**: AST 기반 발화시간 이상치 탐지 (핵심, 아래 상세)
- **D5 (S_stability)**: 온도 변동 전사 안정성 (PENDING 대상 on-demand, 미구현)

---

## 3. AST (Average Spoken Time) 알고리즘 — 설계 과정

### 3-1. 초안: 단어(word) 기반, 스크립트 단위

**아이디어**: 랜덤 50개 WAV에서 단어당 평균 발화시간(AST)을 추출, 대상 WAV의 AST가 p<0.05로 유의미하게 벗어나면 이상치 판정.

**문제 발견**: Script_2_1416.wav가 z=19.34로 극단 이상치 1위. 원인 조사 결과 metadata에 `// 영어 코멘트`가 포함되어 word count가 7→33으로 부풀려짐.
→ `strip_comments()` 추가로 `//` 이후 제거.

### 3-2. 개선 1: 녹음 세션(recording session) 단위

**관찰**: 같은 스크립트라도 녹음 세션(raw audio file)에 따라 화자의 톤/페이스가 다름.
- Script_3_1-404: mean 1.768 words/s
- Script_3_405-878: mean 1.678 words/s (같은 Script_3인데 0.09 차이)

**수정**: raw audio file 1개 = 1 recording session으로 정의. 세션별 AST baseline 계산.
→ 세션 레벨이 15건 더 많은 이상치를 포착.

### 3-3. 개선 2: 단어 → 글자(character) 기반

**문제 발견**: 한국어는 교착어(agglutinative). "준비되셨나요?"는 1단어이지만 6음절.
"네"도 1단어이지만 1음절. 단어 수는 발화시간과 잘 대응되지 않음.

**수정**: `count_characters()` — 한글 음절 + 영숫자만 카운트, 공백/구두점 제외.
→ REJECT 74→87건, PENDING 179→159건. 더 정밀한 이상치 포착 + 노이즈성 flagging 감소.

### 3-4. 개선 3: chars/s → s/char (seconds per character)

**문제**: "characters per second"는 "얼마나 빨리 말하나"를 측정.
올바른 질문은 **"한 글자를 발화하는 데 얼마나 걸리나"** — 즉 s/char.

**최종 정의**:
```
AST = duration_seconds / character_count    (seconds per character)
```

**z-score 해석**:
- z > 0: 세션 평균보다 s/char이 큼 → **slow** (글자당 시간이 더 오래 걸림)
- z < 0: 세션 평균보다 s/char이 작음 → **fast** (글자당 시간이 짧음 → truncation 의심)
- formal ending + z < -1.5 → `formal_ending_truncation_risk`

---

## 4. Composition Decision Logic

### Composite Score
```
S_composite = geometric_mean(S_unprompted, S_gap, S_snr, S_duration, S_confidence, S_boundary)
```

기하평균: 6개 차원 중 1개라도 낮으면 전체를 강하게 끌어내림.

### Threshold Calibration (Bootstrap)
- Known-good: S_unprompted ≥ 0.95 AND S_gap ≥ 0.90
- 5th percentile of known-good → tau_accept (~0.768)
- 95th percentile of known-bad → tau_reject (0.65)
- Bootstrap 1000회로 신뢰구간 산출

### Decision
```
Hard reject: S_unprompted < 0.50 OR S_gap < 0.50 OR S_snr < 0.30
ACCEPT:  S_composite >= 0.768
PENDING: S_composite >= 0.650
REJECT:  S_composite <  0.650
```

---

## 5. Final Results (2026-04-04)

| Metric | Value |
|--------|-------|
| Total segments | 4,176 |
| **ACCEPT** | 3,930 (94.1%) |
| **PENDING** | 159 (3.8%) |
| **REJECT** | 87 (2.1%) |
| Human review needed | 183 |

### REJECT breakdown (87건)
- **slow (76건, 87%)**: 글자 대비 오디오가 너무 긴 — 과도한 silence, alignment 오류, 화자 페이스 이상
- **fast (11건, 13%)**: 글자 대비 오디오가 너무 짧은 — truncation 의심

### Per-session AST baseline (s/char)
| Session | mean | std | n |
|---------|------|-----|---|
| Script_1_1-122 | 0.1916 | 0.0112 | 122 |
| Script_2_1-162 | 0.2111 | 0.0336 | 157 |
| Script_2_163-473 | 0.2170 | 0.0400 | 275 |
| Script_3_1-404 | 0.2029 | 0.0152 | 404 |
| Script_4_1-100 | 0.1830 | 0.0092 | 97 |
| Script_5_542-800 | 0.2233 | 0.0347 | 252 |

---

## 6. Lessons Learned

1. **Metadata 위생**: GT 텍스트에 편집 코멘트(`//`)가 4건 있었음 → AST 계산 오염. 전처리 필수.
2. **세션 단위 baseline**: 스크립트 단위보다 녹음 세션 단위가 화자의 실제 페이스를 더 정확히 반영.
3. **한국어는 글자 기반**: 교착어 특성상 단어 수는 발화시간과 낮은 상관. 음절/글자 수가 훨씬 정확.
4. **s/char > chars/s**: "한 글자에 몇 초"가 "초당 몇 글자"보다 직관적이고 분포가 더 대칭적.
5. **Slow 이상치가 대다수**: REJECT 87건 중 76건이 slow — alignment 시 과도한 silence 포함이 주 원인.

---

## 7. Files

| File | Role |
|------|------|
| `src/selective_composer.py` | 핵심 엔진: 7차원 scoring + AST 통계 검정 + composition decision |
| `src/evaluate_dataset.py` | 수정: 항상 prompted+unprompted 실행, Whisper metadata 추출 |
| `logs/composition_results_20260404.csv` | 전체 4,176 segments 점수 + verdict |
| `logs/reject_list_20260404.csv` | REJECT 87건 상세 (GT 포함) |
| `logs/composition_report.json` | 통계 요약, threshold, per-script breakdown |
| `logs/composition_parameter_dictionary.md` | 파라미터 사전 |

---

## 8. Next Steps

1. **D5 Stability**: PENDING 159건에 대해 temperature 변동 전사 안정성 검사 실행
2. **evaluate_dataset.py 재실행**: extended scoring (prompted+unprompted 모두)으로 D1/D2 정확도 향상
3. **음소(phoneme) 단위 확장**: 글자 → 음소로 좁혀서 화자의 음소별 발화 프로파일 구축
4. **REJECT 청취 검증**: 87건 수동 spot-check → false positive rate 측정
