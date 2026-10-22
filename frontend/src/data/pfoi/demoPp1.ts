/**
 * Component 1 (PFOI): DEMO values for the PP1 development sections (F1–F9).
 *
 * Every number here is synthetic and fictional, like the rest of `demo.ts`: not Farm X
 * data, not a model result and not a backtest. It gives each new panel the exact shape the
 * model's run document will have, so the page can be built and reviewed before the
 * real-data runs come back.
 */

import type {
  GenerationOutcomeRow, HeatSummary, IntervalMethod, LadderRow, OutageRow, PfoiRun, RecordStatus,
  RegistryRow, ReproStepRow, ScenarioRow, WithheldRow,
} from './contract';

/** Demo forecast date inside a recording outage: milk is withheld, the herd is not. */
export const DEMO_OUTAGE_ORIGIN = '2025-03-01';
/** Demo forecast date with stale but usable milk records. */
export const DEMO_STALE_ORIGIN = '2024-07-01';

const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

function recordStatus(origin: string): RecordStatus {
  const withheld = origin === DEMO_OUTAGE_ORIGIN;
  const stale = origin === DEMO_STALE_ORIGIN;
  const staleness = withheld ? 170 : stale ? 12 : 1;
  const fresh = withheld ? 0 : stale ? 16 : 28;
  return {
    status: withheld ? 'withheld' : stale ? 'stale' : 'current',
    last_trusted_day: addDays(origin, -staleness),
    staleness_days: staleness,
    fresh_days: fresh,
    lookback_days: 28,
    checks: [
      { check: 'freshness', ok: staleness <= 3, value: staleness, detail: 'days since the last trusted milk day' },
      { check: 'completeness', ok: fresh >= 14, value: fresh, detail: 'trusted milk days in the last 28' },
      { check: 'plausibility', ok: withheld ? null : true, value: withheld ? null : 9.6,
        detail: 'litres per recorded milking cow-day (at most 20)' },
      { check: 'source_agreement', ok: withheld ? null : !stale, value: withheld ? null : stale ? 0.15 : 0.86,
        detail: 'share of DelPro milk tied to a cow' },
    ],
    milk_withheld: withheld,
    reason: withheld ? 'milk_withheld:no_trusted_recent_days' : null,
    reason_text: withheld
      ? 'No trusted milk records in the last 28 days and no earlier calibration, so no milk forecast is given. Herd numbers are still forecast.'
      : null,
    rule: 'display rule (docs/pp1_plan.md): current = trusted day within 3 days and no failed check',
  };
}

function withheldRows(origin: string): WithheldRow[] {
  if (origin !== DEMO_OUTAGE_ORIGIN) return [];
  return (['day', 'week', 'month'] as const).map((grain) => ({
    series: 'milk_litres', grain, from: origin, to: addDays(origin, 365), reason: 'milk_withheld:no_trusted_recent_days',
  }));
}

function outage(): OutageRow[] {
  const rows: OutageRow[] = [];
  const cells: [OutageRow['grain'], number][] = [['daily', 1], ['daily', 7], ['weekly', 1], ['weekly', 4]];
  for (const [grain, horizon] of cells) {
    rows.push({ gap_days: 0, resumed_days: 0, grain, horizon, n: 160, mae: 400, ratio_to_no_outage: 1, ratio_to_persistence: 1.02, bias: 15 });
    for (const gap of [28, 90, 180]) {
      for (const resumed of [0, 3, 7, 14]) {
        const cost = resumed === 0 ? 1 + gap / 150 : 1 + (gap / 600) / (1 + resumed / 3);
        rows.push({ gap_days: gap, resumed_days: resumed, grain, horizon, n: 160, mae: 400 * cost,
          ratio_to_no_outage: cost, ratio_to_persistence: resumed === 0 ? 0.9 : 1.0 + (cost - 1) / 2, bias: resumed === 0 ? 120 : 25 });
      }
    }
  }
  return rows;
}

function heat(origin: string, through?: string): HeatSummary {
  const last = addDays(origin, -6);
  const doy = (iso: string) => {
    const d = new Date(`${iso}T00:00:00Z`);
    return Math.floor((d.getTime() - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86_400_000);
  };
  const usual = (iso: string) => 80 + 3.5 * Math.sin((2 * Math.PI * (doy(iso) - 60)) / 365);
  const recent = Array.from({ length: 730 }, (_, i) => {
    const date = addDays(last, i - 729);
    const bump = i > 720 ? 2.2 : 0;
    const max = usual(date) + bump + 0.8 * Math.sin(i / 3);
    return { date, thi_mean: Math.round((max - 6) * 100) / 100, thi_max: Math.round(max * 100) / 100 };
  });
  const knots = { p75: 82.1, p90: 83.6 };
  const r2 = (v: number) => Math.round(v * 100) / 100;
  // Chance a normal value with this mean and spread is above t (Abramowitz-Stegun erf).
  const above = (mean: number, sd: number, t: number) => {
    const x = (t - mean) / (sd * Math.SQRT2);
    const k = 1 / (1 + 0.3275911 * Math.abs(x));
    const erf = 1 - k * (0.254829592 + k * (-0.284496736 + k * (1.421413741 + k * (-1.453152027 + k * 1.061405429)))) * Math.exp(-x * x);
    return Math.round(1000 * 0.5 * (1 - Math.sign(x) * erf)) / 1000;
  };
  const climatology = Array.from({ length: 90 }, (_, i) => {
    const date = addDays(origin, i);
    const p50 = usual(date);
    return {
      date, p10: r2(p50 - 2.4), p50: r2(p50), p90: r2(p50 + 2.1),
      share_above_p75: above(p50, 1.75, knots.p75), share_above_p90: above(p50, 1.75, knots.p90),
    };
  });
  return {
    last_weather_day: last, weather_lag_days: 6, knot_p75: knots.p75, knot_p90: knots.p90, hot_run_days: 5,
    heat_load_7d: 0.9, recent, climatology,
    realised: climatology.filter((c) => through != null && c.date <= through).map((c, i) => {
      const max = Math.round((c.p50 + 1.8 * Math.sin(i / 4)) * 100) / 100;
      return { date: c.date, thi_mean: max - 6, thi_max: max };
    }),
    source: 'demo: synthetic weather',
    forecast: {
      status: 'experimental', method: 'synthetic_demo_v2', trained_through: last, n_train: 0,
      thresholds: knots, taper_days: [20, 40], persistence_by_lead: { '7': 0.05, '14': 0.04, '30': 0.06 },
      predictions: climatology.map((c, i) => {
        // Fictional: a recent warm spell fading within about a week, then the season.
        const mean = c.p50 + (1.5 * Math.exp(-(i + 6) / 3) + 0.3) * Math.min(1, Math.max(0, (40 - i) / 20));
        const sd = Math.min(1.75, 1.2 + 0.04 * i);
        return {
          date: c.date, thi_max: r2(mean), seasonal: c.p50, lower: r2(mean - 1.28 * sd), upper: r2(mean + 1.28 * sd),
          p_above: { p75: above(mean, sd, knots.p75), p90: above(mean, sd, knots.p90) },
        };
      }),
    },
  };
}

const REPRO: ReproStepRow[] = (['2015-2019', '2020-2022', '2023-2026'] as const).flatMap((period, k) => [
  { period, step: 'first_ai', n: 900 - k * 150, median_days: 68 + k * 6, p25_days: 52 + k * 4, p75_days: 95 + k * 10,
    censored_share: 0.08 + k * 0.04, left_herd_share: 0.07, by_60d: 0.38 - k * 0.04, by_100d: 0.72 - k * 0.05,
    by_150d: 0.84 - k * 0.04, by_200d: 0.88 - k * 0.03, by_300d: 0.9 - k * 0.03 },
  { period, step: 'conception', n: 900 - k * 150, median_days: 118 + k * 22, p25_days: 82 + k * 10, p75_days: 190 + k * 30,
    censored_share: 0.1 + k * 0.05, left_herd_share: 0.1 + k * 0.02, by_60d: 0.08, by_100d: 0.38 - k * 0.06,
    by_150d: 0.6 - k * 0.07, by_200d: 0.71 - k * 0.06, by_300d: 0.79 - k * 0.06 },
  { period, step: 'pregnancy', n: 700 - k * 140, calved_share: 0.86 - k * 0.06, lost_share: 0.04 + k * 0.04,
    censored_share: 0.02 + k * 0.06, calved_of_resolved: 0.9 - k * 0.04, lost_of_resolved: 0.05 + k * 0.04 },
  { period, step: 'calving_interval', n: 900 - k * 150, median_days: 402 + k * 25, p25_days: 370 + k * 15, p75_days: 460 + k * 35,
    censored_share: 0.12 + k * 0.08, left_herd_share: 0.18 },
]);

const GENERATION: GenerationOutcomeRow[] = (['2020-2022', '2023-2026'] as const).flatMap((period) =>
  (['0', '1', '2'] as const).flatMap((g, i) => [
    { period, generation_group: g, outcome: 'yield_vs_expected', value: 1.02 - i * 0.02, n: 40_000 - i * 12_000 },
    { period, generation_group: g, outcome: 'yield_record_coverage', value: period === '2020-2022' ? 0.6 - i * 0.05 : 0.08, n: 90_000 - i * 25_000 },
    { period, generation_group: g, outcome: 'productive_share', value: 0.82 - i * 0.02, n: 120_000 - i * 30_000 },
    { period, generation_group: g, outcome: 'days_to_conception_median', value: 120 + i * 18, n: 300 - i * 80 },
    { period, generation_group: g, outcome: 'pregnancy_calved_share', value: 0.86 - i * 0.03, n: 240 - i * 60 },
    ...(period === '2023-2026' ? [{ period, generation_group: g, outcome: 'persistent_alarm_share', value: 0.03 + i * 0.006, n: 20_000 - i * 6_000 }] : []),
  ]));

const LADDER: LadderRow[] = (['all', 'normal', 'heat', 'recovery'] as const).flatMap((band) =>
  ([['daily', 7], ['weekly', 4]] as const).flatMap(([grain, horizon]) => {
    const n = band === 'all' ? 180 : band === 'normal' ? 140 : band === 'heat' ? 22 : 9;
    const base = band === 'recovery' ? 1.25 : band === 'heat' ? 1.05 : 1.0;
    const rungs: [string, number, LadderRow['status']][] = [
      ['persistence', 1, 'development'],
      ['current model', 1.01 * base, 'development'],
      ['+ recent records', 0.97 * base, 'development'],
      ['+ heat', 0.96 * base, 'development'],
      ['+ sensors', 0.96 * base, 'cannot be validated with current data'],
      ['oracle heat', 0.93 * base, 'oracle'],
    ];
    return rungs.map(([rung, ratio, status]) => ({
      rung, grain, horizon, band, n, mae: 450 * ratio, bias: 20 * ratio, wape: 0.06 * ratio,
      ratio_to_reference: rung === 'persistence' ? 1 : ratio,
      status: n < 12 && status !== 'oracle' ? 'not interpretable' : status,
    }));
  }));

const REGISTRY: RegistryRow[] = [
  { feature: 'heat_load_7d', active: 300 },
  { feature: 'thi_max_3d', active: 300 },
  { feature: 'persistent_alarm_share_7d', shadow: 290, probation: 10 },
  { feature: 'combined_alarm_share_7d', shadow: 300 },
  { feature: 'yield_vs_expected_7d', shadow: 295, probation: 5 },
  { feature: 'mastitis_per_cow_28d', shadow: 120, active: 180 },
];

export function demoScenarios(run: Partial<PfoiRun>): ScenarioRow[] {
  const resp: Record<string, [number, number, number]> = {  // median, low, high by horizon 1..12
    'herd contraction': [-0.18, -0.3, -0.08],
    'abortion surges': [-0.06, -0.12, -0.01],
  };
  const out: ScenarioRow[] = [];
  for (const [kind, [med, lo, hi]] of Object.entries(resp)) {
    for (const series of ['milk_litres', 'milking', 'total_herd'] as const) {
      (run.outlook ?? []).filter((r) => r.grain === 'month' && r.series === series).forEach((r) => {
        const ramp = Math.min(1, r.horizon / 4);
        out.push({
          kind, label: kind, series, target_period: r.target_period, horizon: r.horizon, forecast: r.forecast,
          scenario: r.forecast * (1 + med * ramp), low: r.forecast * (1 + lo * ramp), high: r.forecast * (1 + hi * ramp),
          n_episodes: 2,
          sentence: `In the 2 earlier ${kind}, this series 3 months after the start was ${Math.round(-med * 75)}% below the forecast. This is what happened before, not a proven cause. (Demo values.)`,
        });
      });
    }
  }
  return out;
}

/** The PP1 sections of the demo run at one forecast date. */
export function demoPp1(origin: string, through?: string): Partial<PfoiRun> {
  const rs = recordStatus(origin);
  const interval: IntervalMethod = { milk: 'aci_quality_band', staleness_scale: 'demo', staleness_days: rs.staleness_days };
  return {
    record_status: rs,
    withheld: withheldRows(origin),
    interval_method: interval,
    outage_simulation: outage(),
    heat: heat(origin, through),
    repro_timing: REPRO,
    generation_outcomes: GENERATION,
    evidence_ladder: LADDER,
    feature_registry: REGISTRY,
  };
}
