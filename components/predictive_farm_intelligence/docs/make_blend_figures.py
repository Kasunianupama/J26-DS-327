"""Charts for docs/pp1_plan.md M10 (persistence blend), from the saved backtest error files.

Run from the repository root on the machine that holds ``logs/pfoi`` (herd-level aggregates only):

    python components/predictive_farm_intelligence/docs/make_blend_figures.py

Development (origins 2017-2023) and the post-hoc replay (origins 2024-01 to 2026-08) use the same
past-only rules: at every origin the adaptive correction and the blend weights see only forecasts
whose target period had ended by that origin (dev raw errors plus earlier post-hoc raw errors).
2024-26 has already been examined, so its numbers are descriptive, not a confirmation.
Writes docs/data/m10_blend_*.csv (the table view of each chart) and docs/figures/m10_blend_*.png.
"""
from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from components.predictive_farm_intelligence.pfoi.blend_outlook import DEFAULT_TAG as TAG, load_backtest  # noqa: E402
from components.predictive_farm_intelligence.pfoi.error_tools import add_intervals  # noqa: E402
from components.predictive_farm_intelligence.pfoi.regimes import assign_regime  # noqa: E402

warnings.filterwarnings("ignore")
LOGS = ROOT / "logs" / "pfoi"
OUT_FIG, OUT_DATA = HERE / "figures", HERE / "data"
OUT_FIG.mkdir(exist_ok=True); OUT_DATA.mkdir(exist_ok=True)
KEYS = ["grain", "horizon", "origin", "period_start"]
POSTHOC_FROM = pd.Timestamp("2024-01-01")
SOURCE_BREAK = pd.Timestamp("2022-08-01")

STYLE = {"adaptive": ("Current model (adaptive)", "#2a78d6"),
         "blend": ("Modified model (blend)", "#1baf7a"),
         "pers": ("Persistence (last value)", "#eb6834")}
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})


def validate_palette() -> None:
    """Refuse to draw if the series colours fail the vendored palette validator."""
    colours = ",".join(c for _, c in STYLE.values())
    r = subprocess.run([sys.executable, str(HERE / "tools" / "validate_palette.py"), colours,
                        "--mode", "light", "--pairs", "all"], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        raise SystemExit("Palette failed validation; fix STYLE before rendering.")


def _load(suffix: str) -> pd.DataFrame:
    e = pd.concat([pd.read_csv(LOGS / RAW.format(g=g, s=suffix)) for g in ("monthly", "weekly")],
                  ignore_index=True)
    for c in ("origin", "period_start", "period_end"):
        e[c] = pd.to_datetime(e[c], format="mixed")
    return e


def build() -> pd.DataFrame:
    """One row per forecast period with the adaptive, blended and persistence forecast. The blend is the one
    the outlook uses (blend_outlook.load_backtest): weekly = structural + persistence, daily = structural +
    persistence + ETS, weights from finished past forecasts only."""
    frame, blend = load_backtest(LOGS, TAG)
    adaptive = frame[frame["model"] == "milk_baseline_adaptive"]
    pers = frame[frame["model"] == "persistence"]
    scored = add_intervals(pd.concat([adaptive, blend], ignore_index=True))
    a = scored[scored["model"] == "milk_baseline_adaptive"][KEYS + ["forecast", "actual", "source", "covered", "lower", "upper", "k_source"]]
    b = scored[scored["model"] == "milk_baseline_adaptive_blend"][KEYS + ["forecast", "covered", "blend_w", "lower", "upper"]]
    p = pers[KEYS + ["forecast"]].rename(columns={"forecast": "pers"})
    t = a.merge(b, on=KEYS, suffixes=("_a", "_b")).merge(p, on=KEYS)
    t["block"] = np.where(t["origin"] >= POSTHOC_FROM, "post-hoc 2024-26", "development 2017-23")
    t["regime"] = assign_regime(t["period_start"], t["source"], t["origin"])
    t["origin_source"] = np.where(t["origin"] < SOURCE_BREAK, "shipment", "delpro")
    for s in ("a", "b"):
        t["err_" + s] = (t["forecast_" + s] - t["actual"]).abs()
    t["err_p"] = (t["pers"] - t["actual"]).abs()
    return t


def summarise(t: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = t.groupby(by)
    return pd.DataFrame({
        "n": g.size(), "mae_adaptive": g["err_a"].mean(), "mae_blend": g["err_b"].mean(),
        "mae_persistence": g["err_p"].mean(),
        "ratio_adaptive": g["err_a"].mean() / g["err_p"].mean(),
        "ratio_blend": g["err_b"].mean() / g["err_p"].mean(),
        "blend_gain_pct": 100 * (1 - g["err_b"].mean() / g["err_a"].mean()),
        "coverage_adaptive_pct": 100 * g["covered_a"].mean(), "coverage_blend_pct": 100 * g["covered_b"].mean(),
    }).reset_index()


def _spread(ys: list[float], min_gap: float) -> list[float]:
    """Move label heights apart (keeping their order) so end labels never overprint."""
    order = np.argsort(ys)
    out = list(ys)
    for a, b in zip(order[:-1], order[1:]):
        if out[b] - out[a] < min_gap:
            out[b] = out[a] + min_gap
    shift = (np.mean(ys) - np.mean(out))
    return [v + shift for v in out]


def _bars(ax, x, series, width=0.36):
    """Thin bars with a 2px surface gap; series = [(label, colour, values)]."""
    k = len(series)
    for i, (lab, col, v) in enumerate(series):
        off = (i - (k - 1) / 2) * width
        ax.bar(x + off, v, width=width * 0.94, color=col, edgecolor=SURFACE, linewidth=1.6,
               label=lab, zorder=3)


def fig_ratio(t: pd.DataFrame) -> pd.DataFrame:
    tbl = summarise(t[t["grain"].isin(["daily", "weekly"])], ["block", "grain", "horizon"])
    cats = [("daily", 1), ("daily", 7), ("daily", 14), ("weekly", 1), ("weekly", 4), ("weekly", 8), ("weekly", 13)]
    labels = [f"{'day' if g == 'daily' else 'week'} {h}" for g, h in cats]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2), sharey=True)
    for ax, blk in zip(axes, ["development 2017-23", "post-hoc 2024-26"]):
        s = tbl[tbl["block"] == blk].set_index(["grain", "horizon"]).reindex(cats)
        x = np.arange(len(cats))
        ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
        _bars(ax, x, [(STYLE["adaptive"][0], STYLE["adaptive"][1], s["ratio_adaptive"].to_numpy()),
                      (STYLE["blend"][0], STYLE["blend"][1], s["ratio_blend"].to_numpy())])
        ax.axhline(1.0, color=STYLE["pers"][1], lw=2, zorder=4)
        for xi, v in enumerate(s["ratio_blend"]):
            if np.isfinite(v):  # above the persistence line when the bar is below it, so they never collide
                ax.annotate(f"{v:.2f}", (xi + 0.18, max(v, 1.0)), xytext=(0, 5), textcoords="offset points",
                            ha="center", fontsize=8.5, color=INK)
        ax.set_xticks(x); ax.set_xticklabels([f"{l}\nn={int(n)}" for l, n in zip(labels, s["n"].fillna(0))], fontsize=8.5)
        ax.set_title(f"Farm X, {blk}", loc="left", color=INK, fontsize=11)
        ax.set_xlim(-0.6, len(cats) + 0.9)
        ax.text(len(cats) - 0.45, 1.0, "persistence\n= 1.0", color=STYLE["pers"][1], fontsize=9,
                va="center", ha="left", linespacing=1.1)
    axes[0].set_ylabel("Error vs persistence\n(MAE ratio, below 1 = better)")
    axes[0].legend(loc="upper left", frameon=False, fontsize=9)
    fig.suptitle("Daily and weekly herd-milk forecasts: the blend cuts the current model's error in every "
                 "case, but after 2024 it still trails persistence", x=0.01, ha="left", fontsize=12.5, color=INK)
    fig.text(0.01, 0.005, "Same periods for every model; labels = blend ratio. Post-hoc 2024-26 was already examined: "
             "descriptive, not a confirmation. Table: docs/data/m10_blend_ratio_by_horizon.csv",
             fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    fig.savefig(OUT_FIG / "m10_blend_ratio_by_horizon.png", dpi=150)
    plt.close(fig)
    return tbl


def fig_regime(t: pd.DataFrame) -> pd.DataFrame:
    w = t[t["grain"] == "weekly"].copy()
    spans = [("shipment_before_2020_08", "development", "Shipment origins before Aug 2020"),
             ("shipment_from_2020_08", "development", "Shipment origins from Aug 2020"),
             ("cross_break_shipment_to_delpro", "development", "Shipment origin to DelPro target"),
             ("delpro_2022_2024", "development", "DelPro record, Aug 2022 - Dec 2023"),
             ("delpro_from_2024_05", "post-hoc", "DelPro record, from May 2024 (post-hoc)")]
    rows = []
    fig, axes = plt.subplots(1, len(spans), figsize=(5 * len(spans), 5), sharey=True)
    hs = [1, 4, 8, 13]
    for ax, (reg, blk, title) in zip(axes, spans):
        sub = w[(w["regime"] == reg) & w["block"].str.startswith(blk)]
        s = summarise(sub, ["horizon"]).set_index("horizon").reindex(hs)
        s.insert(0, "regime", reg)
        rows.append(s.reset_index())
        x = np.arange(len(hs))
        ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
        _bars(ax, x, [(STYLE["pers"][0], STYLE["pers"][1], s["mae_persistence"].to_numpy() / 1000),
                      (STYLE["adaptive"][0], STYLE["adaptive"][1], s["mae_adaptive"].to_numpy() / 1000),
                      (STYLE["blend"][0], STYLE["blend"][1], s["mae_blend"].to_numpy() / 1000)], width=0.27)
        ax.set_xticks(x); ax.set_xticklabels([f"{h} wk ahead\nn={int(n) if np.isfinite(n) else 0}"
                                              for h, n in zip(hs, s["n"])], fontsize=8.5)
        ax.set_title(title, loc="left", color=INK, fontsize=10.5)
    axes[0].set_ylabel("Mean absolute error\n(thousand litres per week)")
    axes[0].legend(loc="upper left", frameon=False, fontsize=9)
    fig.suptitle("Where the blend helps: weekly herd-milk error by recording regime (Farm X)",
                 x=0.01, ha="left", fontsize=12.5, color=INK)
    fig.text(0.01, 0.005, "Same periods for every model. Table: docs/data/m10_blend_mae_by_regime.csv",
             fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    fig.savefig(OUT_FIG / "m10_blend_mae_by_regime.png", dpi=150)
    plt.close(fig)
    return pd.concat(rows, ignore_index=True)


def fig_timeline(t: pd.DataFrame, h: int = 4) -> pd.DataFrame:
    w = t[(t["grain"] == "weekly") & (t["horizon"] == h) & (t["period_start"] >= "2022-01-01")]
    w = w.sort_values("period_start").reset_index(drop=True)
    gap = w["period_start"].diff().dt.days.gt(10)               # break the line where data are missing
    def broken(col):
        v = w[col].astype(float).copy()
        v[gap] = np.nan
        return v
    x = w["period_start"]
    fig, (top, bot) = plt.subplots(2, 1, figsize=(14, 8.2), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    for ax in (top, bot):
        ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
        ax.axvline(SOURCE_BREAK, color=MUTED, lw=1, ls=":")
        ax.axvline(POSTHOC_FROM, color=MUTED, lw=1, ls="--")
    # the line is drawn per contiguous run so that gaps stay empty
    seg = gap.cumsum()
    for _, run in w.groupby(seg):
        xs = run["period_start"]
        top.plot(xs, run["actual"] / 1000, color=INK, lw=2, marker="o", ms=3.5, zorder=5)
        top.plot(xs, run["pers"] / 1000, color=STYLE["pers"][1], lw=1.4, alpha=0.9, marker=".", ms=3, zorder=3)
        top.plot(xs, run["forecast_a"] / 1000, color=STYLE["adaptive"][1], lw=1.4, marker=".", ms=3, zorder=4)
        top.plot(xs, run["forecast_b"] / 1000, color=STYLE["blend"][1], lw=2, marker=".", ms=4, zorder=4)
    last = w.iloc[-1]
    ends = [("Recorded", last["actual"]), ("Blend", last["forecast_b"]),
            ("Current model", last["forecast_a"]), ("Persistence", last["pers"])]
    lo, hi = top.get_ylim()
    pos = _spread([v / 1000 for _, v in ends], 0.055 * (hi - lo))
    for (lab, val), ypos in zip(ends, pos):
        top.annotate(lab, (x.iloc[-1], val / 1000), xytext=(x.iloc[-1] + pd.Timedelta(days=22), ypos),
                     textcoords="data", fontsize=9, color=INK, va="center",
                     arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
    spike = w[(w["period_start"] > "2024-06-15") & (w["period_start"] < "2024-09-01")]
    if len(spike):
        top.annotate("forecasts issued after the\nMar-Apr 2024 data gap", (spike["period_start"].iloc[0], spike["forecast_a"].max() / 1000),
                     xytext=(pd.Timestamp("2024-10-20"), spike["forecast_a"].max() / 1000 - 1.5), fontsize=8.5,
                     color=MUTED, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6), va="center")
    top.set_ylabel("Herd milk, thousand litres per week")
    top.set_title(f"Farm X: weekly herd milk, forecast {h} weeks ahead, against what was recorded",
                  loc="left", color=INK, fontsize=12)
    ymax = top.get_ylim()[1]
    top.text(SOURCE_BREAK, ymax, " record source changes", fontsize=8.5, color=MUTED, va="top")
    top.text(POSTHOC_FROM, ymax, " post-hoc replay starts", fontsize=8.5, color=MUTED, va="top")
    roll = {}
    for key in ("err_p", "err_a", "err_b"):
        roll[key] = w[key].rolling(13, min_periods=6).mean() / 1000
    for key, style in (("err_p", "pers"), ("err_a", "adaptive"), ("err_b", "blend")):
        for _, run in w.groupby(seg):          # never draw a line across a data gap
            bot.plot(run["period_start"], roll[key].loc[run.index], color=STYLE[style][1],
                     lw=2 if style == "blend" else 1.5, marker=".", ms=2.5)
    blo, bhi = bot.get_ylim()
    ends_b = [(STYLE[st][0].split(" (")[0], roll[k].iloc[-1]) for k, st in
              (("err_p", "pers"), ("err_a", "adaptive"), ("err_b", "blend"))]
    for (lab, val), ypos in zip(ends_b, _spread([v for _, v in ends_b], 0.07 * (bhi - blo))):
        bot.annotate(lab, (x.iloc[-1], val), xytext=(x.iloc[-1] + pd.Timedelta(days=22), ypos),
                     textcoords="data", fontsize=9, color=INK, va="center",
                     arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
    bot.set_ylabel("Error: rolling MAE of the last 13\nscored periods (thousand litres per week)")
    bot.set_xlim(x.min(), x.max() + pd.Timedelta(days=200))
    fig.text(0.01, 0.005, "Line breaks = periods with no scoreable milk record (never filled in). "
             "Table: docs/data/m10_blend_timeline_weekly_h4.csv", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(OUT_FIG / f"m10_blend_timeline_weekly_h{h}.png", dpi=150)
    plt.close(fig)
    out = w[["period_start", "actual", "forecast_a", "forecast_b", "pers", "blend_w"]].copy()
    out["rolling13_mae_adaptive"] = roll["err_a"].to_numpy() * 1000
    out["rolling13_mae_blend"] = roll["err_b"].to_numpy() * 1000
    out["rolling13_mae_persistence"] = roll["err_p"].to_numpy() * 1000
    return out


def robustness(t: pd.DataFrame, boots: int = 4000, seed: int = 7) -> pd.DataFrame:
    """How solid are the weekly results? Neighbouring origins overlap, so the effective sample is the
    number of forecast MONTHS, not periods: block bootstrap over origin months for the MAE ratio
    blend / adaptive, medians (typical week), the share of the total gain that comes from the five best
    months, and the share of rows issued before the source break."""
    rng = np.random.default_rng(seed)
    w = t[t["grain"] == "weekly"].copy()
    w["om"] = w["origin"].dt.to_period("M")
    spans = {"shipment before Aug 2020 (development)": w["regime"] == "shipment_before_2020_08",
             "shipment from Aug 2020 (development)": w["regime"] == "shipment_from_2020_08",
             "cross-break (development)": w["regime"] == "cross_break_shipment_to_delpro",
             "DelPro Aug 2022-Dec 2023 (development)": (w["regime"] == "delpro_2022_2024") & w["block"].str.startswith("dev"),
             "DelPro from May 2024 (post-hoc)": w["regime"] == "delpro_from_2024_05"}
    rows = []
    for name, mask in spans.items():
        for h in WEEKLY_H:
            d = w[mask & (w["horizon"] == h)]
            if len(d) < 5:
                continue
            months = d["om"].unique()
            grp = {m: (d.loc[d["om"] == m, "err_a"].to_numpy(), d.loc[d["om"] == m, "err_b"].to_numpy()) for m in months}
            ratios = []
            for _ in range(boots):
                pick = rng.choice(len(months), len(months))
                a = np.concatenate([grp[months[i]][0] for i in pick])
                b = np.concatenate([grp[months[i]][1] for i in pick])
                ratios.append(b.mean() / a.mean())
            lo, hi = np.percentile(ratios, [5, 95])
            gain_by_month = (d["err_a"] - d["err_b"]).groupby(d["om"]).sum().sort_values(ascending=False)
            rows.append(dict(
                regime=name, weeks_ahead=h, periods=len(d), forecast_months=len(months),
                mae_ratio_blend_over_previous=d["err_b"].mean() / d["err_a"].mean(),
                ci90_low=lo, ci90_high=hi,
                median_error_previous=d["err_a"].median(), median_error_blend=d["err_b"].median(),
                median_error_last_value=d["err_p"].median(),
                top5_months_share_of_gain=(gain_by_month.head(5).sum() / gain_by_month.sum()
                                           if gain_by_month.sum() > 0 else np.nan),
                pct_issued_before_source_break=100 * (d["origin_source"] == "shipment").mean()))
    return pd.DataFrame(rows)


DEFAULT_ORIGINS = ["2017-01-02", "2020-08-03", "2023-11-06", "2026-06-01"]   # Mondays near the page's example dates
WEEKLY_H = [1, 4, 8, 13]


def _nearest_origin(w: pd.DataFrame, wanted: str) -> pd.Timestamp | None:
    """The scored weekly origin closest to ``wanted`` (within 45 days) that has at least 3 horizons."""  # 45 days: data gaps leave few scored dates
    cnt = w.groupby("origin")["horizon"].nunique()
    cand = cnt[cnt >= 3].index
    if not len(cand):
        return None
    cand = pd.DatetimeIndex(cand)
    days = np.abs((cand - pd.Timestamp(wanted)).days.to_numpy())
    i = int(np.argmin(days))
    return pd.Timestamp(cand[i]) if days[i] <= 45 else None


def fig_forecast_dates(t: pd.DataFrame, wanted: list[str]) -> pd.DataFrame:
    """Page-style cards: recorded history, previous model, modified model with its likely range, outcome."""
    w = t[t["grain"] == "weekly"].copy()
    hist_all = w.drop_duplicates("period_start").set_index("period_start")["actual"].sort_index()
    chosen = []
    for d in wanted:
        o = _nearest_origin(w, d)
        if o is None:
            print(f"no scored weekly forecast near {d}; skipped")
        elif o not in chosen:
            chosen.append(o)
    n = len(chosen)
    if not n:
        return pd.DataFrame()
    cols = 2 if n > 1 else 1
    rows_ = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows_, cols, figsize=(7.6 * cols, 4.6 * rows_), squeeze=False)
    out = []
    for ax, o in zip(axes.ravel(), chosen):
        f = w[(w["origin"] == o) & w["horizon"].isin(WEEKLY_H)].sort_values("horizon")
        xt = f["period_start"] + pd.Timedelta(days=3)               # centre of the target week
        past = hist_all[(hist_all.index + pd.Timedelta(days=7) <= o) & (hist_all.index >= o - pd.Timedelta(weeks=26))]
        ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
        hx = past.index + pd.Timedelta(days=3)
        gap = pd.Series(hx).diff().dt.days.gt(10).to_numpy()
        seg = np.cumsum(gap)
        for k in np.unique(seg):
            m = seg == k
            ax.plot(hx[m], past.to_numpy()[m] / 7000, color=INK, lw=2, marker="o", ms=3.5, zorder=5)
        ax.fill_between(xt, f["lower_b"] / 7000, f["upper_b"] / 7000, color=STYLE["blend"][1], alpha=0.16,
                        linewidth=0, zorder=1)
        ax.plot(xt, f["pers"] / 7000, color=STYLE["pers"][1], lw=1.4, ls=":", marker=".", ms=5, zorder=3)
        ax.plot(xt, f["forecast_a"] / 7000, color=STYLE["adaptive"][1], lw=2, ls="--", marker="o", ms=5, zorder=4)
        ax.plot(xt, f["forecast_b"] / 7000, color=STYLE["blend"][1], lw=2.2, ls="--", marker="o", ms=5, zorder=4)
        ax.scatter(xt, f["actual"] / 7000, s=55, facecolors=SURFACE, edgecolors=INK, linewidths=1.8, zorder=6)
        ax.axvline(o, color=INK, lw=1, ls=(0, (2, 3)))
        top = ax.get_ylim()[1]
        ax.text(o, top, "Forecast starts ", fontsize=8.5, color=INK, ha="right", va="top")
        e_a = (f["forecast_a"] - f["actual"]).abs().mean() / 7
        e_b = (f["forecast_b"] - f["actual"]).abs().mean() / 7
        e_p = (f["pers"] - f["actual"]).abs().mean() / 7
        ax.set_title(f"Farm X, forecast date {o:%d %b %Y}", loc="left", color=INK, fontsize=11)
        ax.text(0.99, 0.03, f"average miss, {len(f)} points:  previous {e_a:,.0f}  |  modified {e_b:,.0f}  |  "
                f"last value {e_p:,.0f}  (litres per day)", transform=ax.transAxes, fontsize=8.3, color=MUTED,
                ha="right", va="bottom")
        ax.set_ylabel("Milk per day (thousand litres)")
        loc = matplotlib.dates.AutoDateLocator(minticks=4, maxticks=7)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(matplotlib.dates.ConciseDateFormatter(loc))
        ax.set_xlim(o - pd.Timedelta(days=75), xt.max() + pd.Timedelta(days=12))
        if not len(past):
            ax.text(o - pd.Timedelta(days=72), 0.5, "no scored history before the\nfirst forecast date of the backtest",
                    transform=ax.get_xaxis_transform(), fontsize=8.5, color=MUTED, va="center")
        for _, r in f.iterrows():
            out.append(dict(forecast_date=o.date(), weeks_ahead=int(r["horizon"]),
                            target_week=r["period_start"].date(),
                            recorded_litres_per_day=r["actual"] / 7, previous_model=r["forecast_a"] / 7,
                            modified_model=r["forecast_b"] / 7, modified_low=r["lower_b"] / 7,
                            modified_high=r["upper_b"] / 7, last_value=r["pers"] / 7,
                            weight_on_structural=r["blend_w"]))
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [Line2D([], [], color=INK, lw=2, marker="o", ms=4, label="Recorded"),
               Line2D([], [], color=STYLE["adaptive"][1], lw=2, ls="--", marker="o", ms=5, label="Previous model (expected)"),
               Line2D([], [], color=STYLE["blend"][1], lw=2.2, ls="--", marker="o", ms=5, label="Modified model: blend (expected)"),
               Patch(color=STYLE["blend"][1], alpha=0.16, label="Likely range (modified)"),
               Line2D([], [], color=STYLE["pers"][1], lw=1.4, ls=":", marker=".", label="Last value carried forward"),
               Line2D([], [], color=INK, lw=0, marker="o", mfc=SURFACE, mec=INK, mew=1.8, ms=7, label="What actually happened")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.03), ncol=3, frameon=False, fontsize=9.5)
    fig.suptitle("Milk per day at selected forecast dates: previous model, modified model and what actually "
                 "happened (weekly points, 1 / 4 / 8 / 13 weeks ahead)", x=0.01, ha="left", fontsize=12.5, color=INK)
    fig.text(0.01, 0.005, "Blend = past-skill-weighted mix of the previous model and the last value, using only forecasts "
             "already finished at the forecast date; at the first dates there is too little history, so the two lines coincide. "
             "2024-26 dates are post-hoc (already examined). Table: docs/data/m10_blend_forecast_dates.csv",
             fontsize=8.3, color=MUTED)
    fig.tight_layout(rect=(0, 0.11, 1, 0.95))
    fig.savefig(OUT_FIG / "m10_blend_forecast_dates.png", dpi=150)
    plt.close(fig)
    print("forecast dates drawn:", ", ".join(f"{o:%Y-%m-%d}" for o in chosen))
    return pd.DataFrame(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origins", nargs="+", default=DEFAULT_ORIGINS,
                    help="forecast dates for the page-style panels (the nearest scored Monday is used)")
    ap.add_argument("--only-panels", action="store_true", help="draw only the forecast-date panels")
    args = ap.parse_args()
    validate_palette()
    table = build()
    print(f"{len(table)} matched forecast periods; "
          f"{(table['block'] == 'post-hoc 2024-26').sum()} in the post-hoc replay")
    if not args.only_panels:
        fig_ratio(table).round(3).to_csv(OUT_DATA / "m10_blend_ratio_by_horizon.csv", index=False)
        fig_regime(table).round(3).to_csv(OUT_DATA / "m10_blend_mae_by_regime.csv", index=False)
        fig_timeline(table).round(3).to_csv(OUT_DATA / "m10_blend_timeline_weekly_h4.csv", index=False)
    fig_forecast_dates(table, args.origins).round(3).to_csv(OUT_DATA / "m10_blend_forecast_dates.csv", index=False)
    rb = robustness(table)
    rb.round(3).to_csv(OUT_DATA / "m10_blend_robustness.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print("\nRobustness of the weekly results (effective sample = forecast months):")
    print(rb.round(2).to_string(index=False))
    print("wrote", ", ".join(sorted(p.name for p in OUT_FIG.glob("m10_blend_*.png"))))
