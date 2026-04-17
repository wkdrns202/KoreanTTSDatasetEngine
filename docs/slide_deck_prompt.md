# TTS Dataset Auto-Cleansing Pipeline: From Whisper Alignment to SAM-Inspired Data Engine

> 슬라이드 생성 도구(Gamma AI / Genspark)용 프롬프트
> 전체 약 40슬라이드 구성 | 톤: 연구 발표 (학술+엔지니어링) | 언어: 한국어 중심, 기술 용어 영문 병기
>
> **첨부 다이어그램 (논문용 흑백 도식)**:
> - `docs/diagram_pipeline_overview.png` — 전체 파이프라인 + 필터링 흐름도
> - `docs/diagram_composer_decision.png` — Selective Composer 판정 알고리즘
> - `docs/diagram_ast_algorithm.png` — D4 AST 발화길이 이상치 감지 알고리즘
> - `docs/sustained_silence_algorithm.png` — Sustained Silence Verification 알고리즘

---

## Slide 1 — 표지

**제목**: ASR(Whisper) 기반 한국어 TTS 데이터셋 자동 정제 파이프라인
**발표자**: 천영재

---

## Slide 2 — 왜 이 연구를 시작했나?

**핵심 질문**: 성우의 장시간 녹음을 어떻게 TTS 학습용 세그먼트로 자동 분할할 것인가?

- 수작업 정렬: 1시간 녹음 = 수일 소요, 비용 과다, 일관성 보장 불가
- 기존 도구(MFA 등): 한국어 음운변화(연음, 경음화, 비음화)에 취약 -> 한국어 특화 도구는 없으므로 직접 개발 필요.
- 목표: Whisper 등 ASR을 활용한 **완전 자동화** 파이프라인 구축
- 대상 데이터: 5개 스크립트, ~8.2시간, 48kHz/24bit 전문 성우 녹음

---

## Slide 3 — 초기 결과: 35% (처참)

- Whisper medium 기본 설정으로 첫 정렬 시도
- **정렬 정확도: ~35%** — 10시간 중 6시간 이상을 버려야 하는 정확도. 사용가치 없었음.
- 주요 실패 원인:
  - 한국어 조사/어미 패턴이 유사 → false match 연쇄
  - 검색 윈도우 과대 시(너무 넓은 범위 탐색시) 오정렬 누적
  - Whisper 디코딩 불안정성

> "한국어 학습용 데이터 셋의 레이블링 자동화는 불가능한가?" → 이 수요에서 연구 시작

---

## Slide 4 — 파이프라인 아키텍처 개요

> **[도식 삽입: `docs/diagram_pipeline_overview.png`]**

```
Stage 1: Align & Split     Whisper 전사 + 텍스트 매칭 + WAV 분할
     ↓
Stage 2: Post-process       Zero-crossing snap, fade, R6 envelope
     ↓
Stage 3: Validate           각 WAV 재전사 (Tier1: medium → Tier2: large)
     ↓
Stage 4: Evaluate           6개 품질 요건 집계 (R1~R6)
     ↓
Stage 4.5: Selective Compose  7차원 품질 스코어링 (SAM-inspired)
     ↓
Stage 5: Finalize           전 요건 충족 시 데이터셋 확정
```

---

## Slide 5 — Stage 1 핵심 설계: Forward-Only Greedy Search

- **Forward-only search**: 후방 탐색 금지 (한국어 false-match 연쇄 방지)
- **SEG_SEARCH_WINDOW = 25줄**: 100~500줄은 오정렬 유발
- **MAX_MERGE = 5**: Whisper 세그먼트 최대 5개 병합 허용
- **MATCH_THRESHOLD = 0.50**: 유사도 최소 기준
- **Re-sync**: 연속 10회 실패 시 75줄 윈도우로 재동기화

---

## Slide 6 — Stage 2 핵심 설계: R6 오디오 엔벨로프

- **Pre-attack silence**: 400ms (TTS 모델 onset 학습용)
- **Tail silence**: 730ms (자연스러운 발화 종료감)
- **Onset safety**: 30ms (자음 공격음 보존)
- **Offset safety**: 120ms (한국어 어미 감쇠 보존)
- **비대칭 fade**: fade-in 10ms / fade-out 5ms
- **Sustained silence verification**: 1000ms 연속 무음 확인

---

## Slide 7 — 품질 요건 정의 (R1~R6)

| 요건 | 정의 | 기준 |
|------|------|------|
| R1 | Whisper 재전사 유사도 | >= 95% |
| R2 | 경계 노이즈 무결 | >= 95% |
| R3 | R1 AND R2 복합 통과 | >= 95% |
| R4 | 메타데이터 무결성 (파일명, 텍스트, 포맷) | 100% |
| R5 | 재현성 (동일 입력 → 동일 출력) | TRUE |
| R6 | R6 엔벨로프 규격 준수 | >= 95% |

---

## Slide 8 — 파이프라인 R1 이터레이션: 34.7% → 95.48%

전체 파이프라인 (Stage 1~4)의 R1 정확도 진화:

| Iter | 날짜 | R1 | 주요 변경 |
|------|------|-----|-----------|
| 1 | 02-08 | **34.7%** | 베이스라인 (MATCH_THRESHOLD=0.25, medium) |
| 2 | 02-08 | **64.3%** | **GT-prompting 도입** + best-of-2 (+29.6%p) |
| 3 | 02-09 | 69.7% | Tier 2 (Whisper large) 부분 적용 |
| 4c | 02-09 | ~72% | Match confirmation 도입 |
| 5 | 02-09 | **67.8%** | **Inline verification → 역효과 (-4.2%p)** |
| 6 | 02-09 | 미완 | Tier 1을 Whisper large로 전환 시도 |
| 7 | 02-20 | **95.48%** | Audio bleed 수정 + 메타데이터 버그 픽스 |

**핵심 전환점**:
- Iter 1→2: GT-prompting이 정확도를 **2배로** (핵심 돌파구)
- Iter 4→5: Inline verification의 역효과 발견 (교훈)
- Iter 6→7: Audio bleed 수정으로 최종 95% 돌파

---

## Slide 9 — 주요 발견 #1: Inline Verification의 역설

**발견**: 직관적으로 좋아 보이는 "추출 후 재검증" 단계가 오히려 성능을 악화시킴

- Iter 5에서 inline verification 도입 → R1: 72% → **67.8%** (-4.2%p)
- 원인 체인:
  1. 추출 클립을 재전사해 sim < 0.40인 경우 reject
  2. 한국어는 흔한 조사/어미로 baseline sim이 이미 0.30~0.40
  3. reject 시 script pointer가 advance하지 않음 → **오디오 세그먼트 낭비**
  4. pointer가 정체되다가 re-sync 발동 → 좋은 라인을 건너뜀
  5. 결과: 수량 감소 + 품질 저하 (양쪽 모두 나빠짐)

**교훈**: "추가 검증"은 정렬 흐름을 방해할 수 있다. 재검증 로직은 **pointer 진행과 분리**해야 한다.

---

## Slide 10 — 주요 발견 #2: align_and_split 내부의 temperature=0 재앙

**별개의 실험**: Stage 1 내부 매칭률을 최적화하던 중 발견 (R1과 다른 메트릭)

| Iter | Stage 1 매칭률 | 주요 변경 |
|------|---------------|-----------|
| 1 | 92.8% | 베이스라인 |
| 2 | 94.6% | re-sync 도입 |
| 3 | 92.1% | frozen pointer 버그 (회귀) |
| **4** | **86.3%** | **temperature=0 도입 → Script_4가 97.5%→60.1%로 붕괴** |
| 5 | **96.0%** | temperature=0 제거, default fallback 복원 |

**Script_4 붕괴 원인**:
- 한국어 음운변화(연음, 경음화, 비음화)는 확률적 디코딩이 필수
- 예: "독립"→[동닙], "같이"→[가치], "먹는"→[멍는]
- temperature=0은 분포를 delta function으로 축소 → 변형 경로 차단
- Script_4(교육 콘텐츠)가 한자어·용언 활용이 많아 특히 치명적

**교훈**: "결정론적으로 안정화"는 언어 특성에 따라 재앙이 될 수 있다.

---

## Slide 11 — 주요 발견 #3: GT-Prompt Bias — 평가 메트릭의 구조적 결함

**발견**: Ground-Truth 텍스트를 Whisper에 주입하면, 잘린 오디오에서도 높은 유사도를 출력

**최초 관찰 (2026-03-16, Script_2_0153.wav)**:
- GT: "비관적인 전망이 지배적이었**습니다**"
- 실제 오디오: "지배적이었" 에서 절단 ("습니다" 누락)
- GT-prompted Whisper 결과: similarity ≈ 0.95+ (QA 통과)
- 사람이 들으면 명백한 절단

**체계적 재검증 (ending_truncation_report.json, N=592)**:
- 592개 형식어미 후보 중 **29건 (4.9%)** 에서 절단 확인
- 모두 `-습니다` 계열 형식어미
- 대표 사례:
  - `Script_2_0287`: "...어디서든 돌아갔습니다" → "...돌아가" 절단
  - `Script_2_0383`: "...발칵 뒤집혔습니다" → "뒤집혀서" 오인식
  - `Script_2_0388`: "...집사 같았습니다" → "같았" 절단

---

## Slide 12 — GT-Prompt Bias: 왜 발생하는가

**Whisper의 initial_prompt 메커니즘**:

1. GT 텍스트가 디코더의 context(initial_prompt)로 주입됨
2. 디코더의 softmax 분포가 GT 방향으로 강하게 편향
3. 오디오 신호가 약하거나 부재해도 language model이 나머지를 "예측"
4. 결과: 잘린 음성 + GT context = 높은 유사도

**핵심**: 이것은 버그가 아니라 Whisper의 정상 동작. language model의 예측력이 평가 메트릭을 무력화하는 구조적 문제.

**대응 설계: 2-Run 전략** (evaluate_dataset.py):
- **Run 1**: GT-prompted (initial_prompt=GT 텍스트) → sim_prompted
- **Run 2**: Unprompted (prompt 없음) → sim_unprompted
- 두 결과를 모두 기록, **gap = prompted - unprompted**으로 bias 크기 정량화
- gap이 클수록 GT가 결과를 왜곡하고 있다는 증거 → D2 스코어로 Selective Composer에 전달

---

## Slide 13 — GT-Prompt Bias: 한국어 형식어미에서의 발현

**한국어 형식어미 패턴**:

- "-었습니다", "-겠습니다", "-하십시오", "-인 것입니다"
- 이들은 공통적으로:
  1. 본동사 어간이 높은 에너지로 완료
  2. 50~150ms **미세 정지** (micro-pause) 발생
  3. 형식어미가 낮은 에너지로 이어짐

- Whisper word-level timestamp가 미세 정지를 세그먼트 경계로 판단
- 형식어미 절단 → GT-prompt가 마스킹 → **자동 QA 통과**
- 592 후보 중 **29건 (4.9%)** 에서 절단 확인

---

## Slide 14 — 해결: Sustained Silence Verification Algorithm

> **[도식 삽입: `docs/sustained_silence_algorithm.png`]**

**핵심 아이디어**: 무음이 1000ms(1초) 이상 지속되어야만 발화 종료로 인정

- rms_db[] = 10ms 윈도우별 RMS (dB)
- voiced[] = rms_db >= -65dB인 인덱스
- candidate = voiced[-1] → check_start = candidate + 1
- 100개 윈도우 연속 < -65dB → 종료 확인
- 중간에 음성 발견 → candidate 갱신, 재스캔
- 미세 정지(50~150ms)는 100 윈도우(1000ms) 기준 미달 → 무시

---

## Slide 15 — 해결: 4가지 엔지니어링 수정

| 수정 | 변경 전 | 변경 후 | 효과 |
|------|---------|---------|------|
| A. END zero-crossing snap | ±10ms 스냅 | **비활성화** | 음성 꼬리 보존 |
| B. Offset safety margin | 80ms | **120ms** | 미세 정지 커버 |
| C. Fade-out | 10ms (대칭) | **5ms (비대칭)** | 약한 꼬리 보존 |
| D. Sustained silence | 없음 | **1000ms 확인** | 미세 정지 내성 |

적용 후 Script_2_1-162 테스트: **97.5% match rate**

---

## Slide 16 — 최종 달성 지표

| 요건 | 기준 | 달성 | 상태 |
|------|------|------|------|
| R1 정렬 정확도 | >= 95% | **95.48%** | PASS |
| R2 경계 노이즈 | >= 95% | **100%** | PASS |
| R3 복합 통과율 | >= 95% | **95.4%** | PASS |
| R4 메타데이터 무결성 | 100% | **99.9%** | PASS |
| R5 재현성 | TRUE | **TRUE** | PASS |
| R6 엔벨로프 규격 | >= 95% | **99.93%** | PASS |

**6개 요건 전체 충족** — 35%에서 출발, 7회 이터레이션 만에 도달

---

## Slide 17 — 최종 데이터셋 구성 (시점별 변화)

| 시점 | 상태 | 세그먼트 수 |
|------|------|-----------|
| **Iter 7 평가 직후** (2026-02-20) | evaluation_report | **4,199** |
| **큐레이션 후** (2026-02-20) | sim < 0.80 격리 제외 | script.txt **4,196** / WAV **4,200** (4 orphan) |
| **Selective Composer 입력** (2026-04-04) | composition_report | **4,176** |
| 자동 산입 (ACCEPT) | | **3,930 (94.1%)** |

| 포맷 항목 | 값 |
|----------|-----|
| 샘플레이트 | 48kHz |
| 비트 깊이 | 24-bit |
| 채널 | Mono |
| 총 오디오 길이 | ~8.18시간 |
| 격리 (sim < 0.80) | 74개 |

---

## Slide 18 — 스크립트별 성능 분석

| Script | 유형 | 세그먼트 | 통과 | 통과율 |
|--------|------|---------|------|--------|
| 1 | 문학 낭독 | 298 | 294 | **98.66%** |
| 2 | IT/프로그래밍 | 1,254 | 1,146 | **91.39%** |
| 3 | 문학 텍스트 | 865 | 841 | **97.23%** |
| 4 | 교육 콘텐츠 | 990 | 949 | **95.86%** |
| 5 | 내러티브 | 792 | 776 | **97.98%** |

- Script_2가 가장 낮음: IT 기술용어("API", "프레임워크" 등)에서 Whisper 인식 한계
- 잔여 실패의 **95.3%가 Type D** (Whisper 자체 인식 한계)

---

## Slide 19 — 실패 분석: 잔여 5%의 정체

전체 실패 193건 분석:

| 유형 | 건수 | 비율 | 설명 |
|------|------|------|------|
| Type D | 184 | **95.3%** | Whisper 인식 한계 (기술용어, 고유명사) |
| Type A | 6 | 3.1% | 정렬 시프트 (세그먼트 경계 오차) |
| Type F | 3 | 1.6% | 엔벨로프 위반 |

**핵심 통찰**: 파라미터 최적화의 한계에 도달. 파이프라인이 아닌 Whisper 모델이 병목.

---

## Slide 20 — 패러다임 전환: 최적화에서 구성(Composition)으로

**기존 접근법** (Iter 1~7):
- Whisper를 고정 자산으로 두고 파라미터를 최적화
- 결과: 95.48%에서 천장 (ceiling)

**새로운 접근법**:
- 95%를 "최대한 끌어올리는 것"이 아니라
- 높은 신뢰도의 데이터만 **선별적으로 구성**하는 것
- SAM (Segment Anything Model)의 Data Engine에서 영감

> "95%를 100%로 만드는 것이 아니라, 94%를 전략적으로 구성하는 것이 더 가치 있다"

---

## Slide 21 — SAM Data Engine: 영감의 원천

**SAM의 3단계 Data Engine:**

| 단계 | 방식 | 모델 재학습 | 데이터 규모 |
|------|------|-----------|-----------|
| 1. Assisted-Manual | 사람 + 모델 협업 | 6회 | 4.3M masks |
| 2. Semi-Automatic | 자동 승인 + 모호 건 리뷰 | 5회 | 5.9M masks |
| 3. Fully Automatic | 전자동 생성 + stability check | 1회 | 1.1B masks |

**SAM의 99.1%는 1회 시도의 정확도가 아니라 — 다수 후보 중 신뢰도 높은 것만 선별한 "구성률"**

---

## Slide 22 — SAM vs 현재 파이프라인 비교

| 항목 | SAM | 현재 TTS 파이프라인 |
|------|-----|-------------------|
| 모델 피드백 | 출력 → 재학습 (closed-loop) | 없음 (open-loop) |
| 데이터 선별 | stability + confidence | 단일 유사도 (R1) |
| 모델 개선 | 11회 재학습 | Whisper 고정 |
| 신뢰도 검증 | 다차원 (IoU, stability, confidence) | 1차원 (similarity) |
| 최종 지표 | 99.1% 구성률 | 95.48% 정확도 |

**Gap**: 단일 메트릭 의존 → 다차원 검증, 개방 루프 → 폐쇄 루프

---

## Slide 23 — Selective Data Composer 설계 (Stage 4.5)

> **[도식 삽입: `docs/diagram_composer_decision.png`]**

SAM의 confidence-based filtering을 TTS 데이터에 적용

**Composite Score = geometric_mean(D1, D2, D3, D4, D6, D7)**

**Hard Reject Gates:**
- S_unprompted < 0.50 → 즉시 기각
- S_gap < 0.50 → 즉시 기각
- S_snr < 0.30 → 즉시 기각

**Threshold (Bootstrap 1000x 교정):**
- tau_accept = **0.768** (known-good 3,988건의 하위 5%, CI: [0.757, 0.775])
- tau_reject = 0.650 (default, known-bad 4건으로 bootstrap 불충분)
- default(0.88)에서 calibration(0.768)으로 낮아진 이유: 고품질 녹음 데이터의 전반적 높은 기저 품질

---

## Slide 24 — 7차원 품질 스코어링: Textual Fidelity

| 차원 | 측정 대상 | 핵심 역할 |
|------|----------|----------|
| **D1** S_unprompted | GT 없이 Whisper 전사 유사도 | 편향 없는 실제 품질 |
| **D2** S_gap | prompted - unprompted 차이 | **GT-prompt bias 감지** |
| **D6** S_confidence | Whisper avg_logprob | 모델 자체 불확실성 |

- D1과 D2의 조합이 핵심: GT-prompt bias를 정면으로 해결
- D2가 높을수록 → GT가 결과를 왜곡하고 있다는 신호

---

## Slide 25 — 7차원 품질 스코어링: Acoustic & Structural

| 차원 | 측정 대상 | 핵심 역할 |
|------|----------|----------|
| **D3** S_snr | 음성 구간 SNR | 녹음 품질 |
| **D4** S_duration | AST (s/char) z-score | 길이 이상치 감지 |
| **D5** S_stability | 다중 온도 전사 분산 | 디코딩 안정성 (미구현) |
| **D7** S_boundary | 엔벨로프 연속 품질 | 경계 정합성 |

---

## Slide 25.5 — D5의 특수 위치: Factor가 아닌 Gate

**Composite 공식 (주의 깊게 읽을 것)**:
```
S_composite = geometric_mean(D1, D2, D3, D4, D6, D7)   ← D5 없음
              × gate(D5)                                 ← D5는 여기
```

**왜 D5만 다르게 처리되는가**:

| 구분 | D1~D4, D6, D7 (Factor) | D5 (Gate) |
|------|------------------------|-----------|
| 계산 비용 | 수 ms ~ 즉시 | **세그먼트당 15~60초** (Whisper 3회+) |
| 적용 범위 | 전수 (4,176건) | **On-demand** (PENDING 159건만) |
| 수학적 역할 | 기하평균 성분 ("기여") | 조건부 곱 ("감점 관문") |
| 결측 처리 | 기본값 0.5 부여 | 계산 안 하면 skip (페널티 없음) |

**Gate 로직**:
```python
if S_stability is not None:          # 계산됐을 때만
    tau_stab = 0.70
    gate = 1.0 if S_stability >= 0.70
           else S_stability / 0.70
    S_composite *= gate
```

**설계 철학**: 비싼 검증은 보더라인 건에만 적용 — SAM의 "stability check" 철학과 동일.
전수에 D5를 계산하면 4,176건 × 20초 ≈ **23시간 추가 소요** → 경제성 악화.

**세 가지 시나리오**:
- D5 미계산 → S_comp 그대로 (6차원이 멀쩡한데 감점할 이유 없음)
- D5 >= 0.70 → gate=1.0, 감점 없음
- D5 < 0.70 (예: 0.50) → gate=0.714 → S_comp가 28.6% 감쇠 → PENDING→REJECT 전환 가능

> **핵심**: D5는 "빠진 것"이 아니라 **계층적 필터링(hierarchical filtering)** 구조에서 2차 관문으로 의도적으로 분리됨.

---

## Slide 26 — D4: AST (Average Spoken Time) 알고리즘의 진화

> **[도식 삽입: `docs/diagram_ast_algorithm.png`]**

| 버전 | 단위 | 기준 | 문제 |
|------|------|------|------|
| v1 | 단어/초 | 스크립트 전체 | 메타데이터 주석이 단어수 왜곡 |
| v2 | 단어/초 | 녹음 세션별 | 한국어는 교착어 → 단어 단위 부적합 |
| v3 | 글자/초 | 녹음 세션별 | 직관성 부족 |
| **v4** | **초/글자** | **녹음 세션별** | **최종 채택** |

**최종 정의**: s/char (seconds per character)
- z < -1.5 + 형식어미 → "formal_ending_truncation_risk" 플래그
- z > +2.0 → 과도한 무음, 정렬 오류 의심

---

## Slide 27 — D4: 세션별 AST 베이스라인

| 세션 | 평균 (s/char) | 표준편차 | N |
|------|-------------|---------|---|
| Script_1_1-122 | 0.1916 | 0.0112 | 122 |
| Script_2_1-162 | 0.2111 | 0.0336 | 157 |
| Script_2_163-473 | 0.2170 | 0.0400 | 275 |
| Script_3_1-404 | 0.2029 | 0.0152 | 404 |
| Script_4_1-100 | 0.1830 | 0.0092 | 97 |
| Script_5_542-800 | 0.2233 | 0.0347 | 252 |

- 동일 스크립트 내에서도 녹음 세션마다 평균 발화 속도가 다름
- 세션 단위 베이스라인이 글로벌 평균보다 정확한 이상치 감지

---

## Slide 28 — Selective Composer 판정 결과

| 판정 | 건수 | 비율 | 처리 |
|------|------|------|------|
| **ACCEPT** | 3,930 | **94.1%** | 자동 산입 (인간 리뷰 불필요) |
| **PENDING** | 159 | 3.8% | 인간 리뷰 대기 |
| **REJECT** | 87 | 2.1% | 데이터셋 제외 |

**REJECT 87건 내역:**
- Slow (과도하게 긴 오디오): 76건 (87%) — 무음 과다, 정렬 오류, 속도 이상
- Fast (의심 절단): 11건 (13%) — 형식어미 절단 후보

**Human review 총계: 183건** (PENDING 159 + ACCEPT 중 플래그 보유 24건)

---

## Slide 28.5 — 현실 점검: 차원별 실제 분별력

composition_report.json 기준 차원별 통계:

| 차원 | mean | std | 실질 분별력 |
|------|------|-----|-----------|
| D1 S_unprompted | 0.994 | 0.028 | **유효** — 소수 저품질 감지 |
| D2 S_gap | 1.000 | 0.000 | 현재 분별력 없음 (전수 1.0) |
| D3 S_snr | 1.000 | 0.000 | 현재 분별력 없음 (전수 1.0) |
| **D4 S_duration** | **0.776** | **0.196** | **핵심 분별 차원** — 유일한 넓은 분포 |
| D6 S_confidence | 0.500 | 0.000 | 미산출 (Whisper logprob 미추출) |
| D7 S_boundary | 1.000 | 0.000 | 현재 분별력 없음 (전수 ~1.0) |

**해석**: 현재 ACCEPT/REJECT를 실질적으로 가르는 차원은 **D4(발화 길이 이상치)**가 지배적.
D2, D3, D6, D7은 고품질 전문 녹음이라 분산이 없음 — 다양한 화자/환경에서는 활성화될 것으로 기대.
이는 **7차원 프레임워크의 일반화 가능성**을 시사하면서도, 현 데이터셋에서의 한계를 솔직히 인정.

---

## Slide 29 — Ablation Study #1: R6 엔벨로프 효과

4가지 조건에서 80개 세그먼트 비교:

| 조건 | Pre/Tail | Mean Sim | R1 Pass |
|------|----------|----------|---------|
| A. No envelope | 0/0ms | 0.9798 | 83.75% |
| B. Minimal | 50/100ms | 0.9786 | 81.25% |
| C. Moderate | 200/400ms | 0.9803 | 83.75% |
| D. Full R6 | 400/730ms | 0.9806 | 82.5% |

**결론**: 엔벨로프 자체는 ASR 정확도에 큰 영향 없음 → TTS 학습 품질을 위해 유지

---

## Slide 30 — Ablation Study #2: 무음 판별 임계값

| 조건 | 통과율 | Mean Sim |
|------|--------|----------|
| -40dB (높은 임계) | 81.25% | 0.9786 |
| -65dB (낮은 임계) | 81.25% | 0.9781 |

- 두 조건 간 차이 무시 가능 (delta = -0.0005)
- **-65dB 채택**: 녹음 noise floor에 더 근접, 불필요한 민감도 제거

---

## Slide 31 — 하드웨어 제약과 아키텍처 해결

**문제**: RTX 3060 Ti (8GB VRAM) — Whisper medium + large 동시 로딩 불가

**해결: 2-Pass 아키텍처**

```
Pass 1: Whisper medium 로드 → 전사 → 결과 캐시
         ↓ model.cpu() + gc.collect() + torch.cuda.empty_cache()
Pass 2: 정렬 + 분할 (GPU 불필요)
         ↓ (실패 건만)
Tier 2: Whisper large 로드 → 재전사
```

- Tier 2(large)가 Tier 1(medium) 실패의 **~15%를 복구**
- medium: ~1s/항목 vs large: ~20s/항목 (20배 속도 차이)
- 120초 타임아웃: 일부 파일에서 Whisper 무한 디코딩 루프 방지

---

## Slide 32 — 파라미터 진화 요약

| 파라미터 | 초기값 | 최종값 | 변경 사유 |
|---------|--------|--------|----------|
| AUDIO_PAD_MS | 100 | **50** | 100ms에서 인접 세그먼트 블리드 |
| OFFSET_SAFETY_MS | 80 | **120** | 한국어 미세 정지 커버 |
| FADE_OUT_MS | 10 | **5** | 비대칭: 약한 꼬리 보존 |
| SUSTAINED_SILENCE_MS | 없음 | **1000** | 미세 정지 내성 추가 |
| EVAL_STRIP_LEAD_MS | 0 | **350** | R6 엔벨로프가 Whisper 첫 음절 인식 방해 |
| EVAL_STRIP_TAIL_MS | 0 | **700** | R6 꼬리 무음이 Whisper 혼란 유발 |
| temperature | 0 (align_and_split Iter 4) | **default** | 한국어 음운변화에 필수 (Script_4 붕괴) |

---

## Slide 33 — 핵심 교훈 정리

1. **GT-prompting은 강력하지만 양날의 검** — 34.7%→64.3% 돌파구였으나 평가를 오염시킨 원인이기도
2. **"추가 검증"이 항상 옳은 건 아니다** — Inline verification이 -4.2%p 회귀 (Iter 5)
3. **temperature=0은 한국어에서 금기** — 음운변화 경로를 차단, Script_4 97.5%→60.1% 붕괴
4. **Forward-only search가 한국어에 적합** — 후방 탐색은 조사/어미 false match 유발
5. **Sustained silence(1s)가 미세 정지를 해결** — 단순 threshold보다 시간적 검증이 핵심
6. **단일 메트릭 의존은 위험** — 7차원 독립 검증으로 전환 필요
7. **자동 QA의 맹점 인정** — R2/R6가 100% 통과해도 인간 청취 시 bleed 존재 (Iter 7 이전)
8. **95%는 파이프라인의 한계가 아니라 Whisper의 한계** — 패러다임 전환 필요

---

## Slide 34 — 현재 한계와 미해결 과제

| 한계 | 설명 |
|------|------|
| Whisper 천장 | 95.48% — 잔여 5%의 95%가 Whisper 인식 한계 |
| 단일 화자 | 다른 화자/도메인 일반화 미검증 |
| PENDING 159건 | 수동 리뷰 미완료 (3.8%) |
| D5 미구현 | Multi-temperature stability check 미적용 |
| Open-loop | Whisper 자체는 파이프라인 출력으로 개선되지 않음 |

---

## Slide 35 — 향후 로드맵 A: 파이프라인 고도화

**A-1: Pipeline Data Engine**
- PENDING 159건 수동 리뷰 → 최종 데이터셋 확정
- D5 (multi-temperature stability) 전체 적용
- Multi-hypothesis matching: 모호 세그먼트 복수 후보 비교

**A-2: ASR Model Data Engine**
- 검증된 4K 쌍으로 Whisper fine-tuning
- 개선된 Whisper → 더 많은 성공 → 더 많은 학습 데이터 (closed-loop)
- 리스크: 단일 화자 과적합 → A-1 일반화 검증으로 완화

---

## Slide 36 — 향후 로드맵 B~C: TTS 학습과 배포

**B. TTS 모델 학습**
- F5-TTS Phase 1/2: 정제 데이터셋으로 학습
- MOS (Mean Opinion Score) 평가 체계 구축
- TTS 출력 품질 = 데이터 파이프라인의 **궁극적 검증자**

**C. 배포**
- koreanAIvoice.com 모델 업데이트
- 실사용 피드백 수집 → 다음 이터레이션 입력

---

## Slide 37 — 최종 목표: SAM-Style TTS Data Engine

**D. TTS ↔ ASR 피드백 루프 (SAM Fully Automatic Stage 대응)**

```
TTS 합성 → ASR 역전사 → 입력 텍스트와 비교
    ↓ 불일치 시
TTS: 발음 교정 신호
ASR: 새로운 음성 패턴 학습
    ↓ 반복
양쪽 모델이 상호 개선 (closed-loop)
```

- 현재: ASR → Data (단방향)
- 목표: **ASR ↔ TTS (양방향 자기 개선)**
- SAM이 11회 재학습으로 4.3M → 1.1B masks를 달성한 것처럼,
  TTS↔ASR 루프로 데이터 품질과 모델 성능의 동시 향상 추구

---

## Slide 38 — 결론

1. **35% → 95.48%**: Whisper 기반 한국어 TTS 자동 정렬은 가능하다 (7회 이터레이션)
2. **한국어 특화 발견**: temperature=0 금기, 형식어미 미세 정지, GT-prompt bias
3. **평가 메트릭의 구조적 결함 발견과 대응**: 단일 유사도 → 2-Run 비교 + 7차원 프레임워크
4. **패러다임 전환**: 최적화의 한계(95%) → 선별적 구성(94.1% 자동 산입)
5. **솔직한 한계**: 현재 7차원 중 실질 분별력은 D1, D4에 집중 — 다양한 데이터에서 검증 필요
6. **최종 비전**: TTS ↔ ASR 양방향 Data Engine으로 자기 개선 시스템 구축

> "정확도를 1%p 높이는 것보다, 신뢰할 수 있는 94%를 구성하는 것이 더 가치 있다."
> "그리고 그 94%의 신뢰도를 다차원으로 증명할 수 있어야 한다."

---

## Slide 39 — 참고: 주요 실험 파일

| 파일 | 역할 |
|------|------|
| `src/align_and_split.py` | Stage 1-2: 정렬, 분할, 후처리 |
| `src/evaluate_dataset.py` | Stage 3-4: 검증, 평가 |
| `src/selective_composer.py` | Stage 4.5: 7차원 스코어링 |
| `src/experiment_r6_ablation.py` | R6 엔벨로프 ablation (4조건) |
| `src/experiment_threshold_ab.py` | 무음 임계값 A/B 테스트 |

| 로그 | 내용 |
|------|------|
| `logs/evaluation_report.json` | R1~R6 최종 집계 |
| `logs/composition_report.json` | Selective Composer 결과 |
| `logs/composition_scores.json` | 4,176건 7차원 스코어 |
| `logs/ending_truncation_report.json` | 형식어미 절단 29건 분석 |
