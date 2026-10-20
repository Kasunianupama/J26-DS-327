# API

Base path: `/api/v1`. Existing APIs remain available. The Member 1 simulator routes are:

- `GET /interventions/cows/{animal_ref}/state` — latest quality-filtered state from the component's read-only Farm X data access.
- `GET /interventions/cows` — bounded available animal references and latest observation dates for the simulator selector.
- `POST /interventions/simulate-counterfactual` — baseline and up to eight model-based what-if estimates. Missing model/data and unsupported interventions are explicitly reported.
- Legacy `POST /interventions/simulate` — retains its request shape but no longer returns a fabricated yield uplift.

The counterfactual endpoint does not perform biological validation, optimization, recommendation ranking, or human decision handling. See `components/member1_didt/README.md` for source fields, model assumptions, and evidence limitations.
