/**
 * Component 2 — Predictive Farm Intelligence
 * Shared vocabulary, deterministic RNG, calendar and lactation maths.
 *
 * All data in this folder is fictional synthetic scaffold data. It is not NLDB
 * data, not DelPro data, and does not represent research findings.
 */

/* ------------------------------------------------------------------ */
/* Deterministic RNG — the whole prototype must tell one stable story  */
/* ------------------------------------------------------------------ */

export function mulberry32(seed: number) {
  let s = seed >>> 0;
  return function () {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const round = (n: number, dp = 1) => Number(n.toFixed(dp));
export const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

export const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US');
export const fmtL = (n: number) => `${fmtInt(n)} L`;
export const fmtLKR = (thousands: number) =>
  `LKR ${Math.abs(thousands) >= 1000
    ? `${round(thousands / 1000, 2)}M`
    : `${fmtInt(thousands)}k`}`;
export const fmtPct = (n: number, dp = 1) => `${n > 0 ? '+' : ''}${round(n, dp)}%`;

/* ------------------------------------------------------------------ */
/* Standard confidence + evidence vocabulary (§23)                     */
/* ------------------------------------------------------------------ */

/** How much the system trusts a forecast. Never a probability. */
export type Confidence = 'High' | 'Moderate' | 'Limited';

/** Where a prediction's information comes from. */
export type EvidenceSource =
  | 'Individual'
  | 'Individual + peer'
  | 'Peer'
  | 'Herd'
  | 'Historical only';

export const CONFIDENCE_META: Record<
  Confidence,
  { color: string; bg: string; mark: string; blurb: string }
> = {
  High: {
    color: '#1f6b4a',
    bg: '#e3f1e9',
    mark: '●●●',
    blurb: 'Backed by strong recent observations for most of the animals involved.',
  },
  Moderate: {
    color: '#8a6414',
    bg: '#faf0d8',
    mark: '●●○',
    blurb: 'Usable for planning, but part of the estimate depends on future transitions.',
  },
  Limited: {
    color: '#8f3b30',
    bg: '#fbe9e6',
    mark: '●○○',
    blurb: 'Treat as indicative only. Evidence is sparse, stale or heavily peer-derived.',
  },
};

export const EVIDENCE_META: Record<EvidenceSource, { mark: string; blurb: string }> = {
  Individual: {
    mark: '◆',
    blurb: "Built from this animal's own recorded history.",
  },
  'Individual + peer': {
    mark: '◆◇',
    blurb: "Blends this animal's own record with comparable animals.",
  },
  Peer: {
    mark: '◇',
    blurb: 'Mainly derived from comparable animals; individual history is thin.',
  },
  Herd: {
    mark: '△',
    blurb: 'Falls back to a herd-level average. No usable comparable group.',
  },
  'Historical only': {
    mark: '▽',
    blurb: 'Descriptive history only. No forward estimate is published.',
  },
};

/* ------------------------------------------------------------------ */
/* Palette — scoped to Component 2 (§4)                                */
/* ------------------------------------------------------------------ */

export const C2 = {
  observed: '#1f6b4a', // deep green — brand / observed values
  observedSoft: '#d9ebe1',
  predicted: '#5b7fa6', // muted blue — predicted values
  predictedSoft: '#dfe8f1',
  caution: '#b8860b', // amber
  cautionSoft: '#faf0d8',
  concern: '#a44b3c', // muted red, material concerns only
  concernSoft: '#fbe9e6',
  ink: '#1d2b26',
  muted: '#6b7c75',
  line: '#dfe6e2',
  surface: '#ffffff',
} as const;

/* ------------------------------------------------------------------ */
/* Genetics                                                            */
/* ------------------------------------------------------------------ */

export const GENETIC_GROUPS = [
  'Imported Jersey (founder)',
  'F1 Jersey × Local',
  'F2 Jersey Cross',
  'F3 Jersey Cross',
  'Local / Indigenous',
  'Unknown parentage',
] as const;
export type GeneticGroup = (typeof GENETIC_GROUPS)[number];

export const GROUP_COLOR: Record<GeneticGroup, string> = {
  'Imported Jersey (founder)': '#14503a',
  'F1 Jersey × Local': '#1f6b4a',
  'F2 Jersey Cross': '#4d9070',
  'F3 Jersey Cross': '#87b8a0',
  'Local / Indigenous': '#b8860b',
  'Unknown parentage': '#9aa8a2',
};

/**
 * Generation in the grading-up programme. Unlike breed this is ordinal —
 * founder → F4+ is a progression — so it gets a sequential colour ramp rather
 * than a categorical palette, and the ramp direction carries meaning on its own.
 */
export const GENERATIONS = ['Founder', 'F1', 'F2', 'F3', 'F4+', 'Unknown'] as const;
export type Generation = (typeof GENERATIONS)[number];

export const GENERATION_COLOR: Record<Generation, string> = {
  Founder: '#0d3b2a',
  F1: '#1f6b4a',
  F2: '#41906a',
  F3: '#77b795',
  'F4+': '#b4d8c4',
  Unknown: '#b9c4bf',
};

/** Which generation each genetic group belongs to. */
export const GENERATION_OF: Record<GeneticGroup, Generation> = {
  'Imported Jersey (founder)': 'Founder',
  'F1 Jersey × Local': 'F1',
  'F2 Jersey Cross': 'F2',
  'F3 Jersey Cross': 'F3',
  'Local / Indigenous': 'Founder',
  'Unknown parentage': 'Unknown',
};

export const OPERATIONAL_GROUPS = [
  'Shed 1 — high yield',
  'Shed 2 — mid lactation',
  'Shed 3 — late lactation',
  'Dry & transition',
  'Youngstock',
] as const;
export type OperationalGroup = (typeof OPERATIONAL_GROUPS)[number];

/* ------------------------------------------------------------------ */
/* Animal states                                                       */
/* ------------------------------------------------------------------ */

export const PRODUCTION_STATES = ['Milking', 'Dry', 'Heifer', 'Calf', 'Male / bull'] as const;
export type ProductionState = (typeof PRODUCTION_STATES)[number];

export const REPRO_STATES = [
  'Voluntary wait',
  'Eligible to breed',
  'Bred — awaiting check',
  'Pregnant',
  'Repeat breeder',
  'No service recorded',
  'Not applicable',
] as const;
export type ReproState = (typeof REPRO_STATES)[number];

export type LactationStage =
  | 'Early / rising'
  | 'Approaching peak'
  | 'At peak'
  | 'Mid persistence'
  | 'Tapering'
  | 'Late lactation'
  | 'Dry period';

export const STAGE_ORDER: LactationStage[] = [
  'Early / rising',
  'Approaching peak',
  'At peak',
  'Mid persistence',
  'Tapering',
  'Late lactation',
  'Dry period',
];

export const STAGE_COLOR: Record<LactationStage, string> = {
  'Early / rising': '#87b8a0',
  'Approaching peak': '#4d9070',
  'At peak': '#1f6b4a',
  'Mid persistence': '#5b7fa6',
  Tapering: '#b8860b',
  'Late lactation': '#a44b3c',
  'Dry period': '#9aa8a2',
};

/* ------------------------------------------------------------------ */
/* Wood's lactation model:  y(t) = a · t^b · e^(−c·t)                  */
/* ------------------------------------------------------------------ */

export interface WoodsParams { a: number; b: number; c: number }

export const woodsYield = (p: WoodsParams, dim: number) =>
  dim <= 0 ? 0 : p.a * Math.pow(dim, p.b) * Math.exp(-p.c * dim);

/** Solve a and c so the curve peaks at `peakYield` on day `peakDay`. */
export function woodsFromPeak(peakYield: number, peakDay: number, b: number): WoodsParams {
  return {
    a: peakYield / (Math.pow(peakDay, b) * Math.exp(-b)),
    b,
    c: b / peakDay,
  };
}

export function lactationTotal(p: WoodsParams, from: number, to: number) {
  let sum = 0;
  for (let d = Math.max(1, from); d <= to; d++) sum += woodsYield(p, d);
  return sum;
}

export function stageFor(dim: number, peakDay: number): LactationStage {
  if (dim <= 0) return 'Dry period';
  if (dim < peakDay - 25) return 'Early / rising';
  if (dim < peakDay - 8) return 'Approaching peak';
  if (dim <= peakDay + 14) return 'At peak';
  if (dim < 185) return 'Mid persistence';
  if (dim < 265) return 'Tapering';
  if (dim <= 320) return 'Late lactation';
  return 'Dry period';
}

/* ------------------------------------------------------------------ */
/* Calendar — "today" is pinned so the demo is reproducible            */
/* ------------------------------------------------------------------ */

export const TODAY = new Date('2026-08-29T00:00:00Z');
export const DATA_THROUGH = new Date('2026-08-27T00:00:00Z');
export const GENERATED_AT = '2026-08-29 05:40 (+05:30)';
export const PREVIOUS_RUN = '2026-08-22 05:40 (+05:30)';

export const DAY_MS = 86400000;
export const addDays = (base: Date, days: number) => new Date(base.getTime() + days * DAY_MS);
export const dayDiff = (a: Date, b: Date) => Math.round((a.getTime() - b.getTime()) / DAY_MS);
export const isoDate = (d: Date) => d.toISOString().slice(0, 10);

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

export const shortDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return `${d.getUTCDate()} ${MONTH_ABBR[d.getUTCMonth()]}`;
};
export const longDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return `${d.getUTCDate()} ${MONTH_ABBR[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};
export const monthLabel = (key: string) => {
  const d = new Date(`${key}-01T00:00:00Z`);
  return `${MONTH_ABBR[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
};
export const monthKey = (d: Date) =>
  `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;

/** Maximum published forecast. Confidence is intentionally limited in year two. */
export const MAX_FORECAST_DAYS = 730;

/** Horizons offered by the persistent Component 2 control bar. */
export const HORIZONS = [
  { id: '30d', label: '30 days', days: 30 },
  { id: '90d', label: '90 days', days: 90 },
  { id: '12m', label: '12 months', days: 365 },
  { id: '18m', label: '18 months', days: 548 },
  { id: '24m', label: '24 months', days: MAX_FORECAST_DAYS },
] as const;
export type HorizonId = (typeof HORIZONS)[number]['id'];

/* ------------------------------------------------------------------ */
/* External context                                                    */
/* ------------------------------------------------------------------ */

/** Yield seasonality — the dry-season heat window depresses production. */
export const seasonalFactor = (monthIdx0: number) =>
  1 + 0.055 * Math.sin(((monthIdx0 - 2) / 12) * 2 * Math.PI);

/** Synthetic Temperature-Humidity Index for a calendar month. */
export const thiForMonth = (monthIdx0: number) =>
  round(74 + 5.5 * Math.sin(((monthIdx0 - 1) / 12) * 2 * Math.PI), 1);

export const rainfallForMonth = (monthIdx0: number) =>
  Math.round(55 + 190 * Math.max(0, Math.sin(((monthIdx0 - 3) / 12) * 2 * Math.PI)));

/* ------------------------------------------------------------------ */
/* The one coherent future event the whole prototype narrates (§6)     */
/* ------------------------------------------------------------------ */

export const EVENT_WINDOW = {
  start: '2026-10-14',
  end: '2026-10-28',
  label: '14–28 October',
  /** Milking cows scheduled or predicted to leave the milking herd. */
  dryOffs: 21,
  /** Cows expected to calve and enter/re-enter the milking herd. */
  entries: 17,
} as const;
