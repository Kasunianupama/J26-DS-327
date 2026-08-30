/**
 * Component 2 — herd composition at an arbitrary point in time.
 *
 * The timeline player needs to answer "what did / will the herd look like on
 * this day?" for any day in the window. Rather than storing a snapshot per day,
 * each animal is re-classified against its own transition dates, so the
 * pictogram view and the milk forecast can never drift apart.
 */

import {
  GENERATIONS,
  GENERATION_OF,
  GENETIC_GROUPS,
  MAX_FORECAST_DAYS,
  TODAY,
  addDays,
  dayDiff,
  isoDate,
  mulberry32,
  round,
  type GeneticGroup,
  type Generation,
  type ProductionState,
} from './core';
import { HERD, type Animal } from './herd';

export const GROUP_ORDER: ProductionState[] = ['Milking', 'Dry', 'Heifer', 'Calf', 'Male / bull'];

export interface HerdSnapshot {
  date: string;
  offset: number;
  total: number;
  counts: Record<ProductionState, number>;
  pregnant: number;
  /** Animal ids per state, so the pictogram can colour each glyph. */
  members: Record<ProductionState, Animal[]>;
  composition: { group: GeneticGroup; count: number; share: number }[];
  generations: { generation: Generation; count: number; share: number }[];
  exits: { deaths: number; sales: number; transfers: number; total: number };
}

const offsetOf = (iso: string | null) =>
  iso ? dayDiff(new Date(`${iso}T00:00:00Z`), TODAY) : null;

const cache = new Map<string, { calve: number | null; dry: number | null; pred: number | null }>();
function tr(a: Animal) {
  let v = cache.get(a.id);
  if (!v) {
    v = { calve: offsetOf(a.expectedCalving), dry: offsetOf(a.dryOffDate), pred: offsetOf(a.predictedCalving) };
    cache.set(a.id, v);
  }
  return v;
}

/** Length of a full reproductive cycle: ~305 days milking plus a ~90-day rest. */
const CYCLE = 395;

/**
 * Which production state an animal occupies `t` days from today, or `null` if
 * it had not been born yet.
 *
 * Forwards, this follows the animal's own recorded and predicted transition
 * dates. Backwards, there are no stored historical states, so the lactation
 * cycle is walked in reverse from the current days-in-milk and the animal is
 * aged down through heifer and calf. That is why the herd is smaller in 2024
 * than it is today.
 */
export function stateAt(a: Animal, t: number): ProductionState | null {
  const ageThen = a.ageMonths + t / 30.44;
  if (ageThen < 0) return null; // not yet born

  if (a.sex === 'M') return ageThen < 12 ? 'Calf' : 'Male / bull';
  if (ageThen < 13) return 'Calf';

  const { calve, dry, pred } = tr(a);
  const entry = calve ?? pred;

  // Youngstock today: heifer until their first calving lands.
  if (a.prodState === 'Calf' || a.prodState === 'Heifer') {
    if (entry !== null && t > entry) return 'Milking';
    return 'Heifer';
  }

  // Adults, looking forward: follow the explicit transition dates.
  if (t >= 0) {
    if (a.prodState === 'Milking') {
      if (dry !== null && t > dry) return entry !== null && t > entry ? 'Milking' : 'Dry';
      return 'Milking';
    }
    return entry !== null && t > entry ? 'Milking' : 'Dry';
  }

  // Adults, looking back: nothing was milking before its first calving, which
  // in this herd lands around 26 months.
  if (ageThen < FIRST_CALVING_MONTHS) return 'Heifer';
  return cyclePhase(a, t) < 305 ? 'Milking' : 'Dry';
}

/** Age at first calving in this herd, used to age adults back into heifers. */
const FIRST_CALVING_MONTHS = 26;

/** Position within the repeating lactation cycle, in days since calving. */
function cyclePhase(a: Animal, t: number) {
  const lactStart = a.prodState === 'Milking' ? -a.dim : (offsetOf(a.lastCalving) ?? -330);
  return (((t - lactStart) % CYCLE) + CYCLE) % CYCLE;
}

/**
 * Whether an animal was carrying a calf on a given day. Forward, this comes
 * from the recorded or predicted calving date; backward, it falls back to the
 * cycle, where conception sits roughly 85 days after calving.
 */
function pregnantAt(a: Animal, t: number, state: ProductionState) {
  if (state === 'Calf' || state === 'Male / bull') return false;
  const { calve, pred } = tr(a);
  const entry = calve ?? pred;
  if (t >= 0) return entry !== null && t <= entry && t > entry - 283;
  if (a.prodState !== 'Milking' && a.prodState !== 'Dry') return false;
  if (a.ageMonths + t / 30.44 < FIRST_CALVING_MONTHS) return false;
  return cyclePhase(a, t) > 85;
}

/** Cumulative exits since 1 Jan 2024, reconciled before display. */
function exitsAt(t: number) {
  const days = Math.max(0, t + dayDiff(TODAY, new Date('2024-01-01T00:00:00Z')));
  const rnd = mulberry32(9911);
  // Steady deterministic rates, so the number only ever grows with time.
  const deaths = Math.floor(days * 0.0104 + rnd() * 0.5);
  const sales = Math.floor(days * 0.0221 + rnd() * 0.5);
  const transfers = Math.floor(days * 0.0097 + rnd() * 0.5);
  return { deaths, sales, transfers, total: deaths + sales + transfers };
}

const snapshotCache = new Map<number, HerdSnapshot>();

export function herdAt(iso: string): HerdSnapshot {
  const t = dayDiff(new Date(`${iso}T00:00:00Z`), TODAY);
  const hit = snapshotCache.get(t);
  if (hit) return hit;

  const members = {
    Milking: [] as Animal[],
    Dry: [] as Animal[],
    Heifer: [] as Animal[],
    Calf: [] as Animal[],
    'Male / bull': [] as Animal[],
  } as Record<ProductionState, Animal[]>;

  let pregnant = 0;
  for (const a of HERD) {
    const s = stateAt(a, t);
    if (s === null) continue; // not yet born on this date
    members[s].push(a);
    if (pregnantAt(a, t, s)) pregnant++;
  }

  const counts = GROUP_ORDER.reduce((acc, g) => {
    acc[g] = members[g].length;
    return acc;
  }, {} as Record<ProductionState, number>);
  const total = GROUP_ORDER.reduce((s, g) => s + counts[g], 0);

  const present = GROUP_ORDER.flatMap((g) => members[g]);
  const composition = GENETIC_GROUPS.map((group) => {
    const count = present.filter((a) => a.geneticGroup === group).length;
    return { group, count, share: round((count / Math.max(1, present.length)) * 100, 1) };
  }).sort((a, b) => b.count - a.count);

  const generations = GENERATIONS.map((generation) => {
    const count = present.filter((a) => GENERATION_OF[a.geneticGroup] === generation).length;
    return { generation, count, share: round((count / Math.max(1, present.length)) * 100, 1) };
  }).filter((g) => g.count > 0);

  const snap: HerdSnapshot = {
    date: iso,
    offset: t,
    total,
    counts,
    pregnant,
    members,
    composition,
    generations,
    exits: exitsAt(t),
  };
  snapshotCache.set(t, snap);
  return snap;
}

/* ------------------------------------------------------------------ */
/* Long-range generation composition (§16) — 2016 → 2027              */
/* ------------------------------------------------------------------ */

export interface GenerationPoint {
  key: string;
  label: string;
  future: boolean;
  dailyDetail: boolean;
  [group: string]: number | string | boolean;
}

/**
 * Ten years of grading-up. Monthly history, with daily detail only from Jan
 * 2024 — the point where the herd system's records become complete enough.
 */
export const GENERATION_HISTORY: GenerationPoint[] = (() => {
  const out: GenerationPoint[] = [];
  const rnd = mulberry32(31337);
  const start = new Date(Date.UTC(2016, 0, 1));
  const months = 12 * 11 + 6;

  for (let i = 0; i < months; i++) {
    const d = new Date(Date.UTC(2016, i, 1));
    const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    const p = i / (months - 1);

    // Founders and F1 give way to F2/F3/F4 as the programme matures.
    const raw: Record<string, number> = {
      Founder: Math.max(1.5, 41 - p * 30 + rnd()),
      F1: 34 - p * 13 + rnd(),
      F2: 12 + p * 15 + rnd(),
      F3: Math.max(0, -4 + p * 26 + rnd()),
      'F4+': Math.max(0, -9 + p * 15 + rnd() * 0.6),
      Unknown: 9 - p * 3 + rnd(),
    };
    const sum = Object.values(raw).reduce((a, b) => a + b, 0);
    const row = {
      key,
      label: `${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`,
      future: key > '2026-08',
      dailyDetail: key >= '2024-01',
    } as GenerationPoint;
    for (const k of Object.keys(raw)) row[k] = round((raw[k] / sum) * 100, 1);
    out.push(row);
    void start;
  }
  return out;
})();

/* ------------------------------------------------------------------ */
/* Playable window                                                     */
/* ------------------------------------------------------------------ */

export const WINDOW_START = '2024-01-01';
export const WINDOW_END = isoDate(addDays(TODAY, MAX_FORECAST_DAYS));

export const windowDays = dayDiff(
  new Date(`${WINDOW_END}T00:00:00Z`),
  new Date(`${WINDOW_START}T00:00:00Z`),
);

/** Map a 0–1 scrub position onto a date in the playable window. */
export const dateAtProgress = (p: number) =>
  isoDate(addDays(new Date(`${WINDOW_START}T00:00:00Z`), Math.round(p * windowDays)));

/** Inverse: where a date sits on the scrub bar. */
export const progressOfDate = (iso: string) => {
  const t = dayDiff(new Date(`${iso}T00:00:00Z`), new Date(`${WINDOW_START}T00:00:00Z`));
  return Math.min(1, Math.max(0, t / windowDays));
};
