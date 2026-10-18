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

export type MilkFactor = 'herd_size' | 'stage_mix' | 'parity_mix' | 'thi' | 'mastitis' | 'residual';
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
}

/* ------------------------------------------------------------------ */
/* Vocabulary                                                          */
/* ------------------------------------------------------------------ */

export const HORIZONS: Record<Grain, number[]> = {
  day: [1, 7, 14],
  week: [1, 4, 8, 13],
  month: [1, 3, 6, 12],
};

export const GRAIN_LABEL: Record<Grain, { one: string; many: string; short: string }> = {
  day: { one: 'day', many: 'days', short: 'd' },
  week: { one: 'week', many: 'weeks', short: 'w' },
  month: { one: 'month', many: 'months', short: 'm' },
};

/** Series that are forecast at each grain. Daily horizons cover milk only. */
export const FORECAST_SERIES: Record<Grain, SeriesId[]> = {
  day: ['milk_litres'],
  week: ['milk_litres', 'milking', 'dry', 'heifers', 'calves', 'total_herd', 'calvings', 'dry_offs',
    'abortions', 'deaths', 'culls_sales', 'entries', 'mastitis_episodes'],
  month: ['milk_litres', 'milking', 'dry', 'heifers', 'calves', 'total_herd', 'calvings', 'dry_offs',
    'abortions', 'deaths', 'culls_sales', 'entries', 'mastitis_episodes'],
};

export const STOCK_SERIES: SeriesId[] = ['milking', 'dry', 'heifers', 'calves', 'total_herd'];
export const EVENT_SERIES: SeriesId[] = ['calvings', 'dry_offs', 'abortions', 'deaths', 'culls_sales', 'entries'];

export const SERIES_META: Record<SeriesId, { label: string; unit: string; color: string }> = {
  milk_litres: { label: 'Milk', unit: 'L/day', color: '#9a4f27' },
  milking: { label: 'Milking cows', unit: 'head', color: '#9a4f27' },
  dry: { label: 'Dry cows', unit: 'head', color: '#c99a77' },
  heifers: { label: 'Heifers', unit: 'head', color: '#5b7fa6' },
  calves: { label: 'Calves', unit: 'head', color: '#93aec9' },
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
  thi: { label: 'Heat (THI)', kind: 'assumed', blurb: 'Forecasts use the THI climatology of the training years; the past uses measured THI.' },
  mastitis: { label: 'Mastitis', kind: 'derived', blurb: 'Expected episodes = cows at risk × rate from the stated rate period.' },
  residual: { label: 'Unexplained', kind: 'measured', blurb: 'Actual minus model. Only past periods have one; a forecast is fully explained by construction.' },
  determined: { label: 'Already determined', kind: 'measured', blurb: 'Fixed by facts before the origin, such as calvings from recorded conceptions.' },
  rate_driven: { label: 'Rate-driven', kind: 'derived', blurb: 'Expected from trailing-window rates; the uncertain part.' },
};

export const MILK_FACTORS: MilkFactor[] = ['herd_size', 'stage_mix', 'parity_mix', 'thi', 'mastitis', 'residual'];

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
