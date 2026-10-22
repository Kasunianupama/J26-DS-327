# linear_baseline_wape.csv

Herd-level aggregate WAPE (%) for the development block, copied from the `matched` tables the
user supplied from `forecast_experiments` runs (rolling refit, identical target periods per row).
`n` = periods scored. Accuracy = 100 - WAPE. Omitted: monthly h12 2019 (n=1) and monthly h6 2023 (n=1).
No animal-level data. Regenerate figures with `python docs/make_linear_figures.py`.

## Update 2026-10-21
`linear_baseline_wape.csv` now has a `block` column (development) and bias and ridge columns, all
copied from the same `matched` tables (ridge and linear are scored on the same periods as the
current model). `recovery_weekly_h4_E5a.csv`: weekly 4-week recovery after break E5a plus the
no-break rows, each model on its own periods (not matched), from the `recovery` tables.
