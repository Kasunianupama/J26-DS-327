# Frozen model and final test (Step 6)

**Model version `pfoi-1.0.0`, configuration hash `3cbd28787fcb`** (frozen 2026-10-19,
`pfoi/freeze.py`). Every choice below was made on the development block (origins
2017-01 – 2023-12) and is not changed after the final test.

| Part | Frozen choice | Decision record |
|---|---|---|
| Herd rates | 12-month trailing window, beta-binomial shrinkage, exit calibration, calf sex split | herd_engine.md |
| Lactation curve before 2020-09 | herd-fitted shape (Mandal et al. 2026 kept as sensitivity) | milk_model.md |
| Lactation curve from 2020-09 | Wood per parity on reliable cow-days before the origin | milk_model.md |
| Factors | pregnancy factor on, generation factor off | milk_model.md |
| Level | anchored k (last 14 scoreable days) | milk_model.md |
| Intervals | 5 % / 95 % of the model's own past relative errors | milk_model.md |

## Final test block (run once)

Origins 2024-01 – 2026-08 (monthly) and Mondays from 2024-01-01 (weekly), targets up to
the last data day (2026-08-20). The Oct 2024 – Aug 2025 milk gap is never scored. Each
run writes `logs/pfoi/final_test/<name>_pfoi-1.0.0_3cbd28787fcb.json`; a second run is refused
unless `--force` is given, and then the marker records `"rerun": true` and the previous
run time. Development errors are passed in so bias correction and intervals at test
origins use every error known before them.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --block test
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --block test
python -m components.predictive_farm_intelligence.pfoi.cli milk-report --block test
python -m components.predictive_farm_intelligence.pfoi.cli herd-report --block test
```

## Outlook and publication

`build-outlook --origin 2026-08-01` runs the frozen model and writes CSVs and the page
document (`logs/pfoi/outlook/`); with `--write` it replaces that origin's rows in
`c1_output.outlook`, `.attribution`, `.history` and `.run_document`
(DDL: `docs/sql/c1_output_tables.sql`; contract: `shared/schemas/pfoi_outlook.py`).
The page document also carries `moves`: animals moving between herd groups per period
(born → calves, calves → heifers or bulls, heifers → milking = first calvings, dry →
milking = calving again, milking → dry, arrivals into and deaths / culls / sales out of
each group, and pregnancies lost per group, where the animal stays). Recorded months come
from `core.state_transition_month` (pregnant → open counts as a pregnancy lost) plus births
from the day panel. Recorded days and weeks come from dated records (`daily_moves`:
calvings by lactation number, dry-offs, live births, exits by the group the animal was in
on its exit date, calves turning heifer or bull at one year); arrivals and pregnancies lost
are herd totals there (group `herd`), because their group is not dated. Forecast moves are
weekly and monthly, from the herd engine's flows.
The backend serves them when started with `PFOI_OUTLOOK_DB=on`
(`GET /api/v1/predictive/pfoi/run`, `/pfoi/outlook`, `/pfoi/attribution`); otherwise the
page shows its labelled demo run.
