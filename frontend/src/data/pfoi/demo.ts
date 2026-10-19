/**
 * Component 1 (PFOI): deterministic DEMO run.
 *
 * Every number here is synthetic and fictional. It is not Farm X data, not a
 * model result and not a backtest. It exists so the page can be built and
 * reviewed before the model writes `c1_output`, and it has exactly the shape of
 * the planned outputs so the Step 6 API can replace it without chart changes.
 *
 * The generator follows the model's own structure, so the demo explains itself
 * the way the real outputs will: milk = cows in milk × base yield × stage mix ×
 * parity mix × THI × mastitis, and attribution is an exact Shapley split of
 * that product.
 */

import {
  FORECAST_SERIES,
  HORIZONS,
  type ActualRow,
  type AttributionRow,
  type BacktestRow,
  type BenchmarkModel,
  type CoverageRow,
  type FertilityRow,
  type GenerationRow,
  type Grain,
  type MilkFactor,
  type MoveGroup,
  type MoveRow,
  type OutlookRow,
  type PfoiRun,
  type QualityBandRow,
  type QualityFlag,
  type SeriesId,
} from './contract';
import {
  addDays,
  addPeriods,
  daysBetween,
  mulberry32,
  periodDays,
  periodStart,
  poisson,
  round,
  shapley,
  toDate,
} from './util';

const MODEL_VERSION = 'pfoi-demo-0.1';
const CORE_VERSION = 'demo';
const SIM_START = '2019-01-01';
/** A Monday, so daily, weekly and monthly views share one origin. */
const ORIGIN = '2026-08-31';
const DATA_THROUGH = addDays(ORIGIN, -1);
const SIM_END = '2027-09-30';
const SHIPMENT_UNTIL = '2020-08-01';
const GAP = ['2020-06-20', '2020-07-31'] as const;
const BASE_YIELD = 10.2;
const MASTITIS_RATE = 0.0012;

type Driver = [herd: number, stage: number, parity: number, thi: number, mastitis: number];
const DRIVER_FACTORS: MilkFactor[] = ['herd_size', 'stage_mix', 'parity_mix', 'thi', 'mastitis'];
/** Demo bulls and unknown-state animals: counted in the total herd, shown as their own band. */
const DEMO_OTHER = 3;

const milkOf = (x: number[]) => x[0] * BASE_YIELD * x[1] * x[2] * x[3] * x[4];

type EventId = 'calvings' | 'dry_offs' | 'abortions' | 'deaths' | 'culls_sales' | 'entries';
const EVENTS: EventId[] = ['calvings', 'dry_offs', 'abortions', 'deaths', 'culls_sales', 'entries'];

interface Day {
  date: string;
  observed: boolean;
  driver: Driver;
  dry: number;
  heifers: number;
  calves: number;
  modelMilk: number;
  actualMilk: number | null;
  milkScoreable: boolean;
  events: Record<EventId, number>;
  lambda: Record<EventId, number>;
  mastitisRecorded: number;
  mastitisExpected: number;
}

/* ------------------------------------------------------------------ */
/* Daily simulation                                                    */
/* ------------------------------------------------------------------ */

function simulate(): Day[] {
  const rand = mulberry32(20261023);
  const normal = () => Math.sqrt(-2 * Math.log(rand() + 1e-12)) * Math.cos(2 * Math.PI * rand());
  const days: Day[] = [];
  let walk = 0;
  let ar = 0;
  const total = daysBetween(SIM_START, SIM_END);

  for (let t = 0; t <= total; t++) {
    const date = addDays(SIM_START, t);
    const observed = date <= DATA_THROUGH;
    const doy = (toDate(date).getTime() - Date.UTC(toDate(date).getUTCFullYear(), 0, 1)) / 86_400_000;
    const wave = (shift: number) => Math.sin((2 * Math.PI * (doy - shift)) / 365);

    if (observed) walk = Math.max(-6, Math.min(6, walk * 0.995 + normal() * 0.35));
    else walk *= 0.99;

    const milkingMean = 108 + 9 * wave(210) + 4 * Math.sin((2 * Math.PI * t) / (365 * 2.7));
    const milking = observed ? Math.round(milkingMean + walk) : milkingMean + walk;
    const stage = 1 + 0.055 * wave(120);
    const parity = 1 + 0.02 * Math.sin((2 * Math.PI * t) / (365 * 3.1));
    const thi = 1 - 0.045 * Math.max(0, wave(60));
    const mastitis = 1 - 0.012 - 0.006 * Math.max(0, wave(90));
    const driver: Driver = [milking, stage, parity, thi, mastitis];
    const modelMilk = milkOf(driver);

    const recentShift = date >= '2023-01-01';
    const lambda: Record<EventId, number> = {
      calvings: 0.38 * (1 + 0.45 * wave(40)),
      dry_offs: 0.36 * (1 + 0.4 * wave(330)),
      abortions: recentShift ? 0.055 : 0.03,
      deaths: 0.025,
      culls_sales: 0.09,
      entries: 0.38 * (1 + 0.45 * wave(40)) + 0.01,
    };
    const events = Object.fromEntries(
      EVENTS.map((e) => [e, observed ? poisson(rand, lambda[e]) : 0]),
    ) as Record<EventId, number>;

    let actualMilk: number | null = null;
    let milkScoreable = observed;
    if (observed) {
      ar = 0.7 * ar + normal() * 0.018;
      const k = date < SHIPMENT_UNTIL ? 0.93 : 1;
      actualMilk = modelMilk * k * (1 + ar);
      if (date >= GAP[0] && date <= GAP[1]) { actualMilk = null; milkScoreable = false; }
      else if (rand() < 0.004) { actualMilk *= 0.42; milkScoreable = false; }
    }

    const mastitisExpected = milking * MASTITIS_RATE;
    /* Recording falls away after 2022: the model keeps the expectation from the
       rate period, the records show the gap. */
    const recordShare = date < '2023-01-01' ? 1 : 0.18;

    days.push({
      date,
      observed,
      driver,
      dry: observed ? Math.round(26 + 6 * wave(120) + normal() * 0.6) : 26 + 6 * wave(120),
      heifers: observed ? Math.round(64 + 5 * wave(300) + t / 900 + normal() * 0.6) : 64 + 5 * wave(300) + t / 900,
      calves: observed ? Math.round(42 + 7 * wave(20) + normal() * 0.8) : 42 + 7 * wave(20),
      modelMilk,
      actualMilk,
      milkScoreable,
      events,
      lambda,
      mastitisRecorded: observed ? poisson(rand, mastitisExpected * recordShare) : 0,
      mastitisExpected,
    });
  }
  return days;
}

const DAYS = simulate();
const INDEX = new Map(DAYS.map((d, i) => [d.date, i]));
const daysIn = (start: string, end: string) => {
  const out: Day[] = [];
  for (let iso = start; iso < end; iso = addDays(iso, 1)) {
    const i = INDEX.get(iso);
    if (i !== undefined) out.push(DAYS[i]);
  }
  return out;
};
const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / Math.max(1, xs.length);
const sum = (xs: number[]) => xs.reduce((s, x) => s + x, 0);
const avgDriver = (ds: Day[]): Driver => [0, 1, 2, 3, 4].map((i) => mean(ds.map((d) => d.driver[i]))) as Driver;

/* ------------------------------------------------------------------ */
/* Outlook rows                                                        */
/* ------------------------------------------------------------------ */

const firstTarget = (grain: Grain, origin: string = ORIGIN) => {
  const p = periodStart(origin, grain);
  return p < origin ? addPeriods(p, grain, 1) : p;
};
const MAX_H: Record<Grain, number> = { day: 14, week: 13, month: 12 };

function qualityFor(grain: Grain, h: number): QualityFlag {
  if (grain === 'day') return h <= 7 ? 'high' : 'moderate';
  if (grain === 'week') return h <= 4 ? 'high' : h <= 8 ? 'moderate' : 'limited';
  return h <= 2 ? 'high' : h <= 6 ? 'moderate' : 'limited';
}

function widthFor(grain: Grain, h: number, kind: 'milk' | 'stock') {
  if (kind === 'milk') return grain === 'day' ? 0.04 + 0.004 * h : grain === 'week' ? 0.035 + 0.007 * h : 0.03 + 0.011 * h;
  return grain === 'week' ? 0.008 + 0.004 * h : 0.012 + 0.009 * h;
}

function seriesValue(series: SeriesId, ds: Day[], grain: Grain, start: string) {
  const x = avgDriver(ds);
  switch (series) {
    case 'milk_litres': return milkOf(x) * periodDays(start, grain);
    case 'milking': return x[0];
    case 'dry': return mean(ds.map((d) => d.dry));
    case 'heifers': return mean(ds.map((d) => d.heifers));
    case 'calves': return mean(ds.map((d) => d.calves));
    case 'other': return DEMO_OTHER;
    case 'total_herd': return x[0] + mean(ds.map((d) => d.dry + d.heifers + d.calves)) + DEMO_OTHER;
    case 'mastitis_episodes': return sum(ds.map((d) => d.mastitisExpected));
    default: return sum(ds.map((d) => d.lambda[series as EventId]));
  }
}

function outlookRow(origin: string, grain: Grain, h: number, target: string, series: SeriesId, f: number, widthScale = 1): OutlookRow {
  let lower: number;
  let upper: number;
  if (series === 'milk_litres' || ['milking', 'dry', 'heifers', 'calves', 'other', 'total_herd'].includes(series)) {
    const w = widthFor(grain, h, series === 'milk_litres' ? 'milk' : 'stock') * widthScale;
    lower = f * (1 - 1.645 * w);
    upper = f * (1 + 1.645 * w);
  } else {
    const spread = 1.645 * Math.sqrt(Math.max(f, 0.05)) * (1 + 0.03 * h);
    lower = Math.max(0, f - spread);
    upper = f + spread + 0.3;
  }
  return {
    origin_date: origin,
    target_period: target,
    grain,
    horizon: h,
    series,
    forecast: round(f, 2),
    lower: round(lower, 2),
    upper: round(upper, 2),
    quality_flag: qualityFor(grain, h),
    model_version: MODEL_VERSION,
    core_version: CORE_VERSION,
  };
}

/* At an earlier (demo) forecast date the forecast misses the simulated truth by a
   deterministic error that grows with the horizon, so the outcome overlay has
   something to show. At the live origin there is no truth yet and no error. */
const FORECAST_ERROR: Partial<Record<SeriesId, number>> = {
  milk_litres: 0.035, milking: 0.02, dry: 0.05, heifers: 0.03, calves: 0.04, total_herd: 0.015,
};

/** A standard-normal draw fixed by its key (independent of call order). */
function keyedZ(key: string) {
  let hsh = 2166136261;
  for (let i = 0; i < key.length; i++) hsh = Math.imul(hsh ^ key.charCodeAt(i), 16777619);
  const rand = mulberry32(hsh >>> 0);
  return Math.sqrt(-2 * Math.log(rand() + 1e-12)) * Math.cos(2 * Math.PI * rand());
}

function forecastError(origin: string, target: string, series: SeriesId, h: number, grain: Grain) {
  if (origin === ORIGIN) return 1;
  const steps = grain === 'month' ? h : grain === 'week' ? h / 4.35 : h / 30.4;
  const sigma = FORECAST_ERROR[series] ?? 0.12;
  return Math.max(0.2, 1 + sigma * Math.sqrt(steps) * (0.6 * keyedZ(`${origin}|${series}`) + 0.8 * keyedZ(`${origin}|${target}|${series}`)));
}

function buildOutlook(origin: string = ORIGIN): OutlookRow[] {
  const rows: OutlookRow[] = [];
  (['day', 'week', 'month'] as Grain[]).forEach((grain) => {
    const first = firstTarget(grain, origin);
    for (let h = 1; h <= MAX_H[grain]; h++) {
      const start = addPeriods(first, grain, h - 1);
      const ds = daysIn(start, addPeriods(start, grain, 1));
      FORECAST_SERIES[grain].forEach((series) => {
        const f = seriesValue(series, ds, grain, start) * forecastError(origin, start, series, h, grain);
        rows.push(outlookRow(origin, grain, h, start, series, f));
      });
    }
  });
  return rows;
}

/* ------------------------------------------------------------------ */
/* Actuals                                                             */
/* ------------------------------------------------------------------ */

/* Full recorded history at every grain; weeks start on the Monday on or after SIM_START. */
const HISTORY_FROM: Record<Grain, string> = {
  day: SIM_START,
  week: '2019-01-07',
  month: SIM_START,
};

function buildActuals(): ActualRow[] {
  const rows: ActualRow[] = [];
  (['day', 'week', 'month'] as Grain[]).forEach((grain) => {
    for (let start = HISTORY_FROM[grain]; start <= DATA_THROUGH; start = addPeriods(start, grain, 1)) {
      const end = addPeriods(start, grain, 1);
      const all = daysIn(start, end);
      const ds = all.filter((d) => d.observed);
      if (!ds.length) continue;
      /* A period is scored when at least 90% of its days are observed and
         scoreable; single flagged days are dropped rather than sinking the period. */
      const complete = ds.length >= 0.9 * all.length;
      const milkDays = ds.filter((d) => d.actualMilk !== null && d.milkScoreable);
      const gapShare = 1 - milkDays.length / all.length;
      const milk = gapShare > 0.5 ? null : (sum(milkDays.map((d) => d.actualMilk ?? 0)) / milkDays.length) * periodDays(start, grain);
      const source = start < SHIPMENT_UNTIL ? 'shipment' : 'delpro';
      const push = (series: SeriesId, value: number | null, scoreable = complete) =>
        rows.push({ period: start, grain, series, value: value === null ? null : round(value, 2), source: series === 'milk_litres' ? source : null, scoreable });

      push('milk_litres', milk, complete && gapShare <= 0.1);
      push('milking', mean(ds.map((d) => d.driver[0])));
      push('dry', mean(ds.map((d) => d.dry)));
      push('heifers', mean(ds.map((d) => d.heifers)));
      push('calves', mean(ds.map((d) => d.calves)));
      push('other', DEMO_OTHER);
      push('total_herd', mean(ds.map((d) => d.driver[0] + d.dry + d.heifers + d.calves + DEMO_OTHER)));
      EVENTS.forEach((e) => push(e, sum(ds.map((d) => d.events[e]))));
      push('mastitis_episodes', sum(ds.map((d) => d.mastitisRecorded)));
    }
  });
  return rows;
}

/* ------------------------------------------------------------------ */
/* Attribution                                                         */
/* ------------------------------------------------------------------ */

const attr = (origin: string, target: string, grain: Grain, series: SeriesId, factor: AttributionRow['factor'], contribution: number): AttributionRow => ({
  origin_date: origin,
  target_period: target,
  grain,
  series,
  factor,
  contribution: round(contribution, 3),
  model_version: MODEL_VERSION,
  core_version: CORE_VERSION,
});

function buildAttribution(origin: string = ORIGIN): AttributionRow[] {
  const rows: AttributionRow[] = [];
  const ORIGIN_ = origin;

  /* Milk, monthly: change from the previous month in L/day, split by Shapley.
     Past months keep a residual (actual − model); forecasts have none. */
  const lastMonth = addPeriods(firstTarget('month', origin), 'month', MAX_H.month - 1);
  for (let m = addPeriods(firstTarget('month', origin), 'month', -24); m <= lastMonth; m = addPeriods(m, 'month', 1)) {
    const prev = addPeriods(m, 'month', -1);
    const cur = daysIn(m, addPeriods(m, 'month', 1));
    const before = daysIn(prev, m);
    const xNow = avgDriver(cur);
    const xPrev = avgDriver(before);
    const parts = shapley(milkOf, xPrev, xNow);
    parts.forEach((p, i) => rows.push(attr(ORIGIN_, m, 'month', 'milk_litres', DRIVER_FACTORS[i], p)));

    const isPast = m < firstTarget('month', origin);
    let residual = 0;
    if (isPast) {
      const actual = (ds: Day[]) => {
        const ok = ds.filter((d) => d.observed && d.actualMilk !== null && d.milkScoreable);
        return mean(ok.map((d) => d.actualMilk ?? 0));
      };
      residual = (actual(cur) - milkOf(xNow)) - (actual(before) - milkOf(xPrev));
    }
    rows.push(attr(ORIGIN_, m, 'month', 'milk_litres', 'residual', residual));
  }

  /* Herd flows: how much of each forecast count is already fixed at the origin. */
  (['week', 'month'] as Grain[]).forEach((grain) => {
    const first = firstTarget(grain, origin);
    for (let h = 1; h <= MAX_H[grain]; h++) {
      const start = addPeriods(first, grain, h - 1);
      const ds = daysIn(start, addPeriods(start, grain, 1));
      const monthsAhead = grain === 'month' ? h - 0.5 : (h - 0.5) / 4.35;
      EVENTS.forEach((e) => {
        const f = sum(ds.map((d) => d.lambda[e]));
        const share = e === 'calvings' || e === 'entries'
          ? Math.max(0, 1 - monthsAhead / 9.3)
          : e === 'dry_offs' ? Math.max(0, 0.85 - monthsAhead / 10) : 0;
        rows.push(attr(ORIGIN_, start, grain, e, 'determined', f * share));
        rows.push(attr(ORIGIN_, start, grain, e, 'rate_driven', f * (1 - share)));
      });
    }
  });
  return rows;
}

/* ------------------------------------------------------------------ */
/* Replay: earlier monthly origins and their revisions                 */
/* ------------------------------------------------------------------ */

function buildReplay(): { replay: OutlookRow[]; revisions: AttributionRow[] } {
  const rand = mulberry32(777);
  const z = new Map<string, number>();
  const zFor = (key: string) => {
    if (!z.has(key)) z.set(key, Math.sqrt(-2 * Math.log(rand() + 1e-12)) * Math.cos(2 * Math.PI * rand()));
    return z.get(key)!;
  };
  const sigma = [0.012, 0.01, 0.004, 0.008, 0.003];
  const origins: string[] = [];
  for (let o = '2025-09-01'; o <= '2026-08-01'; o = addPeriods(o, 'month', 1)) origins.push(o);

  const xHat = (origin: string, target: string): Driver => {
    const h = daysBetween(origin, target) / 30.4 + 1;
    const x = avgDriver(daysIn(target, addPeriods(target, 'month', 1)));
    return x.map((v, i) => v * (1 + sigma[i] * Math.sqrt(h) * (0.8 * zFor(`${target}|${i}`) + 0.35 * zFor(`${origin}|${target}|${i}`)))) as Driver;
  };

  const replay: OutlookRow[] = [];
  const revisions: AttributionRow[] = [];
  origins.forEach((origin, oi) => {
    for (let h = 1; h <= 12; h++) {
      const target = addPeriods(origin, 'month', h - 1);
      const f = milkOf(xHat(origin, target)) * periodDays(target, 'month');
      replay.push(outlookRow(origin, 'month', h, target, 'milk_litres', f));
      if (oi > 0 && h <= 11) {
        const parts = shapley(milkOf, xHat(origins[oi - 1], target), xHat(origin, target));
        parts.forEach((p, i) => revisions.push(attr(origin, target, 'month', 'milk_litres', DRIVER_FACTORS[i], p)));
      }
    }
  });
  return { replay, revisions };
}

/* ------------------------------------------------------------------ */
/* Backtest, quality bands, generation profile, coverage               */
/* ------------------------------------------------------------------ */

function buildBacktest(): BacktestRow[] {
  const rand = mulberry32(4242);
  const rows: BacktestRow[] = [];
  const level: Partial<Record<SeriesId, number>> = { milk_litres: 1100, milking: 108, total_herd: 245, calvings: 11.5, abortions: 1.4 };
  const models: BenchmarkModel[] = ['pfoi', 'persistence', 'seasonal_naive', 'sarima'];
  (['development', 'test'] as const).forEach((block) => {
    (['day', 'week', 'month'] as Grain[]).forEach((grain) => {
      const series = grain === 'day' ? (['milk_litres'] as SeriesId[]) : (Object.keys(level) as SeriesId[]);
      series.forEach((s) => {
        HORIZONS[grain].forEach((h) => {
          const reach = grain === 'day' ? h / 30 : grain === 'week' ? h / 4.35 : h;
          models.forEach((model) => {
            const isCount = s === 'calvings' || s === 'abortions';
            const base = isCount ? 0.32 : s === 'milk_litres' ? 0.035 : 0.012;
            const growth = { pfoi: 0.008, persistence: 0.016, seasonal_naive: 0.002, sarima: 0.011 }[model];
            const offset = { pfoi: 0.004, persistence: 0, seasonal_naive: 0.03, sarima: 0.006 }[model];
            const testPenalty = block === 'test' ? 1.15 : 1;
            const pct = (base + offset + growth * reach * (isCount ? 2 : 1)) * testPenalty * (0.92 + rand() * 0.16);
            /* Milk is scored in L/day at every grain; counts are per period. */
            const scale = isCount && grain === 'week' ? level[s]! * 0.23 : level[s]!;
            const mae = pct * scale;
            rows.push({
              block, model, grain, horizon: h, series: s,
              mae: round(mae, 2),
              rmse: round(mae * (1.22 + rand() * 0.1), 2),
              bias: round(mae * (rand() - 0.5) * 0.6, 2),
              coverage: model === 'pfoi' || model === 'sarima' ? round(0.93 - 0.012 * reach - rand() * 0.04 - (block === 'test' ? 0.03 : 0), 3) : null,
              n_origins: block === 'development' ? (grain === 'month' ? 84 : grain === 'week' ? 365 : 2550) : (grain === 'month' ? 32 : grain === 'week' ? 139 : 970),
            });
          });
        });
      });
    });
  });
  return rows;
}

const QUALITY_BANDS: QualityBandRow[] = [
  { band: 'high', mae_pct: 0.041, coverage: 0.91, n_periods: 46 },
  { band: 'moderate', mae_pct: 0.063, coverage: 0.87, n_periods: 29 },
  { band: 'limited', mae_pct: 0.098, coverage: 0.78, n_periods: 9 },
];

function buildGenerations(): GenerationRow[] {
  const rows: GenerationRow[] = [];
  const lastMonth = addPeriods(firstTarget('month'), 'month', MAX_H.month - 1);
  for (let m = SIM_START; m <= lastMonth; m = addPeriods(m, 'month', 1)) {
    const t = daysBetween(SIM_START, m) / 365;
    const g1 = 0.22 + 0.035 * t;
    const g2 = 0.05 + 0.03 * t;
    const g3 = Math.max(0, 0.008 * (t - 2.5));
    const g0 = 1 - g1 - g2 - g3;
    const projected = m >= firstTarget('month');
    ([['0', g0], ['1', g1], ['2', g2], ['3+', g3]] as const).forEach(([generation, share]) =>
      rows.push({ period: m, generation, share: round(share, 4), projected }));
  }
  return rows;
}

const FERTILITY: FertilityRow[] = [
  { period_label: '2017–19', generation: '0', services_per_conception: 2.1, abortion_pct: 2.8 },
  { period_label: '2017–19', generation: '1', services_per_conception: 2.4, abortion_pct: 3.1 },
  { period_label: '2017–19', generation: '2', services_per_conception: 2.6, abortion_pct: 3.4 },
  { period_label: '2020–22', generation: '0', services_per_conception: 2.5, abortion_pct: 3.6 },
  { period_label: '2020–22', generation: '1', services_per_conception: 2.9, abortion_pct: 4.0 },
  { period_label: '2020–22', generation: '2', services_per_conception: 3.1, abortion_pct: 4.4 },
  { period_label: '2023–26', generation: '0', services_per_conception: 2.9, abortion_pct: 7.2 },
  { period_label: '2023–26', generation: '1', services_per_conception: 3.4, abortion_pct: 8.1 },
  { period_label: '2023–26', generation: '2', services_per_conception: 3.6, abortion_pct: 8.8 },
];

const COVERAGE: CoverageRow[] = [
  { year: 2019, reliable_cow_days: 0, milk_days_scoreable_pct: 0.98, weather_complete_pct: 0.99, health_records: 410 },
  { year: 2020, reliable_cow_days: 61000, milk_days_scoreable_pct: 0.86, weather_complete_pct: 0.99, health_records: 320 },
  { year: 2021, reliable_cow_days: 52000, milk_days_scoreable_pct: 0.97, weather_complete_pct: 0.98, health_records: 260 },
  { year: 2022, reliable_cow_days: 18000, milk_days_scoreable_pct: 0.96, weather_complete_pct: 0.99, health_records: 190 },
  { year: 2023, reliable_cow_days: 1500, milk_days_scoreable_pct: 0.95, weather_complete_pct: 0.97, health_records: 40 },
  { year: 2024, reliable_cow_days: 900, milk_days_scoreable_pct: 0.97, weather_complete_pct: 0.99, health_records: 31 },
  { year: 2025, reliable_cow_days: 1200, milk_days_scoreable_pct: 0.96, weather_complete_pct: 0.98, health_records: 28 },
  { year: 2026, reliable_cow_days: 9000, milk_days_scoreable_pct: 0.97, weather_complete_pct: 0.96, health_records: 22 },
];

/* ------------------------------------------------------------------ */

let cached: PfoiRun | null = null;

/** The demo run. Built once, on first use. */
/* Moves between groups: recorded by day, week and month, forecast by week and month,
   as the model publishes them. Demo splits: 30% of calvings are first calvings; exits and arrivals
   are shared out by group with fixed demo weights. */
const FIRST_CALVING_SHARE = 0.3;
const DEATH_WEIGHT: [MoveGroup, number][] = [['calves', 0.45], ['heifers', 0.15], ['milking', 0.25], ['dry', 0.15]];
const CULL_WEIGHT: [MoveGroup, number][] = [['calves', 0.1], ['heifers', 0.1], ['milking', 0.55], ['dry', 0.25]];
const ENTRY_WEIGHT: [MoveGroup, number][] = [['heifers', 0.6], ['milking', 0.4]];
const LOST_WEIGHT: [MoveGroup, number][] = [['heifers', 0.35], ['milking', 0.4], ['dry', 0.25]];

/* On recorded days and weeks the group of an arrival or a lost pregnancy is not dated,
   so those are herd totals there, as in the model run. */
function movesFor(ds: Day[], forecast: boolean, herdLevel = false): [MoveGroup, MoveGroup, number][] {
  const ev = (e: EventId) => sum(ds.map((d) => (forecast ? d.lambda[e] : d.events[e])));
  const calvings = ev('calvings');
  const calfDays = sum(ds.map((d) => d.calves));
  const out: [MoveGroup, MoveGroup, number][] = [
    ['born', 'calves', calvings * 0.92],
    ['calves', 'heifers', calfDays * 0.46 / 365],
    ['calves', 'other', calfDays * 0.02 / 365],
    ['heifers', 'milking', calvings * FIRST_CALVING_SHARE],
    ['dry', 'milking', calvings * (1 - FIRST_CALVING_SHARE)],
    ['milking', 'dry', ev('dry_offs')],
  ];
  DEATH_WEIGHT.forEach(([g, w]) => out.push([g, 'died', ev('deaths') * w]));
  CULL_WEIGHT.forEach(([g, w]) => out.push([g, 'culled_sold', ev('culls_sales') * w]));
  if (herdLevel) {
    out.push(['arrived', 'herd', ev('entries')], ['herd', 'lost_pregnancy', ev('abortions')]);
  } else {
    ENTRY_WEIGHT.forEach(([g, w]) => out.push(['arrived', g, ev('entries') * w]));
    LOST_WEIGHT.forEach(([g, w]) => out.push([g, 'lost_pregnancy', ev('abortions') * w]));
  }
  return out;
}

function buildMoves(origin: string = ORIGIN): MoveRow[] {
  const rows: MoveRow[] = [];
  const push = (period: string, grain: Grain, ds: Day[], forecast: boolean) =>
    movesFor(ds, forecast, !forecast && grain !== 'month').forEach(([from, to, v]) => {
      if (v > 1e-6) rows.push({ period, grain, from, to, value: round(v, 3), forecast });
    });
  (['day', 'week', 'month'] as Grain[]).forEach((grain) => {
    const end = firstTarget(grain, origin);
    for (let p = HISTORY_FROM[grain]; addPeriods(p, grain, 1) <= end; p = addPeriods(p, grain, 1)) {
      push(p, grain, daysIn(p, addPeriods(p, grain, 1)), false);
    }
  });
  (['week', 'month'] as Grain[]).forEach((grain) => {
    const first = firstTarget(grain, origin);
    for (let h = 1; h <= MAX_H[grain]; h++) {
      const start = addPeriods(first, grain, h - 1);
      push(start, grain, daysIn(start, addPeriods(start, grain, 1)), true);
    }
  });
  return rows;
}

export function demoRun(): PfoiRun {
  if (cached) return cached;
  const { replay, revisions } = buildReplay();
  cached = {
    source: 'demo',
    model_version: MODEL_VERSION,
    core_version: CORE_VERSION,
    origin_date: ORIGIN,
    data_through: DATA_THROUGH,
    generated_at: '2026-10-19T09:00:00+05:30',
    outlook: buildOutlook(),
    attribution: buildAttribution(),
    actuals: buildActuals(),
    replay,
    revisions,
    backtest: buildBacktest(),
    qualityBands: QUALITY_BANDS,
    generations: buildGenerations(),
    fertility: FERTILITY,
    coverage: COVERAGE,
    mastitis_rate_period: '2017–2019 (demo)',
    moves: buildMoves(),
  };
  return cached;
}

/* ------------------------------------------------------------------ */
/* Demo runs at earlier forecast dates (with their outcomes)           */
/* ------------------------------------------------------------------ */

/** Demo forecast dates: test-block start, before a gap, recent, and the live origin. */
export const DEMO_ORIGINS = ['2024-01-01', '2024-07-01', '2026-07-01', ORIGIN];

const atCache = new Map<string, PfoiRun>();

/**
 * The demo run as it would look at an earlier forecast date: history only before
 * the date, the synthetic forecast from it, and the synthetic outcomes after it
 * (`realised`). Fictional throughout, like `demoRun`.
 */
export function demoRunAt(origin: string): PfoiRun {
  const base = demoRun();
  if (origin === ORIGIN) return { ...base, realised: [], realised_through: DATA_THROUGH };
  const hit = atCache.get(origin);
  if (hit) return hit;
  const outlook = buildOutlook(origin);
  const targets = new Set(outlook.map((r) => `${r.grain}|${r.series}|${r.target_period}`));
  const complete = (period: string, grain: Grain) => addPeriods(period, grain, 1) <= addDays(DATA_THROUGH, 1);
  const run: PfoiRun = {
    ...base,
    origin_date: origin,
    data_through: addDays(origin, -1),
    outlook,
    attribution: buildAttribution(origin),
    actuals: base.actuals.filter((a) => addPeriods(a.period, a.grain, 1) <= origin),
    realised: base.actuals.filter((a) => a.period >= origin && complete(a.period, a.grain)
      && targets.has(`${a.grain}|${a.series}|${a.period}`)),
    realised_through: DATA_THROUGH,
    moves: buildMoves(origin).filter((m) => m.forecast || addPeriods(m.period, m.grain, 1) <= origin),
  };
  atCache.set(origin, run);
  return run;
}
