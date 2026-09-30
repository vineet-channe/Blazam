"""Render the algorithm figures in docs/ from a synthetic signal (no copyrighted audio).

    python scripts/make_plots.py

Outputs: docs/spectrogram_peaks.png, docs/target_zone.png, docs/offset_histogram.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DSP  # noqa: E402
from app.dsp.fingerprint import find_peaks, fingerprint_signal, spectrogram_db  # noqa: E402
from app.dsp.index import HashIndex  # noqa: E402
from app.dsp.matcher import delta_histogram, match  # noqa: E402
from tests.synth import SR, add_noise, make_song  # noqa: E402

# validated palette (dataviz reference instance, light mode): slot 1 blue, slot 2 orange
BLUE, ORANGE = "#2a78d6", "#eb6834"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
FRAME_S = DSP.HOP / DSP.SAMPLE_RATE
HZ_PER_BIN = DSP.SAMPLE_RATE / DSP.N_FFT

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
})


def spectrogram_with_peaks(x: np.ndarray, out: Path) -> None:
    S = spectrogram_db(x)
    pk = find_peaks(S)
    fig, ax = plt.subplots(figsize=(10, 4.6))
    t_max = S.shape[1] * FRAME_S
    f_top = DSP.F_MAX_BIN * HZ_PER_BIN
    ax.imshow(S[: DSP.F_MAX_BIN + 1], origin="lower", aspect="auto", cmap="Greys",
              extent=(0, t_max, 0, f_top), vmin=np.percentile(S, 50), vmax=S.max())
    ax.scatter(pk[:, 0] * FRAME_S, pk[:, 1] * HZ_PER_BIN, s=14, c=ORANGE, edgecolors=SURFACE, linewidths=0.8,
               label=f"peaks ({len(pk)}, max {DSP.MAX_PEAKS_PER_FRAME}/frame)")
    ax.set_title("Spectrogram (log power) with constellation peaks - Wang03 Fig. 1A/1B", color=INK)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("frequency (Hz)")
    ax.legend(loc="upper right", frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def target_zone(x: np.ndarray, out: Path) -> None:
    fp = fingerprint_signal(x)
    pk = fp.peaks
    anchor_i = int(np.argmin(np.abs(pk[:, 0] - pk[:, 0].max() * 0.4)))
    t1, f1 = int(pk[anchor_i, 0]), int(pk[anchor_i, 1])
    # recompute this anchor's pairs exactly as make_hashes does
    pairs = []
    for j in range(anchor_i + 1, len(pk)):
        dt = int(pk[j, 0]) - t1
        if dt > DSP.MAX_DT:
            break
        if dt >= DSP.MIN_DT and abs(int(pk[j, 1]) - f1) <= DSP.MAX_DF:
            pairs.append(j)
            if len(pairs) == DSP.FAN_OUT:
                break
    lo_t, hi_t = t1 - 15, t1 + DSP.MAX_DT + 15
    sel = (pk[:, 0] >= lo_t) & (pk[:, 0] <= hi_t)
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.scatter(pk[sel, 0] * FRAME_S, pk[sel, 1] * HZ_PER_BIN, s=12, c=GRID, edgecolors=INK2, linewidths=0.4,
               label="other peaks")
    ax.add_patch(Rectangle(((t1 + DSP.MIN_DT) * FRAME_S, (f1 - DSP.MAX_DF) * HZ_PER_BIN),
                           (DSP.MAX_DT - DSP.MIN_DT) * FRAME_S, 2 * DSP.MAX_DF * HZ_PER_BIN,
                           fill=False, ec=INK2, lw=1.2, ls="--", label="target zone"))
    for j in pairs:
        ax.plot([t1 * FRAME_S, pk[j, 0] * FRAME_S], [f1 * HZ_PER_BIN, pk[j, 1] * HZ_PER_BIN], c=BLUE, lw=1.5,
                zorder=2)
    ax.scatter(pk[pairs, 0] * FRAME_S, pk[pairs, 1] * HZ_PER_BIN, s=40, c=BLUE, edgecolors=SURFACE,
               linewidths=1.5, zorder=3, label=f"paired targets ({len(pairs)} of FAN_OUT={DSP.FAN_OUT})")
    ax.scatter([t1 * FRAME_S], [f1 * HZ_PER_BIN], s=90, c=ORANGE, edgecolors=SURFACE, linewidths=1.5, zorder=4,
               label="anchor (t1, f1)")
    ax.set_xlim(lo_t * FRAME_S, hi_t * FRAME_S)
    ax.set_ylim(max(0, (f1 - 3 * DSP.MAX_DF)) * HZ_PER_BIN, (f1 + 3 * DSP.MAX_DF) * HZ_PER_BIN)
    ax.set_title(f"Combinatorial hashing for one anchor - Wang03 Fig. 1C "
                 f"(dt in [{DSP.MIN_DT}, {DSP.MAX_DT}] frames, |df| <= {DSP.MAX_DF} bins)", color=INK)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("frequency (Hz)")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def offset_histograms(out: Path) -> None:
    songs = {sid: make_song(seed=sid, duration=30.0) for sid in (1, 2, 3, 4)}
    idx = HashIndex()
    for sid, x in songs.items():
        fp = fingerprint_signal(x)
        idx.add_song(sid, fp.hashes, fp.offsets)
    start = 12.0
    q = add_noise(songs[2][int(start * SR): int((start + 8) * SR)], 5.0, seed=3)
    qfp = fingerprint_signal(q)
    r = match(qfp, idx)
    wrong = next(c.song_id for c in r.candidates if c.song_id != 2)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, sid, title in ((axes[0], 2, "correct song"), (axes[1], wrong, "a wrong song")):
        vals, counts = delta_histogram(qfp, idx, sid)
        score = next(c.score for c in r.candidates if c.song_id == sid)
        # vlines, not bars: 1-frame-wide bars are <1 px at this zoom and can vanish when rasterised
        ax.vlines(vals * FRAME_S, 0, counts, colors=BLUE, linewidth=1.6)
        ax.set_ylim(0, max(counts) * 1.1)
        ax.set_title(f"Offset histogram, {title} (score {score})", color=INK)
        ax.set_xlabel("delta = t_db - t_query (s)")
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("matching hashes per 1-frame bin")
    axes[0].annotate(f"peak at {r.offset_seconds:.2f} s (clip started at {start:.2f} s)",
                     xy=(r.offset_seconds, max(delta_histogram(qfp, idx, 2)[1])), xytext=(0.5, 0.8),
                     textcoords="axes fraction", color=INK2, arrowprops={"arrowstyle": "->", "color": INK2})
    fig.suptitle("Wang03 Fig. 2B / 3B: 8 s clip at 5 dB SNR (synthetic)", x=0.01, ha="left", color=INK2, fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def main() -> None:
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    x = make_song(seed=7, duration=10.0)
    spectrogram_with_peaks(x, docs / "spectrogram_peaks.png")
    target_zone(x, docs / "target_zone.png")
    offset_histograms(docs / "offset_histogram.png")
    print("wrote docs/spectrogram_peaks.png, docs/target_zone.png, docs/offset_histogram.png")


if __name__ == "__main__":
    main()
