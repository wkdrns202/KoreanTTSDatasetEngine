# Gemini Prompt: End-to-End Korean TTS Training Pipeline Diagram

> 이 파일 전체를 Gemini에 복사-붙여넣기 하면 전체 TTS 학습 파이프라인 도식이 생성됩니다.
> 논문/발표용 flowchart로 적합하도록 흑백·수평 3단 구조로 요청합니다.

---

## 프롬프트 시작 (아래 전체 복사)

Create a clean, publication-quality horizontal flowchart diagram for a Korean Text-to-Speech (TTS) training pipeline. The diagram should tell the story of building a complete data-to-model system, with **three distinct phases** organized left-to-right. Use a minimalist black-and-white academic style suitable for a research paper figure.

### Overall Structure

The diagram has **three horizontal phases**, each in its own colored background band:

1. **PHASE 1: Data Collection** (left, light gray band) — Upstream, partially implemented
2. **PHASE 2: Data Processing & Curation** (center, light blue band, HIGHLIGHTED as current focus) — Current research contribution
3. **PHASE 3: TTS Model Training & Deployment** (right, light green band) — Downstream, planned

An arrow labeled "Feedback Loop (future)" should curve from Phase 3 back to Phase 2, indicating a planned SAM-style closed-loop improvement system.

### PHASE 1: Data Collection (Left)

Show these sequential boxes:

- **Voice Talent Recording** — Professional Korean voice actor, studio recording sessions
- **Raw Audio Files** (`rawdata/audio/*.wav`) — 48kHz / 24-bit / Mono, ~8.2 hours total, 5 scripts
- **Script Text Files** (`rawdata/Scripts/Script_N_A0.txt`) — Aligned Korean text, one sentence per line

Output arrow goes to Phase 2.

### PHASE 2: Data Processing & Curation (Center — MAIN FOCUS)

Mark this phase with a bold border labeled "**★ Current Research Contribution ★**".

Show **7 sequential stages** as vertical boxes stacked top-to-bottom within the phase:

1. **Stage 1: DISCOVER** — `pipeline_manager.py` — Scan raw audio + script files
2. **Stage 2: ALIGN & SPLIT** — `align_and_split.py` — Whisper medium transcription, forward-only greedy alignment (SEG_SEARCH_WINDOW=25), R6 envelope processing (pre-attack 400ms, tail 730ms, sustained silence 1000ms verification)
3. **Stage 3: VALIDATE** — WAV ↔ metadata integrity check
4. **Stage 4: ORPHANS / REPORT** — Collect unmatched WAVs + timestamped report
5. **Stage 5: EVALUATE** — `evaluate_dataset.py` — Tier 1 (Whisper medium) + Tier 2 (Whisper large on failures), compute R1~R6 metrics (target ≥95%)
6. **Stage 5.5: CURATION** — Quarantine segments with similarity < 0.80
7. **Stage 6: SELECTIVE COMPOSER** — `selective_composer.py` — SAM-inspired 7-dimension quality scoring (D1 S_unprompted, D2 S_gap, D3 S_snr, D4 S_duration with p-value, D5 S_stability gate, D6 S_confidence, D7 S_boundary)

Under Stage 6, show three output branches:
- **ACCEPT** → 3,930 segments (94.1%) → auto-admitted to final dataset
- **PENDING** → 159 segments (3.8%) → human review
- **REJECT** → 87 segments (2.1%) → excluded

Add a small inline note: "R1=95.48%, R2=100%, R3=95.4%, R4=99.9%, R5=TRUE, R6=99.93% — ALL 6 REQUIREMENTS MET"

Final dataset output box at the bottom of Phase 2:
**Curated Dataset** — 3,930 WAV segments + script.txt + composition_results.csv, ~7.7 hours

### PHASE 3: TTS Training & Deployment (Right)

Show these sequential boxes, marked as "Planned":

1. **F5-TTS Phase 1 Training** — Base model training on curated dataset
2. **F5-TTS Phase 2 Training** — Fine-tuning, voice identity optimization
3. **MOS Evaluation** — Mean Opinion Score (automated + human listening tests)
4. **Deployment** — koreanAIvoice.com model update
5. **Real-world Usage & Feedback** — User synthesis requests, error reports

### Feedback Loop (Curved Arrow from Phase 3 to Phase 2)

Add a dashed curved arrow from "Real-world Usage & Feedback" (Phase 3) back to "Stage 6: SELECTIVE COMPOSER" (Phase 2), labeled:

**"SAM-Style Closed Loop: TTS ↔ ASR Bidirectional Improvement"**

With a smaller annotation:
- TTS synthesis → ASR reverse-transcription → mismatch detection
- Signal used to: (1) refine data composition criteria, (2) fine-tune ASR vocabulary
- Models improve each other without human intervention (vision)

### Visual Style Requirements

- **Color scheme**: Monochrome (black outlines, white fill, gray phase bands)
- **Typography**: Sans-serif, technical/scientific paper style
- **Emphasis**: Phase 2 (current work) should be visually prominent — bold border, slightly larger boxes
- **Phase 1** should appear "completed-upstream" style — normal weight
- **Phase 3** should appear "planned" — dashed borders to indicate future work
- **Arrows**: Solid arrows within each phase, thick solid arrows between phases, dashed curved arrow for the feedback loop
- **Layout**: Horizontal flow with phase headers at the top of each band
- **Scale**: Designed to fit a landscape A4 / 16:9 slide; readable at presentation distance

### Key Data Points to Include on the Diagram

- Total raw audio: ~8.2 hours
- Total segments processed: 4,270 → 4,199 → 4,176 (after curation)
- Final ACCEPT: 3,930 (94.1%) — auto-admitted
- Pipeline target: R1-R6 ≥ 95% (ACHIEVED: 95.48% R1, 100% R2, 99.93% R6)
- 7-dimension scoring threshold: τ_accept = 0.768 (bootstrap-calibrated)

### Title

At the top of the diagram, render the title:

**"End-to-End Korean TTS Training Pipeline"**
**"From Raw Voice Recordings to Deployed Synthesis Model — A SAM-Inspired Data Engine Approach"**

### Caption (below diagram)

"Phase 2 represents the current research contribution: a 7-stage data classification and curation pipeline that admits 94.1% of segments automatically using multi-dimensional quality scoring. Phase 1 (upstream) and Phase 3 (downstream) are positioned to show the full system context. The dashed feedback arrow indicates the planned closed-loop improvement based on SAM's Data Engine architecture."

---

## 프롬프트 끝

### 사용 팁

1. **Gemini 2.0 Flash / Pro** 에서 위 프롬프트 그대로 입력
2. 만약 일부 요소가 생략되면 "Please include the dashed feedback arrow and all 7 stages in Phase 2" 로 추가 요청
3. 흑백 색감이 원하는 수준이 아니면 "Use strictly black-and-white, no color fills" 추가
4. 세부 조정 후 SVG/PNG로 export 가능

### 대체: 다이어그램 코드로 받고 싶을 때

위 프롬프트 끝에 다음 한 줄을 추가:

> "Output the diagram as **Mermaid flowchart code** (graph LR syntax) instead of rendered image, so I can customize it further."

그러면 Mermaid 코드가 반환되어 `docs/` 폴더의 MD 파일에 직접 삽입 가능합니다.
