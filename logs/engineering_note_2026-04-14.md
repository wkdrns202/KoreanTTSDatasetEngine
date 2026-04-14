# Engineering Note — 2026-04-14

## Script_6 정렬 붕괴 — 반복 어휘(repetitive vocabulary)로 인한 유사도 탐색기 오배치

---

## 1. 발견된 문제

### 현상
- 2026-04-14 실행한 두 건의 파이프라인에서 **Script_6 정렬률이 10% 수준으로 붕괴**
- 같은 실행 내 Script_1(96.1%), Script_5(98.3%)는 정상 — 회귀는 S6 한정
- 파이썬 에러·crash 없이 **pipeline exit 0 정상 종료**
- Whisper 전사 자체는 정상(오디오 품질 문제 없음). 실패 지점은 **전사 결과를 스크립트의 어느 라인에 배정하느냐**의 배치 알고리즘

### 구체적 수치 (TaskLogs/)
```
20260414_001113_pipeline_report.txt
  Script_1: 657/684 (96.1%)
  Script_5: 470/478 (98.3%)
  Script_6:  97/1000  (9.7%)   ← 붕괴
  Skipped(S6): 420

20260414_004237_pipeline_report.txt
  Script_6: 110/1000 (11.0%)   ← 붕괴 재현
  Skipped(S6): 578
```

### Script_6 텍스트 특성 (rawdata/Scripts/Script_6_A0.txt)
- 고정된 SF 공포 세계관에서 소수의 모티프 구문이 반복 재조합됨
- 반복 출현 어절 예시:
  - "꿈틀거리는 외계 점액질 물질"
  - "우주선 외부의 차가운 진공 상태"
  - "수신되지 않는 구조 신호"
  - "마지막 남은 다른 생존자"
  - "고장 나서 미쳐버린 나침반"
  - "기괴하게 긁히는 마찰음"
  - "우주를 떠도는 파괴된 유령선"
- 라인 간 구조/어휘 중첩이 매우 높아, 25라인 이내 창(window)에도 **서로 유사한 후보가 다수** 존재

---

## 2. 현재 알고리즘 (align_and_split.py)

### 핵심 파라미터 (src/align_and_split.py:104-107)
```python
SEG_SEARCH_WINDOW = 25       # Forward-only: search up to N lines ahead
SKIP_PENALTY     = 0.01      # Similarity penalty per skipped script line
MATCH_THRESHOLD  = 0.50      # Minimum adjusted similarity to accept
CONSEC_FAIL_LIMIT = 10       # After N fails, try re-sync
```

### 탐색 로직 요지
```
for each Whisper segment:
    스코어 = SequenceMatcher(segment_text, script_line_text).ratio()
    adjusted = 스코어 - (skip_count * SKIP_PENALTY)           # align_and_split.py:818
    현재 포인터 +0 … +25 라인 중 adjusted 최댓값 선택
    if best_score >= MATCH_THRESHOLD: 배정                     # :828
    else: 연속 실패 카운트 증가
연속 실패 10회 → 75라인(=SEG_SEARCH_WINDOW*3) 재동기화 시도   # :1000
    재동기화 임계값 0.35                                      # :1023
    실패 시 포인터 +1 전진                                    # :1042
```

---

## 3. 문제점 분석

### 3-1. 25라인 창 안에 "그럴듯한 오답"이 집단으로 존재
- S6는 서로 유사한 어휘 조합으로 구성된 라인이 창 안에 다수 포진
- `SequenceMatcher.ratio()`가 **정답 라인**뿐 아니라 **모티프 공유 오답 라인**에도 0.5+ 점수를 부여
- `SKIP_PENALTY = 0.01`은 25라인 범위에서 최대 -0.25에 불과 → 어휘 반복으로 인한 유사도 차이를 **흡수하지 못함**
- 결과: 포인터가 **잘못된 라인에 pinning**되고 이후 segments가 줄줄이 오배치

### 3-2. Re-sync가 오히려 공백을 만듦
- 포인터가 오답 라인에 pin되면 이어지는 segments도 낮은 점수 → `CONSEC_FAIL_LIMIT = 10` 도달
- 75라인 window 재동기화(line 1000)에서도 비슷한 모티프 라인이 너무 많음 → 0.35 임계값은 S6에서 너무 낮아 **또 다른 오답으로 점프**
- 재동기화 실패 시 포인터 +1 전진(line 1042) → 구간 내 라인들이 **그대로 skip** 처리되어 420~578건 누락

### 3-3. MEMORY.md 기록된 실패 모드와 정합
- MEMORY.md: "Wider windows (100-500 lines) cause Korean false-match cascading"
- S6는 **window=25조차** 이미 false-match cascading이 시작되는 임계점 — 내용 반복성(content repetitiveness)이 window 크기 대신 그 역할을 수행
- 즉, 기존 경고는 "window가 넓을 때"의 현상이었지만, S6는 "**텍스트 자기 유사도가 높을 때**"라는 **새로운 축의 실패 모드**임

### 3-4. 자동 QA가 이 실패를 숨기지 않음 (cf. 2026-04-03 노트와 대비)
- 2026-04-03 노트의 tail-truncation 건은 GT-prompted Whisper가 누락 어미를 예측 완성해 similarity 1.0으로 **PASS를 위장**했음
- 이번 S6 건은 라인 배정 자체가 틀려 evaluate 단계에서 similarity가 낮게 나올 가능성이 높음 — **자동 QA는 기능하지만**, 그 이전 단계(alignment)에서 대량 skip이 발생하여 97/1000만 생존

### 3-5. 다른 스크립트와 대비
- S1/S5는 서사·주제 다양성이 높아 25라인 창 내 **유일해가 뚜렷**
- 동일 파라미터에서 S1=96.1%, S5=98.3%, S6=9.7% — 알고리즘 결함이 아니라 **S6 텍스트 분포에 대한 파라미터 감수성** 문제

---

## 4. 대응 방향 (미구현 — 실험 설계 단계)

> 2026-04-03 노트의 "Fix A–D"와 달리, 본 건은 **아직 수정 적용 전**. 아래는 제안 및 실험 대상.

### 후보 A: SKIP_PENALTY 상향 (0.01 → 0.03~0.05)
- 포인터가 앞쪽 정답 근처에서 흔들릴 때, skip을 더 강하게 억제
- 리스크: S2·S4의 정상 건너뜀 빈도에 영향 → **S6 전용 튜닝이 아니라 전체 검증 필요**

### 후보 B: Re-sync 임계값 상향 (0.35 → 0.45)
- false re-sync로 인한 2차 오배치를 줄임
- 리스크: 정당한 re-sync 기회 감소 → S2 회복률 저하 가능

### 후보 C: Top-2 마진 기반 수락 (신규 조건)
- `best_score - second_best_score >= margin` 일 때만 수락
- 반복 어휘로 1·2등이 혼재하는 상황을 **본질적으로 거부**
- S6의 cascading 원인에 가장 직접적으로 대응

### 후보 D: Whisper segment 병합 폭 확대
- 인접 segments를 더 길게 묶어 전사 길이를 키워 유사도의 **식별력을 강화**
- 이미 `MAX_MERGE = 5` 존재 — S6에 한해 더 공격적으로 적용

### 후보 E: 스크립트 의존 튜닝(script-aware params)
- `--script` 인자에 따라 파라미터 프로파일 분기
- S6 전용: `SKIP_PENALTY=0.04`, `resync threshold=0.45`, `margin=0.08` 등
- 구현 비용은 있으나 다른 스크립트에 회귀 위험 0

### 추천 실험 순서
1. **C (Top-2 margin)** 단독 도입 → 전 스크립트에서 영향 측정
2. 그래도 S6 복구 불충분 시 **A+B** 동시 적용한 S6 run
3. 회귀 발생 시 **E (script-aware profile)**로 격리

---

## 5. 가설

1. S6 정렬 붕괴의 근본 원인은 **스크립트 텍스트의 자기 유사도(self-similarity)** — 알고리즘 결함이 아님
2. 현재 파라미터는 S1–S5의 다양성 프로파일에 과적합되어 있고, S6 같은 **모티프 반복형 코퍼스**에는 부적합
3. "window를 좁히면 안전"이라는 기존 가정은 **텍스트 분포가 충분히 반복적이면 깨짐**
4. 해결은 window 크기가 아니라 **구분력(discrimination)을 강화하는 조건** (margin, penalty) 축에서 찾아야 함

---

## 6. 관련 파일 / 참고 (Script_6 건)

- `src/align_and_split.py:104-107` — 핵심 파라미터
- `src/align_and_split.py:800` — forward window
- `src/align_and_split.py:818` — adjusted_score 계산
- `src/align_and_split.py:828` — MATCH_THRESHOLD 수락 분기
- `src/align_and_split.py:996-1042` — re-sync 블록
- `TaskLogs/20260414_001113_pipeline_report.txt` — 1차 붕괴 증거

---

# [APPEND] 2026-04-14 오후 — Pipeline Manager 코드 드리프트로 인한 Stage 2 누락 (CRITICAL)

## 1. 발견된 문제

### 현상
- 신규 배치(2026-04-13_new_batch, 1127개 WAV)에 대한 `evaluate_dataset.py` 실행 중 **Tier 2 pool이 849/1127 (75.3%)** 로 치솟음
- 이전 canonical 4196 데이터셋의 Tier 2 pool은 **~4.5%**였음 → **약 17배 이상**
- Tier 2 진입률 메모리 기준("~15% 회복")으로도 설명 불가한 이상치

### Tier 1 유사도 분포 비교
| 구간 | 이전 4196 (2026-02-20) | 신규 1127 (2026-04-14) |
|------|---------------------|-----------------------|
| sim = 1.0 | 91.5% | **39.2%** |
| sim 0.95–1.0 | 4.0% | 2.1% |
| sim 0.80–0.95 | 4.5% | 19.3% |
| sim 0.50–0.80 | 0.1% | 16.0% |
| **sim < 0.50** | **0.0%** | **23.4%** |
| Tier 2 pool | 4.5% | **75.3%** |
| 최종 PASS (Tier 1) | 95.4% | **1.2% (14/1127)** |

### 결정적 증거 — envelope 측정
`datasets/wavs/Script_1_0001.wav` (canonical, align_and_split.py 산출) vs 신규 배치:

| 파일 | lead silence | tail silence | peak | 산출 경로 |
|------|-------------|-------------|------|----------|
| Script_1_0001 (canonical) | 460ms ✅ | 870ms ✅ | 0.891 (normalized) | align_and_split.py |
| Script_1_0301 (신규) | 340ms ❌ | 250ms ❌ | 0.659 | pipeline_manager.py |
| Script_1_0302 (신규) | 380ms ❌ | 280ms ❌ | 0.540 | pipeline_manager.py |
| Script_1_0306 (신규) | 1090ms | **40ms** ❌ | — | pipeline_manager.py |

R6 기준(pre-attack ≥400ms, tail ≥730ms)에 **체계적으로 미달**. 429/1127 (38%)는 sim=1.0임에도 envelope 실패(Type F)로 FAIL 처리.

## 2. 근본 원인 — 두 추출 스크립트의 코드 드리프트

### 발견
- `pipeline_manager.py`는 자체 alignment + WAV 추출 로직을 **내부에 하드코딩**
- `pipeline_manager.py:374-390`의 추출은 단순 padding만 수행:
  ```python
  start_ms = max(0, int(seg['start'] * 1000) - AUDIO_PAD_MS)
  end_ms = min(len(audio), int(best_end_time * 1000) + AUDIO_PAD_MS)
  chunk = audio[start_ms:end_ms]
  chunk.export(str(out_path), format="wav")
  ```
- **Stage 2의 모든 처리 누락**: voice onset/offset 감지, sustained silence 검증, 비대칭 fade, R6 envelope 주입, peak normalization
- 한편 `align_and_split.py`의 `post_process_wavs()` (line 475~587)에는 이 모든 로직이 완비됨
- `pipeline_manager.py`는 `align_and_split`을 **import하지도, 참조하지도 않음** (grep 결과 전무)

### 원래 설계 의도 vs 실제
- **원래 지시사항**: `pipeline_manager.py`는 **얇은 오케스트레이터**, alignment/extraction은 `align_and_split.py`의 함수를 **직접 호출(B-1 패턴)**
- **실제 상태**: `pipeline_manager.py`가 alignment 로직을 **독자적으로 재구현**하면서, 2026-04-03에 `align_and_split.py`에 추가된 Stage 2 업데이트(sustained silence, 비대칭 fade, OFFSET_SAFETY 120ms, end ZC snap 비활성화)가 **완전히 반영되지 않음**

### 왜 발견이 늦었나
- canonical 4196 데이터셋은 `align_and_split.py`로 직접 산출 → 정상
- 신규 배치 실행 시에야 `pipeline_manager.py`가 사용됐고, 결과물의 envelope만 망가짐
- Stage 1의 matched count와 Stage 4.5의 composition은 정상 번호가 찍혀 의심을 피함
- 문제가 표면화된 건 **Tier 2 진입률 이상 → envelope 검증 → 파일 직접 측정** 순서로 역추적한 뒤

## 3. 적용한 수정 (B-1 직접 호출 래퍼)

### Fix A: pipeline_manager.py의 Stage 2 위임
- **변경 전**: pipeline_manager.py가 자체 추출만 수행 (envelope 없음)
- **변경 후**: `align_and_split.post_process_wavs()`를 import해서 Step 3 직후 호출

```python
# src/pipeline_manager.py (top)
from align_and_split import post_process_wavs

# src/pipeline_manager.py (in run())
# Step 4: Stage 2 post-processing — delegates to align_and_split
post_process_wavs(str(self.wavs_dir), wav_filter=self.newly_written_wavs)
```

### Fix B: newly-written WAV 추적
- `align_script()`에서 `chunk.export()` 성공 시 `self.newly_written_wavs.add(out_filename)`
- Step 4에서 이 집합만 post-process → canonical 데이터 건드리지 않음

### Fix C: Step 6단계 → 7단계로 재번호
- `[Step 4/7] Applying Stage 2 post-processing` 신설
- Validate / Orphans / Report는 5/6/7로 한 칸씩 밀림
- docstring도 동일하게 갱신

### Fix D: 주석에 재발 방지 경고
```python
# Stage 2 post-processing (R6 envelope, asymmetric fade, sustained-silence
# voice offset) is implemented in align_and_split.py. Delegate rather than
# reimplement here — see 2026-04-14 envelope regression incident.
```

## 4. 재발 방지 원칙 (필독)

### 원칙 1: 하드코딩된 중복 금지
- **Stage 2(envelope/fade/normalize) 로직은 `align_and_split.post_process_wavs()` 단일 소스에만 존재**
- pipeline_manager, selective_composer, split_audio, 향후 신설 스크립트 — 모두 **import로 재사용**
- 같은 로직을 복붙하고 싶어지면 그건 **리팩토링 신호**이지 허가가 아님

### 원칙 2: 파라미터는 한 곳
- `PREATTACK_SILENCE_MS`, `TAIL_SILENCE_MS`, `OFFSET_SAFETY_MS`, `FADE_OUT_MS`, `SUSTAINED_SILENCE_MS` 등은 `align_and_split.py` 상단에만 정의
- 다른 스크립트가 같은 상수를 재선언하면 드리프트 발생 — **즉시 제거**

### 원칙 3: "산출물 정상성 스모크 테스트"를 배치 실행 직후 자동화
- 각 배치 완료 시 랜덤 샘플 N개의 lead/tail silence를 직접 측정하고 R6 기준 대비 보고
- Tier 2 진입률이 이전 baseline 대비 2σ 이상 튀면 즉시 경고
- 이번 사건은 이 스모크 테스트만 있었어도 새벽 4시가 아니라 직후에 잡혔을 것

### 원칙 4: "데이터 복구" 대신 "재생산"
- 구버전 알고리즘으로 산출된 데이터는 parameter 고정 + envelope post-hoc 적용해도 **alignment 자체의 잠재 결함**(AUDIO_PAD_MS/fade 적용 순서 등)을 되돌릴 수 없음
- 코드 드리프트로 인한 품질 저하는 **항상 원본부터 재실행**이 원칙
- 이번 건도 `datasets/2026-04-13_new_batch/` 전체 폐기 후 `rawdata/audio/2026-04-10_additional_lines/`에서 재실행

### 원칙 5: 엔지니어링 노트가 유일한 기관 기억
- 이런 실수는 commit message나 PR 본문으로는 덮이지 않음
- **"왜 이 구조여야 하는가"를 기록** — 미래의 누군가(또는 나)가 "왜 이걸 pipeline_manager에 직접 넣지 않지?"라고 묻는 순간을 막는 유일한 방법

## 5. 수정 대상 파일

- `src/pipeline_manager.py`
  - 상단 import: `from align_and_split import post_process_wavs` 추가 (line ~58)
  - `__init__`: `self.newly_written_wavs = set()` 초기화 (line 130)
  - `align_script()`: `chunk.export()` 성공 시 set에 등록 (line ~391)
  - `run()`: Step 4로 post-process 호출 신설, 이후 단계 재번호 (line 761~794)
  - docstring 상단: Pipeline Steps 6→7로 갱신 (line 7~13)

## 6. 관련 파일 / 참고 (pipeline_manager 건)

- `src/align_and_split.py:475-587` — `post_process_wavs()` 정식 구현 (유일한 소스)
- `src/pipeline_manager.py:374-390` — 과거 하드코딩 추출 지점 (수정됨)
- `datasets/2026-04-13_new_batch/eval_logs/eval_checkpoint.json` — Tier 2 75.3% 증거
- `datasets/wavs/Script_1_0001.wav` vs `datasets/2026-04-13_new_batch/wavs/Script_1_0301.wav` — envelope 차이 증거
- `logs/_new_batch_pipeline_stdout.log` — pipeline_manager.py 실행 흔적 (align_and_split 미호출)

---

# [APPEND #2] 2026-04-14 저녁 — 전면 감사 & B-1 순수 오케스트레이터 변환

## 1. 원래 설계의 재확인

**원래 지시사항 (user)**: pipeline_manager.py는 **추상적 레벨의 지휘통제만** 수행하고, 실제 로직은 참조된 개별 .py가 처리. "직접 호출 래퍼(B-1)" 패턴.

**실제 상태 (발견 전)**: pipeline_manager.py가 Stage 1 alignment 로직을 **240라인 자체 구현** + Stage 2 로직 완전 부재. 이것이 envelope 재앙의 근본 원인.

## 2. 변환 내용

### `src/align_and_split.py` — 함수 parametrize
`align_and_split()` 시그니처에 오버라이드 파라미터 추가:
```python
def align_and_split(model_size=MODEL_SIZE, script_filter=None, range_filter=None,
                    resume=True, device_override=None,
                    audio_dir=None, output_wav_dir=None, metadata_path=None):
```
- `audio_dir` 제공 시 `RAW_AUDIO_DIR` 대신 사용
- `output_wav_dir` 제공 시 `_make_versioned_output_dir()` 건너뛰고 지정 디렉토리에 저장 → 오케스트레이터가 자체 경로 지정 가능
- 기존 CLI 동작은 변함없음 (파라미터 미제공 시 fallback)

### `src/pipeline_manager.py` — 순수 오케스트레이터화
- 자체 alignment 로직(240라인) **전면 삭제**
- `align_script()` → `_run_align_and_split()` 한 번의 함수 호출로 위임
- `load_model()` 제거 (align_and_split이 Whisper 수명주기 담당)
- `normalize_text`, `AUDIO_PAD_MS`, `MATCH_THRESHOLD`, `SKIP_PENALTY`, `CONSEC_FAIL_LIMIT`, `SEG_SEARCH_WINDOW` 등 **redeclared 상수 전면 제거**
- 리포트에서 설정 표시 시 `align_and_split` 모듈 실시간 import로 표기 → 영원히 실제 값과 동기화
- Step 수 7→5 (Discover / Align(=align_and_split 위임) / Validate / Orphans / Report)
- 파일 라인 수: 860 → 632

### 감사: 다른 Stage 및 보조 스크립트 재점검

| 파일 | 상태 | 조치 |
|------|------|------|
| `src/pipeline_manager.py` | ✅ 순수 오케스트레이터로 변환 | 위 참조 |
| `src/process_missed.py` | ⚠ source WAV을 raw 복사 → envelope 없이 canonical로 유출 위험 | `post_process_wavs(WAVS_DIR, wav_filter=_newly_copied)` 호출 추가 (Stage 2 자동 적용) |
| `src/split_audio.py` | ⚠ 22.05kHz/16bit로 저장, R6 envelope 없음, 레거시 | `[LEGACY — DO NOT USE FOR PRODUCTION]` 헤더 추가 |
| `src/experiment_r6_ablation.py` | ⚠ `OFFSET_SAFETY_MS=80`, `AUDIO_PAD_MS=100` 옛 값 | `[FROZEN EXPERIMENT]` 헤더 추가 |
| `src/experiment_raw_envelope.py` | ⚠ `AUDIO_PAD_MS=100` 옛 값 | `[FROZEN EXPERIMENT]` 헤더 추가 |
| `src/experiment_threshold_ab.py` | ⚠ `OFFSET_SAFETY=20/100` 옛 값 | `[FROZEN EXPERIMENT]` 헤더 추가 |
| `src/evaluate_dataset.py` | ⚠ `SILENCE_THRESHOLD_DB=-40` — 의도된 divergence (boundary noise vs voice detect) | 주석으로 "INTENTIONAL DIVERGENCE" 명시 |
| `src/selective_composer.py` | ⚠ 같음 (+ `PREATTACK_TARGET_MS`, `TAIL_TARGET_MS`는 align_and_split과 **sync 필요**) | 주석으로 sync 필요성 명시 |
| `src/_run_reprocess_s2_partial.py` | ✅ 이미 `aas.OFFSET_SAFETY_MS` 동적 참조 (정상 패턴) | 유지 |
| `src/align_and_split.py.bak_260220` | ⚠ src/ 안에 남은 구버전 백업 | `archive/`로 이동 |

## 3. 단일 소스 원칙 (Single Source of Truth)

재발 방지를 위해 다음 규칙을 못 박습니다:

1. **Stage 1 alignment** 로직 = `align_and_split.align_and_split()` 에만 존재
2. **Stage 2 envelope/fade/normalize** 로직 = `align_and_split.post_process_wavs()` 에만 존재
3. **파라미터 상수** (PREATTACK_SILENCE_MS, TAIL_SILENCE_MS, OFFSET_SAFETY_MS, FADE_MS, FADE_OUT_MS, AUDIO_PAD_MS, SEG_SEARCH_WINDOW, SKIP_PENALTY, MATCH_THRESHOLD, CONSEC_FAIL_LIMIT 등) = `align_and_split.py` 모듈 상단에만 선언
4. **다른 스크립트**는 import로 참조하거나, **의도된 divergence**라면 주석으로 그 이유 명시
5. **`pipeline_manager.py`는 오케스트레이터** — 한 줄의 알고리즘 로직도 들어가지 않음. 추가하고 싶으면 `align_and_split.py`에 넣고 여기서는 호출만

## 4. CI/검증 제안 (미구현 제안)

향후 동일 사고를 방지하기 위한 자동 검사:

- `tests/test_no_param_drift.py`: `src/` 내 파일을 AST 파싱하여 `SEG_SEARCH_WINDOW`, `PREATTACK_SILENCE_MS` 등 특정 식별자의 redeclare를 감지. whitelist(선택지 E에 해당하는 의도된 divergence)만 허용
- `tests/test_batch_envelope_smoketest.py`: 신규 배치 완료 후 랜덤 샘플 N개의 lead/tail silence를 직접 측정, R6 기준 대비 편차 > 10% 면 실패
- `tests/test_tier2_baseline_drift.py`: evaluate_dataset 종료 시 Tier 2 진입률이 기존 baseline(~5%) 대비 2σ 이상이면 경고

현재 이 프로젝트에는 테스트 스위트가 없지만, 이번 사건은 **이 세 테스트만 있었어도 즉시 감지**됐을 것.

## 5. 이번 변환 후 파일별 역할 재정의

```
src/
  align_and_split.py       ← Stage 1 + Stage 2 로직 단일 소스. 모든 파라미터 정의.
                             CLI로 단독 실행 가능. 함수로 import 가능.
  pipeline_manager.py      ← 오케스트레이터. discover → align_and_split 호출
                             → validate → orphans → report. 알고리즘 로직 0 lines.
  evaluate_dataset.py      ← Stage 3-4 (Tier 1/2 Whisper 평가). 독립 모듈.
                             align_and_split과 다른 목적의 상수는 의도된 divergence.
  selective_composer.py    ← Stage 4.5 (SAM-inspired 품질 게이트). 독립 모듈.
                             align_and_split의 PREATTACK/TAIL 목표와 sync 필요.
  process_missed.py        ← 누락 라인 재처리. 복사 후 post_process_wavs 자동 적용.
  _run_reprocess_s2_partial.py  ← 이미 올바른 패턴 (aas 동적 import).
  split_audio.py           ← LEGACY. 건드리지 말 것.
  experiment_*.py          ← FROZEN. 재현용 아카이브, 현재 품질 증거 아님.
```

## 6. 검증 및 재실행

- 변환 후 `pipeline_manager` + `align_and_split` 모듈 import smoke test: PASS
- `align_and_split.align_and_split` 함수 시그니처에 `audio_dir`, `output_wav_dir`, `metadata_path` kwargs 추가 확인: PASS
- 기존 데이터 복구는 포기 (구버전 알고리즘 산출물은 원본부터 재실행하는 것이 원칙 — 원칙 4)
- `datasets/2026-04-13_new_batch/` 전체 폐기 후 `rawdata/audio/2026-04-10_additional_lines/`에서 refactored pipeline_manager로 재실행 예정
- `TaskLogs/20260414_004237_pipeline_report.txt` — 재현
- `rawdata/Scripts/Script_6_A0.txt` — 반복 모티프 원본
- `logs/engineering_note_2026-04-03.md` — tail truncation 노트(직전 건, 포맷 참조)
- `MEMORY.md` — "Wider windows cause Korean false-match cascading" 선행 경고

---

## 7. 사후 조사관 점검 — SRP 재검토 (2026-04-14 09:12 추가)

섹션 5에서 *"pipeline_manager = 오케스트레이터, 알고리즘 로직 0 lines"* 라고 선언했으나,
사후 조사관(agent) 점검에서 **두 건의 silent bug** 및 **한 건의 SRP 누수**가 추가 식별됨.
현재 실행 중인 파이프라인(08:56 시작)의 데이터 산출에는 영향 없음이 확인되었으며,
수정은 다음 실행부터 적용됨.

### 7.1 식별된 결함

**CRITICAL #1 — `--start-line` 플래그가 align_and_split까지 도달하지 못하던 문제**
- `align_and_split()` 시그니처에 `start_line` 파라미터가 없었음.
- `pipeline_manager.run()`에서 auto-compute 또는 CLI `--start-line`으로 산출한 `sl`을
  `align_script()`까지만 넘기고, 실제 위임 호출(`_run_align_and_split(...)`)에는 전달되지 않음.
- 결과: 사용자가 `--start-line 201`을 지정해도 align_and_split은 `current_script_line = min_audio_line`
  (오디오 파일명 범위의 최소 라인)부터 매칭 시작. 오케스트레이터의 지시가 수신자에게 도달하지 않음.

**CRITICAL #2 — `total_lines` 리포트 지표 오염 가능성**
- `align_script()`가 `(matched, [], len(sentences))`를 반환.
- `matched`는 align_and_split의 authoritative 카운트(오디오 커버 범위 기반).
- `len(sentences)`는 pipeline_manager의 로컬 `load_script()`가 `line_num >= sl`로 필터링한 결과
  (스크립트 끝까지 포함). 두 값의 기준이 다르므로 리포트의 `matched/total_lines` 비율이
  최대 수백 %까지 부풀 수 있음 (스크립트 전체 길이 ≫ 오디오 커버 범위일 때).
- **산출 데이터(wavs, script.txt)는 align_and_split 경로에서 생성되므로 무결성 영향 없음**.
  오염 범위는 `TaskLogs/*_pipeline_report.txt`의 진행률 텍스트에 국한.

**SRP 누수 #3 — `load_script()` knowledge fork**
- pipeline_manager.py와 align_and_split.py 양쪽에 동일 목적의 `load_script()`가 공존.
- pipeline_manager 쪽 결과는 `len(sentences)` 집계 + 로그 출력에만 사용되고 실제 정렬에는 미관여.
- 인코딩 리스트(`utf-8-sig, utf-8, cp949, euc-kr`)가 양쪽에 중복 — align_and_split 쪽 리스트가
  바뀌면 pipeline_manager는 조용히 구버전으로 동작.

### 7.2 현재 실행에 미치는 영향 (팩트체크)

| 시각 | 이벤트 |
|---|---|
| 08:56:40 | 파이프라인 시작. `align_and_split` / `pipeline_manager` 모듈이 old 상태로 메모리 로드. |
| 09:12 | `align_and_split.py` 수정 (`start_line` 파라미터 추가). |
| 09:13 | `pipeline_manager.py` 수정 (`start_line` 전달, `len(sentences)` → `total` 교체, `load_script()` 삭제). |

- Python 모듈은 import 시점에 바인딩되므로, 08:56 프로세스는 디스크 수정 영향 없음.
- CRITICAL #1: 08:56 모듈 양쪽 모두 `start_line` 비인지 상태로 일관 → 호출 에러 없음. 유저가
  `--start-line`을 안 넘겼으므로 silent drop도 발생하지 않음. **영향 0**.
- CRITICAL #2: 리포트 내 `total_lines`가 `len(sentences)` 기준으로 기록될 수 있음. 그러나
  datasets/wavs/와 script.txt는 authoritative 경로 산출물이므로 데이터 무결성 영향 없음.
- 결론: **현재 실행은 안전하게 완주 가능. 수정은 다음 실행부터 적용**.

### 7.3 적용된 수정 (온디스크, 다음 실행부터 유효)

- `align_and_split.py:594-596` — 시그니처에 `start_line=1` 추가.
- `align_and_split.py:747-758` — `effective_start = max(min_audio_line, start_line)`로
  `covered_lines` 필터와 `current_script_line` 초기값을 일원화. override 시 로그 추가.
- `pipeline_manager.py:align_script()` — `script_path` 파라미터 제거, 로컬 `load_script()` 호출
  제거, `_run_align_and_split(..., start_line=start_line)`로 전달, 반환값 `total`을 authoritative
  값으로 교체.
- `pipeline_manager.py` — 모듈 레벨 `load_script()` 함수 삭제. knowledge-fork 재발 방지용
  안내 주석 삽입.
- 검증: 두 파일 AST 파싱 통과, 런타임 시그니처 일치 확인.

### 7.4 향후 과제 — SRP 대규모 리팩터 (deferred)

섹션 5의 "알고리즘 로직 0 lines" 원칙은 지켜지고 있으나, pipeline_manager에는 여전히
**오케스트레이션이 아닌 책임**들이 혼재함. 다음 항목들은 즉시 처리가 필요하지 않아 향후 과제로 남김
(현재 파이프라인 동작에는 문제 없음 확인됨, 리소스 분리 불필요 판단).

| 현재 위치 (pipeline_manager.py) | 제안 분리 모듈 | 예상 작업량 |
|---|---|---|
| `validate()` (meta/WAV 무결성 검증, 통계 집계) | `src/dataset_validator.py` | ~20분 |
| `generate_report()` (TaskLogs 텍스트 포매팅) | `src/pipeline_reporter.py` | ~15분 |
| `collect_orphans()` + `write_missed_lines()` (파일 이동 + 리포트 파싱) | `src/orphan_collector.py` | ~10분 |
| 회귀 테스트 (`--validate-only`, `--collect-orphans`) | — | ~10분 |

**총 예상 45–60분**. 착수 조건: (1) 다음번 엔지니어링 여유 시, 또는 (2) 이들 책임 중 하나에
기능 추가/변경이 필요해지는 시점. 현재 모듈 크기(632줄)가 독해에 부담이 되는 단계까지 아직
여유가 있어 급하지 않음.

### 7.5 원칙 보강

섹션 1-5에 추가로 명시:

- **원칙 6 (신규)**: 오케스트레이터가 파라미터를 산출하되 수신자 시그니처에 해당 파라미터가 없으면,
  산출 자체를 금지한다. "UI에 노출된 CLI 플래그는 반드시 downstream까지 도달해야 한다"를
  정적 검증 대상으로 간주 (향후 smoke test로 자동화 가능 — `inspect.signature` 교차 확인).
- **원칙 7 (신규)**: 서로 다른 기준(필터링 규칙)으로 산출된 두 값을 하나의 튜플로 묶어 반환하지 말 것.
  한쪽은 authoritative 경로 산출물, 다른 쪽은 로컬 재계산 — 이런 혼합 반환은 silent metric
  오염의 온상이다. **반환값은 단일 source에서 나와야 한다**.
