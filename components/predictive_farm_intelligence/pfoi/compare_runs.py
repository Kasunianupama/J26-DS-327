"""Two model versions at chosen forecast dates, from their page documents (any grain:
"month" by default; "day" / "week" for the pfoi-1.1.1 daily and weekly path).

Each document (``build-outlook``) holds the forecast, its 5-95 % range, the recorded history
before the forecast date and the recorded outcome after it (never a model input). This
module scores both forecasts on the same recorded months and draws them side by side, like
the page's timeline. Herd-level aggregates only.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

SERIES = ("milk_litres", "milking", "total_herd", "calvings", "abortions")
LABELS = {"milk_litres": "Herd milk (L / {g})", "milking": "Milking cows (daily avg)",
          "total_herd": "Total herd (daily avg)", "calvings": "Calvings / {g}",
          "abortions": "Abortions / {g}"}
HISTORY_MONTHS = 24
HISTORY_DAYS = {"month": 730, "week": 365, "day": 120}  # recorded history drawn before the date


def _frame(rows: list[dict], value: str) -> pd.DataFrame:
    f = pd.DataFrame(rows)
    if not len(f):
        return pd.DataFrame(columns=["series", "period", value])
    return f


def forecasts(doc: dict, grain: str = "month") -> pd.DataFrame:
    f = _frame(doc.get("outlook", []), "forecast")
    if not len(f):
        return f
    f = f[f["grain"] == grain]
    cols = ["series", "period", "horizon", "forecast", "lower", "upper"]
    if "confidence" in f:  # pfoi-1.2.1-dev: gate confidence flag per forecast
        cols.append("confidence")
    return f.assign(period=pd.to_datetime(f["target_period"]).dt.date)[cols]


def corrections(doc: dict, grain: str = "month") -> pd.DataFrame:
    """Correction-layer amounts (forecast - structural) of a pfoi-1.1.x document."""
    f = _frame(doc.get("corrections", []), "correction")
    if not len(f):
        return pd.DataFrame(columns=["series", "period", "correction"])
    f = f[f["grain"] == grain]
    return f.assign(period=pd.to_datetime(f["target_period"]).dt.date)[["series", "period", "correction"]]


def recorded(doc: dict, key: str, grain: str = "month") -> pd.DataFrame:
    """``key`` = "actuals" (before the forecast date) or "realised" (after it)."""
    f = _frame(doc.get(key, []), "value")
    if not len(f):
        return f
    f = f[(f["grain"] == grain) & f["scoreable"].astype(bool) & f["value"].notna()]
    return f.assign(period=pd.to_datetime(f["period"]).dt.date)[["series", "period", "value"]]


def score(frozen: dict, candidate: dict, series=SERIES, grain: str = "month") -> pd.DataFrame:
    """MAE, bias (forecast - recorded) and 5-95 % coverage of both models, on the recorded
    periods both forecast. One row per series (``n_months`` = number of such periods)."""
    real = recorded(candidate, "realised", grain)
    a, b = forecasts(frozen, grain), forecasts(candidate, grain)
    rows = []
    for sid in series:
        r = real[real["series"] == sid]
        m = (r.merge(a[a["series"] == sid], on=["series", "period"])
             .merge(b[b["series"] == sid], on=["series", "period"], suffixes=("_f", "_c")))
        row = {"series": sid, "n_months": len(m)}
        for tag in ("f", "c"):
            e = m[f"forecast_{tag}"] - m["value"]
            # a forecast without a range (no past errors: lower = upper) is not scored for coverage
            has = m[f"lower_{tag}"].notna() & (m[f"upper_{tag}"] > m[f"lower_{tag}"])
            inside = (m["value"] >= m[f"lower_{tag}"]) & (m["value"] <= m[f"upper_{tag}"])
            row[f"mae_{tag}"] = float(e.abs().mean()) if len(m) else np.nan
            row[f"bias_{tag}"] = float(e.mean()) if len(m) else np.nan
            row[f"cover_{tag}"] = float(inside[has].mean()) if has.any() else np.nan
        # how much of the candidate's forecast is its correction layer (0 = structural only)
        cor = corrections(candidate, grain)
        cor = cor[cor["series"] == sid].merge(m[["period"]], on="period")
        row["layer_candidate"] = float(cor["correction"].mean()) if len(cor) else (0.0 if len(m) else np.nan)
        rows.append(row)
    out = pd.DataFrame(rows).rename(columns={
        "mae_f": "mae_frozen", "mae_c": "mae_candidate", "bias_f": "bias_frozen",
        "bias_c": "bias_candidate", "cover_f": "cover90_frozen", "cover_c": "cover90_candidate"})
    out["change_pct"] = 100 * (out["mae_candidate"] / out["mae_frozen"] - 1)
    return out


def plot(frozen: dict, candidate: dict, origin: date, path, labels=("pfoi-1.0.0", "candidate"),
         series=SERIES, grain: str = "month") -> None:
    from datetime import timedelta

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hist, real = recorded(candidate, "actuals", grain), recorded(candidate, "realised", grain)
    start = origin - timedelta(days=HISTORY_DAYS[grain])
    fig, axes = plt.subplots(len(series), 1, figsize=(11, 2.4 * len(series)), sharex=True)
    for ax, sid in zip(np.atleast_1d(axes), series):
        h = hist[(hist["series"] == sid) & (hist["period"] >= start)].sort_values("period")
        ax.plot(h["period"], h["value"], color="#555555", lw=1.4, label="Recorded")
        r = real[real["series"] == sid].sort_values("period")
        ax.plot(r["period"], r["value"], "o-", color="#555555", mfc="white", ms=4, lw=1,
                label="Recorded outcome (not seen by the model)")
        for doc, label, color in ((frozen, labels[0], "#b5651d"), (candidate, labels[1], "#1f6f8b")):
            f = forecasts(doc, grain)
            f = f[f["series"] == sid].sort_values("period")
            if not len(f):
                continue
            ax.plot(f["period"], f["forecast"], "--", color=color, lw=1.6, label=label)
            ax.fill_between(f["period"], f["lower"], f["upper"], color=color, alpha=0.12, lw=0)
        ax.axvline(origin, color="#4a6fa5", lw=0.8, ls=":")
        ax.set_title(LABELS.get(sid, sid).format(g=grain), loc="left", fontsize=10)
        ax.grid(alpha=0.25)
    np.atleast_1d(axes)[0].legend(loc="upper left", fontsize=8, ncol=2, frameon=False)
    fig.suptitle(f"Forecast date {origin:%Y-%m}, by {grain}: {labels[0]} vs {labels[1]} "
                 "(herd level; 5-95 % ranges)",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


VERSION_COLOURS = ("#b5651d", "#1f6f8b", "#2a9d5c", "#8a4fb5")
GAP_DAYS = {"day": 3, "week": 10, "month": 45}  # a longer step in the recorded history is a data gap


def score_versions(docs: list[tuple[str, dict]], series=SERIES, grain: str = "month") -> pd.DataFrame:
    """MAE, bias (forecast - recorded) and 5-95 % coverage of every version on the recorded periods that
    ALL versions forecast, one row per series and version. The first document supplies the recorded
    outcome (every version of a forecast date shares it)."""
    real = recorded(docs[0][1], "realised", grain)
    fc = {label: forecasts(doc, grain) for label, doc in docs}
    rows = []
    for sid in series:
        m = real[real["series"] == sid][["period", "value"]]
        for label, f in fc.items():
            f = f[f["series"] == sid][["period", "forecast", "lower", "upper"]].rename(
                columns={"forecast": f"f_{label}", "lower": f"lo_{label}", "upper": f"hi_{label}"})
            m = m.merge(f, on="period")
        for label, _ in docs:
            e = m[f"f_{label}"] - m["value"]
            has = m[f"lo_{label}"].notna() & (m[f"hi_{label}"] > m[f"lo_{label}"])
            inside = (m["value"] >= m[f"lo_{label}"]) & (m["value"] <= m[f"hi_{label}"])
            rows.append({"series": sid, "version": label, "n_periods": len(m),
                         "mae": float(e.abs().mean()) if len(m) else np.nan,
                         "bias": float(e.mean()) if len(m) else np.nan,
                         "cover90": float(inside[has].mean()) if has.any() else np.nan})
    return pd.DataFrame(rows)


def plot_versions(docs: list[tuple[str, dict]], origin: date, path, series=SERIES, grain: str = "month") -> None:
    """Recorded history, every version's forecast with its 5-95 % range, and the recorded outcome."""
    from datetime import timedelta

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    first = docs[0][1]
    hist, real = recorded(first, "actuals", grain), recorded(first, "realised", grain)
    start = origin - timedelta(days=HISTORY_DAYS[grain])
    fig, axes = plt.subplots(len(series), 1, figsize=(11, max(3.4, 2.6 * len(series))), sharex=True)
    for ax, sid in zip(np.atleast_1d(axes), series):
        h = hist[(hist["series"] == sid) & (hist["period"] >= start)].sort_values("period")
        # a gap in the record stays a gap: break the line instead of drawing across missing periods
        steps = pd.Series(pd.to_datetime(h["period"])).diff().dt.days.to_numpy()
        runs = np.cumsum(np.nan_to_num(steps, nan=0) > GAP_DAYS[grain])
        for k in np.unique(runs):
            part = h[runs == k]
            ax.plot(part["period"], part["value"], color="#555555", lw=1.4, marker="." if len(part) < 3 else None,
                    label="Recorded" if k == runs[0] else None)
        r = real[real["series"] == sid].sort_values("period")
        ax.plot(r["period"], r["value"], "o-", color="#222222", mfc="white", ms=4, lw=1,
                label="What actually happened (not seen by the model)", zorder=6)
        for (label, doc), colour in zip(docs, VERSION_COLOURS):
            f = forecasts(doc, grain)
            f = f[f["series"] == sid].sort_values("period")
            if not len(f):
                continue
            ax.plot(f["period"], f["forecast"], "--", color=colour, lw=1.8, label=label)
            ax.fill_between(f["period"], f["lower"], f["upper"], color=colour, alpha=0.08, lw=0)
            if "confidence" in f:
                low = f[f["confidence"] == "low"]
                if len(low):
                    ax.scatter(low["period"], low["forecast"], marker="X", s=46, color=colour,
                               edgecolor="white", lw=0.6, zorder=7, label=f"{label}: low confidence (gate)")
        ax.axvline(origin, color="#4a6fa5", lw=0.8, ls=":")
        ax.set_title(LABELS.get(sid, sid).format(g=grain), loc="left", fontsize=10)
        ax.grid(alpha=0.25)
    np.atleast_1d(axes)[0].legend(loc="upper left", fontsize=8, ncol=2, frameon=False)
    fig.suptitle(f"Forecast date {origin:%Y-%m}, by {grain}: " + " vs ".join(l for l, _ in docs)
                 + " (herd level; 5-95 % ranges)", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
