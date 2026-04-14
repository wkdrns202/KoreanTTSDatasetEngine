# TTS Dataset Cleanser

한국어 인공지능 음성합성(TTS) 모델의 학습용 데이터셋 자동 정제 파이프라인입니다. OpenAI Whisper ASR을 활용하여 장시간 원본 녹음 데이터를 개별 문장 단위 WAV로 분할하고, 자동 검증 및 품질 관리를 수행합니다.

## 프로젝트 개요

전문 성우의 고품질 녹음 데이터(48kHz/24-bit/Mono)를 기반으로, ASR 기반 자동 정렬(alignment) 기법을 통해 데이터 정제 및 라벨링 과정을 자동화합니다. 7회의 반복 R&D를 거쳐 최초 34.7%에서 최종 95.48%의 정렬 정확도를 달성하였습니다.

## 파이프라인 아키텍처

반복형(iterative) 파이프라인으로 구성됩니다. Stage 3–4 사이에 Tier 구조가, Stage 4와 5 사이에 품질 게이트(4.5)가 위치합니다:

```
STAGE 1        STAGE 2           STAGE 3           STAGE 4
Align &   ->   Clean &      ->   Validate     ->   Evaluate
Split          Post-process      (Tier 1:          (Tier 2:
                                  Whisper           Whisper
                                  medium)           large,
                                                    실패건만)
                                                        |
                                                  STAGE 4.5
                                                  Selective
                                                  Composer
                                                  (품질 게이트)
                                                        |
                                                   STAGE 5
                                                   Finalize
                                                        |
                                               All R >= 95%?
                                                YES /    \ NO
                                              DONE    STAGE 6
                                                    Diagnose
                                                    -> STAGE 1
```

| Stage | 이름 | 설명 |
|-------|------|------|
| Stage 1 | Align & Split | Whisper ASR로 음성 전사 후 스크립트와 정렬, 개별 WAV로 분할 |
| Stage 2 | Clean & Post-process | 비대칭 fade, sustained-silence 기반 voice offset 검증, R6 envelope 적용 |
| Stage 3 | Validate (Tier 1) | Whisper **medium**으로 재전사하여 원문과 유사도 비교 (~1s/item) |
| Stage 4 | Evaluate (Tier 2) | Tier 1 실패 건에 한해 Whisper **large**로 재평가 (~20s/item, 불용처리된 데이터 ~15% 회복) |
| Stage 4.5 | Selective Composer | SAM-inspired 다차원 품질 게이트. 7개 차원 스코어로 ACCEPT/PENDING/REJECT 분류 |
| Stage 5 | Finalize | R1~R6 요구사항 평가 및 최종 데이터셋 확정 |
| Stage 6 | Diagnose & Improve | 95% 미만 시 실패 분석, 파라미터 조정 후 Stage 1로 복귀 |

### Stage 4.5 Selective Composer 스코어링 차원
`src/selective_composer.py` — 모든 세그먼트에 대해 다음 7개 차원을 산출하고, 
D5를 제외한 나머지 차원의 값은 통계적 기준(기하평균)으로 합격/보류/기각을 결정합니다.
D5는 0.7을 기준으로 평균값에 곱하여 게이트 역할*을 합니다.
if Stability >= 0.7 then Gate = 1.0
Else Gate = Stability / 0.7 (Linear Attenuation)

| 차원 | 의미 |
|------|------|
| D1 `S_unprompted` | GT prompting 없이 재전사한 Whisper 유사도 (bias-free) |
| D2 `S_gap` | Prompted vs Unprompted 격차 — 어미 절단(truncation) 탐지 |
| D3 `S_snr` | 음성 구간 SNR |
| D4 `S_duration` | AST(Average Spoken Time) 기반 duration 이상치 z-test (p<0.05) |
| D5 `S_stability` | Decode temperature 변화에 대한 전사 안정성 (on-demand) |
| D6 `S_confidence` | Whisper avg_logprob 기반 self-reported confidence |
| D7 `S_boundary` | 연속적 boundary/envelope 품질 스코어 |

## 원본 데이터

| 스크립트 | 문장 수 | 오디오 파일 수 | 내용 특성 |
|----------|---------|---------------|-----------|
| Script 1 | 300 | 3 | 문학 작품 낭독 |
| Script 2 | 1,644 | 6 | IT/프로그래밍 교육 콘텐츠 |
| Script 3 | 878 | 2 | 문학 텍스트 (고전/현대문학) |
| Script 4 | 1,005 | 5 | 일반 교양 콘텐츠 |
| Script 5 | 1,018* | 4 | 내러티브/서사 콘텐츠 |
| Script 6 | 1,000† | 4 | SF/호러 — 고반복 모티프 코퍼스 |

\* Script 5는 800번 라인까지 오디오가 존재하며, 801~1,018번은 미녹음 상태입니다.
† Script 6는 1~330번 라인 범위만 오디오가 존재합니다.

- 녹음 포맷: 48kHz / 24-bit / Mono WAV (무손실 PCM)
- 파일 명명 규칙: `Script_{N}_{Start}-{End}.wav`

## 최종 품질 지표

| 요구사항 | 기준 | 달성 점수 | 판정 |
|----------|------|-----------|------|
| R1 (Alignment Accuracy) | >= 95% | 95.48% | PASS |
| R2 (Boundary Noise Clean) | >= 95% | 100.0% | PASS |
| R3 (Combined Pass Rate) | >= 95% | 95.4% | PASS |
| R4 (Metadata Integrity) | Complete | 99.9% | PASS |
| R5 (Reproducibility) | TRUE | TRUE | PASS |
| R6 (Audio Envelope) | >= 95% | 99.93% | PASS |

## 최종 데이터셋

| 항목 | 수치 |
|------|------|
| script.txt 엔트리 수 | 4,196 |
| WAV 파일 수 | 4,200 |
| 검역(Quarantine) 파일 | 74 (sim < 0.80) |
| 오디오 포맷 | 48kHz / 24-bit / Mono WAV |
| 총 오디오 시간 | ~8.18시간 |

### 스크립트별 통과율

| 스크립트 | 총 세그먼트 | 통과 | 통과율 |
|----------|------------|------|--------|
| Script 1 | 298 | 294 | 98.66% |
| Script 2 | 1,254 | 1,146 | 91.39% |
| Script 3 | 865 | 841 | 97.23% |
| Script 4 | 990 | 949 | 95.86% |
| Script 5 | 792 | 776 | 97.98% |

## 설치

```bash
pip install -r requirements.txt
```

시스템에 FFmpeg가 설치되어 있어야 합니다.

### 주요 의존성

| 패키지 | 용도 |
|--------|------|
| openai-whisper | ASR 전사 및 정렬 |
| numpy | 오디오 신호 처리 |
| soundfile | WAV 파일 I/O |
| python-Levenshtein | 텍스트 유사도 계산 (CER) |
| torch + CUDA | GPU 가속 |

## 사용법

1. 원본 오디오 파일을 `rawdata/audio/`에, 스크립트를 `rawdata/Scripts/`에 배치합니다.
2. Stage 1-2 (정렬 및 분할):
   ```bash
   python src/align_and_split.py
   ```
   - `--resume`: 체크포인트에서 이어서 실행 (기본값)
   - `--reset`: 처음부터 재실행
   - `--script N`: 특정 스크립트만 처리
3. Stage 3-4 (Tier 1 검증 + Tier 2 재평가):
   ```bash
   python src/evaluate_dataset.py
   ```
   - Tier 1: Whisper medium으로 전체 평가. Tier 2: Tier 1 실패 건에 대해 Whisper large로 재평가
   - VRAM 8GB 환경에서는 medium→large 동시 로드 불가 → 별도 실행 권장
4. Stage 4.5 (Selective Composer, 품질 게이트):
   ```bash
   python src/selective_composer.py --compose
   ```
   - 7차원 스코어 산출 후 ACCEPT/PENDING/REJECT 분류
   - `--stability-pending`: PENDING 풀에 대해 D5(stability)만 추가 계산
   - `--report`: composition 리포트만 재생성
5. 결과물은 `datasets/wavs/`(WAV 파일)와 `datasets/script.txt`(메타데이터)에 출력됩니다.

## 핵심 알고리즘

### Stage 1 정렬
- **Forward-only Search**: 현재 스크립트 위치에서 25줄 전방만 탐색 (후방 탐색은 한국어에서 중복 매칭 유발)
- **Segment Merging**: Whisper가 분할한 1~5개 연속 세그먼트를 결합하여 최적 매칭
- **Skip Penalty**: 먼 라인 매칭 시 줄당 0.01 패널티 부과
- **Re-sync**: 10회 연속 실패 시 75줄 범위에서 threshold 0.35로 재동기화 후 포인터 +1 전진
- **Default temperature fallback** 사용 (temperature=0은 한국어에서 catastrophic)

### Stage 2 R6 Audio Envelope (최신 파라미터, 2026-04-03 업데이트)
- **Pre-attack silence**: 400ms / **Tail silence**: 730ms
- **Onset safety margin**: 30ms (consonant attack 보존)
- **Offset safety margin**: 120ms (한국어 micro-pause 어미 커버, 기존 80ms에서 상향)
- **Sustained silence verification**: 1000ms — voice offset 후보 지점 뒤로 1초 연속 무음이 확인될 때만 종료 확정. micro-pause 후 이어지는 낮은 에너지 어미(예: "-었습니다")를 놓치지 않음
- **비대칭 fade**: fade-in 10ms / fade-out 5ms (quiet tail 감쇄 축소)
- **End zero-crossing snap 비활성화**: ±10ms snap이 speech tail을 절삭하던 결함 제거

### Stage 3–4 평가
- **Two-tier Evaluation**: Whisper medium (Tier 1, 전체) → Whisper large (Tier 2, Tier 1 실패건만, 약 15% 회복)
- **EVAL_STRIP**: Whisper 평가 전 R6 envelope을 제거 (lead 350ms / tail 700ms) — envelope 포함 시 첫 음절 드롭 가능
- **Per-file timeout**: 120s (Whisper의 간헐적 infinite decode loop 방지)

### Stage 4.5 품질 게이트
- **다차원 스코어링**: 7개 차원(S_unprompted, S_gap, S_snr, S_duration, S_stability, S_confidence, S_boundary)
- **Hard reject gates**: unprompted<0.50, gap>0.50, snr<0.30 중 하나라도 해당 시 즉시 기각
- **Soft thresholds**: τ_accept=0.88, τ_reject=0.65 (calibration으로 조정 가능)
- **Prompted-vs-Unprompted gap**: GT-prompted Whisper가 절단된 어미를 예측 완성하여 자동 QA를 통과시키는 문제를 정면으로 탐지

## 핵심 교훈

- **파라미터 적절히 분류**: 한국어 특성을 고려하여 파라미터 설계 필요.
- **전방 탐색만 사용**: 후방 탐색은 한국어 조사/어미의 유사 패턴으로 중복 매칭 유발.
- **탐색 범위 제한**: 100~500줄의 넓은 범위는 false-match cascading 야기. 25줄이 최적.
- **반복 어휘 코퍼스 취약성**: window=25에서도 **텍스트 자체의 모티프 반복성**이 높으면 false-match가 발생 (Script 6 사례). window 크기가 아니라 **구분력(margin, penalty)** 축에서 대응 필요.
- **GT-prompting 효과**: Ground-truth 텍스트를 initial_prompt로 사용하면 R1이 약 2배 향상 (34.7% -> 64.3%).
- **GT-prompting의 그림자**: 평가 단계의 GT prompting은 절단된 어미를 예측 완성하여 similarity 1.0 오탐을 만듦 → Stage 4.5의 `S_gap` 차원으로 탐지.
- **Sustained silence 검증의 필요성**: 한국어 형식 어미의 micro-pause(50~150ms) 이후 낮은 에너지 음절을 voice offset 감지가 놓치지 않으려면 1초 지속 무음 검증 필수.
- **자동 메트릭의 한계**: R2/R6 자동 검사가 100% 통과해도 수동 청취로 audible bleed·어미 절단 발견 가능 → 다차원 품질 게이트(Stage 4.5) 도입.
- **Tier 분리 실행**: 8GB VRAM에서는 medium→large 동시 로드 불가. 모델 교체 시 CPU 이동 + `gc.collect()` 필수.

## 리포지토리 구조

```
{LocalDrive}:\Projects\AI_Research\TTSDataSetCleanser\
  src/align_and_split.py       # Stage 1-2: 정렬 및 분할
  src/evaluate_dataset.py      # Stage 3-4: Tier 1/2 검증 및 평가
  src/selective_composer.py    # Stage 4.5: 다차원 품질 게이트 (SAM-inspired)
  src/pipeline_manager.py      # 워크플로 오케스트레이터
  src/detect_ending_truncation.py  # 어미 절단 진단 툴
  src/validate_dataset.py      # 메타데이터/WAV 무결성 검증
  rawdata/audio/               # 원본 오디오
  rawdata/Scripts/             # 원본 스크립트
  datasets/wavs/               # 출력: 분할된 WAV (정본)
  datasets/script.txt          # 출력: 메타데이터
  datasets/quarantine/         # 격리: similarity < 0.80
  datasets/{date}_{tag}/       # 버전 디렉토리 (정본 덮어쓰기 금지)
  logs/                        # 평가 보고서, 체크포인트, 엔지니어링 노트
    composition_scores.json    # Stage 4.5 스코어
    composition_report.json    # Stage 4.5 합격/보류/기각 집계
    pending_pool.json          # PENDING 풀 (stability 재측정 대상)
    engineering_note_*.md      # 실험/결함/수정 기록
```

## 환경

| 항목 | 사양 |
|------|------|
| OS | Windows 10 Pro |
| Python | 3.11 |
| GPU | NVIDIA RTX 3060 Ti (8GB VRAM) |
| 파일시스템 | exFAT (로컬 드라이브) |
