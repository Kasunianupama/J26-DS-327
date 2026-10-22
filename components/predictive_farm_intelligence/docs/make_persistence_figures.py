"""Charts: recorded herd milk vs the C1 milk model vs persistence, from saved backtest error files.

Run from the repository root on the machine that holds the backtest output (herd-level only):

    .venv/bin/python components/predictive_farm_intelligence/docs/make_persistence_figures.py \
        --dir logs/pfoi_mi2

Reads every milk_backtest_errors_{monthly,weekly}_*.csv in --dir (one run per folder). Only
matched periods are compared: a forecast counts when both the model and persistence made it.
Writes PNGs and the table behind them to <dir>/charts/ and prints the table (aggregates only).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

MODEL, PERSIST = "C1 milk model", "Persistence"
STYLE = {MODEL: ("#2a78d6", "o"), PERSIST: ("#eb6834", "s")}
INK, MUTED, GRID, BG = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
KEYS = ["grain", "horizon", "origin", "period_start"]


def load(folder: Path, model: str) -> pd.DataFrame:
    files = sorted(folder.glob("milk_backtest_errors_monthly_*.csv")) + \
        sorted(folder.glob("milk_backtest_errors_weekly_*.csv"))
    if not files:
        raise SystemExit(f"no milk_backtest_errors_*.csv in {folder}")
    e = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    e = e[e["model"].isin([model, "persistence"])].copy()
    e["label"] = np.where(e["model"] == model, MODEL, PERSIST)
    for c in ("origin", "period_start", "period_end"):
        e[c] = pd.to_datetime(e[c])
    e = e.dropna(subset=["forecast", "actual"]).drop_duplicates(KEYS + ["label"])
    both = e.groupby(KEYS)["label"].transform("nunique") == 2
    return e[both].reset_index(drop=True)


def scores(e: pd.DataFrame) -> pd.DataFrame:
    """Accuracy (1 - WAPE), share within +-10 % and bias, per grain x horizon x model."""
    rows = []
    for (grain, h, label), g in e.groupby(["grain", "horizon", "label"]):
        tot = g["actual"].sum()
        err = g["forecast"] - g["actual"]
        pos = g["actual"] > 0
        rows.append(dict(grain=grain, horizon=h, model=label, n=len(g),
                         accuracy_pct=round(100 * (1 - err.abs().sum() / tot), 1) if tot > 0 else np.nan,
                         within_10_pct=round(100 * float((err[pos].abs() / g.loc[pos, "actual"] <= 0.10).mean()), 1)
                         if pos.any() else np.nan,
                         bias_pct=round(100 * err.sum() / tot, 1) if tot > 0 else np.nan))
    return pd.DataFrame(rows).sort_values(["grain", "horizon", "model"])


def _style():
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": BG, "axes.facecolor": BG})


def timeline(e: pd.DataFrame, path: Path) -> bool:
    """Monthly herd milk (litres/day): recorded vs model vs persistence at 1, 3 and 6 months ahead."""
    m = e[e["grain"] == "monthly"].copy()
    if not len(m):
        return False
    days = (m["period_end"] - m["period_start"]).dt.days
    m["f_day"], m["a_day"] = m["forecast"] / days, m["actual"] / days
    hs = [h for h in (1, 3, 6) if h in set(m["horizon"])]
    months = pd.date_range(m["period_start"].min(), m["period_start"].max(), freq="MS")
    fig, axes = plt.subplots(len(hs), 1, figsize=(13, 3.2 * len(hs)), sharex=True, squeeze=False)
    for ax, h in zip(axes[:, 0], hs):
        p = m[m["horizon"] == h]
        ax.grid(axis="y", color=GRID, lw=.8)
        ax.set_axisbelow(True)
        act = p.drop_duplicates("period_start").set_index("period_start")["a_day"].reindex(months)
        ax.plot(months, act, color=INK, lw=2.4, label="Recorded (core.animal_daily)")
        for label, (col, mk) in STYLE.items():
            q = p[p["label"] == label].set_index("period_start")["f_day"].reindex(months)
            ax.plot(months, q, color=col, lw=1.6, marker=mk, ms=3.5, label=label)
        ax.set_title(f"Forecast made {h} month{'s' if h > 1 else ''} ahead", fontsize=10, color=INK, loc="left")
        ax.set_ylabel("litres per day")
    h_, l_ = axes[0, 0].get_legend_handles_labels()
    fig.legend(h_, l_, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(.5, 1.0))
    fig.suptitle("Herd milk by month: recorded vs forecasts (matched periods; gaps = no usable record)",
                 y=1.04, x=.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return True


def by_horizon(s: pd.DataFrame, path: Path) -> None:
    grains = [g for g in ("daily", "weekly", "monthly") if g in set(s["grain"])]
    fig, axes = plt.subplots(2, len(grains), figsize=(4.4 * len(grains), 6.4), squeeze=False)
    for c, grain in enumerate(grains):
        part = s[s["grain"] == grain]
        hs = sorted(part["horizon"].unique())
        for r, (metric, ylabel) in enumerate((("accuracy_pct", "accuracy % (1 - WAPE)"),
                                              ("within_10_pct", "% of periods within ±10 %"))):
            ax = axes[r, c]
            ax.grid(axis="y", color=GRID, lw=.8)
            ax.set_axisbelow(True)
            for label, (col, mk) in STYLE.items():
                p = part[part["model"] == label].set_index("horizon").reindex(hs)
                ax.plot(range(len(hs)), p[metric], color=col, marker=mk, ms=6, lw=2, label=label)
            ax.set_xticks(range(len(hs)))
            ax.set_xticklabels([str(h) for h in hs])
            n = part.groupby("horizon")["n"].min().reindex(hs)
            if r == 0:
                ax.set_title(f"{grain} (n {int(n.min())}-{int(n.max())})", fontsize=10, color=INK, loc="left")
            if c == 0:
                ax.set_ylabel(ylabel)
            if r == 1:
                ax.set_xlabel("horizon (days / weeks / months ahead)")
    h_, l_ = axes[0, 0].get_legend_handles_labels()
    fig.legend(h_, l_, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(.5, 1.02))
    fig.suptitle("Herd milk: C1 model vs persistence by horizon (matched periods)",
                 y=1.07, x=.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="logs/pfoi_mi2", help="folder with one milk backtest run")
    ap.add_argument("--model", default="milk_baseline", help="model name in the error files")
    a = ap.parse_args(argv)
    folder = Path(a.dir)
    e = load(folder, a.model)
    if not len(e):
        raise SystemExit("no matched model/persistence periods to compare")
    out = folder / "charts"
    out.mkdir(parents=True, exist_ok=True)
    _style()
    s = scores(e)
    s.to_csv(out / "model_vs_persistence_by_horizon.csv", index=False)
    by_horizon(s, out / "model_vs_persistence_by_horizon.png")
    made = timeline(e, out / "milk_recorded_vs_forecasts_monthly.png")
    with pd.option_context("display.width", 140, "display.max_rows", 200):
        print(s.to_string(index=False))
    print(f"\ncharts in {out}/" + ("" if made else " (no monthly rows: timeline skipped)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
