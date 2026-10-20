# Layer 3: scenarios "like last time" (step D)

Code: `pfoi/scenarios.py`; tests: `tests/test_scenarios.py` (synthetic).

## 1. Episode library

Found in the herd-level daily aggregates (`driver_daily`). Labels describe the past, so
they use centred windows (days on both sides), which date the start correctly.

| Kind | Rule |
|---|---|
| heat | 14-day mean THI at least 3 above the seasonal norm (±15 days of the year) for 14+ days |
| drought | 90-day rainfall below the seasonal 20th percentile for 30+ days |
| abortion_surge | 28-day abortions at least 2× the median of the year before, and at least 5 |
| mastitis_surge | same rule for mastitis episodes (only where they were recorded) |
| herd contraction | the labelled breaks E1 and E3 (`episodes.BREAKS`) |

Runs closer than 30 days are merged. Only days with complete weather count for heat and
rain.

## 2. Response

For each episode, take the forecasts made at its onset (first forecast date in the 7 days
from the start) at every grain and horizon. Response = relative error (actual ÷ forecast
− 1) minus the model's median relative error at that horizon over the year before the
episode. So the model's usual bias is removed and only the episode's push remains.
Episodes without an onset forecast (for example during a data gap) are skipped. Per kind
and horizon: number of episodes, median, and range (10th–90th percentile, or min–max
with fewer than 5 episodes).

## 3. Scenario

Scenario forecast = baseline × (1 + median response), range = baseline × (1 + low) to
× (1 + high). Horizons between measured ones are interpolated; none beyond. Each comes
with a sentence like: *"In the 4 earlier heat spells, herd milk 4 weeks after the start
was 6 % below the forecast (range −9 % to −3 %). This is what happened before, not a
proven cause."*

## Commands

```bash
python -m components.predictive_farm_intelligence.pfoi.cli scenarios --tag herd_fitted_p1_g0_ka_w12_ck
python -m components.predictive_farm_intelligence.pfoi.cli scenarios --tag herd_fitted_p1_g0_ka_w12 --outlook logs/pfoi/outlook/outlook_202608.csv
```

Writes `scenario_episodes.csv`, `scenario_response_<tag>.csv` and, with `--outlook`,
`scenarios_<outlook>.csv`. The `_test` files of the tag are added when present (only the
frozen 1.0.0 tag has them), because the library describes the past and is not a scored
claim. Responses from 1–3 episodes are shown with their count and full range; treat them
as indicative.

## Limits

* One herd, few episodes per kind: associations, not causes.
* Episodes overlap (2022–24 contraction, abortion surge, identification decay); a
  response may mix them.
* Macroeconomic scenarios (feed prices, inflation) need the finance and feed files,
  which are not in the data yet.
