# T0 regime review — 2026-10-21

Status: saved-file tables reproduced; synthetic tests passed; boundary audit supplied
by the user. No recent detector hit supports the August 2020/2022 boundaries;
they remain descriptive. T1 began after this audit.

## Definition and interpretation

Primary cells use issuance source × target source. Shipment is split by issuance
before/from 2020-08-01. Shipment-issued forecasts scored against DelPro are separate.
Same-source DelPro targets are split before March 2024, March–April gap, and May 2024
onward. These dates describe the supplied timeline; they are not statistically
confirmed change points. Later results are post-hoc only.

Saved errors lack an explicit origin_source. The default report therefore says it
uses the documented August 2022 timeline. k_source is a calibration source and can
be borrowed after that date. --source-basis calibration reproduces Appendix F's
proxy definition, labelled as a sensitivity; it must not be interpreted as proof
that every such forecast was issued before the switch. An explicit origin_source
column takes priority; unknown sources remain other.

The shipment subdivision uses issuance date, so long-horizon counts differ from
older tables split by target date. The default development CLI excludes origins
outside 2017–2023 and target periods extending beyond 2023. No forecasting model,
weights, adoption choice or frozen configuration changed.

## Saved development evidence

Appendix F's calibration-proxy figures reproduced (MAE ratio to persistence):

| Cell | n | Ratio | Bias % |
|---|---:|---:|---:|
| DelPro calibration, daily h1 | 56 | 1.32 | +0.36 |
| Shipment calibration → DelPro, daily h1 | 3 | 4.37 | +67.28 |
| DelPro calibration, weekly h13 | 40 | 1.27 | −24.36 |
| Shipment calibration → DelPro, weekly h13 | 11 | 1.93 | +55.37 |
| DelPro calibration, monthly h3 | 6 | 1.10 | −23.31 |
| Shipment calibration → DelPro, monthly h3 | 2 | 4.36 | +68.72 |

With issuance-timeline cells instead, DelPro weekly h13 has n=50, ratio 1.54,
bias −6.68%. The actual pre-switch-issued cross-break weekly h13 cell has n=1,
ratio 0.54, bias +81.51%. This discrepancy is explained by borrowed calibration;
it is not a failed numeric reproduction. Small cells are not conclusive and
neighbouring origins overlap.

M9: common-period MAE and bias remain identical with borrowing on/off in all cells.
DelPro issuance cells contain the declined forecasts (daily 2–4, weekly 1–10,
monthly 0–2 per horizon). Do not reinterpret forecast-period counts as unique
origin counts or re-approve the original withholding rule from these counts alone.

M10, issuance-timeline cells: late-shipment weekly h4/h8/h13 MAE changes from
3761.11/5523.03/8356.03 to 3961.76/5680.07/8840.61 litres per week, worsening
5.3%/2.8%/5.8% (n=95/91/87). DelPro daily h1 improves 448.80→309.42 (n=59);
weekly h13 improves 9120.37→5532.38 (n=50). Cross-break daily h14 and weekly
h8/h13 each have n=1 and worsen; no general claim is justified. Monthly blend
rows do not exist by design and appear as unmatched, not failed forecasts.

No new user-supplied aggregate results were received in this session; these figures
were re-tabulated locally from the explicitly permitted saved herd-error files.
No database was opened and no real-data training was run.

## Commands executed from repository root

Synthetic verification: **38 passed**, 1,040 existing NumPy timedelta deprecation
warnings from test_blend.py, no failures. Exact hashes remain pfoi-1.0.0
`3cbd28787fcb` and pfoi-1.1.0 `2a865a0c2687`. The full T7 suite is not run yet.

Command (also checks the two exact frozen hashes):

```bash
.venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_regime_cells.py components/predictive_farm_intelligence/tests/test_source_k.py components/predictive_farm_intelligence/tests/test_blend.py components/predictive_farm_intelligence/tests/test_freeze.py -q -p no:cacheprovider
```

Primary source-pair report:

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.regimes logs/pfoi/milk_backtest_errors_{monthly,weekly}_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3.csv --model milk_baseline_adaptive
```

Appendix F reproduction:

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.regimes logs/pfoi/milk_backtest_errors_{monthly,weekly}_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3.csv --model milk_baseline_adaptive --source-basis calibration
```

M9 matched comparison (raw baseline for both runs):

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.regimes logs/pfoi/milk_backtest_errors_{monthly,weekly}_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6.csv --against logs/pfoi/milk_backtest_errors_{monthly,weekly}_herd_fitted_p1_g0_kfs_w24_ck_kn_rk_lag90_hl6.csv
```

M10 matched comparison:

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.regimes logs/pfoi/milk_backtest_errors_{monthly,weekly}_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3_bl.csv --model milk_baseline_adaptive --model-b milk_baseline_adaptive_blend
```

Also ran git status, git branch --show-current and git diff --check; inspected rules,
source, tests and documentation. No commit, push, staging or AGENTS.md changes.

## Required user-run check (not executed by the agent)

This command uses your existing local configuration to read daily herd aggregates,
then calls breaks.detect_breaks separately on strictly pre-origin data. It prints
only aggregate counts and days since the latest detected break. No files are written.

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.regime_boundary_check
```

Send back the seven-row table: origin, n_days, n_breaks,
days_since_latest, use. A missing detector hit is a valid result; do not move a
boundary to improve forecast scores. The three 2024 checks are descriptive only.
This validates detector evidence, not entry-time availability of retrospective
records. The source dates still rest on the user's Appendix D1 aggregates.

## Files

Created pfoi/regime_cells.py, pfoi/regime_boundary_check.py,
tests/test_regime_cells.py and this review. Modified pfoi/regimes.py and
appended the preregistered T0 protocol to docs/pp1_plan.md. Updated the existing
make_blend_figures.py caller and its panels to avoid silently dropping the new
shipment labels or pooling cross-break rows; no real charts were regenerated.
Historical charts/results remain historical until regenerated by the user.
cli.py, blend.py, command_sheet.md and frozen configurations were not edited here.

## User-supplied boundary audit

| Origin | n_days | n_breaks | Days since latest | Use |
|---|---:|---:|---:|---|
| 2020-08-01 | 1827 | 2 | 1549 | development |
| 2020-09-01 | 1858 | 2 | 1580 | development |
| 2022-08-01 | 2557 | 2 | 2279 | development |
| 2022-09-01 | 2588 | 2 | 2310 | development |
| 2024-03-01 | 3135 | 4 | 396 | post-hoc |
| 2024-05-01 | 3196 | 5 | 4 | post-hoc |
| 2024-06-01 | 3227 | 5 | 35 | post-hoc |

No recent detector support for the 2020/2022 calendar labels. A late-April 2024
hit appears in the post-hoc checks only. No boundary was moved or tuned.
