/**
 * Component 1 (PFOI): turns contract rows into what the charts draw.
 *
 * This is the only place that knows how rows are keyed. When Step 6 swaps the
 * demo run for the API, nothing below this file should need to change.
 */

import {
  EVENT_SERIES,
  FACTOR_META,
  HISTORY_ALL,
  HISTORY_DEFAULT,
  HORIZONS,
  MILK_FACTORS,
  QUALITY_TO_CONFIDENCE,
  STOCK_SERIES,
  type ActualRow,
  type Confidence,
  type FlowFactor,
  type Grain,
  type MilkFactor,
  type OutlookRow,
  type PfoiRun,
  type QualityFlag,
  type SeriesId,
} from './contract';
import { addPeriods, fmt1, fmtInt, periodDays, periodLabel, periodStart } from './util';

/* ------------------------------------------------------------------ */
/* Row lookups                                                         */
/* ------------------------------------------------------------------ */

const key = (grain: Grain, period: string, series: SeriesId) => `${grain}|${period}|${series}`;
const indexCache = new WeakMap<PfoiRun, { outlook: Map<string, OutlookRow>; actual: Map<string, ActualRow>; realised: Map<string, ActualRow> }>();

function indexFor(run: PfoiRun) {
  let idx = indexCache.get(run);
  if (!idx) {
    idx = {
      outlook: new Map(run.outlook.filter((r) => r.origin_date === run.origin_date).map((r) => [key(r.grain, r.target_period, r.series), r])),
      actual: new Map(run.actuals.map((r) => [key(r.grain, r.period, r.series), r])),
      realised: new Map((run.realised ?? []).map((r) => [key(r.grain, r.period, r.series), r])),
    };
    indexCache.set(run, idx);
  }
  return idx;
}

export const forecastRow = (run: PfoiRun, grain: Grain, period: string, series: SeriesId) =>
  indexFor(run).outlook.get(key(grain, period, series));

export const actualRow = (run: PfoiRun, grain: Grain, period: string, series: SeriesId) =>
  indexFor(run).actual.get(key(grain, period, series));

/** Recorded outcome of a forecast period (runs at past forecast dates only). */
export const realisedRow = (run: PfoiRun, grain: Grain, period: string, series: SeriesId) =>
  indexFor(run).realised.get(key(grain, period, series));

/** True when the run holds recorded outcomes for its forecast periods. */
export const hasRealised = (run: PfoiRun) => (run.realised?.length ?? 0) > 0;

/** First period the forecast covers at this grain. */
export function firstTarget(run: PfoiRun, grain: Grain) {
  const p = periodStart(run.origin_date, grain);
  return p < run.origin_date ? addPeriods(p, grain, 1) : p;
}

export const targetPeriod = (run: PfoiRun, grain: Grain, horizon: number) =>
  addPeriods(firstTarget(run, grain), grain, horizon - 1);

/* What a run publishes. pfoi-1.1.1 forecasts every series for 12 months at every grain;
   earlier runs forecast 14 days (milk only) and 13 weeks. The page reads this from the run. */
const reachCache = new WeakMap<PfoiRun, { max: Map<Grain, number>; series: Set<string> }>();

function reachFor(run: PfoiRun) {
  let r = reachCache.get(run);
  if (!r) {
    r = { max: new Map(), series: new Set() };
    for (const row of run.outlook) {
      if (row.origin_date !== run.origin_date) continue;
      r.max.set(row.grain, Math.max(r.max.get(row.grain) ?? 0, row.horizon));
      r.series.add(`${row.grain}|${row.series}`);
    }
    reachCache.set(run, r);
  }
  return r;
}

/** Last horizon the run publishes at this grain (at least 1). */
export const maxHorizon = (run: PfoiRun, grain: Grain) => Math.max(1, reachFor(run).max.get(grain) ?? 1);

/** True when the run forecasts this series at this grain. */
export const isForecast = (run: PfoiRun, grain: Grain, series: SeriesId) => reachFor(run).series.has(`${grain}|${series}`);

/** Quick horizon buttons this run can show: the preset steps it reaches, ending on its last step. */
export function horizonOptions(run: PfoiRun, grain: Grain): number[] {
  const max = maxHorizon(run, grain);
  const opts = HORIZONS[grain].filter((h) => h <= max);
  if (HORIZONS[grain].some((h) => h > max) && opts[opts.length - 1] !== max) opts.push(max);
  return opts;
}

/** Milk is stored as litres in the period; every view shows litres per day. */
export const perDay = (series: SeriesId, value: number, grain: Grain, period: string) =>
  series === 'milk_litres' ? value / periodDays(period, grain) : value;

export const confidenceOf = (q: QualityFlag | null | undefined): Confidence => QUALITY_TO_CONFIDENCE[q ?? 'limited'];

/* ------------------------------------------------------------------ */
/* Timeline                                                            */
/* ------------------------------------------------------------------ */

export interface TimelinePoint {
  period: string;
  label: string;
  short: string;
  future: boolean;
  horizon: number | null;
  quality: QualityFlag | null;
  milkSource: 'shipment' | 'delpro' | null;
  /** True where the milk record is missing or flagged, so the chart can shade it. */
  milkGap: boolean;
  /** Per-series values: `x` actual, `x_f` forecast, `x_band` [lower, upper], `x_r` outcome after the forecast date. */
  [series: string]: unknown;
}

/** Earliest period with a recorded actual at this grain (or the first forecast period). */
export function earliestActual(run: PfoiRun, grain: Grain) {
  const ps = run.actuals.filter((a) => a.grain === grain).map((a) => a.period).sort();
  return ps[0] ?? firstTarget(run, grain);
}

/** Number of periods from the period containing `from` up to the first forecast period. */
export function periodsUntilOrigin(run: PfoiRun, grain: Grain, from: string) {
  const first = firstTarget(run, grain);
  let p = periodStart(from, grain);
  let n = 0;
  while (p < first && n < 5000) { p = addPeriods(p, grain, 1); n++; }
  return n;
}

export function timeline(run: PfoiRun, grain: Grain, horizon: number, history = HISTORY_DEFAULT[grain]): TimelinePoint[] {
  const first = firstTarget(run, grain);
  if (history === HISTORY_ALL) history = periodsUntilOrigin(run, grain, earliestActual(run, grain));
  const points: TimelinePoint[] = [];
  for (let i = -history; i < horizon; i++) {
    const period = addPeriods(first, grain, i);
    const future = i >= 0;
    const p: TimelinePoint = {
      period,
      label: periodLabel(period, grain),
      short: periodLabel(period, grain, true),
      future,
      horizon: future ? i + 1 : null,
      quality: null,
      milkSource: null,
      milkGap: false,
    };
    (['milk_litres', ...STOCK_SERIES, ...EVENT_SERIES, 'mastitis_episodes'] as SeriesId[]).forEach((s) => {
      const a = actualRow(run, grain, period, s);
      if (a && a.value !== null) p[s] = round2(perDay(s, a.value, grain, period));
      if (s === 'milk_litres' && a) {
        p.milkSource = a.source;
        p.milkGap = a.value === null || !a.scoreable;
      }
      const f = forecastRow(run, grain, period, s);
      if (f) {
        p[`${s}_f`] = round2(perDay(s, f.forecast, grain, period));
        p[`${s}_band`] = [round2(perDay(s, f.lower, grain, period)), round2(perDay(s, f.upper, grain, period))];
        if (s === 'milk_litres' || p.quality === null) p.quality = f.quality_flag;
      }
      if (future) {
        const r = realisedRow(run, grain, period, s);
        if (r && r.value !== null && r.scoreable) p[`${s}_r`] = round2(perDay(s, r.value, grain, period));
        if (s === 'milk_litres' && r) {
          p.milkSource = r.source;
          p.milkGap = r.value === null || !r.scoreable;
        }
      }
    });
    /* Join the two lines: the last actual also carries the forecast value. */
    if (i === -1) {
      (['milk_litres', ...STOCK_SERIES] as SeriesId[]).forEach((s) => {
        if (typeof p[s] === 'number') { p[`${s}_f`] = p[s]; p[`${s}_band`] = [p[s], p[s]]; }
      });
    }
    points.push(p);
  }
  return points;
}

const round2 = (n: number) => Math.round(n * 100) / 100;

/** Where the milk record switches source inside the window, if it does. */
export function sourceSwitch(points: TimelinePoint[]) {
  for (let i = 1; i < points.length; i++) {
    if (points[i - 1].milkSource && points[i].milkSource && points[i - 1].milkSource !== points[i].milkSource) return points[i].period;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Forecast vs recorded outcome (runs at past forecast dates)          */
/* ------------------------------------------------------------------ */

export interface OutcomeScore {
  series: SeriesId;
  /** Forecast periods up to the horizon. */
  periods: number;
  /** Of those, periods with a scoreable recorded outcome. */
  scored: number;
  /** Mean absolute error, per day for milk, per period otherwise. */
  mae: number | null;
  /** Mean absolute error as a share of the mean outcome (robust to small counts). */
  maeShare: number | null;
  /** Mean of outcome − forecast: positive = the forecast was too low. */
  bias: number | null;
  inside: number;
}

/** How the forecasts for horizons 1..h compare with what was then recorded. */
export function outcomeScore(run: PfoiRun, grain: Grain, horizon: number, series: SeriesId): OutcomeScore | null {
  let periods = 0;
  const errs: number[] = [];
  const outs: number[] = [];
  let inside = 0;
  for (let h = 1; h <= horizon; h++) {
    const period = targetPeriod(run, grain, h);
    const f = forecastRow(run, grain, period, series);
    if (!f) continue;
    periods++;
    const r = realisedRow(run, grain, period, series);
    if (!r || r.value === null || !r.scoreable) continue;
    const a = perDay(series, r.value, grain, period);
    errs.push(a - perDay(series, f.forecast, grain, period));
    outs.push(a);
    if (r.value >= f.lower && r.value <= f.upper) inside++;
  }
  if (!periods) return null;
  const n = errs.length;
  const mae = n ? errs.reduce((s, e) => s + Math.abs(e), 0) / n : null;
  const meanOut = n ? outs.reduce((s, x) => s + x, 0) / n : 0;
  return {
    series,
    periods,
    scored: n,
    mae,
    maeShare: mae !== null && meanOut > 0 ? mae / meanOut : null,
    bias: n ? errs.reduce((s, e) => s + e, 0) / n : null,
    inside,
  };
}

/* ------------------------------------------------------------------ */
/* Headline at the selected horizon                                    */
/* ------------------------------------------------------------------ */

export interface HeadlineValue {
  series: SeriesId;
  period: string;
  value: number;
  lower: number;
  upper: number;
  quality: QualityFlag;
  /** Latest complete actual at the same grain, for the change. */
  baseline: number | null;
  baselinePeriod: string | null;
  changePct: number | null;
  /** Sum (events) or values (others) along the path up to the horizon, for sparklines. */
  path: number[];
  pathTotal: number;
}

export function lastActual(run: PfoiRun, grain: Grain, series: SeriesId) {
  let period = addPeriods(firstTarget(run, grain), grain, -1);
  for (let i = 0; i < 6; i++) {
    const a = actualRow(run, grain, period, series);
    if (a && a.value !== null && a.scoreable) return { period, value: perDay(series, a.value, grain, period) };
    period = addPeriods(period, grain, -1);
  }
  return null;
}

export function headline(run: PfoiRun, grain: Grain, horizon: number, series: SeriesId): HeadlineValue | null {
  const period = targetPeriod(run, grain, horizon);
  const f = forecastRow(run, grain, period, series);
  if (!f) return null;
  const base = lastActual(run, grain, series);
  const value = perDay(series, f.forecast, grain, period);
  const path: number[] = [];
  for (let h = 1; h <= horizon; h++) {
    const p = targetPeriod(run, grain, h);
    const r = forecastRow(run, grain, p, series);
    if (r) path.push(perDay(series, r.forecast, grain, p));
  }
  return {
    series,
    period,
    value,
    lower: perDay(series, f.lower, grain, period),
    upper: perDay(series, f.upper, grain, period),
    quality: f.quality_flag,
    baseline: base?.value ?? null,
    baselinePeriod: base?.period ?? null,
    changePct: base && base.value ? ((value - base.value) / base.value) * 100 : null,
    path,
    pathTotal: path.reduce((s, x) => s + x, 0),
  };
}

/* ------------------------------------------------------------------ */
/* Attribution                                                         */
/* ------------------------------------------------------------------ */

export interface MilkBreakdown {
  period: string;
  isPast: boolean;
  start: number;
  end: number;
  parts: { factor: MilkFactor; value: number }[];
}

export function attributionMonths(run: PfoiRun) {
  return [...new Set(run.attribution.filter((r) => r.series === 'milk_litres' && r.grain === 'month').map((r) => r.target_period))].sort();
}

/** Shapley parts of the change into `period`, which add up exactly to end − start. */
export function milkBreakdown(run: PfoiRun, period: string): MilkBreakdown | null {
  const rows = run.attribution.filter((r) => r.series === 'milk_litres' && r.grain === 'month' && r.target_period === period && r.origin_date === run.origin_date);
  if (!rows.length) return null;
  const isPast = period < firstTarget(run, 'month');
  const endRow = isPast ? actualRow(run, 'month', period, 'milk_litres') : forecastRow(run, 'month', period, 'milk_litres');
  const endValue = isPast ? (endRow as ActualRow | undefined)?.value : (endRow as OutlookRow | undefined)?.forecast;
  if (endValue === null || endValue === undefined) return null;
  const end = perDay('milk_litres', endValue, 'month', period);
  // only the factors this run reports (the model run has no THI or mastitis factor yet)
  const parts = MILK_FACTORS.filter((factor) => rows.some((r) => r.factor === factor))
    .map((factor) => ({ factor, value: rows.find((r) => r.factor === factor)?.contribution ?? 0 }));
  const total = parts.reduce((s, p) => s + p.value, 0);
  return { period, isPast, start: end - total, end, parts };
}

export function flowSplit(run: PfoiRun, grain: Grain, period: string, series: SeriesId): Record<FlowFactor, number> | null {
  const rows = run.attribution.filter((r) => r.grain === grain && r.target_period === period && r.series === series && r.origin_date === run.origin_date);
  if (!rows.length) return null;
  return {
    determined: rows.find((r) => r.factor === 'determined')?.contribution ?? 0,
    rate_driven: rows.find((r) => r.factor === 'rate_driven')?.contribution ?? 0,
  };
}

/** Totals over horizons 1..h, split into already determined vs rate-driven. */
export function flowTotals(run: PfoiRun, grain: Grain, horizon: number, series: SeriesId) {
  let determined = 0;
  let rate = 0;
  for (let h = 1; h <= horizon; h++) {
    const s = flowSplit(run, grain, targetPeriod(run, grain, h), series);
    if (s) { determined += s.determined; rate += s.rate_driven; }
  }
  return { determined, rate, total: determined + rate };
}

/* ------------------------------------------------------------------ */
/* Replay                                                              */
/* ------------------------------------------------------------------ */

export const replayOrigins = (run: PfoiRun) => [...new Set(run.replay.map((r) => r.origin_date))].sort();

export function replayPath(run: PfoiRun, origin: string) {
  return run.replay
    .filter((r) => r.origin_date === origin)
    .sort((a, b) => a.horizon - b.horizon)
    .map((r) => {
      const a = actualRow(run, 'month', r.target_period, 'milk_litres');
      return {
        period: r.target_period,
        short: periodLabel(r.target_period, 'month', true),
        horizon: r.horizon,
        forecast: round2(perDay('milk_litres', r.forecast, 'month', r.target_period)),
        band: [round2(perDay('milk_litres', r.lower, 'month', r.target_period)), round2(perDay('milk_litres', r.upper, 'month', r.target_period))] as [number, number],
        actual: a && a.value !== null ? round2(perDay('milk_litres', a.value, 'month', r.target_period)) : null,
        scoreable: a?.scoreable ?? false,
      };
    });
}

export function revisionFor(run: PfoiRun, origin: string, target: string) {
  const rows = run.revisions.filter((r) => r.origin_date === origin && r.target_period === target);
  return rows.map((r) => ({ factor: r.factor as MilkFactor, value: r.contribution }));
}

/* ------------------------------------------------------------------ */
/* Findings (computed from the run, so they move with it)              */
/* ------------------------------------------------------------------ */

export type Workspace = 'outlook' | 'herd' | 'confidence';
export type HerdTab = 'milk' | 'flow' | 'events' | 'generations';

export interface Finding {
  id: string;
  kind: 'Forecast change' | 'Upcoming' | 'Pattern' | 'Data limitation';
  severity: 'attention' | 'routine';
  title: string;
  summary: string;
  confidence: Confidence;
  link: { label: string; workspace: Workspace; tab?: HerdTab; period?: string };
}

export function findings(run: PfoiRun): Finding[] {
  const out: Finding[] = [];

  /* The lowest forecast month and what pulls it down. */
  const months = Array.from({ length: 12 }, (_, i) => targetPeriod(run, 'month', i + 1));
  const milk = months
    .map((m) => ({ m, r: forecastRow(run, 'month', m, 'milk_litres') }))
    .filter((x): x is { m: string; r: OutlookRow } => !!x.r);
  if (milk.length) {
    const low = milk.reduce((a, b) => (perDay('milk_litres', b.r.forecast, 'month', b.m) < perDay('milk_litres', a.r.forecast, 'month', a.m) ? b : a));
    const bd = milkBreakdown(run, low.m);
    const driver = bd?.parts.filter((p) => p.factor !== 'residual').sort((a, b) => a.value - b.value)[0];
    out.push({
      id: 'milk-low',
      kind: 'Forecast change',
      severity: 'attention',
      title: `Milk is expected to be lowest in ${periodLabel(low.m, 'month')}`,
      summary: `About ${fmtInt(perDay('milk_litres', low.r.forecast, 'month', low.m))} L/day (range ${fmtInt(perDay('milk_litres', low.r.lower, 'month', low.m))}–${fmtInt(perDay('milk_litres', low.r.upper, 'month', low.m))}).`
        + (driver && driver.value < 0 ? ` The biggest pull on the month before it is ${FACTOR_META[driver.factor].label.toLowerCase()} (${fmt1(driver.value)} L/day).` : ''),
      confidence: confidenceOf(low.r.quality_flag),
      link: { label: 'Open the milk breakdown', workspace: 'herd', tab: 'milk', period: low.m },
    });
  }

  /* Calvings over the next three months and how much of that is already fixed. */
  const calv = flowTotals(run, 'month', 3, 'calvings');
  if (calv.total > 0) {
    out.push({
      id: 'calvings-next',
      kind: 'Upcoming',
      severity: 'routine',
      title: `About ${fmtInt(calv.total)} calvings expected in the next three months`,
      summary: `${Math.round((calv.determined / calv.total) * 100)}% of them come from conceptions already recorded before the origin; the rest are rate-driven.`,
      confidence: 'High',
      link: { label: 'See the herd flow', workspace: 'herd', tab: 'flow' },
    });
  }

  /* Abortion rate by period (descriptive). */
  const g0 = run.fertility.filter((f) => f.generation === '0');
  if (g0.length >= 2) {
    const first = g0[0];
    const last = g0[g0.length - 1];
    out.push({
      id: 'abortion-shift',
      kind: 'Pattern',
      severity: 'attention',
      title: `Abortion rate is higher in ${last.period_label} for every generation`,
      summary: `Generation 0: ${first.abortion_pct}% in ${first.period_label} → ${last.abortion_pct}% in ${last.period_label}. The herd engine uses trailing-window rates, so forecasts carry the recent level.`,
      confidence: 'Moderate',
      link: { label: 'See fertility by period', workspace: 'herd', tab: 'generations' },
    });
  }

  /* Mastitis: expected vs recorded over the last 12 months. */
  let recorded = 0;
  let expectedMilking = 0;
  for (let i = 1; i <= 12; i++) {
    const m = addPeriods(firstTarget(run, 'month'), 'month', -i);
    recorded += actualRow(run, 'month', m, 'mastitis_episodes')?.value ?? 0;
    expectedMilking += actualRow(run, 'month', m, 'milking')?.value ?? 0;
  }
  const nextYear = flowlessSum(run, 'mastitis_episodes');
  out.push({
    id: 'mastitis-gap',
    kind: 'Data limitation',
    severity: 'attention',
    title: 'Mastitis records look incomplete',
    summary: `${fmtInt(recorded)} episodes were recorded in the last 12 months, while the rate from ${run.mastitis_rate_period} implies about ${fmtInt(nextYear)} a year for a herd of ~${fmtInt(expectedMilking / 12)} milking cows. Treat the mastitis layer as an expectation, not a measurement.`,
    confidence: 'Limited',
    link: { label: 'See data coverage', workspace: 'confidence' },
  });

  /* Lactation-curve evidence. */
  const recent = run.coverage.filter((c) => c.year >= 2023);
  if (recent.length) {
    const fitted = run.coverage.filter((c) => c.reliable_cow_days > 10_000).map((c) => c.year);
    out.push({
      id: 'curve-evidence',
      kind: 'Data limitation',
      severity: 'routine',
      title: 'Lactation curves rest on older per-cow records',
      summary: `Reliable cow-days fall below ${fmtInt(Math.max(...recent.map((c) => c.reliable_cow_days)))} a year after 2022, so the curves are fitted mainly on ${fitted.length ? `${Math.min(...fitted)}–${Math.max(...fitted)}` : 'earlier years'}.`,
      confidence: 'Moderate',
      link: { label: 'See data coverage', workspace: 'confidence' },
    });
  }
  return out;
}

function flowlessSum(run: PfoiRun, series: SeriesId) {
  let total = 0;
  for (let h = 1; h <= 12; h++) {
    const r = forecastRow(run, 'month', targetPeriod(run, 'month', h), series);
    if (r) total += r.forecast;
  }
  return total;
}
