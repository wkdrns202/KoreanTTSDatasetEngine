"""
Publication-quality B&W algorithm diagrams for slide deck:
  1. Overall Pipeline Flow
  2. Selective Composer Decision Logic (7-dimension filtering)
  3. D4 AST Duration Anomaly Detection
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.font_manager as fm
import os

# Korean font setup
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

OUT_DIR = 'G:/Projects/AI_Research/TTSDataSetCleanser/docs'


# ═══════════════════════════════════════════════════════════════
# Shared drawing helpers
# ═══════════════════════════════════════════════════════════════

def make_box(ax, cx, cy, w, h, text, fs=9, bold=False, fill='white', lw=1.5):
    rect = mpatches.FancyBboxPatch((cx - w/2, cy - h/2), w, h,
            boxstyle='round,pad=0.08', facecolor=fill, edgecolor='black', linewidth=lw)
    ax.add_patch(rect)
    fw = 'bold' if bold else 'normal'
    ax.text(cx, cy, text, ha='center', va='center', fontsize=fs,
            fontfamily='Malgun Gothic', fontweight=fw)
    return cy + h/2, cy - h/2, cx - w/2, cx + w/2  # top, bot, left, right

def make_diamond(ax, cx, cy, w, h, text, fs=8.5):
    verts = [(cx, cy+h), (cx+w/2, cy), (cx, cy-h), (cx-w/2, cy)]
    poly = plt.Polygon(verts, facecolor='white', edgecolor='black', linewidth=1.5, closed=True)
    ax.add_patch(poly)
    ax.text(cx, cy, text, ha='center', va='center', fontsize=fs, fontfamily='Malgun Gothic')
    return cy + h, cy - h, cx - w/2, cx + w/2

def make_terminal(ax, cx, cy, w, h, text, fs=9, bold=True, fill='#E0E0E0'):
    """Rounded terminal (start/end) box."""
    rect = mpatches.FancyBboxPatch((cx - w/2, cy - h/2), w, h,
            boxstyle='round,pad=0.15', facecolor=fill, edgecolor='black', linewidth=2)
    ax.add_patch(rect)
    ax.text(cx, cy, text, ha='center', va='center', fontsize=fs,
            fontfamily='Malgun Gothic', fontweight='bold' if bold else 'normal')
    return cy + h/2, cy - h/2, cx - w/2, cx + w/2

def varrow(ax, x, y1, y2):
    ax.annotate('', xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle='->', color='black', lw=1.2))

def harrow(ax, x1, y, x2):
    ax.annotate('', xy=(x2, y), xytext=(x1, y),
                arrowprops=dict(arrowstyle='->', color='black', lw=1.2))

def line(ax, x1, y1, x2, y2):
    ax.plot([x1, x2], [y1, y2], 'k-', lw=1.2)

def lbl(ax, x, y, text, fs=9):
    ax.text(x, y, text, fontsize=fs, fontfamily='Malgun Gothic', ha='center', va='center')


# ═══════════════════════════════════════════════════════════════
# DIAGRAM 1: Selective Composer Decision Logic
# ═══════════════════════════════════════════════════════════════

def draw_composer_decision():
    fig, ax = plt.subplots(figsize=(9, 18))
    ax.set_xlim(0, 9)
    ax.set_ylim(0, 22)
    ax.axis('off')

    CX = 4.5

    # Title
    ax.text(CX, 21.5, 'Selective Data Composer', fontsize=14,
            fontweight='bold', ha='center', fontfamily='Malgun Gothic')
    ax.text(CX, 21.1, 'Decision Algorithm', fontsize=12,
            ha='center', fontfamily='Malgun Gothic')

    # ── Input ──
    t, b, l, r = make_terminal(ax, CX, 20.4, 5, 0.55, 'Input: Segment (WAV + GT text)')

    # ── 7-dim scoring ──
    varrow(ax, CX, b, 19.55)
    t1, b1, l1, r1 = make_box(ax, CX, 19.2, 5.5, 0.7,
        'Compute 7 Dimension Scores\nD1~D4, D6, D7', fs=9, bold=True)

    # ── Hard Reject Gate ──
    varrow(ax, CX, b1, 18.15)
    dt, db, dl, dr = make_diamond(ax, CX, 17.6, 3.8, 0.55,
        'Hard Reject Gate', fs=9)

    # Conditions text to the right
    ax.text(dr + 0.2, 17.6,
        'S_unprompted < 0.50\nor S_gap < 0.50\nor S_snr < 0.30',
        fontsize=7.5, fontfamily='Malgun Gothic', va='center',
        bbox=dict(boxstyle='round,pad=0.2', fc='#F5F5F5', ec='grey', lw=0.8))

    # YES → REJECT (right)
    RX = 8.0
    line(ax, dr, 17.6, RX, 17.6)
    lbl(ax, (dr + RX) / 2, 17.85, 'Yes', fs=8)
    t_rj1, b_rj1, _, _ = make_terminal(ax, RX, 17.0, 1.4, 0.45, 'REJECT', fs=9, fill='#D0D0D0')
    varrow(ax, RX, 17.6 - 0.15, t_rj1)

    # NO → Composite Score
    varrow(ax, CX, db, 16.55)
    lbl(ax, CX + 0.35, (db + 16.55) / 2, 'No', fs=8)
    t2, b2, l2, r2 = make_box(ax, CX, 16.15, 5.5, 0.8,
        'S_comp = geometric_mean(\n  D1, D2, D3, D4, D6, D7)', fs=9, bold=True)

    # ── Stability gate (if available) ──
    varrow(ax, CX, b2, 15.0)
    dt2, db2, dl2, dr2 = make_diamond(ax, CX, 14.5, 3.6, 0.5,
        'D5 Stability\navailable?', fs=8.5)

    # YES → apply gate
    LX = 1.0
    line(ax, dl2, 14.5, LX, 14.5)
    lbl(ax, (dl2 + LX) / 2, 14.75, 'Yes', fs=8)
    t_sg, b_sg, _, r_sg = make_box(ax, LX, 13.7, 2.2, 0.65,
        'S_comp *=\nstability\ngate', fs=8)
    varrow(ax, LX, 14.5 - 0.15, t_sg)
    # rejoin
    line(ax, r_sg, 13.7, CX - 0.1, 13.7)
    varrow(ax, CX, 13.7, 13.25)

    # NO → skip
    varrow(ax, CX, db2, 13.25)
    lbl(ax, CX + 0.35, (db2 + 13.25) / 2, 'No', fs=8)

    # ── Decision: S_comp >= tau_accept? ──
    dt3, db3, dl3, dr3 = make_diamond(ax, CX, 12.65, 4.0, 0.6,
        'S_comp >= 0.768\n(tau_accept)', fs=9)

    # YES → ACCEPT
    line(ax, dl3, 12.65, LX, 12.65)
    lbl(ax, (dl3 + LX) / 2, 12.9, 'Yes', fs=8)
    make_terminal(ax, LX, 12.0, 1.8, 0.5, 'ACCEPT', fs=10, fill='#D0D0D0')
    varrow(ax, LX, 12.65 - 0.15, 12.25)

    ax.text(LX, 11.35, 'Auto-admit\n(no human review)', fontsize=7.5,
            ha='center', fontfamily='Malgun Gothic', style='italic')

    # NO → next check
    varrow(ax, CX, db3, 11.45)
    lbl(ax, CX + 0.35, (db3 + 11.45) / 2, 'No', fs=8)

    # ── Decision: S_comp >= tau_reject? ──
    dt4, db4, dl4, dr4 = make_diamond(ax, CX, 10.85, 4.0, 0.6,
        'S_comp >= 0.65\n(tau_reject)', fs=9)

    # YES → PENDING
    line(ax, dr4, 10.85, RX, 10.85)
    lbl(ax, (dr4 + RX) / 2, 11.1, 'Yes', fs=8)
    make_terminal(ax, RX, 10.2, 1.6, 0.5, 'PENDING', fs=9, fill='#D0D0D0')
    varrow(ax, RX, 10.85 - 0.15, 10.45)
    ax.text(RX, 9.55, 'Human review\nrequired', fontsize=7.5,
            ha='center', fontfamily='Malgun Gothic', style='italic')

    # NO → REJECT
    varrow(ax, CX, db4, 9.65)
    lbl(ax, CX + 0.35, (db4 + 9.65) / 2, 'No', fs=8)
    make_terminal(ax, CX, 9.3, 1.6, 0.5, 'REJECT', fs=10, fill='#D0D0D0')

    ax.text(CX, 8.65, 'Excluded from dataset', fontsize=7.5,
            ha='center', fontfamily='Malgun Gothic', style='italic')

    # ── Summary box at bottom ──
    summary = (
        "Results (N=4,176)\n"
        "ACCEPT : 3,930  (94.1%)  Auto-admitted\n"
        "PENDING:   159  ( 3.8%)  Human review\n"
        "REJECT :    87  ( 2.1%)  Excluded"
    )
    ax.text(CX, 7.7, summary, fontsize=9, fontfamily='Malgun Gothic', ha='center', va='center',
            bbox=dict(boxstyle='round,pad=0.4', fc='#F5F5F5', ec='black', lw=1.5))

    # ── Dimension key ──
    dim_text = (
        "D1  S_unprompted   Whisper similarity (no GT prompt)\n"
        "D2  S_gap          Prompted vs unprompted gap\n"
        "D3  S_snr          Signal-to-noise ratio\n"
        "D4  S_duration     AST z-score (s/char, p < 0.05)\n"
        "D5  S_stability    Multi-temperature variance\n"
        "D6  S_confidence   Whisper avg_logprob\n"
        "D7  S_boundary     Envelope boundary quality"
    )
    ax.text(CX, 6.2, dim_text, fontsize=7.5, fontfamily='Malgun Gothic', ha='center', va='center',
            bbox=dict(boxstyle='round,pad=0.4', fc='white', ec='grey', lw=1))

    plt.tight_layout()
    path = os.path.join(OUT_DIR, 'diagram_composer_decision.png')
    plt.savefig(path, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Saved: {path}")


# ═══════════════════════════════════════════════════════════════
# DIAGRAM 2: D4 AST Duration Anomaly Detection
# ═══════════════════════════════════════════════════════════════

def draw_ast_algorithm():
    fig, ax = plt.subplots(figsize=(11, 17))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 21)
    ax.axis('off')

    CX = 5.5
    LX = 2.0   # left column center (ensures caption fits within [0, 4])
    RX = 9.0   # right column center (ensures caption fits within [7, 11])

    ax.text(CX, 20.4, 'D4: AST Duration Anomaly Detection', fontsize=14,
            fontweight='bold', ha='center', fontfamily='Malgun Gothic')

    # Input
    t, b, l, r = make_terminal(ax, CX, 19.6, 5.5, 0.55,
        'Input: WAV file + GT text + session_id')

    # Compute AST
    varrow(ax, CX, b, 18.75)
    t1, b1, l1, r1 = make_box(ax, CX, 18.4, 6.0, 0.7,
        'AST = duration / char_count\n(seconds per character)', fs=9, bold=True)

    # Load baseline
    varrow(ax, CX, b1, 17.4)
    t2, b2, l2, r2 = make_box(ax, CX, 17.05, 6.0, 0.7,
        'Load session baseline\nmean, std from same recording session', fs=9)

    # Compute z and p
    varrow(ax, CX, b2, 16.05)
    t3, b3, l3, r3 = make_box(ax, CX, 15.6, 6.0, 0.9,
        'z = (AST - mean) / std\np = 2 * (1 - CDF(|z|))   [two-tailed]', fs=9, bold=True)

    # Diamond: p < 0.05?
    varrow(ax, CX, b3, 14.45)
    dt, db, dl, dr = make_diamond(ax, CX, 13.85, 3.4, 0.6,
        'p < 0.05 ?', fs=10)

    # ── NO (p >= 0.05): Normal — LEFT branch ──
    line(ax, dl, 13.85, LX, 13.85)
    lbl(ax, (dl + LX) / 2, 14.1, 'No', fs=9)
    t_n, b_n, _, _ = make_terminal(ax, LX, 13.05, 2.8, 0.6,
        'NORMAL\nscore = high', fs=9, fill='#E8E8E8')
    varrow(ax, LX, 13.85 - 0.15, t_n)
    # Caption below NORMAL - constrained width
    ax.text(LX, 12.15, 'p >= 0.05\nStatistically normal\nAuto-admit eligible',
            fontsize=8, ha='center', va='center',
            fontfamily='Malgun Gothic', style='italic',
            bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='none'))

    # ── YES (p < 0.05): Anomaly detected ──
    varrow(ax, CX, db, 12.65)
    lbl(ax, CX + 0.35, (db + 12.65) / 2, 'Yes', fs=9)
    t4, b4, l4, r4 = make_box(ax, CX, 12.25, 5.0, 0.6,
        'ANOMALY: flag HUMAN_REVIEW', fs=9, bold=True)

    # Diamond: z direction
    varrow(ax, CX, b4, 11.25)
    dt2, db2, dl2, dr2 = make_diamond(ax, CX, 10.65, 3.0, 0.6,
        'z > 0 ?', fs=10)

    # z > 0: SLOW (LEFT)
    line(ax, dl2, 10.65, LX, 10.65)
    lbl(ax, (dl2 + LX) / 2, 10.9, 'Yes', fs=9)
    t_slow, b_slow, _, _ = make_terminal(ax, LX, 9.85, 2.4, 0.6,
        'SLOW\nanomaly', fs=9, fill='#E8E8E8')
    varrow(ax, LX, 10.65 - 0.15, t_slow)
    ax.text(LX, 9.0, 'Excess silence\nor alignment error',
            fontsize=8, ha='center', va='center',
            fontfamily='Malgun Gothic', style='italic',
            bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='none'))

    # z < 0: FAST (RIGHT)
    line(ax, dr2, 10.65, RX, 10.65)
    lbl(ax, (dr2 + RX) / 2, 10.9, 'No (z < 0)', fs=8)
    t_fast, b_fast, _, _ = make_box(ax, RX, 9.85, 2.4, 0.6,
        'FAST\nanomaly', fs=9, bold=True)
    varrow(ax, RX, 10.65 - 0.15, t_fast)

    # Diamond: formal ending + z < -1.5?
    varrow(ax, RX, b_fast, 8.85)
    dt3, db3, dl3, dr3 = make_diamond(ax, RX, 8.25, 3.6, 0.6,
        'Formal ending\n+ z < -1.5 ?', fs=8.5)

    # YES → truncation risk (down)
    varrow(ax, RX, db3, 7.2)
    lbl(ax, RX + 0.4, (db3 + 7.2) / 2, 'Yes', fs=9)
    t_tr, b_tr, _, _ = make_terminal(ax, RX, 6.85, 3.0, 0.6,
        'TRUNCATION\nRISK', fs=9, fill='#D0D0D0')
    ax.text(RX, 6.0, 'Flag:\nformal_ending_truncation_risk',
            fontsize=8, ha='center', va='center',
            fontfamily='Malgun Gothic', style='italic',
            bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='none'))

    # NO → FAST only (LEFT from this diamond, back toward center)
    line(ax, dl3, 8.25, CX, 8.25)
    lbl(ax, (dl3 + CX) / 2, 8.5, 'No', fs=9)
    t_fo, b_fo, _, _ = make_terminal(ax, CX, 7.65, 2.4, 0.5,
        'FAST only', fs=9, fill='#E8E8E8')
    varrow(ax, CX, 8.25 - 0.15, t_fo)

    # ── Formula box at bottom ──
    formula = (
        "score = 1.0 - min(1.0, |z| / z_cap)\n"
        "z_cap = 3.0   |   AST_SIGNIFICANCE = 0.05\n"
        "Formal endings: -었습니다, -겠습니다, -하십시오, ..."
    )
    ax.text(CX, 5.3, formula, fontsize=9, fontfamily='Malgun Gothic',
            ha='center', va='center',
            bbox=dict(boxstyle='round,pad=0.5', fc='#F5F5F5', ec='grey', lw=1))

    plt.tight_layout()
    path = os.path.join(OUT_DIR, 'diagram_ast_algorithm.png')
    plt.savefig(path, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Saved: {path}")


# ═══════════════════════════════════════════════════════════════
# DIAGRAM 3: Overall Pipeline with Filtering Summary
# ═══════════════════════════════════════════════════════════════

def draw_pipeline_overview():
    fig, ax = plt.subplots(figsize=(13, 20))
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 24)
    ax.axis('off')

    CX = 6.5
    RX = 11.5
    LX = 1.7

    ax.text(CX, 23.5, 'End-to-End 7-Stage Pipeline',
            fontsize=15, fontweight='bold', ha='center', fontfamily='Malgun Gothic')

    # Raw input
    t0, b0, l0, r0 = make_terminal(ax, CX, 22.7, 7, 0.55,
        'Input: rawdata/audio/*.wav + rawdata/Scripts/Script_N_A0.txt')

    # Stage 1: DISCOVER
    varrow(ax, CX, b0, 21.8)
    t1, b1, l1, r1 = make_box(ax, CX, 21.4, 7.2, 0.8,
        'Stage 1: DISCOVER\npipeline_manager.py  (2026-02-11)', fs=9, bold=True)

    # Stage 2: ALIGN & SPLIT
    varrow(ax, CX, b1, 20.35)
    t2, b2, l2, r2 = make_box(ax, CX, 19.85, 7.2, 1.0,
        'Stage 2: ALIGN & SPLIT\nalign_and_split.py  (2026-02-11)\n+ R6 envelope update (2026-04-04)', fs=9, bold=True)
    ax.text(r2 + 0.15, 19.85, '4,270\nsegments',
            fontsize=8, fontfamily='Malgun Gothic', va='center')

    # Stage 3: VALIDATE
    varrow(ax, CX, b2, 18.55)
    t3, b3, l3, r3 = make_box(ax, CX, 18.15, 7.2, 0.8,
        'Stage 3: VALIDATE\nWAV <-> metadata integrity check', fs=9, bold=True)

    # Stage 4: ORPHANS / REPORT
    varrow(ax, CX, b3, 17.1)
    t4, b4, l4, r4 = make_box(ax, CX, 16.7, 7.2, 0.8,
        'Stage 4: ORPHANS / REPORT\nCollect unmatched WAVs + timestamped report', fs=9, bold=True)

    # Stage 5: EVALUATE
    varrow(ax, CX, b4, 15.65)
    t5, b5, l5, r5 = make_box(ax, CX, 15.15, 7.2, 1.0,
        'Stage 5: EVALUATE\nevaluate_dataset.py  (2026-02-11)\nTier 1 medium + Tier 2 large, R1~R6 metrics', fs=9, bold=True)
    ax.text(r5 + 0.15, 15.15, '4,199\nevaluated',
            fontsize=8, fontfamily='Malgun Gothic', va='center')

    # Stage 5.5: CURATION
    varrow(ax, CX, b5, 13.85)
    ft, fb, fl, fr = make_diamond(ax, CX, 13.25, 3.8, 0.6,
        'Stage 5.5: CURATION\nsim >= 0.80 ?', fs=9)

    # NO -> quarantine
    line(ax, fr, 13.25, RX, 13.25)
    lbl(ax, (fr + RX) / 2, 13.5, 'No', fs=8)
    make_terminal(ax, RX, 12.5, 2.0, 0.55,
        'Quarantine\n74 items', fs=8, fill='#E0E0E0')
    varrow(ax, RX, 13.25 - 0.15, 12.77)

    # YES
    varrow(ax, CX, fb, 12.1)
    lbl(ax, CX + 0.35, (fb + 12.1) / 2, 'Yes', fs=8)
    ax.text(r4 + 0.15, 13.25, '4,176\nafter\ncuration',
            fontsize=8, fontfamily='Malgun Gothic', va='center')

    # Stage 6: SELECTIVE COMPOSER
    t6, b6, l6, r6 = make_box(ax, CX, 11.55, 7.5, 1.1,
        'Stage 6: SELECTIVE COMPOSER  (2026-04-05)\nselective_composer.py\n7-dimension scoring (SAM-inspired + p-value)', fs=9, bold=True,
        fill='#F0F0F0')

    # Hard reject
    varrow(ax, CX, b6, 10.35)
    ht, hb, hl, hr = make_diamond(ax, CX, 9.75, 4.2, 0.6,
        'Hard Reject\nGate', fs=9)
    ax.text(hl - 0.15, 9.75,
        'D1<0.50\nD2<0.50\nD3<0.30', fontsize=7.5, fontfamily='Malgun Gothic',
        ha='right', va='center',
        bbox=dict(boxstyle='round,pad=0.2', fc='#F5F5F5', ec='grey', lw=0.6))

    line(ax, hr, 9.75, RX, 9.75)
    lbl(ax, (hr + RX) / 2, 10.0, 'Fail', fs=8)
    make_terminal(ax, RX, 9.1, 1.8, 0.5, 'REJECT', fs=9, fill='#E0E0E0')
    varrow(ax, RX, 9.75 - 0.15, 9.35)

    varrow(ax, CX, hb, 8.5)
    lbl(ax, CX + 0.35, (hb + 8.5) / 2, 'Pass', fs=8)

    # Composite threshold
    ct, cb, cl, cr = make_diamond(ax, CX, 7.9, 4.4, 0.7,
        'S_comp >= 0.768 ?\n(tau_accept)', fs=9)

    # YES -> ACCEPT
    line(ax, cl, 7.9, LX, 7.9)
    lbl(ax, (cl + LX) / 2, 8.15, 'Yes', fs=9)
    make_terminal(ax, LX, 7.1, 2.4, 0.6,
        'ACCEPT\n3,930 (94.1%)', fs=9, fill='#D0D0D0', bold=True)
    varrow(ax, LX, 7.9 - 0.15, 7.4)
    ax.text(LX, 6.3,
        'Auto-admitted\n(no human review)\np >= 0.05 on D4',
        fontsize=7.5, ha='center', va='center',
        fontfamily='Malgun Gothic', style='italic',
        bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='none'))

    # NO -> next check
    varrow(ax, CX, cb, 6.7)
    lbl(ax, CX + 0.35, (cb + 6.7) / 2, 'No', fs=9)

    ct2, cb2, cl2, cr2 = make_diamond(ax, CX, 6.1, 4.4, 0.7,
        'S_comp >= 0.65 ?\n(tau_reject)', fs=9)

    # YES -> PENDING
    line(ax, cr2, 6.1, RX, 6.1)
    lbl(ax, (cr2 + RX) / 2, 6.35, 'Yes', fs=9)
    make_terminal(ax, RX, 5.3, 2.2, 0.6,
        'PENDING\n159 (3.8%)', fs=9, fill='#E0E0E0', bold=True)
    varrow(ax, RX, 6.1 - 0.15, 5.6)
    ax.text(RX, 4.4,
        'Human review\nrequired',
        fontsize=7.5, ha='center', va='center',
        fontfamily='Malgun Gothic', style='italic',
        bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='none'))

    # NO -> REJECT
    varrow(ax, CX, cb2, 4.9)
    lbl(ax, CX + 0.35, (cb2 + 4.9) / 2, 'No', fs=9)
    make_terminal(ax, CX, 4.5, 2.0, 0.6,
        'REJECT\n87 (2.1%)', fs=9, fill='#D0D0D0', bold=True)

    # Final dataset box
    ax.text(LX, 4.9,
        'Final Dataset\n3,930 segments\n~7.7h audio',
        fontsize=9, ha='center', va='center',
        fontfamily='Malgun Gothic', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', fc='#F0F0F0', ec='black', lw=1.5))

    # Footnote
    ax.text(CX, 3.3,
        'Timeline:   Stage 1-5 (2026-02-11)   ->   R6 envelope update (2026-04-04)   ->   Stage 6 Composer (2026-04-05)\n\n'
        'p >= 0.05 on D4 (AST z-test) = statistically normal duration\n'
        'Combined with S_comp >= 0.768 = safe for auto-admission (no human review)',
        fontsize=8, ha='center', va='center',
        fontfamily='Malgun Gothic', style='italic', color='#333',
        bbox=dict(boxstyle='round,pad=0.4', fc='#F8F8F8', ec='grey', lw=0.5))

    plt.tight_layout()
    path = os.path.join(OUT_DIR, 'diagram_pipeline_overview.png')
    plt.savefig(path, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Saved: {path}")


# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    draw_composer_decision()
    draw_ast_algorithm()
    draw_pipeline_overview()
    print("\nAll diagrams saved.")
