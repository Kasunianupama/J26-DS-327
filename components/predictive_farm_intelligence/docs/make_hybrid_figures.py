"""Charts comparing the 1.3 hybrid with the 1.2 reference and persistence.

Reads only the aggregate tables written by pfoi.hybrid_runner (matched.csv, metrics.csv,
by_origin_year.csv) and writes PNGs to <run_dir>/figures. No row-level data, no database.

    python components/predictive_farm_intelligence/docs/make_hybrid_figures.py logs/pfoi_hybrid_1_3_dev_v1
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REFS = ("persistence", "base_1_2_code_reference")
SPECIALISTS = ("coupled", "history_change", "pipeline_change")
COLOURS = {"hybrid": "#2a78d6", "base_1_2_code_reference": "#6250d6", "persistence": "#eb6834",
           "coupled": "#52514e", "history_change": "#2a9d5c", "pipeline_change": "#c9a227"}


def main(run_dir):
    run = Path(run_dir)
    out = run / "figures"
    out.mkdir(exist_ok=True)
    matched = pd.read_csv(run / "matched.csv")
    metrics = pd.read_csv(run / "metrics.csv")
    hybrid = [m for m in metrics.model.unique() if m not in REFS + SPECIALISTS]
    if len(hybrid) != 1:
        raise SystemExit(f"Expected one hybrid model name, found {hybrid}")
    hybrid = hybrid[0]
    milk = lambda d: d[d.series.eq("herd_milk")]

    # Fig 1: paired skill of the hybrid vs each reference, by grain and horizon (>0 = hybrid better).
    m = milk(matched[matched.model.eq(hybrid)])
    grains = [g for g in ("daily", "weekly", "monthly") if g in set(m.grain)]
    fig, axes = plt.subplots(1, len(grains), figsize=(5 * len(grains), 4), sharey=True, squeeze=False)
    for ax, grain in zip(axes[0], grains):
        for ref, off in zip(REFS, (-0.2, 0.2)):
            d = m[m.grain.eq(grain) & m.reference.eq(ref)].groupby("horizon").apply(
                lambda g: pd.Series({"skill": np.average(g.skill, weights=g.n), "n": g.n.sum(),
                                     "ok": g.interpretable.all()}), include_groups=False).reset_index()
            x = np.arange(len(d)) + off
            ax.bar(x, 100 * d.skill, 0.4, color=COLOURS[ref], label=f"vs {ref}",
                   hatch=None)
            for xi, ok in zip(x, d.ok):
                if not ok:
                    ax.text(xi, 0, "n<12", ha="center", va="bottom", fontsize=7, color="#52514e")
        ax.axhline(0, color="#0b0b0b", lw=0.8)
        ax.set_xticks(np.arange(len(d)), d.horizon.astype(str))
        ax.set_title(f"{grain} milk"); ax.set_xlabel("horizon")
    axes[0][0].set_ylabel("skill % (MAE reduction; >0 = hybrid better)")
    axes[0][0].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / "h1_skill_by_horizon.png", dpi=160); plt.close(fig)

    # Fig 2: WAPE by horizon for every model on the same series (lower is better).
    mm = milk(metrics)
    fig, axes = plt.subplots(1, len(grains), figsize=(5 * len(grains), 4.6), sharey=False, squeeze=False)
    for ax, grain in zip(axes[0], grains):
        sub = mm[mm.grain.eq(grain)]
        hs = sorted(sub.horizon.unique())
        for model in sub.model.unique():
            d = sub[sub.model.eq(model)].groupby("horizon").apply(
                lambda g: (g.wape_pct * g.n).sum() / g.n.sum(), include_groups=False).dropna()
            if d.empty:
                continue
            key = "hybrid" if model == hybrid else model
            ax.plot(d.index, d.values, marker="o", label=key, color=COLOURS.get(key))
        ax.set_xticks(hs, [str(h) for h in hs])
        ax.set_title(f"{grain} milk WAPE %"); ax.set_xlabel("horizon")
    handles, labels = {}, None
    for ax in axes[0]:
        for h, l in zip(*ax.get_legend_handles_labels()):
            handles.setdefault(l, h)
    fig.legend(handles.values(), handles.keys(), loc="lower center", ncol=len(handles), fontsize=8)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(out / "h2_wape_by_horizon.png", dpi=160); plt.close(fig)

    # Fig 3: WAPE by forecast year, monthly milk, all models (does it win consistently?).
    by_year_path = run / "by_origin_year.csv"
    if by_year_path.exists():
        y = pd.read_csv(by_year_path)
        y = y[y.series.eq("herd_milk") & y.grain.eq("monthly")]
        fig, ax = plt.subplots(figsize=(7, 4))
        for model in (hybrid, *REFS):
            d = y[y.model.eq(model)].groupby("origin_year").apply(
                lambda g: (g.wape_pct * g.n).sum() / g.n.sum(), include_groups=False)
            key = "hybrid" if model == hybrid else model
            ax.plot(d.index, d.values, marker="o", label=key, color=COLOURS[key])
        ax.set_xlabel("forecast year"); ax.set_ylabel("monthly milk WAPE % (lower is better)")
        ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(out / "h3_wape_by_year.png", dpi=160); plt.close(fig)

    # Fig 4: interval coverage vs nominal for the hybrid.
    c = milk(metrics[metrics.model.eq(hybrid)])
    fig, ax = plt.subplots(figsize=(7, 4))
    for col, nominal in (("coverage80", 0.8), ("coverage90", 0.9)):
        d = c.groupby(["grain", "horizon"]).apply(lambda g: g[col].mean(), include_groups=False)
        ax.plot([f"{a} h{b}" for a, b in d.index], d.values, marker="o", label=col)
        ax.axhline(nominal, ls="--", lw=0.8, color="#52514e")
    ax.set_ylim(0, 1); ax.set_ylabel("observed coverage"); ax.legend(fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right", fontsize=7)
    fig.tight_layout(); fig.savefig(out / "h4_interval_coverage.png", dpi=160); plt.close(fig)
    print("Wrote", *sorted(p.name for p in out.glob("h*.png")), "to", out)


if __name__ == "__main__":
    main(sys.argv[1])
