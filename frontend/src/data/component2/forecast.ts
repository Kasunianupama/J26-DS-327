/**
 * Component 2 — the forecast spine.
 *
 * Future milk is not an independent time-series model: it is the sum of the
 * individual lactation curves rolled forward, minus scheduled dry-offs, plus
 * the animals expected to calve. Products, revenue and margin are then derived
 * from that single milk series, which is why every screen reconciles.
 */

import {
  DAY_MS,
  EVENT_WINDOW,
  MAX_FORECAST_DAYS,
  TODAY,
  addDays,
  clamp,
  dayDiff,
  isoDate,
  monthKey,
  monthLabel,
  mulberry32,
  rainfallForMonth,
  round,
  seasonalFactor,
  thiForMonth,
  woodsYield,
  type Confidence,
} from './core';
import {
  CALVES,
  DRY_COWS,
  HEIFERS,
  HERD,
  MALES,
  MILKING,
  type Animal,
  type ContributionType,
} from './herd';

/** Complete daily records begin on 1 January 2024. Keep every derived series
 * on this same window so timelines, product output and finance reconcile. */
export const HISTORY_DAYS = dayDiff(TODAY, new Date('2024-01-01T00:00:00Z'));
export const FUTURE_DAYS = MAX_FORECAST_DAYS;

const LAYERS: ContributionType[] = [
  'Established milkers',
  'Approaching peak',
  'Tapering cows',
  'New entrants — scheduled',
  'New entrants — predicted',
];

export interface DayPoint {
  date: string;
  offset: number; // days from TODAY, negative = past
  /** Recorded milk. Null in the future. */
  observed: number | null;
  /** Model expectation. Null in the past. */
  expected: number | null;
  lower: number | null;
  upper: number | null;
  milkers: number;
  calvings: number;
  dryOffs: number;
  layers: Record<ContributionType, number>;
  /** Share of the day's milk that depends on a transition that has not happened. */
  transitionShare: number;
  confidence: Confidence;
  thi: number;
}

/* ------------------------------------------------------------------ */
/* Daily series                                                        */
/* ------------------------------------------------------------------ */

interface Transition {
  calve: number | null;
  dryOff: number | null;
  /** Modelled re-entry for animals without a confirmed pregnancy. */
  predicted: number | null;
  probability: number;
}

const transitionCache = new Map<string, Transition>();
function transitions(a: Animal): Transition {
  let t = transitionCache.get(a.id);
  if (!t) {
    t = {
      calve: a.expectedCalving ? dayDiff(new Date(`${a.expectedCalving}T00:00:00Z`), TODAY) : null,
      dryOff: a.dryOffDate ? dayDiff(new Date(`${a.dryOffDate}T00:00:00Z`), TODAY) : null,
      predicted: a.predictedCalving ? dayDiff(new Date(`${a.predictedCalving}T00:00:00Z`), TODAY) : null,
      probability: a.entryProbability,
    };
    transitionCache.set(a.id, t);
  }
  return t;
}

function futureDay(t: number) {
  const date = addDays(TODAY, t);
  const season = seasonalFactor(date.getUTCMonth());
  const layers: Record<ContributionType, number> = {
    'Established milkers': 0,
    'Approaching peak': 0,
    'Tapering cows': 0,
    'New entrants — scheduled': 0,
    'New entrants — predicted': 0,
  };
  let milkers = 0;
  let calvings = 0;
  let dryOffs = 0;
  let transitionMilk = 0;

  for (const a of HERD) {
    const tr = transitions(a);
    if (tr.calve === t) calvings++;
    if (tr.dryOff === t) dryOffs++;

    let y = 0;
    let layer: ContributionType = a.contributionType;
    // Probability-weighted animals count as a fraction of a milking head.
    let head = 1;

    if (a.prodState === 'Milking') {
      if (tr.dryOff !== null && t > tr.dryOff) {
        if (tr.calve !== null && t > tr.calve) {
          y = woodsYield(a.woods, t - tr.calve);
          layer = a.transitionConfirmed ? 'New entrants — scheduled' : 'New entrants — predicted';
          transitionMilk += y;
        }
      } else {
        const dim = a.dim + t;
        y = woodsYield(a.woods, dim);
        // Re-classify as the animal moves along its own curve.
        layer =
          dim < a.peakDay + 14 ? 'Approaching peak'
          : dim >= 185 ? 'Tapering cows'
          : 'Established milkers';
      }
    } else if (tr.calve !== null && t > tr.calve) {
      y = woodsYield(a.woods, t - tr.calve);
      layer = a.transitionConfirmed ? 'New entrants — scheduled' : 'New entrants — predicted';
      transitionMilk += y;
    }

    // Probabilistic re-entry: an animal with no confirmed pregnancy still
    // contributes its expected milk weighted by the chance the service holds.
    if (y === 0 && tr.predicted !== null && t > tr.predicted) {
      y = woodsYield(a.woods, t - tr.predicted) * tr.probability;
      layer = 'New entrants — predicted';
      head = tr.probability;
      transitionMilk += y;
    }

    if (y > 0) {
      layers[layer] += y * season;
      milkers += head;
    }
  }

  const total = LAYERS.reduce((s, k) => s + layers[k], 0);
  const transitionShare = total > 0 ? transitionMilk * season / total : 0;
  // Uncertainty widens with horizon and with dependence on future transitions.
  const spread = total * (0.03 + (t / FUTURE_DAYS) * 0.12 + transitionShare * 0.09);

  const confidence: Confidence =
    t <= 30 && transitionShare < 0.2 ? 'High'
    : t <= 150 && transitionShare < 0.38 ? 'Moderate'
    : 'Limited';

  LAYERS.forEach((k) => (layers[k] = Math.round(layers[k])));

  return {
    date: isoDate(date),
    offset: t,
    observed: null,
    expected: Math.round(total),
    lower: Math.round(total - spread),
    upper: Math.round(total + spread),
    milkers: Math.round(milkers),
    calvings,
    dryOffs,
    layers,
    transitionShare: round(transitionShare, 3),
    confidence,
    thi: thiForMonth(date.getUTCMonth()),
  } satisfies DayPoint;
}

function buildDaily(): DayPoint[] {
  const out: DayPoint[] = [];
  const rnd = mulberry32(414141);

  // Anchor everything on today's actual summed cow yield.
  const anchor = MILKING.reduce((s, a) => s + a.currentYield, 0);
  const anchorSeason = seasonalFactor(TODAY.getUTCMonth());

  for (let t = -HISTORY_DAYS; t < 0; t++) {
    const date = addDays(TODAY, t);
    const season = seasonalFactor(date.getUTCMonth());
    const trend = 1 + t * 0.00018; // slow herd improvement toward today
    const noise = 0.972 + rnd() * 0.056;
    const observed = Math.round((anchor * season / anchorSeason) * trend * noise);
    const empty: Record<ContributionType, number> = {
      'Established milkers': 0,
      'Approaching peak': 0,
      'Tapering cows': 0,
      'New entrants — scheduled': 0,
      'New entrants — predicted': 0,
    };
    out.push({
      date: isoDate(date),
      offset: t,
      observed,
      expected: null,
      lower: null,
      upper: null,
      milkers: Math.round(MILKING.length * trend * (0.96 + rnd() * 0.08)),
      calvings: rnd() < 0.14 ? 1 : 0,
      dryOffs: rnd() < 0.13 ? 1 : 0,
      layers: empty,
      transitionShare: 0,
      confidence: 'High',
      thi: thiForMonth(date.getUTCMonth()),
    });
  }

  // Today is both the last observation and the forecast anchor. Take the value
  // from the forward model so the observed and predicted series meet exactly and
  // the milk waterfall reconciles against the layer decomposition.
  const today0 = futureDay(0);
  out.push({ ...today0, observed: today0.expected });

  for (let t = 1; t <= FUTURE_DAYS; t++) out.push(futureDay(t));
  return out;
}

export const DAILY = buildDaily();
export const DAY_INDEX = new Map(DAILY.map((d) => [d.date, d]));
export const dayFor = (iso: string) => DAY_INDEX.get(iso);
export const TODAY_ISO = isoDate(TODAY);

/* ------------------------------------------------------------------ */
/* Bucketing                                                           */
/* ------------------------------------------------------------------ */

export interface Bucket {
  key: string;
  label: string;
  start: string;
  end: string;
  future: boolean;
  observed: number | null;
  expected: number | null;
  /** Observed where recorded, expected elsewhere. Always a complete bucket. */
  total: number;
  lower: number | null;
  upper: number | null;
  milkers: number;
  calvings: number;
  dryOffs: number;
  layers: Record<ContributionType, number>;
  transitionShare: number;
  confidence: Confidence;
  thi: number;
  rainfall: number;
}

function reduceBucket(key: string, label: string, days: DayPoint[]): Bucket {
  const sum = (f: (d: DayPoint) => number | null) =>
    days.reduce((s, d) => s + (f(d) ?? 0), 0);
  const anyObserved = days.some((d) => d.observed !== null);
  const anyExpected = days.some((d) => d.expected !== null);
  const layers = LAYERS.reduce((acc, k) => {
    acc[k] = days.reduce((s, d) => s + d.layers[k], 0);
    return acc;
  }, {} as Record<ContributionType, number>);
  const worst = days.some((d) => d.confidence === 'Limited') ? 'Limited'
    : days.some((d) => d.confidence === 'Moderate') ? 'Moderate' : 'High';
  const month0 = new Date(`${days[0].date}T00:00:00Z`).getUTCMonth();

  return {
    key,
    label,
    start: days[0].date,
    end: days[days.length - 1].date,
    future: days[days.length - 1].offset > 0,
    observed: anyObserved ? Math.round(sum((d) => d.observed)) : null,
    expected: anyExpected ? Math.round(sum((d) => d.expected)) : null,
    total: Math.round(days.reduce((s, d) => s + (d.expected ?? d.observed ?? 0), 0)),
    lower: anyExpected ? Math.round(sum((d) => d.lower)) : null,
    upper: anyExpected ? Math.round(sum((d) => d.upper)) : null,
    milkers: Math.round(days.reduce((s, d) => s + d.milkers, 0) / days.length),
    calvings: sum((d) => d.calvings),
    dryOffs: sum((d) => d.dryOffs),
    layers,
    transitionShare: round(days.reduce((s, d) => s + d.transitionShare, 0) / days.length, 3),
    confidence: worst as Confidence,
    thi: thiForMonth(month0),
    rainfall: rainfallForMonth(month0),
  };
}

/** Group the daily series into ISO-week buckets. */
export function weekly(fromOffset: number, toOffset: number): Bucket[] {
  const days = DAILY.filter((d) => d.offset >= fromOffset && d.offset <= toOffset);
  const groups = new Map<string, DayPoint[]>();
  for (const d of days) {
    const dt = new Date(`${d.date}T00:00:00Z`);
    const monday = new Date(dt.getTime() - ((dt.getUTCDay() + 6) % 7) * DAY_MS);
    const k = isoDate(monday);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(d);
  }
  return [...groups.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([k, ds]) => reduceBucket(k, `w/c ${new Date(`${k}T00:00:00Z`).getUTCDate()} ${monthLabel(k.slice(0, 7)).split(' ')[0]}`, ds));
}

/** Group the daily series into calendar-month buckets. */
export function monthly(fromOffset: number, toOffset: number): Bucket[] {
  const days = DAILY.filter((d) => d.offset >= fromOffset && d.offset <= toOffset);
  const groups = new Map<string, DayPoint[]>();
  for (const d of days) {
    const k = d.date.slice(0, 7);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(d);
  }
  return [...groups.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([k, ds]) => reduceBucket(k, monthLabel(k), ds));
}

export const MONTHS_ALL = monthly(-HISTORY_DAYS, FUTURE_DAYS);
export const WEEKS_ALL = weekly(-HISTORY_DAYS, FUTURE_DAYS);

/* ------------------------------------------------------------------ */
/* The defining future movement (§7)                                   */
/* ------------------------------------------------------------------ */

const meanExpected = (from: number, to: number) => {
  const d = DAILY.filter((x) => x.offset >= from && x.offset <= to && x.expected !== null);
  return d.reduce((s, x) => s + (x.expected ?? 0), 0) / Math.max(1, d.length);
};

const eventStartOffset = dayDiff(new Date(`${EVENT_WINDOW.start}T00:00:00Z`), TODAY);
const eventEndOffset = dayDiff(new Date(`${EVENT_WINDOW.end}T00:00:00Z`), TODAY);

const baselineDaily = meanExpected(1, 30);

/**
 * Locate the deepest 14-day stretch inside and just after the transition
 * cluster, rather than assuming where the trough lands. The headline percentage
 * is then read off the series instead of being asserted.
 */
const troughCentre = (() => {
  let best = { offset: eventStartOffset, value: Infinity };
  for (let t = eventStartOffset; t <= eventEndOffset + 24; t++) {
    const v = meanExpected(t - 7, t + 6);
    if (v < best.value) best = { offset: t, value: v };
  }
  return best;
})();
const troughDaily = troughCentre.value;
const dropPct = round(((baselineDaily - troughDaily) / baselineDaily) * 100, 1);

export const DEFINING_MOVEMENT = {
  anchorDaily: Math.round(DAILY.find((d) => d.offset === 0)!.expected!),
  baselineDaily: Math.round(baselineDaily),
  troughDaily: Math.round(troughDaily),
  dropPct,
  /** Rounded outward so the headline band always contains the point estimate. */
  dropBand: [Math.max(1, Math.floor(dropPct - 1)), Math.ceil(dropPct + 1)] as [number, number],
  windowLabel: EVENT_WINDOW.label,
  windowStart: EVENT_WINDOW.start,
  windowEnd: EVENT_WINDOW.end,
  startOffset: eventStartOffset,
  endOffset: eventEndOffset,
  dryOffs: DAILY.filter((d) => d.offset >= eventStartOffset && d.offset <= eventEndOffset)
    .reduce((s, d) => s + d.dryOffs, 0),
  entries: DAILY.filter((d) => d.offset >= eventStartOffset && d.offset <= eventEndOffset)
    .reduce((s, d) => s + d.calvings, 0),
  troughOffset: troughCentre.offset,
  troughDate: isoDate(addDays(TODAY, troughCentre.offset)),
  lowerDaily: Math.round(
    DAILY.filter((d) => Math.abs(d.offset - troughCentre.offset) <= 7)
      .reduce((s, d) => s + (d.lower ?? 0), 0) / 15),
  upperDaily: Math.round(
    DAILY.filter((d) => Math.abs(d.offset - troughCentre.offset) <= 7)
      .reduce((s, d) => s + (d.upper ?? 0), 0) / 15),
  confidence: 'Moderate' as Confidence,
};

/* ------------------------------------------------------------------ */
/* Herd state series (§15)                                             */
/* ------------------------------------------------------------------ */

export interface HerdStatePoint {
  key: string;
  label: string;
  future: boolean;
  Milking: number;
  Dry: number;
  Heifer: number;
  Calf: number;
  'Male / bull': number;
  entries: number;
  exits: number;
  lower: number;
  upper: number;
}

export const HERD_STATE_SERIES: HerdStatePoint[] = MONTHS_ALL.map((m, i, arr) => {
  const rnd = mulberry32(7000 + i);
  const drift = (i - arr.findIndex((x) => x.future)) * 0.6;
  const milking = m.future ? m.milkers : Math.round(MILKING.length - drift * 0.4 + (rnd() - 0.5) * 6);
  const dry = Math.round(DRY_COWS.length + (rnd() - 0.5) * 8 - drift * 0.2);
  const spread = m.future ? 3 + Math.abs(drift) * 0.5 : 0;
  return {
    key: m.key,
    label: m.label,
    future: m.future,
    Milking: milking,
    Dry: dry,
    Heifer: Math.round(HEIFERS.length + (rnd() - 0.5) * 6),
    Calf: Math.round(CALVES.length + (rnd() - 0.5) * 8),
    'Male / bull': Math.round(MALES.length + (rnd() - 0.5) * 3),
    entries: m.calvings,
    exits: m.dryOffs,
    lower: Math.round(milking - spread),
    upper: Math.round(milking + spread),
  };
});

/* ------------------------------------------------------------------ */
/* Genetic composition over time (§16)                                 */
/* ------------------------------------------------------------------ */

export const COMPOSITION_SERIES = MONTHS_ALL.map((m, i, arr) => {
  const drift = i / (arr.length - 1);
  const raw: Record<string, number> = {
    'Imported Jersey (founder)': 7 - drift * 3,
    'F1 Jersey × Local': 25 - drift * 8,
    'F2 Jersey Cross': 29 + drift * 1,
    'F3 Jersey Cross': 18 + drift * 12,
    'Local / Indigenous': 13 - drift * 2,
    'Unknown parentage': 8 + drift * 0,
  };
  const sum = Object.values(raw).reduce((a, b) => a + b, 0);
  const norm: Record<string, number> = {};
  for (const k of Object.keys(raw)) norm[k] = round((raw[k] / sum) * 100, 1);
  return { key: m.key, label: m.label, future: m.future, ...norm };
});

/* ------------------------------------------------------------------ */
/* Cross-domain lookup for the master tooltip / selected date (§8, §28) */
/* ------------------------------------------------------------------ */

export interface CrossDomain {
  date: string;
  label: string;
  future: boolean;
  milk: number;
  range: [number, number] | null;
  milkers: [number, number];
  calvings: number;
  dryOffs: number;
  confidence: Confidence;
  transitionShare: number;
  thi: number;
  productConstraint: 'None' | 'Mild' | 'Moderate' | 'High';
  margin: number;
  revenue: number;
  cost: number;
}

export function crossDomainFor(iso: string): CrossDomain | null {
  const d = dayFor(iso);
  if (!d) return null;
  const week = DAILY.filter((x) => Math.abs(x.offset - d.offset) <= 3);
  const milk = week.reduce((s, x) => s + (x.expected ?? x.observed ?? 0), 0);
  const lower = week.reduce((s, x) => s + (x.lower ?? x.observed ?? 0), 0);
  const upper = week.reduce((s, x) => s + (x.upper ?? x.observed ?? 0), 0);
  const milkersLo = Math.min(...week.map((x) => x.milkers));
  const milkersHi = Math.max(...week.map((x) => x.milkers));

  // Product constraint rises as weekly milk falls below the packing plan.
  const shortfall = (TETRA_WEEKLY_REQUIREMENT - milk) / TETRA_WEEKLY_REQUIREMENT;
  const productConstraint =
    shortfall > 0.06 ? 'High' : shortfall > 0.025 ? 'Moderate' : shortfall > 0 ? 'Mild' : 'None';

  const revenue = round((milk * BLENDED_PRICE) / 1000, 0);
  const cost = round(revenue * 0.83, 0);

  return {
    date: iso,
    label: `Week of ${new Date(`${iso}T00:00:00Z`).getUTCDate()} ${monthLabel(iso.slice(0, 7)).split(' ')[0]}`,
    future: d.offset > 0,
    milk: Math.round(milk),
    range: d.offset > 0 ? [Math.round(lower), Math.round(upper)] : null,
    milkers: [milkersLo, milkersHi],
    calvings: week.reduce((s, x) => s + x.calvings, 0),
    dryOffs: week.reduce((s, x) => s + x.dryOffs, 0),
    confidence: d.confidence,
    transitionShare: d.transitionShare,
    thi: d.thi,
    productConstraint,
    margin: revenue - cost,
    revenue,
    cost,
  };
}

/** Weekly milk needed to keep the tetra-pack line at its normal run rate. */
export const TETRA_WEEKLY_REQUIREMENT = Math.round(baselineDaily * 7 * 0.95);
/** Blended LKR per litre across the current product mix. */
export const BLENDED_PRICE = 158;

/* ------------------------------------------------------------------ */
/* Milk change waterfall (§11)                                         */
/* ------------------------------------------------------------------ */

export interface WaterfallStep {
  label: string;
  value: number;
  kind: 'anchor' | 'increase' | 'decrease' | 'total';
  detail: string;
}

export function milkWaterfall(fromIso: string, toIso: string): WaterfallStep[] {
  const a = dayFor(fromIso);
  const b = dayFor(toIso);
  if (!a || !b) return [];
  const from = a.offset <= b.offset ? a : b;
  const to = a.offset <= b.offset ? b : a;

  const start = from.expected ?? from.observed ?? 0;
  const end = to.expected ?? to.observed ?? 0;

  const dTaper = to.layers['Tapering cows'] - from.layers['Tapering cows'];
  const dEstablished = to.layers['Established milkers'] - from.layers['Established milkers'];
  const dPeak = to.layers['Approaching peak'] - from.layers['Approaching peak'];
  const dScheduled = to.layers['New entrants — scheduled'] - from.layers['New entrants — scheduled'];
  const dPredicted = to.layers['New entrants — predicted'] - from.layers['New entrants — predicted'];

  const dryOffs = DAILY.filter((d) => d.offset > from.offset && d.offset <= to.offset)
    .reduce((s, d) => s + d.dryOffs, 0);
  const calvings = DAILY.filter((d) => d.offset > from.offset && d.offset <= to.offset)
    .reduce((s, d) => s + d.calvings, 0);

  const steps: WaterfallStep[] = [
    { label: 'Expected milk — start', value: Math.round(start), kind: 'anchor', detail: `Daily expectation on ${from.date}` },
    { label: 'Tapering cows', value: Math.round(dTaper), kind: dTaper >= 0 ? 'increase' : 'decrease', detail: 'Movement of cows past 185 days in milk' },
    { label: 'Dry-offs', value: Math.round(dEstablished), kind: dEstablished >= 0 ? 'increase' : 'decrease', detail: `${dryOffs} animals leaving the milking herd in this period` },
    { label: 'Peak-production gains', value: Math.round(dPeak), kind: dPeak >= 0 ? 'increase' : 'decrease', detail: 'Cows climbing toward or holding peak' },
    { label: 'New lactations — scheduled', value: Math.round(dScheduled), kind: dScheduled >= 0 ? 'increase' : 'decrease', detail: `${calvings} expected calvings, confirmed records` },
    { label: 'New lactations — predicted', value: Math.round(dPredicted), kind: dPredicted >= 0 ? 'increase' : 'decrease', detail: 'Entries that depend on a transition that has not happened yet' },
    { label: 'Expected milk — end', value: Math.round(end), kind: 'total', detail: `Daily expectation on ${to.date}` },
  ];
  return steps;
}

/* ------------------------------------------------------------------ */
/* Layer / cohort drill-down (§10)                                     */
/* ------------------------------------------------------------------ */

export type GroupingKey =
  | 'Contribution type'
  | 'Parity'
  | 'Genetic group'
  | 'Operational group'
  | 'Lactation stage'
  | 'Prediction source';

export function groupValue(a: Animal, key: GroupingKey): string {
  switch (key) {
    case 'Contribution type': return a.contributionType;
    case 'Parity': return a.parity === 0 ? 'Youngstock' : `Parity ${a.parity}`;
    case 'Genetic group': return a.geneticGroup;
    case 'Operational group': return a.opGroup;
    case 'Lactation stage': return a.stage;
    case 'Prediction source': return a.evidence;
  }
}

/** Contributing animals for one layer of the river, ranked by 90-day litres. */
export function animalsInLayer(key: GroupingKey, value: string): Animal[] {
  return HERD.filter((a) => a.contribution90 > 0 && groupValue(a, key) === value)
    .sort((x, y) => y.contribution90 - x.contribution90);
}

export function layerSeries(key: GroupingKey, horizonDays: number) {
  const buckets = horizonDays <= 90 ? weekly(0, horizonDays) : monthly(0, horizonDays);
  const values = [...new Set(HERD.filter((a) => a.contribution90 > 0).map((a) => groupValue(a, key)))];

  // Split each bucket's total milk by the group's share of 90-day contribution.
  const totalContribution = HERD.reduce((s, a) => s + a.contribution90, 0);
  const shares = new Map(
    values.map((v) => [
      v,
      HERD.filter((a) => groupValue(a, key) === v)
        .reduce((s, a) => s + a.contribution90, 0) / totalContribution,
    ]),
  );

  const rows = buckets.map((bk) => {
    const row: Record<string, string | number | boolean> = {
      label: bk.label,
      key: bk.key,
      start: bk.start,
      future: bk.future,
      total: bk.expected ?? 0,
    };
    if (key === 'Contribution type') {
      for (const l of LAYERS) row[l] = Math.round(bk.layers[l]);
    } else {
      for (const v of values) row[v] = Math.round((bk.expected ?? 0) * (shares.get(v) ?? 0));
    }
    return row;
  });

  const keys = key === 'Contribution type' ? LAYERS : values;
  return { rows, keys };
}

export { LAYERS };
