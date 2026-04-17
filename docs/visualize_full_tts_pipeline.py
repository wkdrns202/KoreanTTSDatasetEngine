"""
End-to-End Korean TTS Training Pipeline Diagram
3-phase horizontal flowchart with current research highlighted.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import os

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

OUT = 'G:/Projects/AI_Research/TTSDataSetCleanser/docs/diagram_full_tts_pipeline.png'

fig, ax = plt.subplots(figsize=(22, 14))
ax.set_xlim(0, 30)
ax.set_ylim(0, 20)
ax.axis('off')

# ═══════════════════════════════════════════════════════════════
# Phase background bands
# ═══════════════════════════════════════════════════════════════
P1_X = (0.5, 7.5)     # Phase 1: Data Collection
P2_X = (8.0, 21.5)    # Phase 2: Data Processing (MAIN FOCUS - wider)
P3_X = (22.0, 29.5)   # Phase 3: TTS Training

BAND_Y = (1.0, 18.5)

# Phase 1 background
ax.add_patch(mpatches.Rectangle((P1_X[0], BAND_Y[0]), P1_X[1] - P1_X[0], BAND_Y[1] - BAND_Y[0],
             facecolor='#F5F5F5', edgecolor='none', zorder=0))

# Phase 2 background (highlighted)
ax.add_patch(mpatches.Rectangle((P2_X[0], BAND_Y[0]), P2_X[1] - P2_X[0], BAND_Y[1] - BAND_Y[0],
             facecolor='#EAF0F8', edgecolor='black', linewidth=2.5, zorder=0))

# Phase 3 background
ax.add_patch(mpatches.Rectangle((P3_X[0], BAND_Y[0]), P3_X[1] - P3_X[0], BAND_Y[1] - BAND_Y[0],
             facecolor='#F0F5F0', edgecolor='none', zorder=0))

# Phase headers
ax.text((P1_X[0] + P1_X[1]) / 2, 19.2, 'PHASE 1\nData Collection',
        ha='center', va='center', fontsize=14, fontweight='bold',
        fontfamily='Malgun Gothic')
ax.text((P1_X[0] + P1_X[1]) / 2, 18.7, '(Upstream — partially implemented)',
        ha='center', va='center', fontsize=10, style='italic', color='#555')

ax.text((P2_X[0] + P2_X[1]) / 2, 19.2,
        'PHASE 2: Data Processing & Curation',
        ha='center', va='center', fontsize=15, fontweight='bold',
        fontfamily='Malgun Gothic')
ax.text((P2_X[0] + P2_X[1]) / 2, 18.7,
        '★ CURRENT RESEARCH CONTRIBUTION ★',
        ha='center', va='center', fontsize=11, fontweight='bold', color='#1565C0')

ax.text((P3_X[0] + P3_X[1]) / 2, 19.2, 'PHASE 3\nTTS Training & Deployment',
        ha='center', va='center', fontsize=14, fontweight='bold',
        fontfamily='Malgun Gothic')
ax.text((P3_X[0] + P3_X[1]) / 2, 18.7, '(Downstream — planned)',
        ha='center', va='center', fontsize=10, style='italic', color='#555')


# ═══════════════════════════════════════════════════════════════
# Drawing helpers
# ═══════════════════════════════════════════════════════════════
def box(cx, cy, w, h, text, fs=9, bold=False, dashed=False, fill='white', edge='black', lw=1.5):
    ls = '--' if dashed else '-'
    rect = FancyBboxPatch((cx - w/2, cy - h/2), w, h,
            boxstyle='round,pad=0.08', facecolor=fill, edgecolor=edge,
            linewidth=lw, linestyle=ls, zorder=2)
    ax.add_patch(rect)
    fw = 'bold' if bold else 'normal'
    ax.text(cx, cy, text, ha='center', va='center', fontsize=fs,
            fontfamily='Malgun Gothic', fontweight=fw, zorder=3)
    return cy + h/2, cy - h/2, cx - w/2, cx + w/2

def varrow(x, y1, y2, lw=1.5, color='black'):
    ax.annotate('', xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=lw), zorder=2)

def harrow_thick(x1, y, x2):
    ax.annotate('', xy=(x2, y), xytext=(x1, y),
                arrowprops=dict(arrowstyle='->', color='black', lw=2.5), zorder=2)


# ═══════════════════════════════════════════════════════════════
# PHASE 1: Data Collection
# ═══════════════════════════════════════════════════════════════
P1_CX = (P1_X[0] + P1_X[1]) / 2

t, b, _, _ = box(P1_CX, 16.5, 6.0, 1.1,
    'Voice Talent Recording\n전문 성우 녹음 세션',
    fs=10, bold=True, fill='#FFFFFF')

varrow(P1_CX, b, 15.3)
t1, b1, _, _ = box(P1_CX, 14.7, 6.0, 1.2,
    'Raw Audio Files\nrawdata/audio/*.wav\n48kHz / 24-bit / Mono\n~8.2h total, 5 scripts',
    fs=9)

varrow(P1_CX, b1, 12.7)
t2, b2, _, _ = box(P1_CX, 12.0, 6.0, 1.2,
    'Script Text Files\nrawdata/Scripts/*.txt\n한국어 문장 단위',
    fs=9)

# Phase 1 summary at bottom
ax.text(P1_CX, 10.3,
    'Current status:\n• Single voice actor\n• 5 scripts collected\n• No automated ingestion yet',
    ha='center', va='top', fontsize=8.5,
    fontfamily='Malgun Gothic', style='italic',
    bbox=dict(boxstyle='round,pad=0.4', fc='white', ec='grey', lw=0.8))


# ═══════════════════════════════════════════════════════════════
# PHASE 2: Data Processing & Curation (7-Stage — MAIN)
# ═══════════════════════════════════════════════════════════════
P2_CX = (P2_X[0] + P2_X[1]) / 2
STAGE_W = 11.5
STAGE_H = 0.75

stage_y_positions = [17.3, 16.2, 15.1, 14.0, 12.9, 11.8, 10.7]
stage_contents = [
    ('Stage 1: DISCOVER', 'pipeline_manager.py — scan raw audio + scripts'),
    ('Stage 2: ALIGN & SPLIT',
        'align_and_split.py — Whisper medium, forward-only (w=25), R6 envelope (400/730ms, sustained 1000ms)'),
    ('Stage 3: VALIDATE', 'WAV ↔ metadata integrity check'),
    ('Stage 4: ORPHANS / REPORT', 'Collect unmatched WAVs + timestamped report'),
    ('Stage 5: EVALUATE',
        'evaluate_dataset.py — Tier 1 medium + Tier 2 large, R1~R6 metrics (target ≥95%)'),
    ('Stage 5.5: CURATION', 'Quarantine segments with sim < 0.80'),
    ('★ Stage 6: SELECTIVE COMPOSER ★',
        'selective_composer.py — 7-dim scoring (D1~D7, SAM-inspired + p-value)'),
]

prev_b = 17.85  # top anchor for first arrow
for i, (y, (title, desc)) in enumerate(zip(stage_y_positions, stage_contents)):
    is_stage6 = (i == 6)
    fill = '#FFF8E1' if is_stage6 else 'white'
    lw = 2.0 if is_stage6 else 1.3
    text = f'{title}\n{desc}'
    t, b, _, _ = box(P2_CX, y, STAGE_W, STAGE_H, text,
                     fs=8.5, bold=is_stage6, fill=fill, lw=lw)
    if i > 0:
        varrow(P2_CX, prev_b, t, lw=1.3)
    prev_b = b

# Arrow from Phase 1 to Stage 1
harrow_thick(P1_X[1] + 0.1, 14.7, P2_CX - STAGE_W/2 - 0.1)
ax.text((P1_X[1] + P2_CX - STAGE_W/2) / 2, 15.0,
        'input', fontsize=8, fontfamily='Malgun Gothic',
        ha='center', color='#555', style='italic')

# Under Stage 6: 3-way branching
branch_y = 9.5
varrow(P2_CX, prev_b, branch_y + 0.3, lw=1.5)

# ACCEPT (left)
ACC_X = P2_CX - 4.0
box(ACC_X, branch_y - 0.3, 3.2, 1.0,
    'ACCEPT\n3,930 (94.1%)\nAuto-admitted',
    fs=9, bold=True, fill='#C8E6C9')

# PENDING (center)
PEND_X = P2_CX
box(PEND_X, branch_y - 0.3, 3.2, 1.0,
    'PENDING\n159 (3.8%)\nHuman review',
    fs=9, bold=True, fill='#FFE0B2')

# REJECT (right)
REJ_X = P2_CX + 4.0
box(REJ_X, branch_y - 0.3, 3.2, 1.0,
    'REJECT\n87 (2.1%)\nExcluded',
    fs=9, bold=True, fill='#FFCDD2')

# Branch lines
line_y = 9.3
ax.plot([P2_CX, ACC_X], [line_y, line_y], 'k-', lw=1.2, zorder=2)
ax.plot([P2_CX, REJ_X], [line_y, line_y], 'k-', lw=1.2, zorder=2)
varrow(ACC_X, line_y, branch_y + 0.2, lw=1.3)
varrow(PEND_X, line_y + 0.2, branch_y + 0.2, lw=1.3)
varrow(REJ_X, line_y, branch_y + 0.2, lw=1.3)

# Requirement achievement note
ax.text(P2_CX, 7.8,
    'R1=95.48%   R2=100%   R3=95.4%   R4=99.9%   R5=TRUE   R6=99.93%\nALL 6 REQUIREMENTS MET',
    ha='center', va='center', fontsize=9, fontweight='bold',
    fontfamily='Malgun Gothic',
    bbox=dict(boxstyle='round,pad=0.4', fc='#FFFDE7', ec='#F9A825', lw=1.5))

# Final dataset
varrow(P2_CX, 7.35, 6.75, lw=1.8)
box(P2_CX, 6.2, 9.0, 1.0,
    'Curated Dataset\n3,930 WAV segments + script.txt + composition_results.csv  (~7.7h audio)',
    fs=10, bold=True, fill='#E1F5FE', lw=2.0)

# 7-dim detail box (below)
ax.text(P2_CX, 4.8,
    '7-Dim Scoring: D1 S_unprompted · D2 S_gap · D3 S_snr · D4 S_duration (p<0.05) · D5 S_stability (gate) · D6 S_confidence · D7 S_boundary\n'
    'Composite = geometric_mean(D1, D2, D3, D4, D6, D7) × gate(D5)     τ_accept = 0.768 (bootstrap calibrated)',
    ha='center', va='center', fontsize=8.5,
    fontfamily='Malgun Gothic',
    bbox=dict(boxstyle='round,pad=0.35', fc='white', ec='grey', lw=0.8))


# ═══════════════════════════════════════════════════════════════
# PHASE 3: TTS Training & Deployment
# ═══════════════════════════════════════════════════════════════
P3_CX = (P3_X[0] + P3_X[1]) / 2
P3_W = 6.8

p3_stages = [
    ('F5-TTS Phase 1', 'Base model training\non curated dataset'),
    ('F5-TTS Phase 2', 'Fine-tuning\nvoice identity'),
    ('MOS Evaluation', 'Mean Opinion Score\n(automated + human)'),
    ('Deployment', 'koreanAIvoice.com\nmodel update'),
    ('Real-world\nUsage & Feedback', 'User synthesis requests,\nerror reports'),
]
p3_y_positions = [16.8, 14.8, 12.8, 10.8, 8.8]

for i, (y, (title, desc)) in enumerate(zip(p3_y_positions, p3_stages)):
    text = f'{title}\n{desc}'
    t, b, _, _ = box(P3_CX, y, P3_W, 1.3, text,
                     fs=9, bold=True, dashed=True, fill='white', lw=1.3)
    if i > 0:
        varrow(P3_CX, prev_b_p3, t, lw=1.3)
    prev_b_p3 = b

# Arrow from Phase 2 output to Phase 3 Stage 1
harrow_thick(P2_X[1] + 0.1, 6.2, P3_CX - P3_W/2 - 0.1)
ax.plot([P3_CX - P3_W/2 - 0.1, P3_CX - P3_W/2 - 0.1], [6.2, 16.8],
        'k-', lw=2.5, zorder=2)
varrow(P3_CX - P3_W/2 - 0.1, 16.8, 16.8, lw=0)  # no-op, kept for alignment
# Instead, draw direct vertical feeder
# Simpler: draw an L-shaped arrow from Phase 2 dataset to Phase 3 first stage
# Already drawn via harrow_thick + vertical line, add arrowhead at top
ax.annotate('', xy=(P3_CX - P3_W/2, 16.8), xytext=(P3_CX - P3_W/2 - 0.1, 16.8),
            arrowprops=dict(arrowstyle='->', color='black', lw=2.5), zorder=2)

ax.text((P2_X[1] + P3_CX - P3_W/2) / 2, 6.5,
        'curated\ndataset', fontsize=8, fontfamily='Malgun Gothic',
        ha='center', color='#555', style='italic')


# ═══════════════════════════════════════════════════════════════
# FEEDBACK LOOP (curved dashed arrow: Phase 3 bottom → Phase 2 Stage 6)
# ═══════════════════════════════════════════════════════════════
# Start from "Real-world Usage" (P3_CX, 8.2) → curve down and left → end at Stage 6 (P2_CX, 10.7)

feedback_arrow = FancyArrowPatch(
    posA=(P3_CX - P3_W/2 - 0.1, 8.8),
    posB=(P2_CX + STAGE_W/2 + 0.1, 10.7),
    connectionstyle="arc3,rad=-0.35",
    arrowstyle='->', mutation_scale=25,
    lw=2.5, color='#C62828', linestyle='--', zorder=4
)
ax.add_patch(feedback_arrow)

# Feedback label
ax.text(22.5, 3.5,
    'SAM-Style Closed Loop: TTS ↔ ASR Bidirectional Improvement',
    ha='center', va='center', fontsize=10, fontweight='bold', color='#C62828',
    fontfamily='Malgun Gothic',
    bbox=dict(boxstyle='round,pad=0.4', fc='#FFEBEE', ec='#C62828', lw=1.5))

ax.text(22.5, 2.3,
    'TTS synthesis → ASR reverse-transcription → mismatch detection\n'
    '→ Refine data composition criteria + Fine-tune ASR vocabulary\n'
    '→ Models improve each other without human intervention (vision)',
    ha='center', va='center', fontsize=8.5,
    fontfamily='Malgun Gothic', style='italic', color='#444',
    bbox=dict(boxstyle='round,pad=0.35', fc='white', ec='#C62828', lw=0.8, alpha=0.9))


# ═══════════════════════════════════════════════════════════════
# Title & Caption
# ═══════════════════════════════════════════════════════════════
fig.text(0.5, 0.97, 'End-to-End Korean TTS Training Pipeline',
         ha='center', fontsize=17, fontweight='bold',
         fontfamily='Malgun Gothic')
fig.text(0.5, 0.945,
         'From Raw Voice Recordings to Deployed Synthesis Model — A SAM-Inspired Data Engine Approach',
         ha='center', fontsize=11, style='italic',
         fontfamily='Malgun Gothic', color='#444')

# Bottom caption
fig.text(0.5, 0.02,
    'Phase 2 is the current research contribution: a 7-stage data classification and curation pipeline '
    'that admits 94.1% of segments automatically using multi-dimensional quality scoring.  '
    'Dashed borders in Phase 3 indicate planned future work.  '
    'The dashed red curve represents the planned closed-loop improvement inspired by SAM\'s Data Engine.',
    ha='center', fontsize=9, style='italic', color='#333',
    fontfamily='Malgun Gothic', wrap=True)

plt.subplots_adjust(top=0.93, bottom=0.05, left=0.02, right=0.98)
plt.savefig(OUT, dpi=180, bbox_inches='tight', facecolor='white')
plt.close()
print(f"Saved: {OUT}")
