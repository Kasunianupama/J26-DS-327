# Herd engine (Step 3)

Code: `pfoi/` in this folder. Tests: `tests/` (synthetic herd, no database).

## Modules

| Module | Role |
|---|---|
| `config.py` | DB settings from the root `.env` (`APP_DB_HOST/PORT/NAME`, `APP_DB_PFOI_USER/PASSWORD`, role `farmx_model`); `EngineConfig` modelling choices |
| `data.py` | Read-only, aggregate-only SQL loaders + leakage guard (`check_before`) |
| `origin_state.py` | Starting herd: `day_cell` counts on origin − 1, shaped by DIM/gestation histograms |
| `rates.py` | Daily hazards from the trailing window, beta-binomial shrinkage |
| `herd_engine.py` | Daily projection (pure function of starting herd + rates) |
| `periods.py`, `backtest_herd.py`, `cli.py` | Weekly/monthly horizons, rolling-origin backtest, commands |

## Where each rate comes from (window = [origin − W months, origin))

| Flow | Numerator | Exposure |
|---|---|---|
| calf → heifer (female calves), calf → bull (male calves), heifer conception, dry-cow conception | `core.state_transition_month` (complete months) | `day_cell` animal-days, same months |
| death / cull / sale by state | `state_transition_month` exit rows; fallback: `day_panel` totals ÷ herd-days, same rate for every state | as above |
| cow conception by parity × DIM band | `core.lactation.conception_date` (known only if ≥ 35 days before origin) | open milking days from lactation intervals |
| open-cow dry-off by DIM band | `core.lactation.dry_off_date` without conception | same |
| pregnant-cow dry-off | histogram of (dry-off − conception) | — (hazard from distribution) |
| calving | histogram of `core.calf.gestation_d` | — |
| real abortion | `day_panel.real_abortions` | pregnant heifer + dry days (`day_cell`) + pregnant milking days |
| births per calving | `day_panel.births / calvings` | — |
| inseminations (event only) | `day_panel.ais` | open animal-days |
| external entries | median monthly `day_panel.external_entries` per day (one-off restocking is not projected); state from entry rows in transitions, else heifer_open | — |
| extra pregnancy loss (heifers, dry cows) | `state_transition_month` pregnant → open, minus the abortion rate | pregnant animal-days |
| unconfirmed recent service (milking cows) | pregnant with probability conceptions ÷ inseminations in the window | — |

Bulls and unknown-state animals are only reduced by exits.

**Exit calibration.** The transition table counts moves from each animal's state at the
start of a month, so animals that arrive and leave within one month (mostly newborn
calves) are missing from it. Each exit type is matched to `day_panel` over the same
months: a death shortfall becomes early calf deaths at birth (counted as births and
deaths, never added to the herd); a cull or sale shortfall rescales that exit type in
every state (factor limited to 1/3–3). The factors are reported as a note. Every fallback is recorded
in `RateSet.notes` and counted per backtest run.

## Leakage

* Every loader filters to dates before the origin and returns `max_date`; the guard
  raises `LeakageError` otherwise (tested for every query).
* Conception-based statistics stop at origin − 35 days (`pregnancy_check_lag_days`).
* Heifer gestation shape uses days since the last insemination (no outcome, no later
  calving). Cow gestation shape uses `core.lactation.conception_date`.
* Open question for the user check: whether the ETL back-dates `conception_date`
  and the pregnant states in `day_cell` from later calvings. If so, the known-pregnancy
  exception carries some hindsight, and a sensitivity run with uniform gestation
  shapes should be added to bound it.
* The backtest refuses origins or targets in the final test block (2024-01 onward).

## Commands

```bash
python -m components.predictive_farm_intelligence.pfoi.cli herd-rates --origin 2020-01-01
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 12
```

Output: herd-level aggregates only, printed and written to `logs/pfoi/` (gitignored).

## Known limitations (Step 3)

* Calves are split by sex. Measured totals (calf-days, calf exits, calf -> heifer and
  calf -> bull moves) are kept exactly; the female/male division uses the sex ratio of
  animal-days and exits under one year (`core.animal`) and of live births (`core.calf`).
  Constant daily hazards within each sex are an approximation (male calves leave mostly
  in the first weeks).
* Inseminations are an event count only and are over-forecast (ratio 1.4–2.5 vs
  persistence).

## Backtest models

* `herd_engine`: the structural projection (explainable by construction).
* `herd_engine_corrected`: the same forecast minus the engine's own mean error at that
  grain, series and horizon, using only errors whose target period had ended before the
  origin (origins in the previous 2 years, at least 6 errors; otherwise unchanged).
* `persistence`: last known value (stocks) or last period's daily rate (events).
* Diagnostic series `calvings_heifer` (monthly only): first calvings, scored against
  `core.state_transition_month` heifer_pregnant → milking.

## Development decisions (2026-10-18)

Window comparison on the development block (monthly origins 2017-01 – 2023-12), mean
MAE ratio vs persistence over milking, total herd, calvings and real abortions at
horizons 1/3/6/12 months:

| Window | Mean ratio |
|---|---|
| 12 months | **0.82** |
| 24 months | 0.87 |
| 36 months | 0.94 |
| expanding | 1.04 |

The 12-month window is the default: it is best for milking, calvings and abortions,
consistent with the persistent rate shifts in the data (e.g. abortions in 2023–26).
24 months is better for total herd at 3–6 months. The bias-corrected engine is reported
as a variant: it helps milking and total herd at long horizons and calvings at short
horizons, but hurts abortions, so it is not used for that series.
