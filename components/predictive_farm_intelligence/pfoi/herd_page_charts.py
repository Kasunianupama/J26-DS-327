"""Preview of the PFOI page's charts, drawn only from a run document (notebook 09).

Reads the same JSON the page reads (``frontend/run_document.json``) and draws each
panel in the page's style (colours and labels from ``frontend/src/data/pfoi/contract.ts``):
record status (F1), milk timeline per grain with bounds, confidence and withheld periods
(MasterTimeline, F2), herd counts, herd movement, the explanation waterfall and the
contribution chart, evidence (back-test vs benchmarks, coverage, evidence ladder) and
forecast replay. Nothing here recomputes a model: what is drawn is what the page gets.
Herd-level aggregates only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SERIES_META = {
    "milk_litres": ("Milk", "L/day", "#9a4f27"), "milking": ("Milking cows", "head", "#2f7f86"),
    "dry": ("Dry cows", "head", "#c99a77"), "heifers": ("Heifers", "head", "#5b7fa6"),
    "calves": ("Calves", "head", "#93aec9"), "total_herd": ("Total herd", "head", "#34483f"),
    "calvings": ("Calvings", "events", "#3f8c62"), "dry_offs": ("Dry-offs", "events", "#c99a77"),
    "deaths": ("Deaths", "events", "#52665d"), "culls_sales": ("Culls & sales", "events", "#a8770a"),
}
FACTOR_LABEL = {"herd_size": "Herd size", "stage_mix": "Lactation-stage mix", "parity_mix": "Parity mix",
                "pregnancy_mix": "Pregnancy mix", "yield_level": "Yield level",
                "cow_model_correction": "Cow-model correction", "thi": "Heat (THI)",
                "mastitis": "Mastitis", "residual": "Unexplained"}
CONFIDENCE = {"high": ("High", "●●●", "-"), "moderate": ("Moderate", "●●○", "--"),
              "limited": ("Limited", "●○○", ":")}
STATUS_COLOUR = {"current": "#3f8c62", "stale": "#a8770a", "withheld": "#a44b3c"}
MODEL_LABEL = {"pfoi": "PFOI", "persistence": "Persistence", "seasonal_naive": "Seasonal naive"}
INK, MUTED, PAPER, GRID = "#34483f", "#70827a", "#f2f5f8", "#e3e8e5"
DAYS = {"day": 1, "week": 7}


def _style(ax, title: str, sub: str | None = None):
    ax.set_facecolor("white")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(color=GRID, lw=0.8)
    ax.set_title(title + (f"\n{sub}" if sub else ""), loc="left", fontsize=10, color=INK)


def _days(period: pd.Series, grain: str) -> np.ndarray:
    if grain == "month":
        return pd.to_datetime(period).dt.days_in_month.to_numpy()
    return np.full(len(period), DAYS[grain])


def _frame(doc: dict, key: str) -> pd.DataFrame:
    return pd.DataFrame(doc.get(key) or [])


# ---------------------------------------------------------------- panels

def record_status_card(doc: dict, ax):
    """F1: traffic light, sentence and the four checks."""
    r = doc.get("record_status") or {}
    status = r.get("status", "unknown")
    ax.set_axis_off()
    ax.add_patch(__import__("matplotlib").patches.Circle((0.05, 0.75), 0.04, color=STATUS_COLOUR.get(status, MUTED),
                                                        transform=ax.transAxes))
    head = {"current": "Records current", "stale": f"Milk records {r.get('staleness_days')} days old",
            "withheld": "Milk forecast withheld"}.get(status, status)
    ax.text(0.12, 0.75, head, transform=ax.transAxes, fontsize=13, color=INK, va="center", weight="bold")
    ax.text(0.12, 0.6, r.get("reason_text") or f"Last trusted milk day {r.get('last_trusted_day')}.",
            transform=ax.transAxes, fontsize=9, color=MUTED, va="center")
    for i, c in enumerate(r.get("checks", [])):
        mark = {True: "✓", False: "✗", None: "–"}[c.get("ok")]
        ax.text(0.12, 0.42 - 0.1 * i, f"{mark}  {c['check'].replace('_', ' ')}: {c['detail']}",
                transform=ax.transAxes, fontsize=8.5, color=INK if c.get("ok") is not False else "#a44b3c")
    ax.set_title(f"Record status · {doc.get('model_version')} · source {doc.get('source')}",
                 loc="left", fontsize=10, color=INK)


def milk_timeline(doc: dict, grain: str, ax, history_periods: int | None = None):
    """MasterTimeline: recorded milk, forecast, 5-95% range, confidence, withheld, markers."""
    colour = SERIES_META["milk_litres"][2]
    act = _frame(doc, "actuals")
    act = act[(act["series"] == "milk_litres") & (act["grain"] == grain)] if len(act) else act
    if len(act):
        act = act.assign(period=pd.to_datetime(act["period"])).sort_values("period")
        if history_periods:
            act = act.tail(history_periods)
        v = act["value"].astype(float) / _days(act["period"], grain)
        ax.plot(act["period"], v, "o", ms=2.5 if grain == "day" else 4, color=INK, label="Recorded")
        missing = act[act["value"].isna()]
        for p in missing["period"]:
            ax.axvspan(p, p + pd.Timedelta(days=DAYS.get(grain, 30)), color=GRID, alpha=0.8, lw=0)
    f = _frame(doc, "outlook")
    f = f[(f["series"] == "milk_litres") & (f["grain"] == grain)] if len(f) else f
    if len(f):
        f = f.assign(period=pd.to_datetime(f["target_period"])).sort_values("period")
        d = _days(f["period"], grain)
        y, lo, hi = f["forecast"] / d, f["lower"].astype(float) / d, f["upper"].astype(float) / d
        ax.fill_between(f["period"], lo, hi, color=colour, alpha=0.15, lw=0, label="Likely range (5–95%)")
        for q, (label, mark, ls) in CONFIDENCE.items():
            part = f["quality_flag"] == q
            if part.any():
                yy = np.where(part, y, np.nan)
                ax.plot(f["period"], yy, ls=ls, lw=1.8, color=colour, label=f"Forecast · {label} {mark}")
        if grain == "month":
            for m in doc.get("horizon_reliability", []):
                at = f["period"].iloc[0] + pd.DateOffset(months=int(m["horizon"]) - 1)
                ax.axvline(at, color=MUTED, ls=":", lw=1)
                ax.text(at, ax.get_ylim()[1], f" {m['marker'].replace('_', ' ')}", rotation=90,
                        va="top", fontsize=7, color=MUTED)
    for w in doc.get("withheld", []):
        if w.get("grain") == grain:
            ax.axvspan(pd.Timestamp(w["from"]), pd.Timestamp(w["to"]), facecolor="none", hatch="///",
                       edgecolor=MUTED, lw=0, label="Forecast withheld")
    _style(ax, f"Milk, {'daily' if grain == 'day' else grain + 'ly'} (L/day)",
           "dots recorded · line forecast · band likely range · line style = confidence")
    ax.legend(fontsize=7, ncol=3, loc="upper left", frameon=False)


def herd_counts(doc: dict, axes):
    """Herd counts: recorded months and the path forecast with ranges."""
    act, f = _frame(doc, "actuals"), _frame(doc, "outlook")
    for ax, s in zip(axes, ("milking", "dry", "heifers", "calves", "total_herd", "calvings")):
        name, unit, colour = SERIES_META[s]
        if len(act):
            a = act[(act["series"] == s) & (act["grain"] == "month")]
            ax.plot(pd.to_datetime(a["period"]), a["value"], "o", ms=3, color=INK)
        g = f[(f["series"] == s) & (f["grain"] == "month")] if len(f) else f
        if len(g):
            x = pd.to_datetime(g["target_period"])
            ax.fill_between(x, g["lower"].astype(float), g["upper"].astype(float), color=colour, alpha=0.18, lw=0)
            ax.plot(x, g["forecast"], color=colour, lw=1.8)
        _style(ax, f"{name} ({unit}{', per month' if unit == 'events' else ''})")


def herd_movement(doc: dict, ax, months: int = 12):
    """Herd movement: projected moves in and out of the milking herd per month."""
    f = _frame(doc, "outlook")
    if not len(f):
        ax.set_axis_off(); return
    f = f[f["grain"] == "month"]
    piv = f.pivot_table(index="target_period", columns="series", values="forecast").head(months)
    x = pd.to_datetime(piv.index)
    w = 20
    if "calvings" in piv:
        ax.bar(x, piv["calvings"], width=w, color=SERIES_META["calvings"][2], label="Calvings (in)")
    bottom = np.zeros(len(piv))
    for s in ("dry_offs", "culls_sales", "deaths"):
        if s in piv:
            ax.bar(x, -piv[s], width=w, bottom=-bottom, color=SERIES_META[s][2], label=f"{SERIES_META[s][0]} (out)")
            bottom += piv[s].to_numpy()
    ax.axhline(0, color=INK, lw=0.8)
    if "milking" in piv:
        ax2 = ax.twinx()
        ax2.plot(x, piv["milking"], color=SERIES_META["milking"][2], lw=2, label="Milking cows")
        ax2.set_ylabel("milking cows", color=SERIES_META["milking"][2], fontsize=8)
        ax2.tick_params(colors=MUTED, labelsize=8)
    _style(ax, "Herd movement, next 12 months", "bars: animals in (up) and out (down) · line: milking cows")
    ax.legend(fontsize=7, ncol=4, loc="lower left", frameon=False)


def _breakdowns(doc: dict) -> list[dict]:
    a = _frame(doc, "attribution")
    if not len(a):
        return []
    out = []
    f = _frame(doc, "outlook")
    fm = f[(f["series"] == "milk_litres") & (f["grain"] == "month")] if len(f) else f
    act = _frame(doc, "actuals")
    am = act[(act["series"] == "milk_litres") & (act["grain"] == "month")] if len(act) else act
    for kind in ("forecast", "past"):
        k = a[a["kind"] == kind]
        if not len(k):
            continue
        tp = k["target_period"].min() if kind == "forecast" else k["target_period"].max()
        if kind == "past" and len(am):
            have = set(pd.to_datetime(am.loc[am["value"].notna(), "period"]).dt.strftime("%Y-%m-%d"))
            ok = sorted(t for t in k["target_period"].astype(str).unique() if t in have)
            tp = ok[-1] if ok else tp
        parts = k[k["target_period"].astype(str) == str(tp)].groupby("factor")["contribution"].sum()
        if kind == "forecast" and len(fm):
            row = fm[fm["target_period"] == tp]
            end = float(row["forecast"].iloc[0] / pd.Timestamp(tp).days_in_month) if len(row) else np.nan
        else:
            row = am[pd.to_datetime(am["period"]) == pd.Timestamp(tp)] if len(am) else am
            end = float(row["value"].iloc[0] / pd.Timestamp(tp).days_in_month) if len(row) and pd.notna(row["value"].iloc[0]) else np.nan
        out.append({"kind": kind, "period": tp, "parts": parts, "end": end, "start": end - parts.sum()})
    return out


def waterfall(b: dict, ax):
    """Waterfall: last month → this month, one bar per part (adds up exactly)."""
    parts = b["parts"][b["parts"].abs() >= 0.05].sort_values(key=np.abs, ascending=False)
    if b["kind"] == "forecast":
        parts = parts.drop("residual", errors="ignore") if abs(parts.get("residual", 0)) < 0.05 else parts
    change = b["parts"].sum()
    labels = ["Last month"] + [FACTOR_LABEL.get(f, f) for f in parts.index] + ["This month"]
    if not (np.isfinite(b["start"]) and np.isfinite(b["end"])):
        # No recorded level for this month: draw the change alone, from zero.
        b = {**b, "start": 0.0, "end": float(change)}
        labels[0], labels[-1] = "Start (0)", "Change"
    level = b["start"]
    for i, (f, v) in enumerate(parts.items(), start=1):
        ax.bar(i, v, bottom=level, color="#3f8c62" if v > 0 else "#a44b3c", width=0.6)
        ax.text(i, level + v, f"{v:+,.1f}", ha="center", va="bottom" if v > 0 else "top", fontsize=7.5, color=INK)
        level += v
    ax.bar(0, b["start"], color=MUTED, width=0.6)
    ax.bar(len(labels) - 1, b["end"], color=SERIES_META["milk_litres"][2], width=0.6)
    vals = np.array([b["start"], b["end"], *(b["start"] + np.cumsum(parts.to_numpy()))], dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals):
        lo, hi = vals.min(), vals.max()
        pad = max(0.02 * max(abs(lo), abs(hi)), 0.05 * (hi - lo), 1.0)
        ax.set_ylim(lo - pad, hi + pad)
    ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right", fontsize=8)
    verb = ("rose" if change > 0.5 else "fell" if change < -0.5 else "held steady") if b["kind"] == "past" else \
        ("is expected to rise" if change > 0.5 else "is expected to fall" if change < -0.5 else "is expected to hold steady")
    main = parts.drop("residual", errors="ignore")
    reason = f" Main reason: {FACTOR_LABEL.get(main.index[0], main.index[0]).lower()} ({main.iloc[0]:+,.1f} L/day)." if len(main) else ""
    _style(ax, f"Milk change explained · {pd.Timestamp(b['period']).strftime('%b %Y')}",
           f"Milk {verb} by {abs(change):,.0f} L/day.{reason} Parts add up exactly ({change:+,.1f}).")


def contributions(doc: dict, ax):
    """ContributionChart: monthly forecast changes split by factor (stacked)."""
    a = _frame(doc, "attribution")
    a = a[a["kind"] == "forecast"] if len(a) else a
    if not len(a):
        ax.set_axis_off(); return
    piv = a.pivot_table(index="target_period", columns="factor", values="contribution", aggfunc="sum").fillna(0)
    x = pd.to_datetime(piv.index)
    pos, neg = np.zeros(len(piv)), np.zeros(len(piv))
    cmap = __import__("matplotlib").colormaps["tab10"]
    for i, f in enumerate(piv.columns):
        v = piv[f].to_numpy()
        if not np.any(np.abs(v) > 0.05):
            continue
        base = np.where(v >= 0, pos, neg)
        ax.bar(x, v, bottom=base, width=20, color=cmap(i), label=FACTOR_LABEL.get(f, f))
        pos, neg = np.where(v >= 0, pos + v, pos), np.where(v < 0, neg + v, neg)
    ax.plot(x, piv.sum(axis=1), "o-", color=INK, ms=3, lw=1, label="Net change")
    ax.axhline(0, color=INK, lw=0.6)
    _style(ax, "Why the forecast changes month to month (L/day)", "each bar: change from the previous month, by reason")
    ax.legend(fontsize=7, ncol=5, loc="lower left", frameon=False)


def evidence(doc: dict, axes):
    """Evidence: MAE by horizon vs benchmarks, bound coverage, evidence ladder."""
    bt = _frame(doc, "backtest")
    ax1, ax2, ax3 = axes
    if len(bt):
        m = bt[(bt["grain"] == "month")]
        piv = m.pivot_table(index="horizon", columns="model", values="mae", aggfunc="mean")
        for i, col in enumerate([c for c in ("pfoi", "persistence", "seasonal_naive") if c in piv]):
            ax1.bar(piv.index + (i - 1) * 0.27, piv[col] / 30.4, width=0.27, label=MODEL_LABEL[col],
                    color={"pfoi": SERIES_META["milk_litres"][2], "persistence": MUTED, "seasonal_naive": "#93aec9"}[col])
        ax1.legend(fontsize=7, frameon=False)
        cov = bt[(bt["model"] == "pfoi") & bt["coverage"].notna()]
        if len(cov):
            c = cov.assign(inside=cov["coverage"] * cov["n"]).groupby(["block", "grain"])[["inside", "n"]].sum()
            labels = [f"{b}\n{g}" for b, g in c.index]
            ax2.bar(labels, 100 * c["inside"] / c["n"], color=SERIES_META["milk_litres"][2])
            ax2.axhline(90, color=INK, ls="--", lw=0.8)
            for i, n in enumerate(c["n"]):
                ax2.text(i, 2, f"n={int(n)}", ha="center", fontsize=7, color="white")
    _style(ax1, "Monthly error by months ahead (MAE, L/day)", "lower is better · PFOI vs benchmarks, same months")
    _style(ax2, "Share of actuals inside the 5–95% range (%)", "target about 90")
    lad = _frame(doc, "evidence_ladder")
    if len(lad):
        lad = lad[lad["grain"] == "monthly"] if (lad["grain"] == "monthly").any() else lad[lad["grain"] == lad["grain"].iloc[0]]
        ax3.barh(lad["rung"], lad["ratio_to_reference"], color=[MUTED if s == "not interpretable" else SERIES_META["milk_litres"][2]
                                                            for s in lad["status"]])
        ax3.axvline(1, color=INK, ls="--", lw=0.8)
        for i, (r, n, s) in enumerate(zip(lad["ratio_to_reference"], lad["n"], lad["status"])):
            ax3.text(r, i, f"  n={n} · {s}", va="center", fontsize=7, color=INK)
        ax3.invert_yaxis()
        ax3.tick_params(axis="y", labelsize=7.5)
        _style(ax3, f"Evidence ladder ({lad['grain'].iloc[0]}, test): error ÷ persistence error", "below 1 = better than persistence")
    else:
        ax3.set_axis_off()


def replay(doc: dict, ax):
    """ForecastReplay: test forecasts as they were made vs what happened."""
    r = _frame(doc, "replay")
    r = r[(r["grain"] == "month") & (r["series"] == "milk_litres")] if len(r) else r
    if not len(r):
        ax.set_axis_off(); return
    r = r.assign(period=pd.to_datetime(r["target_period"]), d=lambda t: t["period"].dt.days_in_month)
    for o, g in r.groupby("origin_date"):
        ax.plot(g["period"], g["forecast"] / g["d"], "-", lw=1, alpha=0.7, label=f"made {str(o)[:7]}")
    act = r.drop_duplicates("period")
    ax.plot(act["period"], act["actual"] / act["d"], "o", color=INK, ms=4, label="Recorded")
    _style(ax, "Forecast replay (test): what each forecast said vs what happened (L/day)")
    ax.legend(fontsize=7, ncol=4, frameon=False)


def render_all(doc: dict, out_dir) -> list[Path]:
    """Every page panel this model feeds, saved as PNGs; returns the paths."""
    import matplotlib.pyplot as plt

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []

    def save(fig, name):
        fig.patch.set_facecolor(PAPER)
        fig.tight_layout()
        p = out / f"{name}.png"
        fig.savefig(p, dpi=140, bbox_inches="tight", facecolor=PAPER)
        plt.show(); plt.close(fig)
        paths.append(p)

    fig, ax = plt.subplots(figsize=(12, 2.8)); record_status_card(doc, ax); save(fig, "page_f1_record_status")
    fig, axes = plt.subplots(3, 1, figsize=(14, 11))
    for ax, (g, n) in zip(axes, (("day", 60), ("week", 52), ("month", 24))):
        milk_timeline(doc, g, ax, n)
    save(fig, "page_milk_timeline")
    fig, axes = plt.subplots(2, 3, figsize=(15, 7)); herd_counts(doc, axes.ravel()); save(fig, "page_herd_counts")
    fig, ax = plt.subplots(figsize=(13, 4.5)); herd_movement(doc, ax); save(fig, "page_herd_movement")
    bds = _breakdowns(doc)
    if bds:
        fig, axes = plt.subplots(1, len(bds), figsize=(7 * len(bds), 4.8), squeeze=False)
        for ax, b in zip(axes[0], bds):
            waterfall(b, ax)
        save(fig, "page_waterfalls")
    fig, ax = plt.subplots(figsize=(14, 4.8)); contributions(doc, ax); save(fig, "page_contributions")
    fig, axes = plt.subplots(1, 3, figsize=(18, 4.8)); evidence(doc, axes); save(fig, "page_evidence")
    fig, ax = plt.subplots(figsize=(13, 4.5)); replay(doc, ax); save(fig, "page_replay")
    return paths
