"""Charts for the neural milk model (pfoi/neural.py) from its saved test error file.

Run from the repository root after ``pfoi.cli neural`` (herd-level aggregates only):

    python components/predictive_farm_intelligence/docs/make_neural_figures.py

Writes PNGs to logs/pfoi_neural/figures/ (not committed; copy chosen charts yourself):
  neural_ratio_<stage>.png    MAE ratio to persistence by grain x horizon, every model
  neural_weekly_<stage>.png   weekly h1 and h4 forecasts vs actual through the test years
Stage-2 test 2024 onward was viewed in earlier post-hoc replays: descriptive, not confirmation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).parents[3]
MODELS = ("neural", "neural_transfer", "neural_scratch", "milk_baseline", "persistence",
          "seasonal_naive", "ets")
COLOURS = {"neural": "#1f6feb", "neural_transfer": "#1f6feb", "neural_scratch": "#8957e5",
           "milk_baseline": "#d29922", "persistence": "#6e7781", "seasonal_naive": "#bf8700",
           "ets": "#2da44e", "actual": "#000000"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "logs" / "pfoi_neural"))
    ap.add_argument("--errors", default=None, help="error file (default: newest neural_errors_*.csv)")
    a = ap.parse_args()
    d = Path(a.dir)
    path = Path(a.errors) if a.errors else max(d.glob("neural_errors_*.csv"), key=lambda p: p.stat().st_mtime)
    e = pd.read_csv(path, parse_dates=["origin", "period_start"])
    out = d / "figures"
    out.mkdir(exist_ok=True)
    tag = path.stem.replace("neural_errors_", "")
    summary = pd.read_csv(d / f"neural_summary_{tag}.csv")
    for stage, s in summary.groupby("stage"):
        s = s.assign(key=s["grain"].str[0] + s["horizon"].astype(str))
        order = [k for g in ("d", "w") for k in sorted(s.loc[s["grain"].str[0] == g, "key"].unique(),
                                                       key=lambda x: int(x[1:]))]
        models = [m for m in MODELS if m in set(s["model"])]
        fig, ax = plt.subplots(figsize=(10, 4))
        w = 0.8 / len(models)
        for i, m in enumerate(models):
            v = s[s["model"] == m].set_index("key")["ratio_to_persistence"].reindex(order)
            ax.bar([j + i * w for j in range(len(order))], v, w, label=m, color=COLOURS[m],
                   alpha=1.0 if m.startswith("neural") else 0.55,
                   hatch="//" if m == "neural_scratch" else None)
        ax.axhline(1.0, color="k", lw=0.8, ls="--")
        ax.set_xticks([j + 0.4 - w / 2 for j in range(len(order))], order)
        n = s.groupby("key")["n"].max().reindex(order)
        ax.set_xlabel("grain + horizon (d = days, w = weeks); n periods: " + ", ".join(
            f"{k}={int(x)}" for k, x in n.items()))
        ax.set_ylabel("MAE / persistence MAE (lower is better)")
        ax.set_title(f"{stage}: test MAE relative to persistence (identical periods)")
        ax.legend(ncol=4, fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"neural_ratio_{stage}.png", dpi=140)
        plt.close(fig)

        es = e[(e["stage"] == stage) & (e["grain"] == "weekly")]
        fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
        for ax, h in zip(axes, (1, 4)):
            eh = es[es["horizon"] == h]
            act = eh.groupby("period_start")["actual"].first() / 7
            ax.plot(act.index, act.values, color="k", lw=1.6, label="actual")
            for m in [m for m in MODELS if m in set(eh["model"])
                      and m in ("neural", "neural_transfer", "neural_scratch", "milk_baseline", "persistence")]:
                v = eh[eh["model"] == m].set_index("period_start")["forecast"].sort_index() / 7
                ax.plot(v.index, v.values, color=COLOURS[m], lw=1.0,
                        ls=":" if m == "neural_scratch" else "-", label=m)
            ax.set_ylabel("litres per day")
            ax.set_title(f"{stage}: weekly forecasts {h} week(s) ahead vs actual")
            ax.legend(ncol=6, fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"neural_weekly_{stage}.png", dpi=140)
        plt.close(fig)
    print(f"Charts in {out}/ from {path.name}")


if __name__ == "__main__":
    main()
