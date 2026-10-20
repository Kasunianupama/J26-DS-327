# Explanation (Step 5)

Code: `pfoi/attribution.py`. Tests: `tests/test_attribution.py` (synthetic).

## Milk: Shapley split of month-on-month change (litres/day)

The model's herd milk per day is
`k × N × Σ_p π_p Σ_d σ_{d|p} Σ_b ρ_{b|p,d} Y[p, d, b]`
(N milking cows, π parity mix, σ lactation-stage mix within parity, ρ pregnancy mix
within parity × stage, Y curve yield in 10-day DIM bins, k yield level). Five factors:

| Factor | Meaning |
|---|---|
| herd_size | more or fewer milking cows |
| parity_mix | share of first-lactation vs older cows |
| stage_mix | share of cows early vs late in lactation |
| pregnancy_mix | share of cows ≥ 150 / ≥ 200 days pregnant (yield factor) |
| yield_level | change in k (per-cow level known at the start of the month) |
| residual (past only) | actual change − model change: heat, health, feed, recording |

Each factor's share is its Shapley value (all 2⁵ switch combinations); the five sum
exactly to the model change, and with the residual exactly to the actual change (tests).
Past months use milking cow-days from `core.lactation` and k_m = actual ÷ curve milk of
the month before; month pairs with a missing month or a source change are skipped.
Forecast months use the engine's projected mix and the anchored k, so yield_level is 0.
THI and mastitis are not factors yet (deferred to the H2 layer; they sit in the residual).

## Herd flows

The engine records every flow by state (births, calf → heifer/bull, conception, abortion,
extra pregnancy loss, calving, dry-off, deaths, culls, sales, entries). Monthly sums of a
state's flows equal its stock change exactly (test). Calvings are split into
`determined` (pregnancies already in the herd at the origin) and `rate_driven` (from
projected conceptions); the engine is linear, so a run without new conceptions gives the
determined part exactly.

## Mastitis (low confidence)

Expected episodes = projected milking cow-days × episode rate, with two labelled rates:
the 12 months before the origin, and the 2016–2018 reference period (only when it ended
before the origin). The gap between them shows the recording gap since 2023.

## Generation

Projected mean animals by stage group (calves, heifers, cows) and generation, plus
descriptive fertility by generation within calving period (services per conception,
% aborted). Generation is confounded with time and parity: associations only.

## Commands

```bash
python -m components.predictive_farm_intelligence.pfoi.cli explain-milk --origin 2023-06-01
python -m components.predictive_farm_intelligence.pfoi.cli explain-herd --origin 2023-06-01
python -m components.predictive_farm_intelligence.pfoi.cli explain-generation --origin 2023-06-01
```

Rows are `(origin_date, target_period, grain, series, factor, contribution)`, the
`c1_output.attribution` contract for Step 6, saved to `logs/pfoi/` (gitignored).

## Data-source consistency (2026-10-19)

Milking cow-days rebuilt from `core.lactation` match `day_cell` within 0–1.3 % in
2016–2023 but are 2.5 % higher in 2024 and 8.6 % higher in 2025–2026 (check 3, extended).
Past-month attribution uses the rebuild throughout, so it is internally consistent. The
first forecast month is now compared with the engine's starting herd (from `day_cell`),
not with the rebuilt last month, which had shown a false herd-size step (−327 L/day at
origin 2026-08-01). Forecasts are unchanged by this.
