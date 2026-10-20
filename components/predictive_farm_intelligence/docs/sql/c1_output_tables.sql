-- PFOI (Component 1) output tables in schema c1_output. Run once, as farmx_model
-- (the schema owner). Herd-level aggregates only: no animal keys, no row-level data.
-- These columns are a contract (shared/schemas/pfoi_outlook.py): change them only with a
-- version bump and a note in shared/schemas/PFOI_OUTLOOK_CHANGES.md.

CREATE TABLE IF NOT EXISTS c1_output.outlook (
    origin_date   date             NOT NULL,
    target_period date             NOT NULL,  -- first day of the forecast period
    grain         text             NOT NULL,  -- daily | weekly | monthly
    horizon       integer          NOT NULL,
    series        text             NOT NULL,  -- herd_milk (litres per period), n_herd, milking (mean animals), calvings, dry_offs, real_abortions (counts per period)
    forecast      double precision NOT NULL,
    lower         double precision,           -- 5 % (empirical, from past errors)
    upper         double precision,           -- 95 %
    quality_flag  text             NOT NULL,  -- ok | low_recording | source_switch | k_window (; separated)
    model_version text             NOT NULL,
    core_version  text,
    created_at    timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_date, grain, horizon, series, model_version)
);

CREATE TABLE IF NOT EXISTS c1_output.attribution (
    origin_date   date             NOT NULL,
    target_period date             NOT NULL,
    grain         text             NOT NULL,
    series        text             NOT NULL,  -- herd_milk_litres_per_day | <state> | calvings | mastitis_expected_episodes
    factor        text             NOT NULL,
    contribution  double precision,
    kind          text             NOT NULL,  -- past | forecast
    model_version text             NOT NULL,
    core_version  text,
    created_at    timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_date, target_period, grain, series, factor, kind, model_version)
);

CREATE TABLE IF NOT EXISTS c1_output.history (
    origin_date   date             NOT NULL,
    period        date             NOT NULL,
    grain         text             NOT NULL,
    series        text             NOT NULL,
    actual        double precision,           -- null when the period is not scoreable
    quality_flag  text             NOT NULL,  -- ok | partial | gap
    model_version text             NOT NULL,
    core_version  text,
    created_at    timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_date, period, grain, series, model_version)
);

-- The page document: one frozen-model run in the shape the React page reads
-- (frontend/src/data/pfoi/contract.ts, PfoiRun). Herd-level aggregates only.
CREATE TABLE IF NOT EXISTS c1_output.run_document (
    origin_date   date        NOT NULL,
    model_version text        NOT NULL,
    core_version  text,
    document      jsonb       NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_date, model_version)
);

-- farmx_api already gets SELECT on new c1_output tables through the default privileges
-- set up in docs/database/app_database_setup.md (section 5). Check with:
-- SELECT table_name, privilege_type FROM information_schema.role_table_grants
-- WHERE table_schema = 'c1_output' AND grantee = 'farmx_api';
