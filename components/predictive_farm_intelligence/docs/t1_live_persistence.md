# T1 live persistence option — 2026-10-21

Status: **rejected by the user (2026-10-21)**; the option stays off and the replay
below is not needed. Kept for the record only. Originally: implemented; adoption and real-data replay pending. The keep rule was
written in pp1_plan.md before implementation. No real-data runs by the agent.

`build-outlook --persistence-blend on` applies the M10 persistence-only mixture
inside OutputLayer after adaptive milk correction. Default is off, registered in
freeze.LEGACY_OUTPUT_VALUES. Enabled runs use pfoi-1.2.0-dev-persistence in a
separate output directory. Frozen engine/milk configurations and hashes are unchanged.

Daily/weekly milk changes; monthly and herd outputs retain their original values.
Weights use matched completed errors only (at least eight); the next longer scored
horizon supplies weights for intermediate horizons. Persistence uses the same last
available calendar-week mean as M10 (at least 5/7 scoreable days). Weekly totals are
seven times the daily reference. This may be stale near a recording gap: reference
week and age are recorded, not silently described as current. No reference means
adaptive-only output. No sufficient error history means structural/adaptive weight one.

The page's blend field records model, rule, reference, horizon weights and finished
sample counts. Page corrections still reconcile structural + correction to displayed
forecast. The table and page use the same blend errors for ranges; no structural
interval is relabelled as a blend interval. ACI, when selected, operates on blend
errors for these rows. Interval quality still requires empirical replay. Monthly
intervals keep the existing M4 rule. No interval is claimed with too few errors.

The existing offline blend-outlook command now includes ETS in daily forecasts;
that belongs to the parallel session. This live option deliberately implements
M10's persistence-only candidate. Reconciled pfoi-1.1.1 and break-reset on are rejected
before source access; their paths/history differ from this tested candidate.

## User-run post-hoc replay (descriptive only)

Run from the repository root. These commands read your local data and write a new
local replay folder, not c1_output. Do not add --write. No new model choice should
be made from 2024–2026 accuracy. No model download is needed.

Build the unchanged development baseline:

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli build-outlook --preset pfoi-1.1 --k anchor_first --intervals aci --origin 2024-01-01 2024-07-01 2025-09-01 2026-01-01 2026-08-01 --backtests logs/pfoi --out logs/pfoi_t1_replay
```

Build the persistence-only candidate with identical settings:

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli build-outlook --preset pfoi-1.1 --k anchor_first --intervals aci --persistence-blend on --origin 2024-01-01 2024-07-01 2025-09-01 2026-01-01 2026-08-01 --backtests logs/pfoi --out logs/pfoi_t1_replay
```

Compare daily forecasts on matched periods:

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli compare-runs --base pfoi-1.2.0-dev --candidate pfoi-1.2.0-dev-persistence --grain day --origins 2024-01-01 2024-07-01 2025-09-01 2026-01-01 2026-08-01 --out logs/pfoi_t1_replay
```

Compare weekly forecasts on matched periods:

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli compare-runs --base pfoi-1.2.0-dev --candidate pfoi-1.2.0-dev-persistence --grain week --origins 2024-01-01 2024-07-01 2025-09-01 2026-01-01 2026-08-01 --out logs/pfoi_t1_replay
```

Return the printed per-origin/grain weight summaries (min/mean/max, finished-pair
counts, persistence reference and age), build/withheld counts, and daily/weekly
milk comparison rows: n, MAE, bias, change_pct, coverage and width where available.
No animal records or keys. Missing/withheld origins and unscoreable periods remain
reported, not replaced with zero. The last origin has very little realised follow-up.

## Files and checks

Created pfoi/live_persistence.py and tests/test_live_persistence.py. Modified
pfoi/outlook.py, pfoi/page_run.py and narrow CLI integration/compare options;
added the off value to pfoi/freeze.py. Updated docs/pp1_plan.md and the T0 audit note.
Created tests/no_database.py to block SQLAlchemy/SQLite connections during tests.
No AGENTS.md changes, commits, pushes or publishing.

An initial regression selection accidentally ran the pre-existing synthetic
in-memory SQLite writer test. This violated the no-connection rule; no farm database
or credentials were accessed. That batch was stopped after three tests, and the
writer test was explicitly deselected for the guarded run. Existing assertions were
not relaxed. Future full-suite selection must account for database integration tests.

## Verification commands executed

Targeted adapter/blend/source/freeze batch: 39 passed, 1364 NumPy/Pandas deprecation
warnings. Two further default-off/withheld tests were then added; the final adapter
file run passed all 8 tests (3 Pandas deprecation warnings). Exact frozen hashes
remain 3cbd28787fcb and 2a865a0c2687. git diff --check passed.

```bash
.venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_live_persistence.py components/predictive_farm_intelligence/tests/test_source_k.py components/predictive_farm_intelligence/tests/test_blend.py components/predictive_farm_intelligence/tests/test_freeze.py -q -p no:cacheprovider -p components.predictive_farm_intelligence.tests.no_database
```

```bash
.venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_live_persistence.py -q -p no:cacheprovider -p components.predictive_farm_intelligence.tests.no_database
```

Existing outlook/page/preview regression batch, writer integration test deselected:

```bash
.venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_outlook.py components/predictive_farm_intelligence/tests/test_pp1_outlook.py components/predictive_farm_intelligence/tests/test_blend_outlook.py -k 'not test_writer_replaces_rows_of_one_origin' -q -p no:cacheprovider -p components.predictive_farm_intelligence.tests.no_database
```

Guarded regression result: **26 passed, 1 deselected**, 11,341 existing NumPy
timedelta deprecation warnings, in 276.99 seconds. All 67 distinct selected tests
passed across the targeted batches and regression run. The full T7 suite has not
been run. No accuracy improvement or adoption is asserted from synthetic tests.
