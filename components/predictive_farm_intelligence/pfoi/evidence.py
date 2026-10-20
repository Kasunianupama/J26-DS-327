"""Evidence ladder (docs/pp1_plan.md §5, frontend F7): which additions help, on identical periods.

Rungs are saved backtest error tables (one model each), for example:
persistence -> current model -> + recent records (M1/M3) -> + heat (M5) -> + sensors (M6)
-> combined; an oracle run (actual future weather) may be shown but is labelled and never
counts as a result. Every rung is scored only on the forecast periods that **all** rungs
forecast (grain, horizon, origin, period), so differences are not coverage differences.

Bands: ``all``; ``recovery`` (forecast date 0-5 whole months after a labelled break);
``heat`` (period mean THI above the 90th percentile of earlier complete days, when THI is
given); ``normal`` (neither). Status comes from the files: development files are
``development``; ``_posthoc`` files are ``post-test development``; rows with fewer than 12
periods are ``not interpretable``.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from .episodes import months_since_break

KEYS = ["grain", "horizon", "origin", "period_start"]
MIN_N = 12


@dataclass(frozen=True)
class Rung:
    label: str
    model: str
    status: str = "development"  # development | post-test development | oracle


def matched(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Rows of every rung restricted to the forecast periods all rungs share."""
    parts = []
    for label, f in frames.items():
        if f is None or not len(f):
            return pd.DataFrame()
        g = f.copy()
        for c in ("origin", "period_start", "period_end"):
            g[c] = pd.to_datetime(g[c]).dt.date
        parts.append(g.drop_duplicates(KEYS).assign(rung=label))
    all_rows = pd.concat(parts, ignore_index=True)
    n = all_rows.groupby(KEYS)["rung"].transform("nunique")
    return all_rows[n == len(frames)].reset_index(drop=True)


def add_bands(rows: pd.DataFrame, thi_daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Band of each forecast period (evaluation labels only, never model inputs)."""
    out = rows.copy()
    rec = {o: months_since_break(o)[1] for o in set(out["origin"])}
    out["recovery"] = [np.isfinite(rec[o]) and rec[o] < 6 for o in out["origin"]]
    out["heat"] = False
    if thi_daily is not None and len(thi_daily):
        t = thi_daily.copy()
        t["date"] = pd.to_datetime(t["date"]).dt.date
        t = t.set_index("date")["thi_mean"].dropna().sort_index()
        cache = {}
        for (s, e) in set(zip(out["period_start"], out["period_end"])):
            past = t[t.index < s]
            if len(past) < 365:
                cache[(s, e)] = False
                continue
            cut = float(np.percentile(past.to_numpy(), 90))
            period = t[(t.index >= s) & (t.index < e)]
            cache[(s, e)] = bool(len(period) and period.mean() > cut)
        out["heat"] = [cache[(s, e)] for s, e in zip(out["period_start"], out["period_end"])]
    return out


def ladder(frames: dict[str, pd.DataFrame], rungs: list[Rung], reference: str = "persistence",
           thi_daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per rung x grain x horizon x band: n, MAE, bias, WAPE and MAE ratio to the
    reference rung on exactly the same periods, plus status."""
    m = matched(frames)
    if not len(m):
        return pd.DataFrame()
    m = add_bands(m, thi_daily)
    m["abs_err"] = (m["forecast"] - m["actual"]).abs()
    m["err"] = m["forecast"] - m["actual"]
    status = {r.label: r.status for r in rungs}
    rows = []
    bands = {"all": lambda d: d, "recovery": lambda d: d[d["recovery"]],
             "heat": lambda d: d[d["heat"]], "normal": lambda d: d[~d["recovery"] & ~d["heat"]]}
    for band, pick in bands.items():
        sub = pick(m)
        if not len(sub):
            continue
        ref = sub[sub["rung"] == reference].groupby(["grain", "horizon"])["abs_err"].mean()
        for (rung, grain, h), g in sub.groupby(["rung", "grain", "horizon"]):
            n = len(g)
            mae = float(g["abs_err"].mean())
            st = status.get(rung, "development")
            rows.append(dict(rung=rung, grain=grain, horizon=int(h), band=band, n=n, mae=mae,
                             bias=float(g["err"].mean()),
                             wape=float(g["abs_err"].sum() / g["actual"].sum()),
                             ratio_to_reference=mae / float(ref.loc[(grain, h)]) if (grain, h) in ref.index else np.nan,
                             status="not interpretable" if n < MIN_N and st != "oracle" else st))
    order = {r.label: i for i, r in enumerate(rungs)}
    out = pd.DataFrame(rows)
    out["_o"] = out["rung"].map(order)
    return out.sort_values(["band", "grain", "horizon", "_o"]).drop(columns="_o").reset_index(drop=True)


def status_of_tag(tag: str) -> str:
    if tag.endswith("_oracle"):
        return "oracle"
    if tag.endswith("_posthoc"):
        return "post-test development"
    return "development"


def parse_rung(spec: str) -> tuple[str, str, str]:
    """``label=tag:model`` -> (label, tag, model)."""
    label, rest = spec.split("=", 1)
    tag, model = rest.rsplit(":", 1)
    return label.strip(), tag.strip(), model.strip()


def latest(paths) -> object | None:
    paths = sorted(paths, key=lambda p: p.stat().st_mtime)
    return paths[-1] if paths else None



def plot_ladder(table: pd.DataFrame, path, band: str = "all", title: str = "") -> None:
    """One panel per grain x horizon: each rung's error relative to persistence (below 1 =
    better), with its n and status. Herd-level aggregates only."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = table[table["band"] == band]
    cells = list(dict.fromkeys(zip(t["grain"], t["horizon"])))
    if not cells:
        return
    fig, axes = plt.subplots(1, len(cells), figsize=(3.6 * len(cells), 3.8), sharey=True, squeeze=False)
    colour = {"development": "#9a4f27", "post-test development": "#a8770a",
              "oracle": "#a44b3c", "not interpretable": "#b9c2bd"}
    for ax, (grain, h) in zip(axes[0], cells):
        g = t[(t["grain"] == grain) & (t["horizon"] == h)]
        y = np.arange(len(g))[::-1]
        ax.barh(y, g["ratio_to_reference"], color=[colour.get(s, "#93a29b") for s in g["status"]],
                hatch=["//" if s == "oracle" else "" for s in g["status"]])
        ax.axvline(1.0, color="#52665d", lw=1, ls="--")
        ax.set_yticks(y, g["rung"])
        ax.set_title(f"{grain} · {h} ahead (n {int(g['n'].iloc[0])})", fontsize=10)
        ax.set_xlabel("error / persistence")
        for yi, r in zip(y, g["ratio_to_reference"]):
            ax.text(r, yi, f" {r:.2f}", va="center", fontsize=8)
    fig.suptitle(title or f"Which additions help ({band} periods); below 1 beats persistence", fontsize=11)
    fig.text(0.01, 0.01, "Oracle (hatched) uses actual future weather: analysis only. "
             "Same forecast periods for every bar.", fontsize=8, color="#52665d")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)
