"""
Sustained Silence Detection Algorithm - Clean B&W Flowchart for publication
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

fig, ax = plt.subplots(figsize=(8, 14))
ax.set_xlim(0, 8)
ax.set_ylim(0, 18)
ax.axis('off')

CX = 4  # center x
BW = 4.5  # box width
BH = 0.65  # box height

# Diamond actual rendered sizes
D1W = 3.6   # diamond 1 full width
D1H = 0.85  # diamond 1 half-height
D2W = 3.6
D2H = 0.85

def box(y, text, bw=BW, bh=BH):
    """Returns (top, bottom, left, right) edges."""
    rect = mpatches.FancyBboxPatch((CX - bw/2, y - bh/2), bw, bh,
            boxstyle='round,pad=0.1', facecolor='white', edgecolor='black', linewidth=1.5)
    ax.add_patch(rect)
    ax.text(CX, y, text, ha='center', va='center', fontsize=9, fontfamily='monospace')
    return y + bh/2, y - bh/2, CX - bw/2, CX + bw/2

def diamond(y, text, dw, dh):
    """Returns (top, bottom, left, right) edges."""
    verts = [(CX, y+dh), (CX+dw/2, y), (CX, y-dh), (CX-dw/2, y)]
    poly = plt.Polygon(verts, facecolor='white', edgecolor='black', linewidth=1.5, closed=True)
    ax.add_patch(poly)
    ax.text(CX, y, text, ha='center', va='center', fontsize=8.5, fontfamily='monospace')
    return y + dh, y - dh, CX - dw/2, CX + dw/2

def varrow(x, y1, y2):
    ax.annotate('', xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle='->', color='black', lw=1.2))

def harrow(x1, y, x2):
    ax.annotate('', xy=(x2, y), xytext=(x1, y),
                arrowprops=dict(arrowstyle='->', color='black', lw=1.2))

def line(x1, y1, x2, y2):
    ax.plot([x1, x2], [y1, y2], 'k-', lw=1.2)

def label(x, y, text, fs=8):
    ax.text(x, y, text, fontsize=fs, fontfamily='monospace', ha='center', va='center')

# ── Nodes top to bottom ──
b0_t, b0_b, b0_l, b0_r = box(17.2, 'Compute rms_db[]\n(RMS per 10ms window, in dB)')

b1_t, b1_b, b1_l, b1_r = box(16.0, 'voiced[] = indices where\nrms_db >= -65 dB')
varrow(CX, b0_b, b1_t)

b2_t, b2_b, b2_l, b2_r = box(14.8, 'candidate = voiced[-1]\n(last voiced window)')
varrow(CX, b1_b, b2_t)

b3_t, b3_b, b3_l, b3_r = box(13.6, 'check_start = candidate + 1\nsilent_count = 0')
varrow(CX, b2_b, b3_t)

# ── Diamond 1: rms < threshold? ──
YD1 = 12.1
d1_t, d1_b, d1_l, d1_r = diamond(YD1, 'rms_db[check_start]\n< -65 dB ?', D1W, D1H)
varrow(CX, b3_b, d1_t)

# ── YES (down): increment silent_count ──
b4_t, b4_b, b4_l, b4_r = box(10.7, 'silent_count += 1\ncheck_start += 1')
varrow(CX, d1_b, b4_t)
label(CX + 0.3, (d1_b + b4_t) / 2, 'Yes', fs=9)

# ── Diamond 2: silent_count >= 100? ──
YD2 = 9.3
d2_t, d2_b, d2_l, d2_r = diamond(YD2, 'silent_count >= 100 ?\n(= 1000ms)', D2W, D2H)
varrow(CX, b4_b, d2_t)

# ── YES (down): CONFIRMED ──
b5_t, b5_b, b5_l, b5_r = box(7.8, 'Voice offset CONFIRMED\noffset = (candidate+1) * window_size', BW + 0.5, BH + 0.1)
varrow(CX, d2_b, b5_t)
label(CX + 0.3, (d2_b + b5_t) / 2, 'Yes', fs=9)

# ── NO from Diamond 2 (right): loop back to Diamond 1 ──
RX = 7.0
line(d2_r, YD2, RX, YD2)            # horizontal right from diamond edge
line(RX, YD2, RX, YD1)              # vertical up
harrow(RX, YD1, d1_r)               # arrow into diamond 1 right edge
label((d2_r + RX) / 2, YD2 + 0.25, 'No', fs=9)
label(RX + 0.4, (YD2 + YD1) / 2, 'next\nwindow', fs=7)

# ── NO from Diamond 1 (left): speech resumed ──
LX = 1.0
line(d1_l, YD1, LX, YD1)            # horizontal left from diamond edge
label((d1_l + LX) / 2, YD1 + 0.25, 'No', fs=9)

# Side box: update candidate
side_bw = 1.8
side_bh = 0.8
side_cy = YD1 - 0.5
rect = mpatches.FancyBboxPatch((LX - side_bw/2, side_cy - side_bh/2), side_bw, side_bh,
        boxstyle='round,pad=0.1', facecolor='white', edgecolor='black', linewidth=1.5)
ax.add_patch(rect)
ax.text(LX, side_cy, 'candidate\n= this w', ha='center', va='center',
        fontsize=8, fontfamily='monospace')
side_top = side_cy + side_bh / 2

# Arrow from side box top, up to b3 level, then right into b3 left edge
line(LX, side_top, LX, 13.6)        # vertical up to b3 center height
harrow(LX, 13.6, b3_l)              # arrow right into box left edge
label(LX - 0.45, (side_top + 13.6) / 2, 'restart', fs=7)

# ── Bottom note ──
ax.text(CX, 7.0,
    '1 window = 10 ms    |    100 windows = 1000 ms    |    threshold = -65 dB',
    fontsize=7.5, ha='center', va='center', color='#444', fontfamily='monospace', style='italic')

# ── Title ──
ax.text(CX, 17.85, 'Sustained Silence Verification Algorithm',
        fontsize=13, fontweight='bold', ha='center', va='center', fontfamily='serif')

plt.tight_layout()
plt.savefig('G:/Projects/AI_Research/TTSDataSetCleanser/docs/sustained_silence_algorithm.png',
            dpi=200, bbox_inches='tight', facecolor='white')
print("Saved.")
