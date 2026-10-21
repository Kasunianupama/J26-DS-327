"""Comparison charts: pfoi-1.4.0-dev (direct ML) vs pfoi-1.2.0-dev vs persistence.

Reads finished backtest error files only (nothing is re-run) and draws herd-level PNGs.
Every comparison uses matched periods: a forecast (series, grain, horizon, origin,
period) counts only if all three models made it. No animal-level data is read or drawn.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ML, CURRENT, PERSIST = "pfoi-1.4.0-dev (ML)", "pfoi-1.2.0-dev (current)", "Persistence"
STYLE = {CURRENT: ("#2a78d6", "o"), ML: ("#6250d6", "^"), PERSIST: ("#eb6834", "s")}
INK, MUTED, GRID, BG = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
GRAINS = ("daily", "weekly", "monthly")
SERIES_LABEL = {"herd_milk": "Herd milk", "milking": "Milking cows", "n_herd": "Total herd",
                "calvings": "Calvings"}
KEYS = ["series", "grain", "horizon", "origin", "period_start"]


def load(ml_files: list[Path], milk_files: list[Path], herd_files: list[Path],
         current_milk_model: str = "milk_baseline_adaptive",
         current_herd_model: str = "herd_engine") -> pd.DataFrame:
    """One long frame with a ``label`` per model, restricted to matched periods."""
    parts = []
    for f in ml_files:
        e = pd.read_csv(f)
        parts.append(e[e["model"] == "ml_lgbm"].assign(label=ML))
        parts.append(e[e["model"] == "persistence"].assign(label=PERSIST))
    for f in milk_files:
        e = pd.read_csv(f)
        parts.append(e[e["model"] == current_milk_model].assign(label=CURRENT, series="herd_milk"))
    for f in herd_files:
        e = pd.read_csv(f)
        parts.append(e[e["model"] == current_herd_model].assign(label=CURRENT))
    e = pd.concat(parts, ignore_index=True)
    e = e[e["series"].isin(SERIES_LABEL)]
    for c in ("origin", "period_start", "period_end"):
        e[c] = pd.to_datetime(e[c]).dt.date
    e = e.drop_duplicates(KEYS + ["label"])
    n = e.groupby(KEYS)["label"].transform("nunique")
    return e[n == 3].reset_index(drop=True)


def scores(e: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Accuracy (1 - WAPE), share within +-10 % and bias per group and model."""
    rows = []
    for k, g in e.groupby(by + ["label"]):
        tot = g["actual"].sum()
        err = g["forecast"] - g["actual"]
        pos = g["actual"] > 0
        rows.append(dict(zip(by + ["label"], k), n=len(g),
                         accuracy=100 * (1 - err.abs().sum() / tot) if tot > 0 else np.nan,
                         within_10=100 * float((err[pos].abs() / g.loc[pos, "actual"] <= 0.10 + 1e-9).mean())
                         if pos.any() else np.nan,
                         bias=100 * err.sum() / tot if tot > 0 else np.nan))
    return pd.DataFrame(rows)


def _style(plt):
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": BG, "axes.facecolor": BG})


def _by_horizon(plt, s: pd.DataFrame, series: list[str], metric: str, ylabel: str, title: str, path: Path):
    fig, axes = plt.subplots(len(series), 3, figsize=(13, 3.1 * len(series)), squeeze=False)
    for r, ser in enumerate(series):
        for c, grain in enumerate(GRAINS):
            ax = axes[r, c]
            ax.grid(axis="y", color=GRID, lw=.8)
            ax.set_axisbelow(True)
            part = s[(s["series"] == ser) & (s["grain"] == grain)]
            if not len(part):
                ax.axis("off")
                ax.text(0, .5, f"{SERIES_LABEL[ser]}, {grain}:\nnot forecast by pfoi-1.2.0-dev",
                        fontsize=9, color=MUTED, transform=ax.transAxes)
                continue
            hs = sorted(part["horizon"].unique())
            for label, (col, mk) in STYLE.items():
                p = part[part["label"] == label].set_index("horizon").reindex(hs)
                ax.plot(range(len(hs)), p[metric], color=col, marker=mk, ms=6, lw=2, label=label)
            ax.set_xticks(range(len(hs)))
            ax.set_xticklabels([str(h) for h in hs])
            n = part.groupby("horizon")["n"].min().reindex(hs)
            ax.set_title(f"{SERIES_LABEL[ser]}, {grain}  (n {int(n.min())}-{int(n.max())})",
                         fontsize=9.5, color=INK, loc="left")
            if c == 0:
                ax.set_ylabel(ylabel)
            if r == len(series) - 1:
                ax.set_xlabel("horizon (days / weeks / months ahead)")
    h, l = axes[0, 0].get_legend_handles_labels()
    if not h:
        for ax in axes.flat:
            h, l = ax.get_legend_handles_labels()
            if h:
                break
    fig.legend(h, l, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(.5, 1.0))
    fig.suptitle(title, y=1.04, x=.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _timeline(plt, e: pd.DataFrame, path: Path):
    """Monthly herd milk (litres/day): recorded vs each model's forecast at 1, 3 and 6 months."""
    m = e[(e["series"] == "herd_milk") & (e["grain"] == "monthly")].copy()
    if not len(m):
        return False
    days = (pd.to_datetime(m["period_end"]) - pd.to_datetime(m["period_start"])).dt.days
    m["f_day"], m["a_day"] = m["forecast"] / days, m["actual"] / days
    hs = [h for h in (1, 3, 6) if h in set(m["horizon"])]
    fig, axes = plt.subplots(len(hs), 1, figsize=(13, 3.2 * len(hs)), sharex=True, squeeze=False)
    months = pd.date_range(pd.Timestamp(min(m["period_start"])), pd.Timestamp(max(m["period_start"])), freq="MS")
    for ax, h in zip(axes[:, 0], hs):
        p = m[m["horizon"] == h]
        ax.grid(axis="y", color=GRID, lw=.8)
        ax.set_axisbelow(True)
        act = p.drop_duplicates("period_start").set_index(pd.to_datetime(p.drop_duplicates("period_start")["period_start"]))
        ax.plot(months, act["a_day"].reindex(months), color=INK, lw=2.4, label="Recorded")
        for label, (col, mk) in STYLE.items():
            q = p[p["label"] == label]
            q = q.set_index(pd.to_datetime(q["period_start"]))["f_day"].reindex(months)
            ax.plot(months, q, color=col, lw=1.6, marker=mk, ms=3.5, label=label)
        ax.set_title(f"Forecast made {h} month{'s' if h > 1 else ''} ahead", fontsize=10, color=INK, loc="left")
        ax.set_ylabel("litres per day")
    h_, l_ = axes[0, 0].get_legend_handles_labels()
    fig.legend(h_, l_, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(.5, 1.0))
    fig.suptitle("Herd milk by month: recorded vs forecasts (matched periods; gaps = not scoreable)",
                 y=1.04, x=.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return True


def _by_year(plt, e: pd.DataFrame, path: Path):
    """Share within +-10 % by forecast year for milk at weekly 13 and monthly 3, 6, 12."""
    cells = [("weekly", 13), ("monthly", 3), ("monthly", 6), ("monthly", 12)]
    m = e[e["series"] == "herd_milk"].assign(year=lambda d: pd.to_datetime(d["origin"]).dt.year)
    s = scores(m, ["grain", "horizon", "year"])
    fig, axes = plt.subplots(1, len(cells), figsize=(15, 3.8), sharey=True)
    labels = list(STYLE)
    for ax, (g, h) in zip(axes, cells):
        p = s[(s["grain"] == g) & (s["horizon"] == h)]
        years = sorted(p["year"].unique())
        x = np.arange(len(years))
        for i, label in enumerate(labels):
            v = p[p["label"] == label].set_index("year")["within_10"].reindex(years)
            ax.bar(x + (i - 1) * .27, v, width=.27, color=STYLE[label][0], label=label)
        ax.set_xticks(x)
        ax.set_xticklabels([str(y) for y in years], rotation=0, fontsize=8.5)
        ax.grid(axis="y", color=GRID, lw=.8)
        ax.set_axisbelow(True)
        ax.set_title(f"{g} {h} ahead", fontsize=10, color=INK, loc="left")
    axes[0].set_ylabel("% of forecasts within ±10 %")
    h_, l_ = axes[0].get_legend_handles_labels()
    fig.legend(h_, l_, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(.5, 1.04))
    fig.suptitle("Herd milk: share within ±10 % by forecast year (matched periods)", y=1.12, x=.01,
                 ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _shap(plt, importance: pd.DataFrame, path: Path) -> bool:
    if importance is None or not len(importance):
        return False
    rows = importance[importance["grain"] == "monthly"].set_index("series")
    groups = [c for c in rows.columns if c not in ("grain", "baseline")]
    show = [s for s in ("herd_milk", "milking", "calvings") if s in rows.index]
    fig, axes = plt.subplots(1, len(show), figsize=(5 * len(show), 4.2), squeeze=False)
    for ax, ser in zip(axes[0], show):
        v = rows.loc[ser, groups].astype(float)
        v = (100 * v / v.sum()).sort_values()
        ax.barh(v.index, v.to_numpy(), color=STYLE[ML][0])
        ax.set_title(SERIES_LABEL[ser] + ", monthly", fontsize=10, color=INK, loc="left")
        ax.set_xlabel("% of mean |SHAP| (excluding baseline)")
        ax.grid(axis="x", color=GRID, lw=.8)
        ax.set_axisbelow(True)
    fig.suptitle("pfoi-1.4.0-dev: what drives the ML forecast (feature groups)", y=1.03, x=.01,
                 ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return True


def draw(e: pd.DataFrame, out: Path, importance: pd.DataFrame | None = None) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    out.mkdir(parents=True, exist_ok=True)
    s = scores(e, ["series", "grain", "horizon"])
    series = [x for x in SERIES_LABEL if x in set(s["series"])]
    written = []
    p = out / "1_accuracy_by_horizon.png"
    _by_horizon(plt, s, series, "accuracy", "accuracy % (100 - WAPE)",
                "Accuracy by horizon: ML vs current model vs persistence (development, matched periods)", p)
    written.append(p)
    p = out / "2_milk_within10_by_horizon.png"
    _by_horizon(plt, s, ["herd_milk"], "within_10", "% within ±10 %",
                "Herd milk: share of forecasts within ±10 % (target 85 %)", p)
    written.append(p)
    p = out / "3_milk_bias_by_horizon.png"
    _by_horizon(plt, s, series, "bias", "bias % (forecast - recorded)",
                "Bias by horizon (0 = unbiased)", p)
    written.append(p)
    p = out / "4_milk_timeline_monthly.png"
    if _timeline(plt, e, p):
        written.append(p)
    p = out / "5_milk_within10_by_year.png"
    _by_year(plt, e, p)
    written.append(p)
    p = out / "6_ml_shap_groups.png"
    if _shap(plt, importance, p):
        written.append(p)
    s.to_csv(out / "scores_matched.csv", index=False)
    return written
