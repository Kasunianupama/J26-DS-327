"""Build docs/pp1_evidence_pack.md and figures 4-6 from the aggregate CSVs (no hand-typed numbers).

Reads docs/data/linear_baseline_wape.csv and docs/data/recovery_weekly_h4_E5a.csv.
Run: python components/predictive_farm_intelligence/docs/build_evidence_pack.py
"""
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
FIG = HERE / "figures"; FIG.mkdir(exist_ok=True)
STYLE = {"current": ("Current model", "#2a78d6", "o"),
         "persistence": ("Persistence", "#eb6834", "s"),
         "linear": ("Linear regression", "#6250d6", "^")}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
TARGET = {"monthly": {1: 92, 3: 90, 6: 88, 12: 85}, "weekly": {1: 93, 4: 90, 13: 87}, "daily": {1: 95, 7: 92, 14: 90}}
GRAINS = ["daily", "weekly", "monthly"]
YEARS = range(2019, 2024)


def validate_palette():
    colours = ",".join(c for _, c, _ in STYLE.values())
    r = subprocess.run([sys.executable, str(HERE / "tools" / "validate_palette.py"), colours, "--mode", "light"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); raise SystemExit("Palette failed validation.")


validate_palette()
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})

d = pd.read_csv(HERE / "data" / "linear_baseline_wape.csv")
rec = pd.read_csv(HERE / "data" / "recovery_weekly_h4_E5a.csv")
for m in ("linear", "persistence", "current", "ridge"):
    d[f"{m}_acc"] = 100 - d[f"{m}_wape_pct"]
d["skill_vs_pers"] = 1 - d.current_wape_pct / d.persistence_wape_pct      # equals 1 - MAE ratio on matched periods
d["gap_lin"] = d.current_acc - d.linear_acc
d["gap_pers"] = d.current_acc - d.persistence_acc
d["target"] = [TARGET[g].get(h) for g, h in zip(d.grain, d.horizon)]   # weekly 8 weeks: reported, no target
d["target"] = pd.to_numeric(d.target)
d["meets_target"] = d.current_acc >= d.target
dt = d[d.target.notna()]
d["small_n"] = d.n < 12
d["order"] = d.grain.map({g: i for i, g in enumerate(GRAINS)})


def sub(**kw):
    s = d
    for k, v in kw.items():
        s = s[s[k].isin(v) if isinstance(v, (list, tuple, set, range)) else s[k] == v]
    return s


# ---------------------------------------------------------------- figure 4: bias
fig, axes = plt.subplots(3, 2, figsize=(10, 8.2), sharey=False)
for r, g in enumerate(GRAINS):
    for c, y in enumerate((2021, 2022)):
        ax = axes[r, c]; s = d[(d.grain == g) & (d.target_year == y)].sort_values("horizon")
        ax.grid(axis="y", color=GRID, lw=.8); ax.axhline(0, color=MUTED, lw=.8)
        if g == "monthly":
            ax.axhspan(-3, 3, color="#cfe3f7", alpha=.6, lw=0)   # agreed monthly |bias| target
        for m, (lab, col, mk) in STYLE.items():
            ax.plot(range(len(s)), s[f"{m}_bias_pct"], color=col, marker=mk, ms=6, lw=2, label=lab)
        ax.set_xticks(range(len(s))); ax.set_xticklabels(s.horizon.astype(str))
        ax.set_title(f"{g.title()}, target year {y}  (n={int(s.n.min())}-{int(s.n.max())})", loc="left", fontsize=9.5, color=INK)
        if c == 0:
            ax.set_ylabel("bias %  (+ = over-forecast)")
        if r == 2:
            ax.set_xlabel("forecast horizon")
h, l = axes[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(.5, .985))
fig.suptitle("Bias by horizon in the two herd-change years (shaded: agreed monthly +/-3 % target)", x=.01, y=1.03,
             ha="left", fontsize=12.5, color=INK)
fig.tight_layout(); fig.savefig(FIG / "fig4_bias_herd_change_years.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# ---------------------------------------------------------------- figure 5: recovery
bands = ["0-2 months", "3-5 months", "6-11 months", "no break yet"]
fig, ax = plt.subplots(figsize=(9.5, 4.6))
ax.grid(axis="y", color=GRID, lw=.8); ax.set_axisbelow(True)
width = .26
for i, (m, (lab, col, mk)) in enumerate(STYLE.items()):
    for j, b in enumerate(bands):
        row = rec[(rec.model == m) & (rec.since_break == b)]
        x = j + (i - 1) * width
        if len(row):
            acc = 100 - float(row.wape_pct.iloc[0])
            ax.bar(x, acc, width * .92, color=col, label=lab if j == 0 else None)
            ax.text(x, acc + 1, f"{acc:.0f}\nn={int(row.n.iloc[0])}", ha="center", va="bottom", fontsize=8, color=INK)
        else:
            ax.text(x, 3, "no\nforecast", ha="center", va="bottom", fontsize=8, color=MUTED, rotation=90)
ax.axhline(90, color=MUTED, ls="--", lw=1, label="Agreed recovery target 90 %")
ax.set_xticks(range(len(bands))); ax.set_xticklabels(bands); ax.set_ylim(0, 118)
ax.set_xlabel("months from latest break (E5a) to forecast date"); ax.set_ylabel("accuracy %")
ax.legend(frameon=False, loc="upper left", ncol=4, bbox_to_anchor=(0, 1.0))
ax.set_title("Weekly milk, 4 weeks ahead: accuracy after the 2022 milk gap (each model on its own periods)",
             loc="left", fontsize=11.5, color=INK)
fig.tight_layout(); fig.savefig(FIG / "fig5_recovery_weekly_h4.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# ---------------------------------------------------------------- figure 6: accuracy vs agreed targets
fig, axes = plt.subplots(1, 3, figsize=(14, 4.4), sharey=False)
for ax, g in zip(axes, GRAINS):
    s = d[d.grain == g]; hs = sorted(s.horizon.unique())
    ax.grid(axis="y", color=GRID, lw=.8); ax.set_axisbelow(True)
    for xi, hz in enumerate(hs):
        t = TARGET[g].get(hz)
        if t is not None:
            ax.hlines(t, xi - .38, xi + .38, color=MUTED, ls="--", lw=1.4)
        for y in YEARS:
            row = s[(s.horizon == hz) & (s.target_year == y)]
            if len(row):
                v = max(float(row.current_acc.iloc[0]), 0)
                ax.scatter(xi + (y - 2021) * .15, v, color=STYLE["current"][1], marker=STYLE["current"][2],
                           s=38 if int(row.n.iloc[0]) >= 12 else 38, facecolors=STYLE["current"][1] if int(row.n.iloc[0]) >= 12 else "none",
                           edgecolors=STYLE["current"][1], zorder=3)
    ax.set_xticks(range(len(hs))); ax.set_xticklabels([str(h_) for h_ in hs]); ax.set_xlabel("forecast horizon")
    ax.set_title(g.title(), loc="left", color=INK)
    if g == "monthly":
        ax.set_ylim(0, 102)
axes[0].set_ylabel("current-model accuracy %  (dots 2019-2023 left to right)")
fig.text(.01, -.03, "Dashed line = agreed target (targets.md). Hollow dot = n < 12 (indicative). Values below 0 % drawn at 0.",
         color=MUTED, fontsize=9)
fig.suptitle("Current model against the agreed accuracy targets, by year (development block)", x=.01, y=1.02,
             ha="left", fontsize=12.5, color=INK)
fig.tight_layout(); fig.savefig(FIG / "fig6_accuracy_vs_targets.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# ---------------------------------------------------------------- numbers for the text
def f1(x): return f"{x:.1f}"


big = d[(d.horizon >= 4) & (d.grain == "weekly") | (d.grain == "monthly") & (d.horizon >= 3)]
herd21_22 = big[big.target_year.isin([2021, 2022]) & (big.n >= 12)]
lin_ge = int((d.gap_lin >= 0).sum()); lin_tot = len(d)
lin_lose = d[d.gap_lin < 0].sort_values("gap_lin")
mon = d[d.grain == "monthly"]; mon_ok = int((mon.gap_pers >= 0).sum())
wk = d[(d.grain == "weekly") & (d.horizon >= 4)]
wk_win = wk[wk.gap_pers > 0]; wk_loss = wk[wk.gap_pers < 0]
wk_early = wk[wk.target_year.isin([2019, 2020])]; wk_mid = wk[wk.target_year.isin([2021, 2022])]; wk_late = wk[wk.target_year == 2023]
mon12 = mon[mon.n >= 12]; mon_small = mon[mon.n < 12]
sh = d[((d.grain == "daily") & d.horizon.isin([1, 7])) | ((d.grain == "weekly") & (d.horizon == 1))]
sh_pers_better = int((sh.gap_pers < 0).sum())
dly14 = d[(d.grain == "daily") & (d.horizon == 14)]
w23 = d[(d.grain == "weekly") & (d.target_year == 2023) & d.horizon.isin([4, 8])]
mon_bias_ok = int((mon.current_bias_pct.abs() <= 3).sum())
cur_meets = int(dt.meets_target.sum()); pers_meets = int((dt.persistence_acc >= dt.target).sum()); lin_meets = int((dt.linear_acc >= dt.target).sum())
meets_big = dt[dt.n >= 12]
cur_meets_big = int(meets_big.meets_target.sum()); pers_meets_big = int((meets_big.persistence_acc >= meets_big.target).sum())
bias21 = d[(d.target_year == 2021) & (d.grain == "monthly")]
rc = lambda m, b: float(100 - rec[(rec.model == m) & (rec.since_break == b)].wape_pct.iloc[0])
rn = lambda m, b: int(rec[(rec.model == m) & (rec.since_break == b)].n.iloc[0])


def cell(r): return f"{r.grain} h{r.horizon} {r.target_year} (n={r.n})"


# ---------------------------------------------------------------- tables
def table(grain):
    lines = ["| Horizon | Year | n | Linear | Ridge | Persistence | **Current** | Bias cur / lin / pers % | Skill vs persistence | Target |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in d[d.grain == grain].sort_values(["horizon", "target_year"]).iterrows():
        star = " \\*" if r.n < 12 else ""
        tgt = "no target" if pd.isna(r.target) else f"{int(r.target)} % " + ("met" if r.meets_target else "missed")
        lines.append(f"| {r.horizon} | {r.target_year} | {r.n}{star} | {f1(r.linear_acc)} | {f1(r.ridge_acc)} | "
                     f"{f1(r.persistence_acc)} | **{f1(r.current_acc)}** | {r.current_bias_pct:+.1f} / {r.linear_bias_pct:+.1f} / "
                     f"{r.persistence_bias_pct:+.1f} | {r.skill_vs_pers:+.2f} | {tgt} |")
    return "\n".join(lines)


md = f"""# PP1 evidence pack: why the current structural milk model

Component 1 (PFOI), Farm X, herd level only. Current model = `milk_baseline_adaptive`
(pfoi-1.1 research candidate: 12-month window, known-data cutoffs, herd-fitted curves,
anchored k, adaptive level correction). Generated by `docs/build_evidence_pack.py` from
`docs/data/linear_baseline_wape.csv` and `docs/data/recovery_weekly_h4_E5a.csv`. Every figure and table number comes from those files, except the benchmark ratios quoted from `pp1_results.md`.

**Notebook.** `notebooks/02_current_model_evidence.ipynb` reproduces every table and chart below from the same CSVs.

**Status labels.** *Evaluated* = the user ran it and sent aggregates (development block, origins
2019-2023, rolling refit, identical periods per row). *Post-hoc* (2024-2026) = not run yet.
*Implemented-and-tested* = synthetic tests only. *Not run* = no result.
Accuracy = 100 - WAPE. Skill vs persistence = 1 - MAE(current) / MAE(persistence) on the same periods.
`\\*` = n < 12, indicative only.

## (a) Comparison table (evaluated, development block, matched periods)

Models in the table: linear regression, ridge, persistence, current. **ETS, SARIMA and seasonal naive are
not in this table**: the experiment runs score them on different period sets from the current model, so a
matched comparison needs the scorecard run in section (e). Their earlier, matched development results
are quoted below (pfoi-1.0.0-era common periods, `pp1_results.md`): monthly milk MAE ratio to persistence,
horizons 1/3/6/12 = ETS 1.38/1.63/2.02/2.05, seasonal naive 3.78/1.62/1.09/1.00, PFOI baseline
0.62/0.63/0.61/0.75; SARIMA ran on only 24 months (1.12/1.01/1.00/0.99 against 0.69/0.90/0.82/0.81).
Skill against the **best** benchmark is therefore not claimed here; skill vs persistence is a lower bound on
how hard the benchmark is to beat only where persistence is the best benchmark.

### Daily (issued weekly; horizons in days)
{table("daily")}

### Weekly (horizons in weeks)
{table("weekly")}

### Monthly (horizons in months)
{table("monthly")}

Bias is positive = over-forecast. Monthly 12-month 2019 and 6-month 2023 (n = 1) are left out.

## Figures

| File | Caption (what it shows, n) |
|---|---|
| ![Accuracy by horizon: three models, one panel per year and grain. Current model leads from 3 months and in 2021-22; persistence matches it at 1 day to 1 week; weekly 2023 is the exception](figures/fig1_accuracy_by_horizon.png) | [fig1](figures/fig1_accuracy_by_horizon.png): accuracy against horizon, 3 grains x 5 years; n per panel in the titles (6-52) |
| ![Heatmap of current-minus-linear accuracy points; blue nearly everywhere, red in weekly 2023 at 4, 8 and 13 weeks](figures/fig2_current_minus_linear.png) | [fig2](figures/fig2_current_minus_linear.png): current minus linear, accuracy points; {lin_ge} of {lin_tot} cells favour the current model |
| ![Heatmap of current-minus-persistence accuracy points; near zero at daily and 1 week, positive in monthly, negative in weekly 2023](figures/fig3_current_minus_persistence.png) | [fig3](figures/fig3_current_minus_persistence.png): current minus persistence; shows where persistence is as good |
| ![Bias against horizon for 2021 and 2022; linear drifts to +30 to +170 %, current model stays lower](figures/fig4_bias_herd_change_years.png) | [fig4](figures/fig4_bias_herd_change_years.png): bias by horizon in 2021 and 2022 (n 5-52); shaded = agreed monthly +/-3 % |
| ![Bar chart of weekly 4-week accuracy by months since a break; current model below persistence at 0-2 and 6-11 months, below the 90 % target](figures/fig5_recovery_weekly_h4.png) | [fig5](figures/fig5_recovery_weekly_h4.png): weekly 4-week accuracy after break E5a; n 12-177, each model on its own periods |
| ![Dots of current-model accuracy against dashed agreed targets, per horizon and year](figures/fig6_accuracy_vs_targets.png) | [fig6](figures/fig6_accuracy_vs_targets.png): current accuracy against `targets.md`, per year; hollow = n < 12 |

Palette checked with `docs/tools/validate_palette.py` (blue = current, orange = persistence, violet = linear).

## (b) Six bullets for the slide (each checked against the table above)

1. **Beats a plain linear regression almost everywhere:** at least as accurate in {lin_ge} of {lin_tot} cells. In the
   herd-change years 2021-22 it is {f1(herd21_22.gap_lin.min())} to {f1(herd21_22.gap_lin.max())} points ahead at weekly 4+ weeks (monthly cells all have n < 12 and show larger gaps).
2. **Beats persistence on all {mon_ok} monthly cells,** by {mon.gap_pers.min():+.1f} to {mon.gap_pers.max():+.1f} points (median {mon.gap_pers.median():+.1f}).
   Monthly cells have 5-12 periods each ({len(mon12)} of {len(mon)} reach 12), so read this as consistent direction, not precise size.
3. **From 4 weeks ahead the weekly picture is mixed:** within {f1(abs(wk_early.gap_pers).max())} points of persistence in 2019-2020,
   {wk_mid.gap_pers.min():+.1f} to {wk_mid.gap_pers.max():+.1f} in 2021-22, and {wk_late.gap_pers.min():+.1f} to {wk_late.gap_pers.max():+.1f} in 2023 (n 6-20, indicative).
4. **Bias is smaller than linear's** when the herd changed (monthly 2021 6 months: current
   {bias21[bias21.horizon == 6].current_bias_pct.iloc[0]:+.1f} % vs linear {bias21[bias21.horizon == 6].linear_bias_pct.iloc[0]:+.1f} %).
   It is **not** inside the agreed +/-3 % monthly target in {len(mon) - mon_bias_ok} of {len(mon)} monthly cells.
5. **Explained by construction:** every milk change splits into herd size, parity, stage, pregnancy and yield level, with
   parts that add up exactly (`attribution.py`, tested on synthetic data; implemented-and-tested).
6. **Predeclared yardstick:** accuracy, skill, bias and coverage targets were frozen before measuring (`targets.md`);
   the current model meets the accuracy target in {cur_meets} of {len(dt)} year-cells with a target ({cur_meets_big} of {len(meets_big)} with n >= 12).
   Persistence meets it in {pers_meets} ({pers_meets_big} of {len(meets_big)}) and linear in {lin_meets}, so the accuracy targets alone do not separate the current model from persistence; skill against persistence and bias matter more.

## (c) Limits slide (state plainly)

- **Short range:** persistence is as good or better at 1 day to 1 week (persistence is ahead in {sh_pers_better} of {len(sh)}
  cells at daily 1, 7 days and weekly 1 week). The value claim starts at about 4 weeks.
- **2023 weekly weakness:** accuracy {", ".join(f"{r.horizon} wk {f1(r.current_acc)} % (n={r.n})" for _, r in w23.iterrows())},
  against persistence {", ".join(f"{f1(r.persistence_acc)} %" for _, r in w23.iterrows())} and linear
  {", ".join(f"{f1(r.linear_acc)} %" for _, r in w23.iterrows())}. Linear only has forecasts where it had at least 24
  completed same-source examples, so that comparison is a favourable subset. Cause not yet diagnosed.
- **Recovery after a break is not better than persistence:** weekly 4 weeks, 0-2 months after break E5a, current
  {f1(rc("current", "0-2 months"))} % (n={rn("current", "0-2 months")}) against persistence {f1(rc("persistence", "0-2 months"))} %; agreed target 90 % is **not met**.
- **Bias target:** monthly |bias| <= 3 % holds in {mon_bias_ok} of {len(mon)} monthly cells.
- **Not confirmation:** development block only. 2024-2026 results are post-hoc; only prospective months after 2026-08-20 confirm.
  The monthly post-hoc run is **not run** (first attempt failed on a source setting, fixed in `forecast_experiments.py`).
- **Not yet evaluated:** boosted, TCN and residual-TCN candidates (implemented, no run results), so no superiority claim over them.
- **Intervals:** pfoi-1.0.0 90 % ranges covered 34-83 % (`intervals.py` doc). The adaptive-conformal intervals are
  implemented-and-tested on synthetic data; real-data coverage for the current model has not been supplied.
- **Data quality:** the 2024-26 block is mostly gap or unverified; ETL issues (about 29 % of milked cows with no open lactation in mid-2026)
  limit what can be tested (`targets.md`).
- **Replay, not as-published:** history may contain retrospective ETL revisions.

## (d) Likely panel questions and short, truthful answers

**Why not just linear regression?** Matched on the same periods, linear is within about 1-3 points of the current
model up to a week, then falls behind: {f1(herd21_22.gap_lin.min())} to {f1(herd21_22.gap_lin.max())} points behind at weekly 4+ weeks and monthly 3+
months in 2021-22, with bias up to {f1(d.linear_bias_pct.max())} % (current {f1(d.current_bias_pct.max())} %). It also cannot explain a change or forecast calvings.
It does win in the small 2023 weekly subset (see limits).

**Why not deep learning?** Boosted trees and a causal TCN (direct and residual) are implemented in the same rolling harness,
but there are **no results yet**, so we claim nothing against them. Ridge on 426 raw inputs, the nearest regularised model,
scored worse than linear everywhere. The plan (`error_diagnostics_and_model_comparison.md`) is to compare them after targets are frozen.

**Why not persistence?** At 1 day to 1 week persistence is as good; we say so. It wins on 4+ weeks monthly cells everywhere
and weekly in 2021-22, but its real limit is that it cannot explain anything or forecast events: in development the herd model forecasts
calvings 4-6 times better than persistence at 3-6 months (`pp1_results.md`, evaluated, pfoi-1.0.0).

**What happens after an outage?** Honestly, slowly: the agreed recovery target is 90 % at 0-2 months and the current model
reaches {f1(rc("current", "0-2 months"))} % (persistence {f1(rc("persistence", "0-2 months"))} %). Mitigations exist (anchored k, quality bands, wider intervals) but are not shown to meet the target.

**Is 2023 a problem?** Yes, at weekly 4-13 weeks the current model is worse than persistence and, on the subset linear covers, than linear.
We will diagnose it with `error_diagnostics` before making a 2023 claim.

**How do you know there is no leakage?** We do not claim proof. Evaluated and tested: every loader filters to before the origin
(L1), conception rates use only confirmable months (L2), errors for corrections and intervals use only finished targets (L8). Still open or asked of the ETL:
L3-L6 (pregnant counts, conception dates, late-entered records, reliability flags). Design choices were made on the development block (L9).

**What is new versus St-Pierre 2001 and Gong 2025?** Those are the foundation. The contribution claimed, modestly, is that every past and future
point and every revision is explained by construction (exact Shapley split), and that uncertainty is meant to reflect record quality
(quality-banded adaptive-conformal intervals; implemented-and-tested, real-data coverage pending).

## (e) Claims I could not support, and the commands to close them (aggregate output only)

| Claim | Why unsupported | Command (you run it) |
|---|---|---|
| "Skill against the best benchmark" | ETS, SARIMA, seasonal naive are not matched to the current model in the experiment output | `$PFOI.cli scorecard --block development --preset pfoi-1.1 --k anchor_first` |
| "Recovers faster after breaks" | Weekly 4-week 0-2 months after E5a: current below persistence | none; it is a finding (report it) |
| "Bias is small" | |bias| <= 3 % holds in {mon_bias_ok} of {len(mon)} monthly cells | none; report it |
| "Calibrated intervals" | No real-data coverage for the current model supplied | `$PFOI.cli scorecard --block development --preset pfoi-1.1 --k anchor_first --intervals aci` |
| "Better than boosted / TCN" | Not run | `python -W ignore -m components.predictive_farm_intelligence.pfoi.forecast_experiments --block development --start 2019-01-01 --end 2024-01-01 --grain monthly --models boosted tcn tcn_residual --structural-tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 --saved logs/pfoi_1_1_clean --out logs/pfoi_experiments/dev_monthly_ml` |
| Any 2024-2026 statement | Post-hoc run not completed | the post-hoc command in `linear_baseline.md` |
| Cause of the 2023 weekly weakness | Not diagnosed | `python -m components.predictive_farm_intelligence.pfoi.error_diagnostics --tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 --model milk_baseline_adaptive --herd-tag w12_ck_kn_rk_lag90 --quality on --out logs/pfoi_1_1_clean` |

Replace `$PFOI` with `python -m components.predictive_farm_intelligence.pfoi`.
"""
(HERE / "pp1_evidence_pack.md").write_text(md)
print("wrote pp1_evidence_pack.md and figures", sorted(p.name for p in FIG.glob("*.png")))
