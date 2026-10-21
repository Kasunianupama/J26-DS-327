# Counterfactual Intervention Simulator

This component currently implements the simulator only. It loads the latest quality-filtered cow-day available to the `farmx_c13` read-only role, predicts next-day milk yield, then compares that baseline with independent one-feature model-input perturbations. The returned differences are observational model estimates, not causal effects or management recommendations.

## Farm X data and limits

The read-only repository uses:

- `core.daily_milk`: `animal_key`, `milk_date`, `yield_litres`, `dim`, `lactation_no`, quality flags, `milkings`, `dm_consumed`, `conc_consumed`, `avg_bcs`, `avg_weight`, and `avg_rectal_temp`.
- `core.animal`: `breed`, `birth_date`, and `n_calvings`.
- `core.weather_day`: `thi_mean` joined by date.
- `core.cow_day`: `days_pregnant` for the matching animal/date.
- `core.clinical_event` and `core.treatment_history`: counts in the 30 days up to the observation date.

The role also had visibility into `publish.publish_log`; its listed `model_input` relations were not granted/visible to `farmx_c13`, so the simulator does not query them. The inspected source has daily production and environmental features, but no accessible data dictionary documents units or intervention meaning for `dm_consumed` and `conc_consumed`. These are therefore unsupported for intervention prediction. THI and milkings/day are modeled as input perturbations only; the simulator does not model cooling equipment, labor, cost, welfare, feasibility, or a verified intervention mechanism. Source data and read-only SQL access were inspected during development; runtime queries use parameterized animal references and do not write to the database.

## Predictor

`FarmXMilkYieldPredictor` loads the local ignored artifact at `prediction/artifacts/farmx_milk_yield.joblib` (or `DIDT_MODEL_PATH`). The current artifact was serialized with scikit-learn 1.6.1, so the runtime uses that exact version; retrain and update the pin together when intentionally changing the model environment. It predicts next-calendar-day yield in litres/cow/day from the observed day using the fitted HistGradientBoosting pipeline with the same feature ordering and transformations for baseline and counterfactual input. The artifact records training ranges used to withhold estimates outside numeric training support. These empirical ranges are not biological limits.

Training is offline from approved actual Farm X history with a chronological holdout and persistence baseline. The API never trains a model. No mock prediction fallback exists: a missing/incompatible artifact or prediction failure returns unavailable estimates. The artifact is ignored by Git and must be trained in each intended environment. Historical forecast metrics do not validate counterfactual effects.

```bash
python -m pip install -r backend/requirements.txt
python -m components.member1_didt.prediction.train_model --output components/member1_didt/prediction/artifacts/farmx_milk_yield.joblib
```

## API

- `GET /api/v1/interventions/cows` returns up to 10,000 available approved animal references and their latest usable observation dates for selection.
- `GET /api/v1/interventions/cows/{animal_ref}/state` returns the latest usable cow state and missing-data notes.
- `POST /api/v1/interventions/simulate-counterfactual` accepts an animal reference, one-day horizon, and 1–8 independent scenario inputs. Supported model-input pairs are `heat`/`thi_mean` in `THI` and `management`/`milkings_per_day` in `milkings/day`. Feed and supplement scenarios are explicitly marked unsupported because source units/action semantics are unavailable. Estimates outside model training support are withheld.
- Legacy `POST /api/v1/interventions/simulate` keeps its endpoint/request shape but returns no demo yield uplift.

Example request:

```json
{
  "animal_ref": "<approved-animal-reference>",
  "prediction_horizon_days": 1,
  "scenarios": [{
    "scenario_id": "whatif-1",
    "category": "heat",
    "name": "THI exposure what-if",
    "feature": "thi_mean",
    "proposed_value": 68,
    "unit": "THI",
    "intervention_description": "Exposure perturbation only; no cooling action modeled"
  }]
}
```

The example value is illustrative, not a recommended threshold or observed cow value. The response separates `observed_milk_yield_l_day` from the predicted next-day baseline and includes each scenario's status, predictions, changes, assumptions, model version, and warnings.

## Limitations

- The current model is a one-day observational predictor, not a causal estimator.
- Feed and supplement intervention semantics cannot be established from the accessible source columns.
- THI changes are not linked to a specific cooling intervention; milking-frequency scenarios are not checked for operational or welfare feasibility.
- No intervention cost, resource availability, uncertainty interval, biological validation, optimization, recommendation, or human decision workflow is implemented here.
- Actual Farm X records and credentials are not committed. Unit/API tests use synthetic fixtures and mocked repositories only.
