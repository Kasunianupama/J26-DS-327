/**
 * Component 1 (PFOI): the output contract the page reads.
 *
 * `OutlookRow` and `AttributionRow` mirror the planned `c1_output.outlook` and
 * `c1_output.attribution` tables column for column, so the Step 6 API can be
 * dropped in without touching the charts. The other row types (actuals,
 * backtest, generation profile) are what the page also needs; they are not in
 * the planned contract yet and need a decision before Step 6.
 */

export type Grain = 'day' | 'week' | 'month';

export type SeriesId =
  | 'milk_litres'
  | 'milking'
  | 'dry'
  | 'heifers'
  | 'calves'
  | 'other'
  | 'total_herd'
  | 'calvings'
  | 'dry_offs'
  | 'abortions'
  | 'deaths'
  | 'culls_sales'
  | 'entries'
  | 'mastitis_episodes';

/** Record quality behind a value, which is what widens or narrows its range. */
export type QualityFlag = 'high' | 'moderate' | 'limited';

export type RunSource = 'demo' | 'model';

/** One row of `c1_output.outlook`. Milk is litres in the period; stocks are daily averages. */
export interface OutlookRow {
  origin_date: string;
  target_period: string;
  grain: Grain;
  horizon: number;
  series: SeriesId;
  forecast: number;
  lower: number;
  upper: number;
  quality_flag: QualityFlag;
  model_version: string;
  core_version: string;
}

export type MilkFactor =
  | 'herd_size' | 'stage_mix' | 'parity_mix' | 'pregnancy_mix' | 'yield_level' | 'thi' | 'mastitis' | 'residual';
export type FlowFactor = 'determined' | 'rate_driven';
export type Factor = MilkFactor | FlowFactor;

/**
 * One row of `c1_output.attribution`. For milk the parts of one period add up
 * exactly to the change from the previous period (litres per day). For herd
 * flows they split the forecast count into already determined vs rate-driven.
 */
export interface AttributionRow {
  origin_date: string;
  target_period: string;
  grain: Grain;
  series: SeriesId;
  factor: Factor;
  contribution: number;
  model_version: string;
  core_version: string;
}

export type MilkSource = 'shipment' | 'delpro';

/** Observed history at the same grain. Not in the planned contract yet. */
export interface ActualRow {
  period: string;
  grain: Grain;
  series: SeriesId;
  value: number | null;
  /** Milk only: which record the target comes from. */
  source: MilkSource | null;
  /** False inside the data gap, on suspect-low days, or when the period is incomplete. */
  scoreable: boolean;
}

export type BenchmarkModel = 'pfoi' | 'persistence' | 'seasonal_naive' | 'sarima';

/** Rolling-origin backtest metrics. Not in the planned contract yet. */
export interface BacktestRow {
  block: 'development' | 'test';
  model: BenchmarkModel;
  grain: Grain;
  horizon: number;
  series: SeriesId;
  mae: number;
  rmse: number;
  bias: number;
  /** Share of actuals inside the 5–95% range; null for models without intervals. */
  coverage: number | null;
  n_origins: number;
}

/** Backtest error by record-quality band (PFOI only, monthly milk). */
export interface QualityBandRow {
  band: QualityFlag;
  mae_pct: number;
  coverage: number;
  n_periods: number;
}

export interface GenerationRow {
  period: string;
  generation: '0' | '1' | '2' | '3+';
  share: number;
  projected: boolean;
}

export interface FertilityRow {
  period_label: string;
  generation: '0' | '1' | '2' | '3+';
  services_per_conception: number;
  abortion_pct: number;
}

export interface CoverageRow {
  year: number;
  reliable_cow_days: number;
  milk_days_scoreable_pct: number;
  weather_complete_pct: number;
  health_records: number;
}

/** Herd groups an animal can move between, plus where animals come from and go to. */
export type MoveGroup =
  | 'born' | 'arrived' | 'calves' | 'heifers' | 'milking' | 'dry' | 'other' | 'died' | 'culled_sold'
  /** the group is not recorded (arrivals and pregnancies lost on recorded days and weeks) */
  | 'herd'
  /** a pregnancy lost (abortion); the animal stays in its group */
  | 'lost_pregnancy';

/**
 * Animals that moved from one group to another during a period. Recorded months come
 * from the state-transition table; recorded days and weeks from dated calving, dry-off,
 * birth and exit records; forecasts (week and month) from the herd engine. Heifers →
 * milking are first calvings; dry → milking are cows calving again. Not in older runs,
 * so optional.
 */
export interface MoveRow {
  period: string;
  grain: Grain;
  from: MoveGroup;
  to: MoveGroup;
  value: number;
  forecast: boolean;
}

/** Everything one model run publishes for the page. */
export interface PfoiRun {
  source: RunSource;
  model_version: string;
  core_version: string;
  /** First day the forecast covers; no fact on or after it is used. */
  origin_date: string;
  data_through: string;
  generated_at: string;
  outlook: OutlookRow[];
  attribution: AttributionRow[];
  actuals: ActualRow[];
  /**
   * What was recorded in the forecast periods (same shape as `actuals`), for runs at
   * past forecast dates. Display and scoring only: the model never saw these values.
   * Missing on older documents and empty for the live outlook.
   */
  realised?: ActualRow[];
  /** Last data day whose outcomes `realised` holds, or null. */
  realised_through?: string | null;
  /** Forecasts from earlier monthly origins (monthly milk), for the replay. */
  replay: OutlookRow[];
  /** Why the forecast for a target moved between consecutive origins. */
  revisions: AttributionRow[];
  backtest: BacktestRow[];
  qualityBands: QualityBandRow[];
  generations: GenerationRow[];
  fertility: FertilityRow[];
  coverage: CoverageRow[];
  /** Period the mastitis rate was taken from, shown next to every expected-episode value. */
  mastitis_rate_period: string;
  /** Moves between herd groups per period (see MoveRow). */
  moves?: MoveRow[];

  /* PP1 development sections (docs/pp1_frontend_plan.md). All optional: older documents
   * lack them and the page says "not available for this run". */
  /** F1: are the milk records behind this run current, stale, or too poor to forecast milk? */
  record_status?: RecordStatus;
  /** F2: series and periods with no published forecast, and why. */
  withheld?: WithheldRow[];
  interval_method?: IntervalMethod;
  /** F3: simulated outages on the development block (milk hidden, actuals kept). */
  outage_simulation?: OutageRow[];
  /** F4: recent heat and the usual heat for the coming weeks (weather only). */
  heat?: HeatSummary;
  /** F5: calving → first recorded service → known conception → next calving. */
  repro_timing?: ReproStepRow[];
  /** F6: separate outcomes by generation within calving period (associations). */
  generation_outcomes?: GenerationOutcomeRow[];
  /** F7: which model additions help, all scored on the same periods. */
  evidence_ladder?: LadderRow[];
  /** F8: sensor and other driver signals and whether the model uses them yet. */
  feature_registry?: RegistryRow[];
  /** 1c: monthly forecasts under "like last time" scenarios (what happened after earlier episodes). */
  scenarios?: ScenarioRow[];
}

export interface ScenarioRow {
  kind: string;
  label: string;
  series: SeriesId;
  target_period: string;
  horizon: number;
  forecast: number;
  scenario: number;
  low: number;
  high: number;
  n_episodes: number;
  sentence: string;
}

/** Result labels shown on every evidence card (set by the model run, never by the page). */
export type EvidenceStatus = 'development' | 'post-test development' | 'not interpretable' | 'oracle'
  | 'implemented, not yet evaluated' | 'cannot be validated with current data';

export interface RecordCheck {
  check: 'freshness' | 'completeness' | 'plausibility' | 'source_agreement';
  ok: boolean | null;
  value: number | null;
  detail: string;
}

export interface RecordStatus {
  status: 'current' | 'stale' | 'withheld';
  last_trusted_day: string | null;
  staleness_days: number | null;
  fresh_days: number;
  lookback_days: number;
  checks: RecordCheck[];
  milk_withheld: boolean;
  reason: string | null;
  reason_text: string | null;
  rule: string;
}

export interface WithheldRow {
  series: SeriesId;
  grain: Grain;
  from: string;
  to: string;
  reason: string;
}

export interface IntervalMethod {
  milk: 'aci_quality_band' | 'empirical_quantiles';
  staleness_scale: string;
  staleness_days: number | null;
}

export interface OutageRow {
  gap_days: number;
  resumed_days: number;
  grain: 'daily' | 'weekly' | 'monthly';
  horizon: number;
  n: number;
  mae: number;
  ratio_to_no_outage: number;
  ratio_to_persistence: number;
  bias: number;
}

export interface HeatDay { date: string; thi_mean: number | null; thi_max: number | null }
export interface HeatClimate { date: string; p10: number; p50: number; p90: number }

export interface HeatSummary {
  last_weather_day: string;
  weather_lag_days: number;
  knot_p75: number | null;
  knot_p90: number | null;
  hot_run_days: number | null;
  heat_load_7d: number | null;
  recent: HeatDay[];
  climatology: HeatClimate[];
  source: string;
}

export interface ReproStepRow {
  period: string;
  step: 'first_ai' | 'conception' | 'calving_interval' | 'pregnancy';
  n: number;
  median_days?: number | null;
  p25_days?: number | null;
  p75_days?: number | null;
  censored_share?: number;
  left_herd_share?: number;
  by_60d?: number;
  by_100d?: number;
  by_150d?: number;
  by_200d?: number;
  by_300d?: number;
  calved_share?: number | null;
  lost_share?: number | null;
  /** Over pregnancies with a known outcome (pending ones are not failures). */
  calved_of_resolved?: number | null;
  lost_of_resolved?: number | null;
  n_resolved?: number;
}

export interface GenerationOutcomeRow {
  period: string;
  generation_group: string;
  outcome: string;
  value: number;
  n: number;
}

export interface LadderRow {
  rung: string;
  grain: 'daily' | 'weekly' | 'monthly';
  horizon: number;
  band: 'all' | 'normal' | 'heat' | 'recovery';
  n: number;
  mae: number;
  bias: number;
  wape: number;
  ratio_to_reference: number | null;
  status: EvidenceStatus;
}

export interface RegistryRow {
  feature: string;
  shadow?: number;
  probation?: number;
  active?: number;
}

/* ------------------------------------------------------------------ */
/* Vocabulary                                                          */
/* ------------------------------------------------------------------ */

/** Quick horizon buttons (the scored steps). A run shows only those it reaches (view.horizonOptions):
 *  pfoi-1.1.1 publishes 12 months at every grain, earlier runs 14 days and 13 weeks. */
export const HORIZONS: Record<Grain, number[]> = {
  day: [1, 7, 14, 30, 91, 182, 365],
  week: [1, 4, 13, 26, 52],
  month: [1, 3, 6, 12],
};

/** Upper bound of any published step; the run's own last step is view.maxHorizon. */
export const MAX_HORIZON: Record<Grain, number> = { day: 366, week: 52, month: 12 };

/** History shown before the origin, in periods; -1 = all recorded history. */
export const HISTORY_ALL = -1;
export const HISTORY_OPTIONS: Record<Grain, number[]> = {
  day: [30, 60, 90, 180, 365],
  week: [13, 26, 52, 104, 156],
  month: [12, 24, 36, 60, 120, HISTORY_ALL],
};
export const HISTORY_DEFAULT: Record<Grain, number> = { day: 60, week: 52, month: 36 };

export const GRAIN_LABEL: Record<Grain, { one: string; many: string; short: string }> = {
  day: { one: 'day', many: 'days', short: 'd' },
  week: { one: 'week', many: 'weeks', short: 'w' },
  month: { one: 'month', many: 'months', short: 'm' },
};

/** Series the demo run forecasts at each grain (a real run: view.isForecast). pfoi-1.1.1
 *  forecasts every series daily; earlier runs only milk. */
export const FORECAST_SERIES: Record<Grain, SeriesId[]> = {
  day: ['milk_litres', 'milking', 'dry', 'heifers', 'calves', 'other', 'total_herd', 'calvings', 'dry_offs',
    'abortions', 'deaths', 'culls_sales', 'entries', 'mastitis_episodes'],
  week: ['milk_litres', 'milking', 'dry', 'heifers', 'calves', 'other', 'total_herd', 'calvings', 'dry_offs',
    'abortions', 'deaths', 'culls_sales', 'entries', 'mastitis_episodes'],
  month: ['milk_litres', 'milking', 'dry', 'heifers', 'calves', 'other', 'total_herd', 'calvings', 'dry_offs',
    'abortions', 'deaths', 'culls_sales', 'entries', 'mastitis_episodes'],
};

export const STOCK_SERIES: SeriesId[] = ['milking', 'dry', 'heifers', 'calves', 'other', 'total_herd'];
export const EVENT_SERIES: SeriesId[] = ['calvings', 'dry_offs', 'abortions', 'deaths', 'culls_sales', 'entries'];

export const SERIES_META: Record<SeriesId, { label: string; unit: string; color: string }> = {
  milk_litres: { label: 'Milk', unit: 'L/day', color: '#9a4f27' },
  milking: { label: 'Milking cows', unit: 'head', color: '#2f7f86' },
  dry: { label: 'Dry cows', unit: 'head', color: '#c99a77' },
  heifers: { label: 'Heifers', unit: 'head', color: '#5b7fa6' },
  calves: { label: 'Calves', unit: 'head', color: '#93aec9' },
  other: { label: 'Bulls & other', unit: 'head', color: '#8a8f87' },
  total_herd: { label: 'Total herd', unit: 'head', color: '#34483f' },
  calvings: { label: 'Calvings', unit: 'events', color: '#3f8c62' },
  dry_offs: { label: 'Dry-offs', unit: 'events', color: '#c99a77' },
  abortions: { label: 'Abortions', unit: 'events', color: '#a44b3c' },
  deaths: { label: 'Deaths', unit: 'events', color: '#52665d' },
  culls_sales: { label: 'Culls & sales', unit: 'events', color: '#a8770a' },
  entries: { label: 'Entries', unit: 'events', color: '#5b7fa6' },
  mastitis_episodes: { label: 'Mastitis episodes', unit: 'episodes', color: '#a44b3c' },
};

export const FACTOR_META: Record<Factor, { label: string; kind: 'measured' | 'derived' | 'assumed'; blurb: string }> = {
  herd_size: { label: 'Herd size', kind: 'derived', blurb: 'More or fewer cows in milk, from the herd engine.' },
  stage_mix: { label: 'Lactation-stage mix', kind: 'derived', blurb: 'Share of cows early, mid or late in lactation, read off the lactation curve.' },
  parity_mix: { label: 'Parity mix', kind: 'derived', blurb: 'Share of first, second and later lactations, each with its own curve.' },
  pregnancy_mix: { label: 'Pregnancy mix', kind: 'derived', blurb: 'Share of cows 150+ or 200+ days pregnant, who yield less (fitted factor).' },
  yield_level: { label: 'Yield level', kind: 'measured', blurb: 'Per-cow level known at the start of the month (recorded milk ÷ curve milk); constant within a forecast.' },
  thi: { label: 'Heat (THI)', kind: 'assumed', blurb: 'Forecasts use the THI climatology of the training years; the past uses measured THI.' },
  mastitis: { label: 'Mastitis', kind: 'derived', blurb: 'Expected episodes = cows at risk × rate from the stated rate period.' },
  residual: { label: 'Unexplained', kind: 'measured', blurb: 'Actual minus model. Only past periods have one; a forecast is fully explained by construction.' },
  determined: { label: 'Already determined', kind: 'measured', blurb: 'Fixed by facts before the origin, such as calvings from recorded conceptions.' },
  rate_driven: { label: 'Rate-driven', kind: 'derived', blurb: 'Expected from trailing-window rates; the uncertain part.' },
};

export const MILK_FACTORS: MilkFactor[] = ['herd_size', 'stage_mix', 'parity_mix', 'pregnancy_mix', 'yield_level', 'thi', 'mastitis', 'residual'];

export type Confidence = 'High' | 'Moderate' | 'Limited';

export const QUALITY_TO_CONFIDENCE: Record<QualityFlag, Confidence> = {
  high: 'High',
  moderate: 'Moderate',
  limited: 'Limited',
};

export const CONFIDENCE_META: Record<Confidence, { mark: string; blurb: string }> = {
  High: { mark: '●●●', blurb: 'Complete records and a short horizon; the range is narrow.' },
  Moderate: { mark: '●●○', blurb: 'Some missing records or a longer horizon; the range is wider.' },
  Limited: { mark: '●○○', blurb: 'Sparse records or a long horizon; read the range, not the line.' },
};

export const MODEL_LABEL: Record<BenchmarkModel, string> = {
  pfoi: 'PFOI',
  persistence: 'Persistence',
  seasonal_naive: 'Seasonal naive',
  sarima: 'SARIMA',
};

export const SEVERITY_META: Record<'attention' | 'routine', { label: string; color: string; mark: string }> = {
  attention: { label: 'Worth attention', color: '#8a6414', mark: '◆' },
  routine: { label: 'For information', color: '#4a6a5c', mark: '●' },
};

/** One forecast date with a published run (`GET /predictive/pfoi/runs`). */
export interface RunOrigin {
  origin_date: string;
  model_version: string;
  realised_through: string | null;
}

/** First forecast date of the final test block (frozen model, run once). */
export const TEST_BLOCK_START = '2024-01-01';
