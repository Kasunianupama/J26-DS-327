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
| calf → heifer, heifer conception, dry-cow conception | `core.state_transition_month` (complete months) | `day_cell` animal-days, same months |
| death / cull / sale by state | `state_transition_month` exit rows; fallback: `day_panel` totals ÷ herd-days, same rate for every state | as above |
| cow conception by parity × DIM band | `core.lactation.conception_date` (known only if ≥ 35 days before origin) | open milking days from lactation intervals |
| open-cow dry-off by DIM band | `core.lactation.dry_off_date` without conception | same |
| pregnant-cow dry-off | histogram of (dry-off − conception) | — (hazard from distribution) |
| calving | histogram of `core.calf.gestation_d` | — |
| real abortion | `day_panel.real_abortions` | pregnant heifer + dry days (`day_cell`) + pregnant milking days |
| births per calving | `day_panel.births / calvings` | — |
| inseminations (event only) | `day_panel.ais` | open animal-days |
| external entries | `day_panel.external_entries` per day; state from entry rows in transitions, else heifer_open | — |

Bulls and unknown-state animals are only reduced by exits. Every fallback is recorded
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
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 24
```

Output: herd-level aggregates only, printed and written to `logs/pfoi/` (gitignored).
