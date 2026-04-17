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

---

# [APPEND #3] 2026-04-14 저녁 — Front Truncation 완전 해소 여정

## 1. 발견된 문제

DAW에서 산출물을 수동 검증한 결과, 한국어 어두 자음 attack의 **"시작 살짝 씹힘"** 현상 확인. 자동 검증(similarity)은 통과하지만 청취 시 매 라인 앞단이 부자연스럽게 잘려있음.

## 2. 진단 과정 — 네 단계의 가설과 검증

### 단계 1: Stage 2 파라미터 튜닝 (효과 부분)
가설: fade-in 10ms과 zero-crossing snap이 자음 attack을 감쇠/절삭.
- `FADE_MS: 10 → 5`
- `ONSET_SAFETY_MS: 30 → 40`
- START zero-crossing snap 비활성화
- 결과: mean onset -0.52ms 앞당김, 64% 라인 개선. 하지만 청취 체감 부족.

### 단계 2: Stage 1 padding 확대 (표면적 개선, 실효 0)
가설: Whisper가 약한 자음 attack을 타임스탬프에서 누락 → Stage 1 추출 자체가 늦음.
- `AUDIO_PAD_MS: 50 → 80`
- `SILENCE_THRESHOLD_DB: -65 → -68`
- 결과: WAV duration +33ms (padding 확장은 성공), **그러나 voiced region 시작점은 V1과 동일**.

### 단계 3: 구조적 원인 규명 (핵심 발견)
Stage 2의 트림 로직을 역추적:
```python
onset_detected = find_voice_onset_offset(samples)  # 검출된 음성 시작
onset = max(0, onset_detected - ONSET_SAFETY_MS)   # 30ms pull back
voiced = samples[onset:offset]
```
Stage 1이 padding을 30ms 늘려도, Stage 2의 `voice_onset` 검출 위치도 chunk 내부에서 30ms 이동 → `-30ms pullback`이라는 상수 오프셋이 그대로 작용하여 최종 voiced region 시작점은 **항상 source time −30ms로 고정**.

즉 `ONSET_SAFETY_MS`가 **Stage 2의 실효 최대 pullback 거리**. 이 값이 작으면 Stage 1의 여유 padding은 Stage 2에 의해 다시 트림됨.

### 단계 4: Pull-back 확장 실험 (80/100/120)
가설: ONSET_SAFETY_MS를 pad 크기만큼 키우면 효과.
- 테스트: 80, 100, 120 각각 실행
- 결과: 세 값 모두 **거의 동일한 산출**. 대부분 라인에서 `onset = 0`으로 clamp (chunk 경계 도달).
- 결론: AUDIO_PAD_MS가 병목. 80ms 한계에서 safety 확장은 효과 없음.

### 단계 5: DAW 수동 분석 → 320ms 경계 발견
사용자 DAW 검증: **최소 320ms는 확보되어야** consonant attack + pre-attack breath가 완전 보존됨.
- `AUDIO_PAD_MS: 80 → 320` (Stage 1 extraction)
- `ONSET_SAFETY_MS: 80 → 320` (Stage 2 pullback)
- 결과: voiced region 시작점이 source 기준 −320ms로 이동, speech는 voiced region 170-230ms 위치.

## 3. 320ms 검증 결과

| 지표 | V1 | S80 | S320 |
|------|----|----|------|
| dur delta vs V1 | — | +234ms | **+448ms** |
| onset shift vs V1 | — | +106ms | **+281ms** |
| head20 peak (voiced 첫 20ms amplitude) | 0.279 | 0.210 | **0.002** |
| 인접 WAV cross-correlation max | — | — | 0.257 (< 0.5) |

**부작용 평가**:
- ✅ **bleed 없음**: head20 peak 0.002 = -54dB (무음 수준), 인접 WAV 상관 ≤ 0.26
- ✅ **MIN_GAP_FOR_PAD_MS=30 보호** 유지: gap < 30ms 시 left_pad=0 로직이 밀집 발화에서 이전 세그먼트 침범 방지
- ⚠ **pre-speech ambient 180ms**: voiced region 첫 180ms가 불필요한 녹음실 ambient (기계적 낭비)

## 4. 해결 방안 — 320ms 사수 + 앞단 100ms 완전 무음화

**핵심 설계**:
- Stage 1 320ms 추출 + Stage 2 320ms pullback **유지** (consonant attack 손실 방지)
- Stage 2 처리 후 voiced region의 **pre-speech ambient 구간을 100ms로 trim**
- Trim 후 남은 100ms를 **완전 무음(sample=0)으로 대체** — 녹음실 ambient noise 제거

**최종 voiced region 구조**:
```
[100ms 완전 무음(zeros)] + [speech content with full consonant attack]
```

**최종 WAV 구조**:
```
[400ms pre-attack 무음(envelope)] + [100ms trim된 완전 무음] + [speech] + [730ms tail 무음]
```

총 pre-speech 길이 500ms (400 + 100), 모두 완전 무음. TTS 학습 측면에서:
- Ambient noise가 "silence" 토큰에 섞이지 않음 → 모델이 더 깨끗한 무음-발화 전이를 학습
- 300-500ms 범위는 TTS 표준 prosodic prefix 범위 내

## 5. 적용 파라미터 (최종)

| 파라미터 | 값 | 역할 |
|---------|-----|------|
| `AUDIO_PAD_MS` | **320** | Stage 1 left padding — consonant attack 원본 보존 |
| `MIN_GAP_FOR_PAD_MS` | 30 | 밀집 발화 시 padding=0으로 bleed 방지 |
| `SILENCE_THRESHOLD_DB` | **-68** | Stage 2 voice detection — 약한 자음 민감도 |
| `RMS_WINDOW_MS` | 10 | voice detection 해상도 |
| `FADE_MS` (fade-in) | **3** | speech boundary fade (공백→발화 전환) |
| `FADE_OUT_MS` | 5 | tail fade |
| `ONSET_SAFETY_MS` | **320** | Stage 2 pullback — Stage 1 padding과 동일하여 clamp 해제 |
| `OFFSET_SAFETY_MS` | 120 | tail side (sustained silence 보호) |
| `SUSTAINED_SILENCE_MS` | 1000 | 한국어 micro-pause 보호 |
| `PREATTACK_SILENCE_MS` | 400 | envelope pre-attack |
| `TAIL_SILENCE_MS` | 730 | envelope tail |
| **`PRESPEECH_PAD_MS`** (신규) | **100** | 음성 시작 전 무음 패드 — ambient trim 후 zero-fill 적용 |

## 6. 재발 방지 원칙 (추가)

- **원칙 8 (신규)**: Stage 1 padding과 Stage 2 pullback은 **동일 값으로 동반 조정**해야 한다. 한쪽만 키우면 다른 쪽이 병목이 된다. 두 값은 논리적 짝이다.
- **원칙 9 (신규)**: 사용자 DAW/청취 검증으로 도출된 파라미터는 자동 측정 메트릭보다 우선한다. 자동 측정은 "유의미한 변화가 있는가"는 잘 보지만 "듣기에 자연스러운가"는 못 본다.
- **원칙 10 (신규)**: ambient 무음 구간과 완전 무음 구간을 구분하여 관리한다. TTS 학습 데이터는 "silence = 정확히 0"을 요구하므로 녹음실 ambient는 샘플 레벨에서 zeroing 필요.


---

# [APPEND #4] 2026-04-14 저녁 — Zero-fill 구현의 함정과 Dual-Threshold 해법

## 1. 1차 구현 실패

`PRESPEECH_PAD_MS=100` 구현 1차 버전:
```python
speech_pos = speech_onset_abs - onset   # Stage 2의 voice_onset 재사용
if speech_pos > target_pre:
    voiced = voiced[speech_pos - target_pre:]
if speech_pos > 0:
    voiced[:min(speech_pos, target_pre)] = 0.0
```

테스트 결과: 18개 라인 중 **3개만 100ms 목표 도달**, 나머지는 0-50ms만 zero-fill.

## 2. 진단 — SILENCE_THRESHOLD_DB = -68이 ambient까지 voiced로 판정

Stage 2의 `find_voice_onset_offset()`가 **-68dB**로 동작 중. 녹음실 ambient noise floor가 전형적으로 -55 ~ -60dB 수준이라 **-68dB 이상이 됨** → Stage 2 관점에서 chunk 전체가 이미 "voiced" → `voice_onset ≈ chunk 시작 0`.

결과: `speech_pos = voice_onset - onset = 0 - 0 = 0` → 제로화할 영역 자체가 없음.

즉 **Stage 2의 voice-onset 검출은 "약한 자음 attack까지 포착하는 것"이 목적이지, "loud speech body 위치"를 찾는 게 아님**. 두 용도를 하나의 임계값으로 겸하려 한 것이 설계 오류.

## 3. Dual-Threshold 아키텍처 도입

**두 개의 임계값을 용도별로 분리**:

| 상수 | 값 | 용도 |
|------|-----|------|
| `SILENCE_THRESHOLD_DB` | **-68** | Stage 2 `find_voice_onset_offset()`의 voice onset 검출. ONSET_SAFETY=320 pullback의 기준점. **자음 attack 민감도** 확보 목적. ambient를 voiced로 잘못 봐도 괜찮음(pullback이 어차피 320ms). |
| `SPEECH_DETECT_DB` (신규) | **-40** | Step 3.5의 loud speech body 위치 독립 탐색. **ambient(-55~-60dB)와 loud speech(>-40dB)의 명확한 분리** 목적. 자음 attack은 의도적으로 포함 안 시킴 — 100ms 범위 내로 보존. |

## 4. 구현 변경

`post_process_wavs()` Step 3.5에서 별도 RMS 스캔 수행:

```python
win = int(sr * RMS_WINDOW_MS / 1000)
nw = len(voiced) // win
body_pos = 0
if nw >= 5:
    trimmed = voiced[:nw*win].reshape(nw, win)
    rms_v = np.sqrt(np.mean(trimmed**2, axis=1) + 1e-12)
    db_v = 20 * np.log10(np.maximum(rms_v, 1e-10))
    loud_idx = np.where(db_v >= SPEECH_DETECT_DB)[0]   # -40dB
    if len(loud_idx) > 0:
        body_pos = int(loud_idx[0]) * win

# Trim pre-body ambient beyond 100ms, zero-fill the rest
target_pre = int(sr * PRESPEECH_PAD_MS / 1000)
if body_pos > target_pre:
    trim = body_pos - target_pre
    voiced = voiced[trim:]
    body_pos = target_pre
if body_pos > 0:
    voiced[:body_pos] = 0.0

speech_pos = body_pos  # fade-in은 이 위치에서 시작
```

## 5. 검증 결과 (L0301-0318, 18개 라인)

| 지표 | 측정값 | 판정 |
|------|-------|------|
| Zero-fill 영역 길이 mean | 99.47ms | ✅ 목표 100ms 도달 |
| 100ms 정확 도달 라인 | 17/18 | ✅ 94% |
| 제로 영역 내 peak amplitude | max = 0.000000 | ✅ EXACT -∞ dB |
| TRIM vs S320 duration delta | -266ms | ✅ ambient 제거 확인 |
| TRIM vs V1 duration delta | +182ms | ✅ (100ms zeros + 82ms consonant attack) |
| Zero → speech 경계 click | ramp 첫 10 samples 모두 < 0.0002 | ✅ 3ms raised-cosine fade 정상 |

## 6. 재발 방지 원칙 (추가)

- **원칙 11 (신규)**: **하나의 상수를 여러 용도에 겹쳐 쓰지 말 것.** Voice onset 검출(민감도 높은 임계)과 speech body 위치 판정(엄격한 임계)은 물리적으로 다른 목적이다. 용도 분리가 곧 안정성.
- **원칙 12 (신규)**: Zero-fill 같은 파괴적 연산은 그 범위를 결정하는 임계값이 **의도대로 작동하는지 먼저 측정 검증**해야 한다. 1차 구현이 거의 no-op이었던 것은 측정 없이 "Stage 2 결과를 재사용하면 될 것"이라 가정했기 때문.
- **원칙 13 (신규)**: voiced region 내부 구조(`[pre-speech silence][consonant][body]`)를 스테이지별로 **명시적으로 모델링**해야 한다. 각 구간의 경계가 어떤 임계로 결정되는지 문서화되지 않으면 이번 같은 사고가 반복된다.

## 7. 최종 활성 파라미터 (2026-04-14 확정)

```python
# Stage 1
AUDIO_PAD_MS         = 320      # Left pad — consonant attack 원본 보존
MIN_GAP_FOR_PAD_MS   = 30       # bleed 방지 최소 gap
MAX_MERGE            = 5
SEG_SEARCH_WINDOW    = 25
SKIP_PENALTY         = 0.01
MATCH_THRESHOLD      = 0.50
CONSEC_FAIL_LIMIT    = 10
TAIL_EXTEND_MAX_MS   = 400

# Stage 2 DSP thresholds
SILENCE_THRESHOLD_DB = -68      # voice onset 검출 (sensitive)
SPEECH_DETECT_DB     = -40      # loud speech body 검출 (strict, zero-fill용)
RMS_WINDOW_MS        = 10
PEAK_NORMALIZE_DB    = -1.0

# Stage 2 timing
ONSET_SAFETY_MS      = 320      # Pullback (Stage 1 pad와 짝)
OFFSET_SAFETY_MS     = 120
SUSTAINED_SILENCE_MS = 1000
PRESPEECH_PAD_MS     = 100      # zero-fill 영역 길이

# Stage 2 envelope
PREATTACK_SILENCE_MS = 400
TAIL_SILENCE_MS      = 730
FADE_MS              = 3        # speech boundary fade-in
FADE_OUT_MS          = 5        # tail fade-out
```


---

# [APPEND #5] 2026-04-15 새벽 — Python Default-Argument Capture 하드코딩 (Stage 4.5)

## 1. 발견된 문제

Stage 4.5 Selective Composer 1차 실행 결과:
- ACCEPT 239 (16.2%) / PENDING 1183 (80.3%) / REJECT 51 (3.5%)
- 7 차원 중 3 차원이 상수(S_gap, S_snr, S_boundary 모두 1.0으로 고정)
- **S_confidence가 1473개 전부 정확히 0.5** (std=0.000)
- Per-script 분포 극단적 편향: S1 ACCEPT=0, S5 ACCEPT=239, S6 ACCEPT=0

## 2. 진단

### 2-1. 로그 단서
```
2026-04-15 01:24:12,858 [INFO] Loaded 4199 evaluation results   ← 우리 v3는 1473개
2026-04-15 01:24:12,858 [WARNING] Evaluation results lack unprompted scores
```

4199개는 2026-02-20 canonical 배치 checkpoint. Composer가 **잘못된 파일을 읽고 있음**.

### 2-2. 원인 — Python Default-Argument Capture

`selective_composer.py:574`:
```python
def load_eval_results(checkpoint_path=EVAL_CHECKPOINT_PATH):
```

Python은 **함수 정의 파싱 시점에** default 값 표현식을 평가하고 그 결과 객체를 함수에 바인딩합니다. `EVAL_CHECKPOINT_PATH`는 import 시점에 `os.path.join(LOG_DIR, "eval_checkpoint.json")`으로 평가되어 **구체적 문자열**이 박힙니다.

내 드라이버 스크립트의 런타임 override:
```python
sc.EVAL_CHECKPOINT_PATH = '...new batch path...'  # 모듈 attribute 변경
sc.main()                                          # main 내부에서 load_eval_results() 호출
                                                   # → 이미 박힌 default 사용 (OLD 경로)
```

모듈 attribute는 바뀌었지만, 함수 시그니처의 default는 바인딩 당시의 **구 경로 문자열**을 그대로 참조.

## 3. 수정

`load_eval_results`, `load_metadata`, `score_all_segments` 세 함수 모두 동일 결함.

```python
# BEFORE
def load_eval_results(checkpoint_path=EVAL_CHECKPOINT_PATH):
    if not os.path.exists(checkpoint_path):

# AFTER
def load_eval_results(checkpoint_path=None):
    if checkpoint_path is None:
        checkpoint_path = EVAL_CHECKPOINT_PATH  # 호출 시점 resolve
    if not os.path.exists(checkpoint_path):
```

## 4. 수정 후 재실행 결과

| 지표 | 수정 전 | 수정 후 |
|------|--------|--------|
| ACCEPT | 239 (16.2%) | **1245 (84.5%)** |
| PENDING | 1183 | 204 |
| REJECT | 51 | 24 |
| S_confidence mean/std | 0.500 / 0.000 | **0.783 / 0.048** |
| S_gap mean/std | 1.000 / 0.000 | **0.982 / 0.035** |
| tau_accept (calibrated) | 0.7646 | **0.8424** |

차원별 변별력 회복, per-script 분포 정상화(S1 A=546, S5 A=403, S6 A=296).

## 5. 전 스테이지 감사 결과

유사 결함 전수 조사 (`Explore` agent 활용) 결과:

### CRITICAL (현재 문제 있거나 될 여지 있음)
- **`align_and_split.py:594`**: `def align_and_split(model_size=MODEL_SIZE, ...)` — 현재는 모든 call site가 explicit arg 전달하여 작동 중이나, 새 caller가 `model_size` 생략하면 import 시점 "medium" 고정. 같은 클래스 결함. **None default 패턴으로 전환 권고**.

### MEDIUM (Side-effect at import time)
- **`align_and_split.py:131`**, **`evaluate_dataset.py:92`**, **`selective_composer.py:106`**: 모두 모듈 상단에서
  ```python
  logging.FileHandler(..., mode='w')
  ```
  사용. 모듈 import 시마다 로그 파일 **truncate**. 다른 orchestrator가 import하면 이전 실행 로그 손실. `mode='a'`로 변경 권고.

### LATENT (현재 안전, 패턴 취약)
- `evaluate_dataset.py:164,230`: `compute_rms_windowed(window_ms=RMS_WINDOW_MS)`, `transcribe_with_timeout(timeout_s=WHISPER_TIMEOUT_S)` — 모든 call site가 explicit arg 전달 중이나 동일 결함 소지
- `align_and_split.py:184,347,364`: `apply_fade`, `compute_rms_windowed`, `find_voice_onset_offset` 동일 패턴
- `selective_composer.py:440`: `compose_decision(tau_accept=DEFAULT_TAU_ACCEPT, ...)` 동일

### SAFE BY DESIGN
- `pipeline_manager.py`: CLEAN (오케스트레이터로서 상수 미redeclaration, __init__에서 수용, 명시적 전달)
- `selective_composer.py:578,596` (이번 수정본): None default + 런타임 resolve — **정답 패턴**

## 6. 재발 방지 원칙 (추가)

- **원칙 14 (신규)**: 함수 default 인자로 모듈 전역 상수를 직접 쓰지 말 것. Python은 함수 정의 시점에 default를 평가·바인딩하므로, 런타임 모듈 attribute override가 무력화됨. 정답 패턴:
  ```python
  def foo(path=None):
      if path is None:
          path = GLOBAL_PATH   # 호출 시점 resolve
  ```
- **원칙 15 (신규)**: 모듈 상단의 `logging.FileHandler(mode='w')`는 import 부수효과. 멀티-오케스트레이터 환경에서 로그 유실 야기. `mode='a'` 또는 orchestrator가 logger 주입하는 구조로 전환.
- **원칙 16 (신규)**: 모든 경로/임계값 상수는 **두 개의 단일 소스 원칙**을 만족해야 한다:
  (a) 값 자체는 모듈 상단에 단 한 곳 (원칙 1-3 이미 명시)
  (b) 함수가 해당 상수를 런타임에 참조해야 override 가능 (원칙 14 신규)
  두 원칙을 모두 만족해야 진정한 "single source of truth".

## 7. 심각성 평가

이번 결함은 외관상 "파이썬 gotcha"로 분류되지만, **프로젝트의 운영 단위에서는 하드코딩**입니다:
- 사용자가 의도적으로 `sc.EVAL_CHECKPOINT_PATH`를 override했음에도 기능이 먹지 않음
- 오케스트레이터 입장에서 "모듈 attribute = 설정"이라는 당연한 가정이 깨짐
- Stage 4.5의 결과가 **전체 배치 품질 평가를 완전히 왜곡** (84.5% vs 16.2%는 정성적·정량적으로 다른 판단 영역)

이는 2026-04-14 오후의 pipeline_manager 하드코딩 envelope 누락 사고와 **같은 클래스** — "외관상 override 가능한 것처럼 보이지만 실제로는 고정된 값".


---

# [APPEND #6] 2026-04-16 — Tail Zero-Fill + SUSTAINED_SILENCE 정렬 + D8 Bimodality Filter

## 1. 배경 — L0313 케이스

Stage 1+2 수정(AUDIO_PAD=320, ONSET_SAFETY=320, PRESPEECH_PAD=100, POSTSPEECH_PAD=300) 적용 후에도 일부 라인에서 **voiced region 내부의 이웃 문장 leak**이 잔존. 대표 사례가 Script_1_0313:
```
voiced region 구조: [front speech] + [880ms 연속 silence] + [tail speech]
최장 silent gap: 880ms
voiced region 마지막 300ms peak: 0.815 (전 amplitude 수준 — 이웃 문장)
```

v3 배치 Stage 4.5에서 이 케이스가 **ACCEPT로 분류됨** (sim=1.0 prompted=unprompted=1.0, 모든 R 지표 100%). 7 차원 중 어느 축도 "bimodal distribution"을 잡지 못함.

## 2. 진단 — 엔벨로프 불일치 + 검출 차원 누락

### 두 개의 구조적 gap

**Gap 1 — 설계 상수 간 불일치**:
```
TAIL_SILENCE_MS      = 730    (envelope tail 설계)
SUSTAINED_SILENCE_MS = 1000   (voice offset 확정 기준)
```
두 상수의 의미가 다름에도 하나는 730, 하나는 1000. 내부 로직 정합성 차원에서 bug.

**Gap 2 — Stage 4.5 차원 부재**:
정상 한국어 문장은 **정규분포 유사 단일 peak** 에너지 엔벨로프. 양 끝이 감쇠하는 unimodal 구조.
L0313은 "speech → 긴 silence → speech" 의 **bimodal 구조** — 현재 7차원(S_unprompted/S_prompted/S_gap/S_snr/S_duration/S_confidence/S_boundary) 중 **직접 측정하는 축이 없음**.

## 3. 적용한 수정

### 수정 1 — SUSTAINED_SILENCE_MS 1000 → 730

`align_and_split.py`:
```python
SUSTAINED_SILENCE_MS = 730   # was 1000, aligned to TAIL_SILENCE_MS
```

`find_voice_onset_offset()` default 인자도 None + 런타임 resolve 패턴으로 전환 (원칙 14 준수).

**⚠ 실측 결과: 현재 아키텍처에서는 measurable effect 없음**.

이유: `find_voice_onset_offset`의 `SILENCE_THRESHOLD_DB = -68dB` 기준으로 voiced window 검출 → 녹음실 ambient(-55~-60dB)가 전부 voiced로 분류 → `voiced[-1] = chunk 끝`으로 고정 → sustained silence 검증이 chunk 너머에서 silence 찾기 시도, 당연히 없음 → return (chunk_start, chunk_end) 사실상 no-op.

그래도 원칙적 정합성 확보 및 미래 threshold 재조정 시 올바른 동작 보장 위해 **변경 유지**.

### 수정 2 — D8 S_continuity 신설 (핵심)

`selective_composer.py`에 **bimodality 검출 차원** 추가:

```python
SPEECH_DETECT_DB = -40           # 기존 align_and_split과 동일 의미 (loud body 검출)
HARD_REJECT_CONTINUITY = 0.3     # 즉시 REJECT 임계
CONTINUITY_GAP_MS = 730          # gap 임계 = envelope tail 길이

def compute_continuity_score(samples, sr):
    """D8 — voiced region 내부에 (gap >= 730ms) + (gap 이후 speech 재등장) 패턴이
    있으면 bimodality violation. severity는 gap 길이 초과분에 비례."""
    win = int(sr*0.010); nw = len(samples)//win
    rms = np.sqrt(np.mean(samples[:nw*win].reshape(nw,win)**2, axis=1) + 1e-12)
    db = 20*np.log10(np.maximum(rms, 1e-10))
    is_speech = db >= SPEECH_DETECT_DB
    # ... scan for (long gap) + (speech after)
    # severity = min(1.0, 0.5 + excess_ms / 500.0)
    # return 1.0 - worst_severity
```

`compose_decision()`에 hard gate 추가:
```python
if scores.get('S_continuity', 1.0) < HARD_REJECT_CONTINUITY:
    return 'REJECT', 0.0, flags + ['hard_reject:S_continuity']
```

composite geometric mean 에도 포함 → 7차원 → 8차원.

### 수정 3 — Exception narrowing

발견 과정에서 `score_all_segments()` 의 `except Exception:` 가 NameError를 silent로 삼킨 사고 — `SPEECH_DETECT_DB` 미정의 버그가 "모든 S_boundary=0, S_continuity=0.5" 로 나타남. 원칙 15/16과 유사한 "조용한 실패" 패턴:

```python
# BEFORE
try:
    samples, sr = sf.read(wav_path, ...)
    scores['S_boundary'] = compute_boundary_score(samples, sr)
    scores['S_continuity'] = compute_continuity_score(samples, sr)
except Exception:
    scores['S_boundary'] = 0.0; scores['S_continuity'] = 0.5

# AFTER
try:
    samples, sr = sf.read(wav_path, ...)
except (IOError, OSError, RuntimeError) as e:
    logger.warning(...); scores['S_boundary'] = 0.0; scores['S_continuity'] = 0.5
else:
    scores['S_boundary'] = compute_boundary_score(samples, sr)
    scores['S_continuity'] = compute_continuity_score(samples, sr)
```

## 4. 검증

### Test 범위 (Script_1_0301-0318, 18 WAVs)

S_continuity 단독 측정:
```
L0313: 0.000   → hard_reject:S_continuity
L0301, 0302, 0303, 0305, 0315 (normal): 1.000
```
- 5 샘플 분석: longest gap L0313=880ms > 730ms threshold, 나머지 ≤ 660ms
- L0305(gap 660ms)도 threshold 아래라서 통과 — false positive 없음

Stage 4.5 재스코어링:
```
18개 중 ACCEPT 17 / REJECT 1 (L0313)
```

### Full v3 배치 (1473 WAVs)

D8 적용 전:
```
ACCEPT 1245 (84.5%) / PENDING 204 (13.8%) / REJECT 24 (1.6%)
```

D8 적용 후:
```
ACCEPT 1291 (87.6%) / PENDING 44 (3.0%) / REJECT 138 (9.4%)
↑ +46            ↓ -160             ↑ +114
```

Rejection 분석: 138 중 **132개가 `hard_reject:S_continuity`** (95.7%). D8이 rejection의 주동력.

Per-script bimodality 비율:
```
Script_1: 43/675 (6.4%)
Script_5: 52/471 (11.0%)
Script_6: 43/327 (13.1%)  ← 반복 어휘 → alignment 오류 높은 배치
```

S6 가 가장 높은 rejection — repetitive vocabulary의 영향.

## 5. 원칙 (추가)

- **원칙 17 (신규)**: 엔벨로프/타이밍 설계 상수 간 **관계식을 명시적으로 문서화**한다. `SUSTAINED_SILENCE_MS = TAIL_SILENCE_MS` 같은 제약은 코드 주석 + note에 둘 다 기록 (원칙 8 연장).
- **원칙 18 (신규)**: 단일 지표(similarity) 가 1.0 이어도 **구조적 기형**(bimodal distribution, 에너지 imbalance, 비정상 pause 등) 은 별개 축으로 검증해야 한다. Whisper는 prompted + unprompted 둘 다 GT text를 출력할 수 있는데, 이는 "audio 내용이 정확히 GT" 를 증명하지 않음 — GT 문맥을 알고 transcribe한 결과일 뿐.
- **원칙 19 (신규)**: 새 dimension 추가 시 **정상 샘플에서의 std** 를 반드시 측정하여 discriminative 여부 확인. std=0 이면 dead dimension (예: S_snr 이 모든 녹음에서 1.0 = 변별 없음).

## 6. 활성 파라미터 (2026-04-16 확정)

```python
# Stage 1 / Stage 2 align_and_split.py
AUDIO_PAD_MS         = 320
MIN_GAP_FOR_PAD_MS   = 30
SILENCE_THRESHOLD_DB = -68
SPEECH_DETECT_DB     = -40
RMS_WINDOW_MS        = 10
FADE_MS              = 3
FADE_OUT_MS          = 5
ONSET_SAFETY_MS      = 320
OFFSET_SAFETY_MS     = 120
SUSTAINED_SILENCE_MS = 730    # was 1000 (원칙 17)
PRESPEECH_PAD_MS     = 100
POSTSPEECH_PAD_MS    = 300
PREATTACK_SILENCE_MS = 400
TAIL_SILENCE_MS      = 730

# Stage 4.5 selective_composer.py
SILENCE_THRESHOLD_DB     = -40
SPEECH_DETECT_DB         = -40   # NEW
HARD_REJECT_UNPROMPTED   = 0.50
HARD_REJECT_GAP          = 0.50
HARD_REJECT_SNR          = 0.30
HARD_REJECT_CONTINUITY   = 0.3   # NEW — D8
CONTINUITY_GAP_MS        = 730   # NEW
DEFAULT_TAU_ACCEPT       = 0.88
DEFAULT_TAU_REJECT       = 0.65
```

## 7. 다음 단계 (미해결)

사용자 질문: **"SUSTAINED_SILENCE_MS=730으로 Stage 1+2에서 접근했는데도 L0313 증상이 여전한 이유?"**

답변 — `find_voice_onset_offset`가 SILENCE_THRESHOLD_DB=-68로 ambient까지 voiced로 분류하여 실효적으로 no-op인 구조. 근본 해결에는 아래 중 하나 필요:
1. 별도 "loud body threshold" 로 voice onset/offset 재검출 (현재 Step 3.5/3.6이 이미 하는 것과 유사, 단 Stage 2 trim 시점으로 옮겨야 함)
2. `find_voice_onset_offset` 에 bimodality 감지 추가 — 긴 gap 발견 시 첫 cluster 만 채택
3. Stage 1 word-level boundary refinement 를 end 쪽도 엄격 적용 (2026-04-03 formal ending 보호와 충돌 주의)

옵션 선택 및 설계는 별도 세션에서.


---

# [APPEND #7] 2026-04-16 — Tail Preservation 재설계 + Bimodal 차단 + 파라미터 4축 정렬

## 1. 배경

Option B 구현 후 L0313 bimodal 케이스는 원천 차단되었으나, 사용자가 청취한 결과 **정상 라인의 tail fade-out이 여전히 급격하게 cut-off** 되는 느낌을 보고. 기존 설계(5ms fade at body_end + 300ms zero-fill)는 실제 녹음의 자연 decay를 보존하지 못하고 본문 끝에서 바로 무음으로 전환하여 부자연스러운 끝마침을 생성.

## 2. 디자인 재정립 — 정규분포 엔벨로프 관점

사용자 직관: **오디오 엔벨로프는 정규분포 유사 단일 peak 형태, 양측 꼬리는 자연스럽게 감쇠**. 인공적 무음 절단보다 **natural decay + ambient preserve + 부드러운 fade**가 귀에 맞음.

정렬 원칙: 
```
SUSTAINED_SILENCE_MS (voice offset 확정 기준)
= TAIL_SILENCE_MS     (envelope tail zero 길이)
= POSTSPEECH_PAD_MS + FADE_OUT_MS (natural preserve + fade)
= 730ms
```

세 영역이 모두 같은 730ms 타임스케일에서 작동 → 내부 설계 일관성 확보.

## 3. 변경 사항 (세부 트레이스)

### Change 1 — POSTSPEECH_PAD_MS 300 → 700 (의미 전환)

**이전 (APPEND #3)**: body_end 이후 300ms를 **zero-fill** (ambient 완전 제거)
**이후**: body_end 이후 **700ms 자연 audio 보존** (zero-fill 삭제)

Step 3.6의 `voiced[body_end_pos:] = 0.0` 한 줄 제거. voiced region 끝단에 녹음 상의 decay + ambient가 그대로 통과.

### Change 2 — FADE_OUT_MS 5 → 30 + fade 위치 이동

**이전**: `voiced[body_end - 5ms : body_end] *= fade_curve` (body_end 직전 5ms fade)
**이후**: `voiced[-30ms:] *= fade_curve` (voiced region 맨 끝 30ms fade)

30ms raised-cosine이 자연 decay → 완전 무음 전환을 부드럽게 보간. Fade-in은 기존대로 speech_pos 지점 유지 (asymmetric: 3ms in / 30ms out).

### Change 3 — Option B: Stage 1+2 단계 bimodal 검출

**문제**: `find_voice_onset_offset`의 SILENCE_THRESHOLD_DB=-68dB가 ambient(-55~-60dB)까지 voiced로 판정 → voiced[-1]이 chunk 끝에 고정 → sustained silence 검증 사실상 no-op. L0313 같은 "speech + 긴 silence + 이웃 speech" 패턴이 그대로 통과.

**해법**: `find_voice_onset_offset` 내부에 **SPEECH_DETECT_DB(-40dB) 기반 body cluster 분석** 추가:
```python
body_windows = np.where(rms_db >= SPEECH_DETECT_DB)[0]
diffs = np.diff(body_windows)
split_points = np.where(diffs >= silence_windows_needed)[0]  # 730ms 기준
if len(split_points) > 0:
    # Bimodal 확인 → 첫 cluster 끝에서 offset 확정
    bimodal_offset = int(body_windows[split_points[0]])
```

**결과** (L0313):
- Voiced duration: 6680ms → 5560ms (-1120ms, 이웃 문장 제외)
- 최장 silent gap: 1040ms → 100ms
- Last 300ms peak: 0.815 (loud 이웃 content) → 0.338 (자연 decay)

이중 방어 구조 완성:
```
Stage 1+2 bimodal 검출 (prevention)
  → Stage 4.5 D8 S_continuity (residual filter)
```

### Change 4 — TAIL_EXTEND_MAX_MS 400 → 730

**문제**: Change 1-2로 POSTSPEECH_PAD=700 설정했으나, Phase A 측정에서 대부분 라인이 +400ms에서 clamp. Stage 1의 `right_pad = min(TAIL_EXTEND_MAX_MS, right_gap - 20)` 로직이 Whisper segment end 뒤 최대 400ms만 chunk에 포함 → Stage 2가 확보할 수 있는 post-body content 상한 = 400ms.

**해법**: TAIL_EXTEND_MAX_MS = 400 → **730** 상향. 네 개 상수가 모두 730ms로 일치.

**리스크 완화**:
- `right_pad = min(TAIL_EXTEND_MAX_MS, right_gap - 20)` — 인접 segment와의 gap 기준으로 자동 clamp (bleed 방지 유지)
- Option B의 bimodality detector가 이웃 문장 추출됐을 때 Stage 2에서 자동 trim

## 4. 검증 타임라인

### Unit test Phase A (L0301-0318, 150s 트림 오디오)

| 지표 | Option B (before tail fix) | Tail-preserve (after) |
|------|---------------------------|----------------------|
| Mean voiced duration delta vs prev | 0 | **+331ms** |
| Last 30ms peak | N/A | 0.004 mean (fade 작동) |
| Last 300ms peak | 0 (zero-fill) | 0.028 mean (자연 decay) |
| Fade profile (last 30ms, 5ms bins) | [0, 0, ...] | **monotonic 감쇠 → 0.000** |
| L0313 voiced duration | 5560ms | 5560ms (변화 없음, bimodal cap 유지) |
| L0313 longest gap | 100ms | 100ms |

청취 확인: 사용자 피드백 "끝 잘림 문제가 깨끗히 해결됐어"

### 사용자 발견: +400ms clamp 이상 (ref → Change 4)

측정에서 duration delta가 정확히 +400ms로 대부분 고정됨 발견. Stage 1 TAIL_EXTEND_MAX_MS의 제약임을 규명. 사용자 질문 "Whisper가 400ms단위로 분석을 하는건가?" → 아님, 단순 파이프라인 우리 쪽 magic number임을 확인 후 730으로 상향.

## 5. CUDA OOM 발견 (환경 이슈)

### 증상

전체 배치 실행 시 align_and_split 시작 즉시 OOM:
```
CUDA out of memory. Tried to allocate 20.00 MiB.
GPU 0 has a total capacity of 8.00 GiB of which 3.08 GiB is free.
Of the allocated memory 3.86 GiB is allocated by PyTorch
```

### 진단

- GPU 총: 8GB
- 시스템 UI 앱 (Chrome, Cursor, Visual Studio, Parsec, OneDrive, Claude, WhatsApp, Explorer, devenv x2 등) GPU 가속 점유: **~1GB**
- Whisper medium 로드 peak: **3.89GB**
- Transcribe workspace: 추가 1-2GB
- 합계: 6-7GB 필요 vs 실제 가용 ~7GB → 마진 거의 없음. 할당 과정에서 fragmentation으로 20MB 블록 못 찾아 OOM.

### 과거 성공 조건

이전 세션의 Stage 1+2 run들은 동일 하드웨어에서 성공 — 해당 시점에 UI 앱이 적었던 것으로 추정. 동일 VRAM 8GB지만 활성 앱 수에 따라 마진 가변.

### 해결 (환경)

`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 시도했으나 효과 없음 (이미 3.89GB 실제 allocated 상태, fragmentation만의 문제가 아님).

**사용자 조치**: Chrome, Cursor, Visual Studio 종료 → GPU 여유 확보.

### 재발 방지 원칙 (추가)

- **원칙 20 (신규)**: 8GB VRAM 환경에서 Whisper medium + 다수 UI 앱은 배타적. 풀 배치 실행 전 GPU-intensive 앱 종료 체크리스트 필요.
- **원칙 21 (신규)**: CUDA OOM은 fragmentation만의 문제가 아니다. `expandable_segments` 환경 변수는 마진이 충분할 때 fragmentation 해결용이지, 절대 메모리 부족은 해결 못 함.
- **원칙 22 (신규)**: 이전 run이 성공했다고 현재 run이 성공한다는 보장 없음 — 시스템 상태(다른 앱의 GPU 사용량)가 변수. 풀 배치 시점의 GPU 여유 명시적 확인 필요.

## 6. 최종 파라미터 스냅샷 (2026-04-16 확정)

```python
# Stage 1 extraction
AUDIO_PAD_MS         = 320     # front chunk pad
TAIL_EXTEND_MAX_MS   = 730     # rear chunk pad (was 400, 2026-04-16)
MIN_GAP_FOR_PAD_MS   = 30      # bleed 방지 gap threshold
MAX_MERGE            = 5
SEG_SEARCH_WINDOW    = 25
SKIP_PENALTY         = 0.01
MATCH_THRESHOLD      = 0.50
CONSEC_FAIL_LIMIT    = 10

# Stage 2 DSP
SILENCE_THRESHOLD_DB = -68     # voice onset (sensitive for soft consonants)
SPEECH_DETECT_DB     = -40     # loud body detection (bimodality + tail trim)
RMS_WINDOW_MS        = 10
PEAK_NORMALIZE_DB    = -1.0

# Stage 2 timing (all at 730ms for design consistency)
ONSET_SAFETY_MS      = 320
OFFSET_SAFETY_MS     = 120
SUSTAINED_SILENCE_MS = 730     # bimodality gap threshold (find_voice_onset_offset)
PRESPEECH_PAD_MS     = 100     # front zero-fill (preserve silence)
POSTSPEECH_PAD_MS    = 700     # rear natural preserve (no zero-fill, 2026-04-16)
FADE_MS              = 3       # fade-in at speech boundary
FADE_OUT_MS          = 30      # fade-out at voiced[-30ms:] (2026-04-16)

# Stage 2 envelope
PREATTACK_SILENCE_MS = 400
TAIL_SILENCE_MS      = 730

# Stage 4.5
HARD_REJECT_UNPROMPTED = 0.50
HARD_REJECT_GAP        = 0.50
HARD_REJECT_SNR        = 0.30
HARD_REJECT_CONTINUITY = 0.3
CONTINUITY_GAP_MS      = 730
```

## 7. 최종 WAV 구조 (2026-04-16)

```
[400ms envelope pre-silence (zeros)]
  + [100ms front zero-fill (PRESPEECH_PAD)]
  + [~220ms captured consonant attack region (320 pad - 100 zero)]
  + [3ms fade-in]
  + [speech body]
  + [~670ms natural decay + ambient (POSTSPEECH_PAD - FADE_OUT)]
  + [30ms fade-out raised-cosine]
  + [730ms envelope tail-silence (zeros)]
```

Total tail 구간 (speech body 끝부터 WAV 끝까지): 700 + 730 = **1430ms**, 그 중 30ms만 fade 처리, 나머지는 자연 decay + 무음.

## 8. Four-way Parameter Alignment

세 개의 독립 로직이 모두 730ms 타임스케일에서 작동:

| 로직 | 역할 | 상수 |
|------|------|------|
| Stage 1 extraction | Whisper_end 뒤 chunk 확장 | TAIL_EXTEND_MAX_MS=730 |
| Stage 2 bimodality | cluster 간 gap 판정 | SUSTAINED_SILENCE_MS=730 |
| Stage 2 preserve + fade | natural tail + smooth fade | POSTSPEECH_PAD_MS+FADE_OUT_MS=700+30=730 |
| Stage 2 envelope tail | 최종 zero silence | TAIL_SILENCE_MS=730 |

**설계 원칙**: 시간 기준이 하나(730ms)로 통일되어 각 로직의 경계가 서로 충돌하지 않음. 이전 1000/400/300 혼용 상태 대비 내부 정합성 대폭 향상.


---

# [APPEND #8] 2026-04-16 — 벤치마크 + AST 미계산 진단

## 1. 총 보유 오디오 데이터셋

| 데이터셋 | WAVs | 길이 | 커버 스크립트 |
|---------|------|------|-------------|
| Canonical (2026-02) | 4,206 | 8.43 h | S1(1-300), S2, S3, S4, S5(1-800) |
| v4 ACCEPT (2026-04-16) | 1,410 | 2.84 h | S1(301-984), S5(542-1019), S6(1-330) |
| 중복 (Script_5 542-800) | -243 | -0.44 h | v4 우선 적용 |
| **합계 (unique)** | **5,373** | **10.83 h** | S1-S6 전체 |

## 2. 파이프라인 벤치마크 — v4 배치 기준

### 처리 성능

| 지표 | 값 | 산식 |
|------|-----|------|
| **RT Rate** | **2.28x** | Raw Audio (201min) / Pipeline Compute (88min) |
| 정렬률 | 99.3% | Matched (1481) / Target (1492) |
| **Alignment Accuracy** | **94.5%** | ACCEPT (1410) / Target (1492) |
| Tier 1 R1 | 96.15% | Tier 1 PASS (1424) / Matched (1481) |

### 단계별 소요시간 (v4 실측)

| 단계 | 시간 | 비중 |
|------|------|------|
| Stage 1+2 (정렬+분할+envelope) | 32m 54s | 37% |
| Stage 3+4 (Tier 1 eval) | ~55m | 63% |
| Stage 4.5 (composer) | 18s | <1% |
| **총 파이프라인** | **~88분** | 100% |

### 환경

- GPU: NVIDIA RTX 3060 Ti (8GB VRAM)
- CPU: [user machine]
- 입력: 48kHz/24-bit/Mono WAV × 8 files, 총 200.97 min (3.35 h)
- Whisper: medium (Tier 1), large 미실행 (Tier 2 CUDA OOM)

## 3. 선행 연구 대비 신규성

### 기존 존재 (개별 컴포넌트)

| 기술 | 출처 |
|------|------|
| Whisper forced alignment | WhisperX (Bain et al., 2023) |
| Forced aligner for TTS | Montreal Forced Aligner (MFA, Kaldi-based) |
| VAD dual threshold | pyannote-audio, SpeechBrain |
| ASR confidence (logprob) | Whisper discussions, OpenAI docs |
| Quality scoring 2차원 | TTSDS2 (2025) |

### 미보고 (이 파이프라인의 신규 기여)

| 요소 | 설명 |
|------|------|
| **Bimodality detection** (D8 S_continuity) | silence cluster 분석으로 이웃 문장 leak 탐지 → Stage 1+2 예방 + Stage 4.5 필터 이중 방어 |
| **8차원 통합 quality gate** | D1-D8 + bootstrap calibration — 기존 1-2차원 대비 근본적 확장 |
| **S_stability (D5)** | Whisper multi-temperature sampling으로 전사 안정성 정량화 — 미보고 |
| **Dual-threshold voice detection** | -68dB onset sensitivity + -40dB body detection 분리 운용 |
| **Asymmetric DSP recipe** | 3ms fade-in / 30ms fade-out + 100ms front zero-fill + 700ms tail natural preserve |
| **한국어 formal ending 보호** | -습니다 등 형식 어미 boundary 650ms 확장 + micro-pause tolerance |
| **Forward-only search + skip-penalty** | 한국어 조사/어미 false-match cascading 방지에 특화 |

### 종합 평가

개별 컴포넌트(Whisper alignment, VAD, quality scoring)는 선행 연구에 존재하나, **이들을 8차원 통합 gate로 구성하고 한국어 형태론 특화 최적화를 적용한 end-to-end 자동화 파이프라인**은 학계·산업계에 보고되지 않음. 특히 **bimodality detection + multi-temperature stability scoring** 조합과 **dual-threshold voice detection의 분리 운용**은 완전 신규.

## 4. D4 S_duration (AST) 미계산 현황

### 증상

v4 배치 1,481개 중 **1,224개 (83%)가 `ast_not_computed`** → S_duration=0.5 fallback.

### 원인

`selective_composer.py:866-867`:
```python
raw_audio_dir = os.path.join(BASE_DIR, "rawdata", "audio")
sessions = discover_sessions(raw_audio_dir)
```

`discover_sessions`는 `rawdata/audio/` 직하 파일만 scan. v4 배치의 원본 오디오는 `rawdata/audio/2026-04-10_additional_lines/` **하위 디렉토리**에 위치 → session discovery 미포함 → session_id = 'unknown'.

### 영향

- S_duration이 전수 0.5 → composite score에서 duration anomaly 검출 불능
- 현재 ACCEPT/REJECT 판정은 나머지 7차원이 보상 (S_unprompted, S_gap 등이 주도)
- 그러나 **duration outlier**(비정상적으로 긴/짧은 segment)가 ACCEPT로 통과할 위험 잔존

### 해결 방향

파이프라인 자동화(`--full` 구현) 시 함께 해결:
1. `discover_sessions`에 recursive directory scan 추가
2. 또는 `--raw-audio-dir` override를 composer에 전달 (pipeline_manager가 관리)

---

# [IDEA #1] 2026-04-16 — G2P Phonetic Normalization으로 전사 신뢰도 향상

**상태**: 아이디어 — 미구현, 추후 검증 필요

## 1. 문제

현재 Stage 4.5의 S_unprompted(D1) / S_prompted(D2)는 **표기형(grapheme) 기준** 유사도 비교.
한국어 음운 변동(연음, 경음화, 비음화, ㅎ축약 등)으로 인해 Whisper가 **발음형으로 전사**하면 GT와의 similarity가 하락.

```
GT:      "먹었습니다"
Whisper: "머겄습니다"   ← 연음 반영 전사
raw sim: ~0.7x          ← 실제로는 정확한 음성인데 감점
```

이 문제는 **자유 연기(감정 발화, 극적 pause 등)** 톤에서 특히 심화됨.
Whisper가 감정적 발화를 표준 표기보다 실제 발음에 가깝게 전사하는 경향.

## 2. 제안

GT와 Whisper 전사 결과 **양쪽 모두를 G2P(Grapheme-to-Phoneme) 변환** 후 비교.

```
GT → G2P:      "머거씀니다"
Whisper → G2P: "머거씀니다"
phonetic sim:  1.0  ← 정확한 매칭 복구
```

한국어 음운 규칙은 규칙성이 높아(예외 거의 없는 필수 규칙) 기계적 변환 정확도가 실용 수준.

### 활용 가능한 규칙:
- **연음**: 받침 + 모음 → 초성 이동 (먹어 → 머거)
- **경음화**: 받침 ㄱㄷㅂ + ㄱㄷㅂㅅㅈ → 된소리 (학교 → 학꾜)
- **비음화**: 받침 ㄱㄷㅂ + ㄴㅁ → ㅇㄴㅁ (국물 → 궁물)
- **ㅎ 축약**: ㅎ + ㄱㄷㅈ → ㅋㅌㅊ (좋다 → 조타)

### 후보 라이브러리:
- `g2pk` (Korean G2P) — 검증 필요
- 또는 자체 규칙 기반 변환기 (규칙이 한정적이므로 가능)

## 3. 적용 방안

**Option A — max 병행**: `max(raw_sim, phonetic_sim)` 채택 → 연음 오탐만 복구, 기존 동작 보존

**Option B — 별도 차원**: D9 `S_phonetic` 신설 → composite score에 포함

**Option C — fallback**: raw_sim < threshold 일 때만 phonetic_sim 계산 (연산량 절감)

## 4. 기대 효과

- 연음/음운 변동에 의한 false rejection 감소
- 자유 연기 톤 데이터셋으로 확장 시 bimodality 오탐 완화 (strict envelope 가정 완화의 전제 조건)
- Whisper backward 분석의 한국어 연음 불일치 문제 우회

## 5. 리스크 및 검증 과제

- G2P 라이브러리 자체의 변환 정확도 → 소규모 검증 선행 필요
- 고유명사/외래어 처리 품질
- 연산 비용 (per-utterance G2P는 가벼울 것으로 예상, 단 확인 필요)
- 기존 파이프라인 안정성에 영향 없도록 Option A(max 병행)가 안전

## 6. 선행 조건

- [ ] `g2pk` 또는 대안 라이브러리 설치 및 기본 동작 확인
- [ ] 현재 v4 배치의 reject 케이스 중 음운 변동이 원인인 비율 측정
- [ ] 소규모 A/B 테스트 (raw_sim vs phonetic_sim, 50개 샘플)


---

# [APPEND #9] 2026-04-17 — D9 S_decay: Tail Truncation 자동 검출

## 1. 동기 — "귀로만 잡을 수 있는 결함"이라는 공백

APPEND #3~#7에서 tail cut-off 문제를 Stage 1+2 파라미터 통일(730ms 4축 정렬)로 **예방**했으나, 예방이 실패했을 때 이를 **감지**할 수단이 없었다. 현재 9개 차원(D1-D8 + D5 optional) 중 어느 것도 "발화 끝단이 자연스럽게 감쇠하는가"를 측정하지 않음:

- D1 S_unprompted / D2 S_gap: 텍스트 내용 기반 → 내용이 온전하면 1.0
- D4 S_duration (AST): 수십ms 잘림은 z-score 범위 안
- D7 S_boundary: envelope 무음 구간 존재 여부만 확인
- D8 S_continuity: bimodal(이웃 문장 leak) 전용

사용자 판단: "Stage 1+2에서 prevention은 됐지만, detection 필터가 아예 없으면 미래에 파라미터가 변경되거나 외부 데이터가 들어올 때 tail truncation이 무방비로 통과할 수 있다."

## 2. 가설 — 에너지 차분(finite difference)으로 cliff vs natural decay 구분

정상적인 한국어 발화의 에너지 엔벨로프는 정규분포 유사 단일 peak 형태. 발화 끝단은 **자연 감쇠(exponential-like decay)**를 보이며, 에너지가 수십~수백ms에 걸쳐 점진적으로 하강함.

반면 인공적 truncation(zero-fill, 급격한 fade, 또는 Stage 1 extraction 부족)은 에너지가 정상 수준에서 무음으로 **급락**. 이 차이는 에너지 엔벨로프의 **1차 차분(기울기, dB/ms)**으로 정량화 가능:

```
자연 감쇠:   ... -35 -38 -42 -47 -53 -60 -68  (완만한 roll-off)
             기울기: -0.6  -0.8  -1.0  -1.2  -1.4  -1.6 dB/ms

인공 cliff:  ... -35 -36 -120 -120 -120 -120    (급락)
             기울기: -0.2  -16.8  0.0  0.0  0.0 dB/ms  ← spike
```

**가설**: tail 구간 내 최대 |기울기|가 임계값(4 dB/ms)을 초과하면 비자연적 truncation.

## 3. 구현 여정 — 3차에 걸친 설계 수정

### 3-1. 1차 구현: body_end 기준 + 고정 50ms 분석 (실패)

```
body_end(-40dB) 에서 뒤로 50ms를 분석.
DECAY_NATURAL_THRESHOLD = 1.0 dB/ms, DECAY_CLIFF_THRESHOLD = 4.0 dB/ms
```

**결과**: canonical 30개 전부 S_decay > 0.8 (대부분 1.0). 변별력 있어 보였으나 **관측 구간이 잘못됨**.

**문제 진단**: -40dB 경계는 아직 speech body 안이다. body_end에서 50ms 뒤를 봐봤자 여전히 시끄러운 영역이라 기울기가 완만하게 나옴. 실제 잘림은 -40dB **아래**의 decay 영역에서 발생하는데, 그 구간을 전혀 보고 있지 않았음.

### 3-2. 2차 구현: body_end → last_signal 실구간 분석 (부분 성공)

사용자 지적: "speechbody는 -40dB true/false 기준이라 너무 높다(아직 시끄럽다). 마지막 signal 위치에서 -200ms까지를 보는 게 맞다."

```
body_end(-40dB) → last_signal(-68dB) 구간의 실제 길이와 gradient 분석.
두 가지 피처: (a) gradient steepness, (b) decay span(ms).
Score = min(gradient_score, span_score).
```

**결과**:
- canonical: mean 0.20, cliff 82% → **구 zero-fill 데이터를 정확히 감지**
- v4 tail-preserve: mean 0.97, natural 96% → **정상 데이터는 통과**

변별력 확보. 그러나 **구조적 맹점** 발견:

**문제**: body_end를 분석의 "시작점 앵커"로 쓰면, body_end 이전에 truncation이 발생한 경우를 감지 못함. 또한 body_end 자체가 없는 조용한 발화에서 return 1.0 (false negative).

### 3-3. 3차 구현: last_signal 앵커 + 역방향 730ms 스캔 (최종)

사용자 지적: "body_end 이전에 잘리는 사고가 발생했으면 어떻게 구별해? last_signal에서 역으로 730ms를 탐색하는 식의 정교한 접근이 좋겠다."

```
last_signal(-68dB) 앵커 → 역방향 730ms(=TAIL_SILENCE_MS) 스캔.
body_end는 span 계산의 "참고값"으로만 사용 (없어도 동작).
```

**핵심 변경**:
1. 앵커를 body_end → **last_signal**로 이동 (유일한 의존점)
2. 탐색 방향을 forward → **backward** (last_signal에서 역산)
3. 탐색 범위를 고정 50ms → **TAIL_SILENCE_MS(730ms)** 파라미터 연동
4. body_end 없는 경우 tail window 길이를 span 대체값으로 사용

## 4. 차분(finite difference) vs 미분(derivative) — 왜 극한을 사용하지 않는가

구현에서는 5ms RMS window의 **차분(finite difference)**을 사용한다:

```python
gradient = np.diff(tail_db) / DECAY_WINDOW_MS   # Δ(dB) / Δt = dB/ms
```

수학적으로 엄밀하게 이것은 **미분이 아니라 차분(finite difference)**이다. 미분은 lim(Δt→0) Δf/Δt로 정의되지만, 여기서는 Δt=5ms로 고정된 차분이다. 신호처리 실무에서 "discrete derivative"라는 관행적 표현이 있으나, 극한이 없으므로 수학적 미분과는 별개의 연산이다. 극한을 사용하지 않은 이유:

**이유 1 — 디지털 오디오는 본질적으로 이산 시계열이다.**
48kHz 샘플링의 해상도는 ~0.02ms. 이론적으로 1-sample 단위의 gradient를 계산할 수 있지만, 개별 샘플의 amplitude는 **정현파의 순간값**이지 에너지가 아니다. "볼륨"을 의미 있게 정의하려면 일정 구간에 걸쳐 RMS(에너지의 평균)를 계산해야 하며, 그 구간이 곧 window이다.

**이유 2 — window를 줄이면 노이즈에 취약해진다.**
에너지의 순간 변동(마찰음, 파열음의 release burst, 마이크 팝 등)이 극도로 짧은 window에서는 cliff처럼 보일 수 있다. 5ms window는 이런 순간 변동을 평활화하면서도 실제 truncation(10-20ms 단위의 구조적 급락)은 잡을 수 있는 해상도. 이것은 극한 접근이 아니라 **신호처리에서의 적정 해상도 선택** 문제다.

**이유 3 — 연산량은 무관하다.**
1481개 WAV × 730ms / 5ms = ~216,000 window. `np.diff`는 이 규모에서 < 1ms. window를 1ms(해상도 5배)로 줄여도 연산 시간 차이는 무시할 수 있다. 5ms를 선택한 것은 연산량이 아니라 **노이즈 내성과 검출 해상도의 tradeoff**이다.

요약: Δt=5ms의 차분은 미분의 근사가 아니라, 이산 에너지 시계열에 대해 **그 자체로 정확한 연산**이다. 연속 미분의 극한은 이 도메인에서 물리적 의미가 없으므로 추구할 이유가 없다.

## 5. 최종 알고리즘 구조

```python
def compute_decay_score(samples, sr):
    # Step 1: Strip R6 envelope (400ms lead + 730ms tail zeros 제거)
    # Step 2: 5ms RMS window로 dB 엔벨로프 계산
    # Step 3: last_signal(-68dB) 위치 확정 — 유일한 앵커
    # Step 4: last_signal에서 역방향 730ms를 tail window로 정의
    # Step 5: tail window 내 gradient(dB/ms) 계산, 최대 |기울기| 추출
    #          <= 4 dB/ms → 1.0 (natural)
    #          >= 10 dB/ms → 0.0 (cliff)
    # Step 6: body_end(-40dB) → last_signal 거리를 span으로 계산
    #          >= 50ms → 1.0 (충분한 decay 구간)
    #          <= 10ms → 0.0 (decay 없음)
    #          body_end 없으면 tail window 길이로 대체
    # Step 7: score = min(gradient_score, span_score)
```

## 6. 검증 결과

### 200개 샘플 비교 (최종 버전)

| 배치 | mean | natural (>=0.8) | borderline | cliff (<0.3) |
|------|------|----------------|-----------|-------------|
| canonical (구 zero-fill) | 0.2033 | 36 (18%) | 2 (1%) | **162 (81%)** |
| v4 tail-preserve | **0.9707** | **193 (97%)** | 2 (1%) | 5 (2.5%) |

### v4 전수 (1481개)

- cliff (<0.3): **32개 (2.2%)** — 청취 검증 대상
- 대표 cliff 파일: Script_1_0354, Script_1_0389, Script_1_0402, Script_5_0621, Script_6_0146

### 변별력 확인

- std = 0.16 (v4), 0.38 (canonical) — dead dimension이 아님
- canonical의 81% cliff 감지는 **정상** — 구 배치는 실제로 tail zero-fill 처리됨
- v4의 97% natural은 **730ms 4축 정렬의 효과** 확인

## 7. 파라미터 (최종)

```python
DECAY_SIGNAL_DB = -68        # align_and_split.SILENCE_THRESHOLD_DB와 동일
DECAY_WINDOW_MS = 5          # RMS 해상도 (노이즈 내성과 검출력의 tradeoff)
DECAY_SCAN_MS = 730          # 역방향 탐색 범위 (= TAIL_SILENCE_MS)
DECAY_MIN_SPAN_MS = 10       # 이하 → score 0 (truncated)
DECAY_GOOD_SPAN_MS = 50      # 이상 → score 1 (충분한 tail)
DECAY_NATURAL_GRAD = 4.0     # dB/ms, 자연 감쇠 상한
DECAY_CLIFF_GRAD = 10.0      # dB/ms, cliff 하한
```

## 8. 설계 원칙 (추가)

- **원칙 23 (신규)**: Prevention(파라미터 수정)과 Detection(품질 게이트)은 **독립적으로 모두 존재해야 한다**. Prevention이 완벽하더라도 Detection이 없으면 회귀를 감지할 수 없고, Detection만으로는 산출 단계에서 이미 발생한 결함을 되돌릴 수 없다.
- **원칙 24 (신규)**: 분석 구간의 앵커는 **"결함이 발생할 수 있는 위치"보다 하류(downstream)**에 잡아야 한다. body_end를 앵커로 쓰면 body_end 이전의 결함을 볼 수 없다. last_signal을 앵커로 쓰고 역방향 탐색하면 모든 위치의 결함을 커버할 수 있다.
- **원칙 25 (신규)**: 이산 시계열의 기울기 분석에는 **적정 해상도의 차분(finite difference)**을 사용한다. 미분(극한)이 아닌 차분인 이유: (a) 디지털 오디오의 RMS 에너지는 본질적으로 이산 시계열, (b) window를 줄여 극한에 접근하면 정현파 진동과 순간 burst가 구조적 결함으로 오판됨, (c) 해상도는 검출 대상의 시간 스케일(10-50ms)에 맞춰야 함.

## 9. 통합 상태

- `selective_composer.py`: 9차원 (D1-D9) + D5 optional
- `compose_decision()`: geometric mean에 S_decay 포함
- `calibrate_thresholds()`: bootstrap에 S_decay 포함
- `score_all_segments()`: D7/D8과 함께 WAV 읽기 시 계산
- `export_composition_csv()`: S_decay 컬럼 포함
- hard reject gate: **미설정** — 청취 검증 후 임계값 결정 예정

## 10. HEAD(앞단) 검출 — 구현 + 근본적 한계 발견

### 10-1. 1차 시도: zero-fill 전이 포함 → 전수 false positive

zero-fill(-120dB) → speech(-30dB) 전이를 포함해 gradient를 측정하면, 정상 파일도 12~18 dB/ms로 전수 cliff 판정. 인공 경계가 gradient를 지배하기 때문.

### 10-2. 2차 시도: zero-fill skip → 극단적 cliff만 감지 가능

first_signal(-68dB) **이후**의 speech 내부만 스캔하도록 수정. zero-fill 전이를 skip하면 정상 데이터의 max_rise가 1~4 dB/ms로 안정됨. HEAD에서는 span 조건을 비활성화 (한국어 파열음은 원래 span=0이 정상).

v4 1,481개 결과: HEAD natural 95.3%, borderline 70건(4.7%), cliff 0건. borderline 파일(0.315~0.797)을 청취한 결과 **전부 문제 없음 확인**.

### 10-3. 근본적 한계 발견 — 자음 절삭은 DSP로 감지 불가

사용자가 귀로 앞단 잘림을 확인한 파일:

```
Script_2_0011.wav: head=1.000, max_rise=3.21 dB/ms → 알고리즘은 "완벽한 정상"
Script_2_0068.wav: head=0.960, max_rise=4.24 dB/ms → 알고리즘은 "거의 정상"
```

두 파일 모두 gradient가 정상 범위(3~4 dB/ms)인데, **귀로 들으면 자음이 잘려 있다**.

이것은 HEAD truncation의 본질적 비대칭성 때문이다:

```
모음으로 시작하는 정상 발음 "아버지":
  [silence] → [-35dB] → [-14dB] → [-9dB]    gradient = 4.2 dB/ms

자음이 잘린 발음 "(ㄱ절삭)아버지":
  [silence] → [-35dB] → [-14dB] → [-9dB]    gradient = 4.2 dB/ms
                                              ↑ 동일한 파형
```

**"자음이 있었어야 하는데 없다"는 정보는 파형에 존재하지 않는다.** 이것은 Ground Truth 텍스트와 대조해야만 알 수 있는 **언어학적 정보**이지, 에너지 프로필에서 읽을 수 있는 **물리적 정보**가 아니다.

### 10-4. HEAD vs TAIL 비대칭 정리

| | TAIL (offset) | HEAD (onset) |
|--|--|--|
| 정상 패턴 | 점진적 감쇠 (1~4 dB/ms) | **급격한 시작** (자연) |
| 잘림 패턴 | 급격한 절단 (10+ dB/ms) | **급격한 시작** (잘림) |
| gradient로 구분 | **가능** — 정상과 잘림의 gradient가 4배+ 차이 | **불가능** — 정상과 잘림의 gradient가 동일 |
| 이유 | 발화 끝단은 물리적으로 자연 감쇠가 있음 | 발화 시작은 원래 급격 (consonant burst) |
| 감지 가능한 결함 | zero-fill cliff, fade 부족, extraction 부족 | 극단적 cliff(10+ dB/ms)만 가능 |
| 감지 불가능한 결함 | — | **자음 절삭** (gradient 정상 범위) |

### 10-5. D9 HEAD의 위치: "극단적 cliff만 잡는 안전망"

현재 구현(first_signal 앵커 + forward 스캔, gradient only)은:
- ✅ zero-fill/extraction 부족으로 인한 **에너지 절벽** (10+ dB/ms)을 감지
- ❌ 자음 절삭으로 인한 **미묘한 onset truncation**은 감지 불가

후자를 잡으려면 D1(S_unprompted, Whisper 전사)이 유일한 수단이다. Whisper가 "가버지"를 "아버지"로 전사하면 similarity가 떨어지고 → S_unprompted가 페널티를 줌. 그러나 Whisper도 한국어 자음 onset의 미묘한 절삭을 항상 감지하지는 못하므로 (prompted 모드에서 GT를 "알고" 맞춤), **이 클래스의 결함은 현재 파이프라인의 미해결 한계**로 남는다.

### 10-6. 기울기 임계값 정의 (최종)

**완만한 전이 (natural, <= 4 dB/ms)**:
- 30dB 에너지 차이가 50ms 이상에 걸쳐 분포
- TAIL: 자연 감쇠 p95 = 3.57 dB/ms
- HEAD: 정상 onset 후 speech 내부 p95 = 3.81 dB/ms
- 양쪽 모두 동일 임계값 사용 가능

**극단적 전이 (cliff, >= 10 dB/ms)**:
- 50dB+ 에너지 차이가 5ms 만에 발생
- TAIL: zero-fill cliff 실측 12~15 dB/ms
- HEAD: zero-fill 전이(skip 대상) 12~18 dB/ms, speech 내부 극단 케이스 6~8 dB/ms

**4~10 dB/ms 구간 (선형 보간)**:
- 파열음 release burst, 마찰음 onset 등 자연 순간 변동 보호
- HEAD에서는 이 구간에 걸리는 borderline(70건/1481)이 청취 확인 결과 전부 정상

