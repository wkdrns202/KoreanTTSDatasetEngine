"""Visualize the Sustained Silence Verification algorithm."""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ============================================================
# Simulated RMS data (10ms windows)
# ============================================================
np.random.seed(42)

# Build a scenario: speech → micro-pause → speech tail → real silence
n_windows = 200  # 2 seconds total

rms_db = np.full(n_windows, -80.0)  # start all silent

# Main speech: windows 10-95 (850ms)
rms_db[10:96] = np.random.uniform(-50, -35, 86)

# Micro-pause: windows 96-103 (80ms) — dips below -65dB
rms_db[96:104] = np.random.uniform(-72, -66, 8)

# Speech tail (formal ending): windows 104-118 (150ms)
rms_db[104:119] = np.random.uniform(-62, -48, 15)

# Real silence: windows 119+ (810ms to end)
rms_db[119:] = np.random.uniform(-85, -68, n_windows - 119)

threshold_db = -65.0

# ============================================================
# Run the algorithm (simplified reproduction)
# ============================================================
voiced = np.where(rms_db >= threshold_db)[0]
onset_window = voiced[0]
candidate_offset = voiced[-1]
silence_windows_needed = 100  # 1000ms

check_start = candidate_offset + 1
history = []  # track algorithm steps

iteration = 0
while check_start < n_windows:
    silent_count = 0
    resumed_at = None
    for w in range(check_start, min(check_start + silence_windows_needed, n_windows)):
        if rms_db[w] < threshold_db:
            silent_count += 1
        else:
            candidate_offset = w
            resumed_at = w
            break

    history.append({
        'iter': iteration,
        'check_start': check_start,
        'silent_count': silent_count,
        'candidate_offset': candidate_offset,
        'resumed_at': resumed_at,
        'confirmed': silent_count >= silence_windows_needed
    })

    if silent_count >= silence_windows_needed:
        break
    elif silent_count == min(check_start + silence_windows_needed, n_windows) - check_start:
        break
    else:
        check_start = candidate_offset + 1
    iteration += 1

# ============================================================
# Plot
# ============================================================
fig, axes = plt.subplots(3, 1, figsize=(16, 12), gridspec_kw={'height_ratios': [3, 2, 2]})
fig.suptitle('Sustained Silence Verification Algorithm', fontsize=16, fontweight='bold')

time_ms = np.arange(n_windows) * 10  # x-axis in ms

# --- Panel 1: RMS + threshold + algorithm trace ---
ax1 = axes[0]
colors = ['#2196F3' if db >= threshold_db else '#BDBDBD' for db in rms_db]
ax1.bar(time_ms, rms_db, width=9, color=colors, alpha=0.7, edgecolor='none')
ax1.axhline(y=threshold_db, color='red', linestyle='--', linewidth=1.5, label=f'Threshold ({threshold_db} dB)')

# Mark onset
ax1.axvline(x=onset_window * 10, color='green', linestyle='-', linewidth=2, alpha=0.8)
ax1.annotate('onset', xy=(onset_window * 10, -30), fontsize=10, color='green', fontweight='bold',
             ha='center', va='bottom')

# Mark old offset (voiced[-1] without sustained check)
old_offset = voiced[-1]
ax1.axvline(x=old_offset * 10, color='#FF5722', linestyle='-', linewidth=2, alpha=0.8)
ax1.annotate(f'final offset\n(window {old_offset})', xy=(old_offset * 10, -28),
             fontsize=9, color='#FF5722', fontweight='bold', ha='center', va='bottom')

# Mark micro-pause region
ax1.axvspan(96 * 10, 104 * 10, alpha=0.15, color='orange')
ax1.annotate('micro-pause\n(80ms)', xy=(100 * 10, -90), fontsize=9, color='darkorange',
             ha='center', va='bottom', style='italic')

# Mark speech tail
ax1.axvspan(104 * 10, 119 * 10, alpha=0.15, color='green')
ax1.annotate('speech tail\n"-습니다"', xy=(111 * 10, -90), fontsize=9, color='darkgreen',
             ha='center', va='bottom', style='italic')

ax1.set_ylabel('RMS (dB)', fontsize=12)
ax1.set_xlim(-10, n_windows * 10 + 10)
ax1.set_ylim(-95, -25)
ax1.legend(loc='upper right', fontsize=10)
ax1.set_title('Audio RMS per 10ms Window', fontsize=12)

# Blue/gray legend
voiced_patch = mpatches.Patch(color='#2196F3', alpha=0.7, label='Voiced (>= -65dB)')
silent_patch = mpatches.Patch(color='#BDBDBD', alpha=0.7, label='Silent (< -65dB)')
ax1.legend(handles=[voiced_patch, silent_patch,
           plt.Line2D([0], [0], color='red', linestyle='--', label=f'Threshold ({threshold_db}dB)')],
           loc='upper right', fontsize=9)

# --- Panel 2: Old algorithm (instant offset) ---
ax2 = axes[1]
ax2.bar(time_ms, rms_db, width=9, color='#BDBDBD', alpha=0.4, edgecolor='none')
ax2.axhline(y=threshold_db, color='red', linestyle='--', linewidth=1, alpha=0.5)

# Old algorithm: last voiced window = immediate offset
old_last_voiced_before_pause = 95  # last voiced before micro-pause
ax2.axvline(x=old_last_voiced_before_pause * 10, color='red', linewidth=3)
ax2.annotate(f'OLD: instant cut\n(window {old_last_voiced_before_pause})',
             xy=(old_last_voiced_before_pause * 10, -30), fontsize=11, color='red',
             fontweight='bold', ha='center', va='bottom')

# Shade what gets cut
ax2.axvspan(96 * 10, 119 * 10, alpha=0.3, color='red')
ax2.annotate('LOST: micro-pause + speech tail\n"-습니다" truncated',
             xy=(107 * 10, -55), fontsize=10, color='darkred',
             ha='center', va='bottom', fontweight='bold',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFCDD2', alpha=0.8))

# Shade kept
ax2.axvspan(10 * 10, 96 * 10, alpha=0.15, color='green')

ax2.set_ylabel('RMS (dB)', fontsize=12)
ax2.set_xlim(-10, n_windows * 10 + 10)
ax2.set_ylim(-95, -25)
ax2.set_title('OLD Algorithm: Instant Offset (micro-pause = end of speech)', fontsize=12, color='red')

# --- Panel 3: New algorithm (sustained silence) ---
ax3 = axes[2]
ax3.bar(time_ms, rms_db, width=9, color='#BDBDBD', alpha=0.4, edgecolor='none')
ax3.axhline(y=threshold_db, color='red', linestyle='--', linewidth=1, alpha=0.5)

# Show algorithm iterations
iter_colors = ['#FF9800', '#4CAF50']
for i, step in enumerate(history):
    cs = step['check_start'] * 10
    if step['resumed_at'] is not None:
        # Failed: speech resumed
        end_ms = step['resumed_at'] * 10
        ax3.annotate(f'iter {step["iter"]}: check {step["silent_count"]} windows\n→ speech resumed!',
                     xy=(cs, -88), fontsize=8, color='#FF9800', ha='left')
        ax3.axvspan(cs, end_ms, alpha=0.2, color='orange')
    elif step['confirmed']:
        # Success: 1000ms silence confirmed
        end_ms = min((step['check_start'] + silence_windows_needed) * 10, n_windows * 10)
        ax3.axvspan(cs, end_ms, alpha=0.15, color='green')
        ax3.annotate(f'iter {step["iter"]}: {step["silent_count"]} windows silent\n→ 1000ms confirmed!',
                     xy=(cs + 50, -88), fontsize=8, color='green', ha='left', fontweight='bold')

# New offset
ax3.axvline(x=candidate_offset * 10, color='green', linewidth=3)
ax3.annotate(f'NEW: offset after\nspeech tail\n(window {candidate_offset})',
             xy=(candidate_offset * 10, -30), fontsize=11, color='green',
             fontweight='bold', ha='center', va='bottom')

# Shade kept (including tail)
ax3.axvspan(10 * 10, (candidate_offset + 1) * 10, alpha=0.15, color='green')
ax3.annotate('KEPT: speech tail preserved',
             xy=(107 * 10, -55), fontsize=10, color='darkgreen',
             ha='center', va='bottom', fontweight='bold',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#C8E6C9', alpha=0.8))

ax3.set_ylabel('RMS (dB)', fontsize=12)
ax3.set_xlabel('Time (ms)', fontsize=12)
ax3.set_xlim(-10, n_windows * 10 + 10)
ax3.set_ylim(-95, -25)
ax3.set_title('NEW Algorithm: Sustained Silence Verification (1000ms continuous silence required)',
              fontsize=12, color='green')

plt.tight_layout()
plt.savefig('G:/Projects/AI_Research/TTSDataSetCleanser/docs/sustained_silence_algorithm.png',
            dpi=150, bbox_inches='tight')
plt.show()
print("Saved to docs/sustained_silence_algorithm.png")
