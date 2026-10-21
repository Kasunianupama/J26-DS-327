"""Charts for docs/linear_baseline.md from docs/data/linear_baseline_wape.csv (aggregates only)."""
from pathlib import Path
import subprocess
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "figures"; OUT.mkdir(exist_ok=True)
d = pd.read_csv(HERE / "data" / "linear_baseline_wape.csv")
for m in ("linear", "persistence", "current"):
    d[m] = 100 - d[f"{m}_wape_pct"]
GRAINS = ["daily", "weekly", "monthly"]
STYLE = {"current": ("Current model", "#2a78d6", "o"),
         "persistence": ("Persistence", "#eb6834", "s"),
         "linear": ("Linear regression", "#6250d6", "^")}

def validate_palette():
    """Refuse to draw if the model colours fail the vendored palette validator."""
    colours = ",".join(c for _, c, _ in STYLE.values())
    r = subprocess.run([sys.executable, str(HERE / "tools" / "validate_palette.py"), colours, "--mode", "light"],
                       capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        raise SystemExit("Palette failed validation; fix STYLE colours before rendering.")


validate_palette()
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})

# Figure 1: accuracy by horizon, one panel per year, one row per grain.
fig, axes = plt.subplots(3, 5, figsize=(15, 8.5), sharey="row")
for r, g in enumerate(GRAINS):
    for c, y in enumerate(range(2019, 2024)):
        ax = axes[r, c]; s = d[(d.grain == g) & (d.target_year == y)].sort_values("horizon")
        ax.grid(axis="y", color=GRID, lw=.8); ax.set_axisbelow(True)
        for mi, (m, (lab, col, mk)) in enumerate(STYLE.items()):
            if len(s):
                v = s[m].clip(lower=0) if g != "daily" else s[m]
                ax.plot(range(len(s)), v, color=col, marker=mk, ms=6, lw=2, label=lab)
                for k, (x_, raw) in enumerate(zip(range(len(s)), s[m])):
                    if g != "daily" and raw < 0:  # below the 0 % floor: show the true value
                        ax.annotate(f"{raw:.0f}", (x_, 0), textcoords="offset points", xytext=(0, 5 + 9 * mi),
                                    ha="center", fontsize=8, color=col)
        ax.set_xticks(range(len(s))); ax.set_xticklabels(s.horizon.astype(str))
        if g != "daily":
            ax.set_ylim(-4, 102)
        if len(s):
            ax.set_title(f"{y}  (n={int(s.n.min())}-{int(s.n.max())})", fontsize=9.5, color=INK, loc="left")
        else:
            ax.set_title(f"{y}  (no matched periods)", fontsize=9.5, color=MUTED, loc="left")
        if c == 0:
            ax.set_ylabel(f"{g.title()}\naccuracy %")
        if r == 2:
            ax.set_xlabel("forecast horizon")
h, l = axes[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(.5, .985))
fig.suptitle("Accuracy (100 - WAPE) by horizon, matched periods, development block", y=1.03, x=.01,
             ha="left", fontsize=13, color=INK)
fig.tight_layout(); fig.savefig(OUT / "fig1_accuracy_by_horizon.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# Figure 2/3: accuracy-point gap heatmaps (diverging, neutral midpoint at zero).
def heat(ref, name, title):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    d["gap"] = d["current"] - d[ref]
    lim = 20  # colour scale capped at +/-20 points; the printed value is always the true gap
    norm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
    for ax, g in zip(axes, GRAINS):
        p = d[d.grain == g].pivot(index="horizon", columns="target_year", values="gap").reindex(columns=range(2019, 2024))
        n = d[d.grain == g].pivot(index="horizon", columns="target_year", values="n").reindex(columns=range(2019, 2024))
        im = ax.imshow(p.values, cmap="RdBu", norm=norm, aspect="auto")
        ax.set_xticks(range(5)); ax.set_xticklabels(range(2019, 2024))
        ax.set_yticks(range(len(p))); ax.set_yticklabels(p.index)
        ax.set_title(g.title(), loc="left", color=INK); ax.set_ylabel("horizon")
        for i in range(p.shape[0]):
            for j in range(p.shape[1]):
                v = p.values[i, j]
                if pd.notna(v):
                    small = n.values[i, j] < 12
                    ax.text(j, i, f"{v:+.1f}" + ("*" if small else ""), ha="center", va="center", fontsize=9,
                            color="white" if abs(v) > lim * .6 else INK)
        for s_ in ax.spines.values(): s_.set_visible(False)
    fig.colorbar(im, ax=axes, shrink=.8, label="accuracy points (blue = current model better)")
    fig.suptitle(title, x=.01, ha="left", fontsize=13, color=INK)
    fig.text(.01, -.02, "* n < 12 periods: indicative only. Colour capped at +/-20 points; numbers are the true gaps.", color=MUTED, fontsize=9)
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight"); plt.close(fig)

heat("linear", "fig2_current_minus_linear.png", "Current model minus linear regression (accuracy points)")
heat("persistence", "fig3_current_minus_persistence.png", "Current model minus persistence (accuracy points)")
print("wrote", sorted(p.name for p in OUT.glob("*.png")))
