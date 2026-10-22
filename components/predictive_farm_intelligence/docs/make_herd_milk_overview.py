"""Descriptive chart, no model: monthly herd by group and monthly recorded milk, whole data period.

Run from the repository root (reads model_input2.period_panel, herd-level monthly aggregates only):

    .venv/bin/python components/predictive_farm_intelligence/docs/make_herd_milk_overview.py

Database settings come from the same environment variables as C1 (read-only connection).
Milk bars: measured herd milk (herd-total days) and estimated herd milk (cow-sample days), stacked.
Writes herd_milk_overview.png, milk_yield_per_cow.png, milk_composition.png and the monthly tables behind it to logs/pfoi_mi2/charts/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
INK, MUTED, GRID, BG = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
# Herd groups, bottom to top of the stack.
GROUPS = [
    ("milking", "Milking, milk record that day", "#2a78d6"),
    ("lactating_unrecorded", "Milking, not recorded that day", "#9cc3ee"),
    ("adult_no_calving", "Adult, no calving in records", "#c9c3e8"),
    ("dry", "Dry", "#e9a23b"),
    ("heifers", "Heifers", "#4f9d69"),
    ("calves", "Calves", "#a6d3a0"),
    ("bulls", "Bulls", "#8a8580"),
    ("other_unknown", "Unknown (no birth date / sex)", "#d9d6d0"),
]
COLUMNS = """period_start, avg_herd, avg_calves, avg_heifers_open, avg_heifers_pregnant, avg_milking,
             avg_dry_open, avg_dry_pregnant, avg_bulls, avg_lactating_unrecorded,
             avg_adult_no_recorded_calving, milk_observed_litres, target_litres, milk_observed_records,
             n_observed_days, n_sparse_days, n_days, distinct_observed_cows, herd_milk_measured,
             herd_milk_estimated, n_herd_total_days, n_cow_sample_days, milk_reassigned_to_unidentified"""


def load_db(schema: str) -> pd.DataFrame:
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import create_engine, text
    from components.predictive_farm_intelligence.pfoi.config import DatabaseSettings

    engine = create_engine(DatabaseSettings.from_env().url,
                           connect_args={"options": "-c default_transaction_read_only=on"})
    # Cow milk (placeholder herd totals excluded), summed from the daily panel per month.
    sql = f"""SELECT {COLUMNS}, d.cow_litres, d.cow_litres_usable, d.placeholder_litres
               FROM {schema}.period_panel p
               LEFT JOIN (SELECT month, SUM(milk_observed_cow_litres) AS cow_litres,
                                 SUM(milk_observed_cow_litres) FILTER (WHERE NOT data_gap) AS cow_litres_usable,
                                 SUM(milk_observed_placeholder_litres) AS placeholder_litres
                          FROM {schema}.day_panel GROUP BY month) d ON d.month = p.period_start
               WHERE p.grain = 'month' ORDER BY p.period_start"""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


YIELD_SQL = """SELECT month AS period_start,
       SUM(milk_per_recorded_cow * observed_milking_cows) FILTER (WHERE milk_per_recorded_cow IS NOT NULL)
         / NULLIF(SUM(observed_milking_cows) FILTER (WHERE milk_per_recorded_cow IS NOT NULL), 0) AS litres_per_cow_day,
       percentile_cont(0.1) WITHIN GROUP (ORDER BY milk_per_recorded_cow) AS p10_day,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY milk_per_recorded_cow) AS p90_day,
       SUM(observed_milking_cows) FILTER (WHERE milk_per_recorded_cow IS NOT NULL) AS cow_days,
       COUNT(milk_per_recorded_cow) AS days
FROM {schema}.day_panel GROUP BY month ORDER BY month"""


def load_yield(schema: str) -> pd.DataFrame:
    """Monthly litres per recorded cow per day (cow records <= 18 L, days with >= 10 cows)."""
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import create_engine, text
    from components.predictive_farm_intelligence.pfoi.config import DatabaseSettings

    engine = create_engine(DatabaseSettings.from_env().url,
                           connect_args={"options": "-c default_transaction_read_only=on"})
    with engine.connect() as conn:
        return pd.read_sql(text(YIELD_SQL.format(schema=schema)), conn)


def draw_yield(y: pd.DataFrame, path: Path) -> None:
    """Milk yield per cow over time: no herd count involved."""
    y = y.copy()
    y["period_start"] = pd.to_datetime(y["period_start"])
    y = y.set_index("period_start").sort_index()
    months = pd.date_range(y.index.min(), y.index.max(), freq="MS")
    y = y.reindex(months)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(14, 7), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    a1.fill_between(months, y["p10_day"], y["p90_day"], color="#9cc3ee", alpha=.6, lw=0,
                    label="Spread of daily values (10th-90th percentile)")
    a1.plot(months, y["litres_per_cow_day"], color="#2a78d6", lw=2, marker="o", ms=3,
            label="Litres per recorded cow per day (monthly)")
    a1.axhline(18, color="#a2462f", lw=1, ls="--", label="18 L limit (records above are excluded)")
    a1.set_ylabel("litres per cow per day")
    a1.set_ylim(0, 20)
    a1.grid(axis="y", color=GRID, lw=.8)
    a1.set_axisbelow(True)
    a1.legend(loc="upper right", frameon=False, fontsize=9)
    a1.set_title("Milk yield per cow (identified cows in core.animal_daily, records <= 18 L, days with >= 10 cows)",
                 loc="left", fontsize=10.5, color=INK)
    a2.bar(months, y["cow_days"].fillna(0), width=24, color="#c9c3e8")
    a2.set_ylabel("recorded cow-days")
    a2.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    a2.grid(axis="y", color=GRID, lw=.8)
    a2.set_axisbelow(True)
    a2.set_title("How many cow-days the average rests on (blank = no usable per-cow data)",
                 loc="left", fontsize=10, color=INK)
    fig.suptitle("Farm X: milk yield per cow by month, recorded data only (no herd scaling, no model)",
                 x=.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


COMP_SQL = """SELECT month AS period_start,
       SUM(milk_observed_litres) AS total_litres,
       SUM(milk_observed_cow_litres) AS cow_litres_le18,
       SUM(milk_excluded_high_litres) AS cow_litres_over18,
       SUM(milk_observed_placeholder_litres) AS placeholder_litres,
       SUM(milk_observed_records) AS records,
       AVG(n_herd) AS avg_herd, AVG(milking) AS avg_milking,
       AVG(observed_milking_cows) AS avg_cows_recorded,
       SUM(milk_observed_cow_litres) FILTER (WHERE milk_per_recorded_cow IS NOT NULL)
         / NULLIF(SUM(observed_milking_cows) FILTER (WHERE milk_per_recorded_cow IS NOT NULL), 0) AS litres_per_recorded_cow,
       SUM(herd_milk_measured) / NULLIF(SUM(milking) FILTER (WHERE milk_record_type = 'herd_total'), 0)
         AS herd_total_litres_per_milking_cow
FROM {schema}.day_panel GROUP BY month ORDER BY month"""

PARTS = [("cow_litres_le18", "Identified cows, records <= 18 L", "#2a78d6"),
         ("cow_litres_over18", "Identified cows, records > 18 L", "#e9a23b"),
         ("placeholder_litres", "Placeholder (unidentified, herd total)", "#a2462f")]


def load_comp(schema: str) -> pd.DataFrame:
    """Monthly milk split into its parts, herd counts and per-cow yields (herd-level aggregates)."""
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import create_engine, text
    from components.predictive_farm_intelligence.pfoi.config import DatabaseSettings

    engine = create_engine(DatabaseSettings.from_env().url,
                           connect_args={"options": "-c default_transaction_read_only=on"})
    with engine.connect() as conn:
        return pd.read_sql(text(COMP_SQL.format(schema=schema)), conn)


def draw_comp(c: pd.DataFrame, path: Path) -> None:
    """Total milk = identified cows <= 18 L + identified cows > 18 L + placeholder, next to herd and per cow."""
    c = c.copy()
    c["period_start"] = pd.to_datetime(c["period_start"])
    c = c.set_index("period_start").sort_index()
    x = c.index
    parts = c[[k for k, _, _ in PARTS]].fillna(0)
    fig, ax = plt.subplots(4, 1, figsize=(14, 15), sharex=True, gridspec_kw={"height_ratios": [1.2, .8, 1, 1]})
    w = 24
    bottom = np.zeros(len(c))
    for k, label, col in PARTS:
        ax[0].bar(x, parts[k], width=w, bottom=bottom, color=col, label=label)
        bottom = bottom + parts[k].to_numpy()
    ax[0].plot(x, c["total_litres"], color=INK, lw=1, marker="_", ms=6, ls="none", label="Total recorded milk (= Query 1)")
    ax[0].set_ylabel("litres per month")
    ax[0].yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax[0].set_title("1. Total recorded milk and what it is made of (core.animal_daily, is_yield_valid)",
                    loc="left", fontsize=10.5, color=INK)
    tot = parts.sum(axis=1).replace(0, np.nan)
    share = parts.div(tot, axis=0) * 100
    bottom = np.zeros(len(c))
    for k, label, col in PARTS:
        ax[1].bar(x, share[k].fillna(0), width=w, bottom=bottom, color=col)
        bottom = bottom + share[k].fillna(0).to_numpy()
    ax[1].set_ylabel("% of the month's milk")
    ax[1].set_ylim(0, 100)
    ax[1].set_title("2. The same as shares: how much was measured per cow vs unidentified",
                    loc="left", fontsize=10.5, color=INK)
    ax[2].plot(x, c["avg_herd"], color=INK, lw=2, label="Total herd")
    ax[2].plot(x, c["avg_milking"], color="#2a78d6", lw=2, label="Milking herd (in lactation)")
    ax[2].plot(x, c["avg_cows_recorded"], color="#e9a23b", lw=2, label="Cows with a milk record (per day)")
    ax[2].set_ylabel("head (daily average)")
    ax[2].set_title("3. Herd: total, milking, and cows actually recorded", loc="left", fontsize=10.5, color=INK)
    ax[3].plot(x, c["litres_per_recorded_cow"], color="#2a78d6", lw=2, marker="o", ms=3,
               label="Per recorded cow (identified records <= 18 L)")
    ax[3].plot(x, c["herd_total_litres_per_milking_cow"], color="#a2462f", lw=2, marker="s", ms=3,
               label="Herd-total days: total milk / milking herd")
    ax[3].axhline(18, color="#a2462f", lw=1, ls="--", label="18 L per cow")
    ax[3].set_ylabel("litres per cow per day")
    ax[3].set_ylim(0, max(25, float(np.nanmax(c[["litres_per_recorded_cow", "herd_total_litres_per_milking_cow"]]
                                               .to_numpy(dtype=float), initial=0)) + 2))
    ax[3].set_title("4. Milk per cow per day", loc="left", fontsize=10.5, color=INK)
    for a in ax:
        a.grid(axis="y", color=GRID, lw=.8)
        a.set_axisbelow(True)
    for a in (ax[0], ax[2], ax[3]):
        a.legend(loc="upper left", bbox_to_anchor=(1.005, 1.0), frameon=False, fontsize=9)
    fig.suptitle("Farm X: milk composition, herd and milk per cow by month (recorded data only, no model)",
                 x=.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def groups(m: pd.DataFrame) -> pd.DataFrame:
    """Average head per day in each herd group; the groups add up to avg_herd."""
    g = pd.DataFrame(index=m.index)
    # Milking = in lactation; split into recorded that day and not recorded that day.
    g["milking"] = (m["avg_milking"] - m["avg_lactating_unrecorded"]).clip(lower=0)
    g["lactating_unrecorded"] = m["avg_lactating_unrecorded"]
    g["adult_no_calving"] = m["avg_adult_no_recorded_calving"]
    g["dry"] = m["avg_dry_open"] + m["avg_dry_pregnant"]
    g["heifers"] = m["avg_heifers_open"] + m["avg_heifers_pregnant"]
    g["calves"] = m["avg_calves"]
    g["bulls"] = m["avg_bulls"]
    g["other_unknown"] = (m["avg_herd"] - g.sum(axis=1)).clip(lower=0)
    return g.fillna(0)


def draw(m: pd.DataFrame, path: Path) -> None:
    m = m.copy()
    m["period_start"] = pd.to_datetime(m["period_start"])
    m = m.set_index("period_start").sort_index()
    g = groups(m)
    x = m.index
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": BG, "axes.facecolor": BG})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [1.15, 1]})

    a1.stackplot(x, *[g[k] for k, _, _ in GROUPS], labels=[l for _, l, _ in GROUPS],
                 colors=[c for _, _, c in GROUPS], lw=0)
    a1.plot(x, m["avg_herd"], color=INK, lw=1.4, label="Total herd")
    a1.set_ylabel("head (daily average in the month)")
    a1.set_title("Herd by group, monthly (core: entries, exits, calvings, dry-offs, pregnancies; "
                 "milking = in lactation; daily milk record is a sample)", loc="left", fontsize=10.5, color=INK)
    a1.grid(axis="y", color=GRID, lw=.8)
    a1.set_axisbelow(True)
    a1.legend(loc="upper left", bbox_to_anchor=(1.005, 1.0), frameon=False, fontsize=9)

    w = 24
    # Herd milk: MEASURED on herd-total days (cows + reassigned >18 L + placeholder), ESTIMATED on
    # cow-sample days (milk per recorded cow x milking herd). Never added into one unlabelled bar.
    measured = m["herd_milk_measured"].fillna(0)
    estimated = m["herd_milk_estimated"].fillna(0)
    a2.bar(x, measured, width=w, color="#a2462f", label="Herd milk, measured (herd-total days)")
    a2.bar(x, estimated, width=w, bottom=measured, color="#e7b8a6", hatch="///", edgecolor="#c98670", lw=0,
           label="Herd milk, estimated (milk per recorded cow x milking herd)")
    missing = (measured + estimated) <= 0
    for d in x[missing]:
        a2.axvspan(d, d + pd.offsets.MonthEnd(1), color="#5a8fd1", alpha=.12, lw=0)
    a2.plot([], [], color="#5a8fd1", alpha=.3, lw=8, label="No usable milk in the month")
    a2.set_ylabel("litres per month")
    a2.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    a2.grid(axis="y", color=GRID, lw=.8)
    a2.set_axisbelow(True)
    a3 = a2.twinx()
    a3.plot(x, m["distinct_observed_cows"].replace(0, np.nan), color=INK, lw=1.2, label="Cows with milk records in the month")
    a3.set_ylabel("cows with records")
    a3.spines["right"].set_visible(True)
    h1, l1 = a2.get_legend_handles_labels()
    h2, l2 = a3.get_legend_handles_labels()
    a2.legend(h1 + h2, l1 + l2, loc="upper left", bbox_to_anchor=(1.06, 1.0), frameon=False, fontsize=9)
    a2.set_title("Herd milk, monthly (core.animal_daily, is_yield_valid; measured vs estimated)",
                 loc="left", fontsize=10.5, color=INK)
    fig.suptitle("Farm X: herd and milk by month, recorded data only (no model)",
                 x=.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--schema", default="model_input2")
    ap.add_argument("--csv", default=None, help="read this monthly period_panel export instead of the database")
    ap.add_argument("--out", default="logs/pfoi_mi2/charts")
    a = ap.parse_args(argv)
    m = pd.read_csv(a.csv) if a.csv else load_db(a.schema)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    m.to_csv(out / "herd_milk_overview_monthly.csv", index=False)
    draw(m, out / "herd_milk_overview.png")
    if not a.csv:
        yld = load_yield(a.schema)
        yld.to_csv(out / "milk_yield_per_cow_monthly.csv", index=False)
        draw_yield(yld, out / "milk_yield_per_cow.png")
        yy = yld.assign(year=pd.to_datetime(yld["period_start"]).dt.year).groupby("year").apply(
            lambda g: pd.Series({"litres_per_cow_day": (g["litres_per_cow_day"] * g["cow_days"]).sum()
                                 / g["cow_days"].sum() if g["cow_days"].sum() else np.nan,
                                 "cow_days": g["cow_days"].sum()}))
        print(yy.round(1).to_string())
        print(f"chart: {out / 'milk_yield_per_cow.png'}")
        comp = load_comp(a.schema)
        comp.to_csv(out / "milk_composition_monthly.csv", index=False)
        draw_comp(comp, out / "milk_composition.png")
        yc = comp.assign(year=pd.to_datetime(comp["period_start"]).dt.year).groupby("year").agg(
            total=("total_litres", "sum"), cows_le18=("cow_litres_le18", "sum"),
            cows_over18=("cow_litres_over18", "sum"), placeholder=("placeholder_litres", "sum"),
            herd=("avg_herd", "mean"), milking=("avg_milking", "mean"), recorded_per_day=("avg_cows_recorded", "mean"))
        print(yc.round(0).to_string())
        print(f"chart: {out / 'milk_composition.png'}")
    yr = m.assign(year=pd.to_datetime(m["period_start"]).dt.year).groupby("year").agg(
        herd=("avg_herd", "mean"), milking=("avg_milking", "mean"),
        recorded_milk=("milk_observed_litres", "sum"), measured_herd_milk=("herd_milk_measured", "sum"),
        estimated_herd_milk=("herd_milk_estimated", "sum"), herd_total_days=("n_herd_total_days", "sum"),
        cow_sample_days=("n_cow_sample_days", "sum"))
    print(yr.round(0).to_string())
    print(f"\nchart: {out / 'herd_milk_overview.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
