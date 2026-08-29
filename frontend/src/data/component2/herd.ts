/**
 * Component 2 — the individual-animal layer.
 *
 * This is the single source of truth for the prototype. Herd counts, the milk
 * river, the capacity flow, product output and the financial forecast are all
 * aggregations of these records, so every screen reconciles by construction.
 */

import {
  DAY_MS,
  EVENT_WINDOW,
  GENETIC_GROUPS,
  OPERATIONAL_GROUPS,
  TODAY,
  addDays,
  clamp,
  dayDiff,
  isoDate,
  lactationTotal,
  mulberry32,
  round,
  stageFor,
  woodsFromPeak,
  woodsYield,
  GENERATION_OF,
  type Confidence,
  type EvidenceSource,
  type GeneticGroup,
  type Generation,
  type LactationStage,
  type OperationalGroup,
  type ProductionState,
  type ReproState,
  type WoodsParams,
} from './core';

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

export type ProfileId = 'HP' | 'PT' | 'SR' | 'HA' | 'LH';

export const PROFILES: Record<
  ProfileId,
  { name: string; short: string; color: string; shape: 'circle' | 'square' | 'triangle' | 'diamond' | 'cross'; blurb: string }
> = {
  HP: {
    name: 'High persistent producers',
    short: 'Persistent',
    color: '#1f6b4a',
    shape: 'circle',
    blurb:
      'Strong peak with a flat post-peak curve. This group carries most of the late-lactation milk and is the priority to protect through the October transition.',
  },
  PT: {
    name: 'High peak / fast taper',
    short: 'Fast taper',
    color: '#b8860b',
    shape: 'triangle',
    blurb:
      'Reaches a high peak then falls away quickly. Total lactation yield under-delivers relative to the peak, and these cows dominate the tapering layer of the milk river.',
  },
  SR: {
    name: 'Strong reproduction profile',
    short: 'Strong repro',
    color: '#5b7fa6',
    shape: 'square',
    blurb:
      'Conceives early with few services. Short calving intervals make this the most reliable source of future lactation entries.',
  },
  HA: {
    name: 'Health-affected production',
    short: 'Health-affected',
    color: '#a44b3c',
    shape: 'diamond',
    blurb:
      'Repeated health events and raised cell counts depress the curve. Forecasts here carry wider ranges and a higher review priority.',
  },
  LH: {
    name: 'Limited history / new animals',
    short: 'Limited history',
    color: '#9aa8a2',
    shape: 'cross',
    blurb:
      'First-parity or recently recorded animals. Estimates lean on comparable cows rather than individual history, so confidence is capped.',
  },
};

export type ContributionType =
  | 'Established milkers'
  | 'Approaching peak'
  | 'Tapering cows'
  | 'New entrants — scheduled'
  | 'New entrants — predicted';

export const CONTRIBUTION_META: Record<
  ContributionType,
  { color: string; pattern: boolean; evidence: string }
> = {
  'Established milkers': { color: '#1f6b4a', pattern: false, evidence: 'Strong known evidence' },
  'Approaching peak': { color: '#4d9070', pattern: false, evidence: 'Strong known evidence' },
  'Tapering cows': { color: '#b8860b', pattern: false, evidence: 'Strong known evidence' },
  'New entrants — scheduled': { color: '#5b7fa6', pattern: true, evidence: 'Confirmed transition' },
  'New entrants — predicted': { color: '#93aec9', pattern: true, evidence: 'Future-transition dependent' },
};

export interface AiEvent {
  date: string;
  sire: string;
  outcome: 'Confirmed pregnant' | 'Returned to heat' | 'Awaiting check' | 'Not recorded';
}

export interface HealthEvent {
  date: string;
  type: string;
}

export interface Animal {
  id: string;
  tag: string;
  geneticGroup: GeneticGroup;
  /** Position in the grading-up programme. Ordinal, unlike the breed group. */
  generation: Generation;
  breedComposition: { jersey: number; local: number; unknown: number };
  opGroup: OperationalGroup;
  parity: number;
  ageMonths: number;
  sex: 'F' | 'M';
  prodState: ProductionState;
  reproState: ReproState;

  /* lactation */
  dim: number;
  woods: WoodsParams;
  peakYield: number;
  peakDay: number;
  currentYield: number;
  /** Yield at 240 DIM as a % of peak. */
  persistence: number;
  projected305: number;
  previous305: number | null;
  stage: LactationStage;
  /** Litres this animal is expected to add over the next 90 days. */
  contribution90: number;
  contributionType: ContributionType;

  /* transitions */
  lastCalving: string | null;
  dryOffDate: string | null;
  expectedCalving: string | null;
  /** True when the transition date comes from a confirmed record, not a model. */
  transitionConfirmed: boolean;
  /**
   * For animals with no confirmed pregnancy: the date they would calve if the
   * next service holds. Weighted by `entryProbability`, this is the
   * probabilistic transition layer that keeps the 12-month horizon honest
   * instead of letting the herd run itself down to nothing.
   */
  predictedCalving: string | null;
  entryProbability: number;

  /* reproduction */
  aiEvents: AiEvent[];
  aiAttempts: number;
  daysSinceLastAI: number | null;
  conceptionProb: number | null;
  peerConceptionBaseline: number;

  /* health */
  healthEvents: HealthEvent[];
  scc: number;
  mortalityRisk90: [number, number] | null;
  mortalityBaseline: number;

  /* evidence */
  evidence: EvidenceSource;
  confidence: Confidence;
  validLactationDays: number;
  peerCount: number;

  /* profiling */
  profile: ProfileId;
  landscape: { x: number; y: number };
  landscapeDrift: { x: number; y: number };

  /* lineage */
  damId: string | null;
  sireCode: string | null;

  flags: string[];
}

/* ------------------------------------------------------------------ */
/* Generation parameters                                               */
/* ------------------------------------------------------------------ */

const HERD_SIZE = 284;
const PARITY_PEAK = [0, 15.4, 18.6, 19.9, 19.4, 18.2, 16.6];
const GROUP_LIFT: Record<GeneticGroup, number> = {
  'Imported Jersey (founder)': 1.24,
  'F1 Jersey × Local': 1.0,
  'F2 Jersey Cross': 1.1,
  'F3 Jersey Cross': 1.17,
  'Local / Indigenous': 0.76,
  'Unknown parentage': 0.92,
};
const GROUP_SHARE: [GeneticGroup, number][] = [
  ['Imported Jersey (founder)', 0.05],
  ['F1 Jersey × Local', 0.21],
  ['F2 Jersey Cross', 0.28],
  ['F3 Jersey Cross', 0.24],
  ['Local / Indigenous', 0.14],
  ['Unknown parentage', 0.08],
];
const BREED_COMP: Record<GeneticGroup, { jersey: number; local: number; unknown: number }> = {
  'Imported Jersey (founder)': { jersey: 100, local: 0, unknown: 0 },
  'F1 Jersey × Local': { jersey: 50, local: 50, unknown: 0 },
  'F2 Jersey Cross': { jersey: 75, local: 25, unknown: 0 },
  'F3 Jersey Cross': { jersey: 87.5, local: 12.5, unknown: 0 },
  'Local / Indigenous': { jersey: 0, local: 100, unknown: 0 },
  'Unknown parentage': { jersey: 0, local: 0, unknown: 100 },
};
const SIRES = ['JX-4471', 'JX-5120', 'JX-5533', 'LK-BULL-02', 'JX-6014', 'JX-6288', 'LK-BULL-05'];
const HEALTH_TYPES = ['Mastitis', 'Lameness', 'Metritis', 'Milk fever', 'Retained placenta', 'Ketosis'];

function weightedPick<T>(r: number, table: [T, number][]): T {
  let acc = 0;
  for (const [v, w] of table) {
    acc += w;
    if (r <= acc) return v;
  }
  return table[table.length - 1][0];
}

/**
 * Move the nearest candidates in or out of a date window until exactly
 * `target` of them fall inside it. This is how the October event is pinned:
 * the narrative numbers are enforced on the animals themselves, so every
 * downstream aggregate reproduces them without special-casing.
 */
function snapToCount(
  animals: Animal[],
  field: 'dryOffDate' | 'expectedCalving',
  windowStart: string,
  windowEnd: string,
  target: number,
) {
  const s = new Date(`${windowStart}T00:00:00Z`).getTime();
  const e = new Date(`${windowEnd}T00:00:00Z`).getTime();
  const mid = (s + e) / 2;
  const inWindow = (a: Animal) => {
    const v = a[field];
    if (!v) return false;
    const t = new Date(`${v}T00:00:00Z`).getTime();
    return t >= s && t <= e;
  };

  const has = animals.filter(inWindow);
  if (has.length > target) {
    // Push the furthest-from-centre out past the window end.
    has
      .sort(
        (a, b) =>
          Math.abs(new Date(`${b[field]}T00:00:00Z`).getTime() - mid) -
          Math.abs(new Date(`${a[field]}T00:00:00Z`).getTime() - mid),
      )
      .slice(0, has.length - target)
      .forEach((a, i) => {
        a[field] = isoDate(new Date(e + (6 + i * 2) * DAY_MS));
      });
    return;
  }

  const need = target - has.length;
  if (need <= 0) return;
  const candidates = animals
    .filter((a) => a[field] && !inWindow(a))
    .sort(
      (a, b) =>
        Math.abs(new Date(`${a[field]}T00:00:00Z`).getTime() - mid) -
        Math.abs(new Date(`${b[field]}T00:00:00Z`).getTime() - mid),
    )
    .slice(0, need);
  candidates.forEach((a, i) => {
    a[field] = isoDate(new Date(s + ((i * (e - s)) / Math.max(1, need - 1) || 0)));
  });
}

/* ------------------------------------------------------------------ */
/* Build                                                               */
/* ------------------------------------------------------------------ */

function buildHerd(): Animal[] {
  const rnd = mulberry32(20260829);
  const animals: Animal[] = [];
  const damPool: string[] = [];

  for (let i = 0; i < HERD_SIZE; i++) {
    const id = `LK-${String(2100 + i * 3).padStart(4, '0')}`;
    const geneticGroup = weightedPick(rnd(), GROUP_SHARE);

    // Population mix: ~145 milking, ~42 dry, ~38 heifers, ~46 calves, ~13 male.
    const roll = rnd();
    let prodState: ProductionState;
    if (roll < 0.51) prodState = 'Milking';
    else if (roll < 0.66) prodState = 'Dry';
    else if (roll < 0.79) prodState = 'Heifer';
    else if (roll < 0.955) prodState = 'Calf';
    else prodState = 'Male / bull';

    const sex: 'F' | 'M' = prodState === 'Male / bull' ? 'M' : prodState === 'Calf' && rnd() < 0.48 ? 'M' : 'F';
    const adult = prodState === 'Milking' || prodState === 'Dry';
    const parity = adult ? 1 + Math.floor(rnd() * 5.6) : 0;
    const ageMonths =
      prodState === 'Calf' ? 1 + Math.floor(rnd() * 11)
      : prodState === 'Heifer' ? 13 + Math.floor(rnd() * 12)
      : prodState === 'Male / bull' ? 14 + Math.floor(rnd() * 40)
      : 26 + parity * 13 + Math.floor(rnd() * 9);

    const peakDay = 40 + Math.floor(rnd() * 34);
    const b = 0.15 + rnd() * 0.14;
    const peakYield = adult
      ? round(PARITY_PEAK[parity] * GROUP_LIFT[geneticGroup] * (0.85 + rnd() * 0.32), 1)
      : round(14 * GROUP_LIFT[geneticGroup] * (0.9 + rnd() * 0.2), 1);
    const woods = woodsFromPeak(peakYield, peakDay, b);
    const persistence = round((woodsYield(woods, 240) / peakYield) * 100, 0);
    const projected305 = Math.round(lactationTotal(woods, 1, 305));

    const dim = prodState === 'Milking' ? 4 + Math.floor(rnd() * 300) : 0;
    const currentYield = prodState === 'Milking' ? round(woodsYield(woods, dim), 1) : 0;

    const healthCount = rnd() < 0.68 ? Math.floor(rnd() * 2) : 2 + Math.floor(rnd() * 3);
    const healthEvents: HealthEvent[] = Array.from({ length: healthCount }, (_, k) => ({
      date: isoDate(addDays(TODAY, -(20 + Math.floor(rnd() * 500)))),
      type: HEALTH_TYPES[Math.floor(rnd() * HEALTH_TYPES.length)],
    })).sort((x, y) => y.date.localeCompare(x.date));
    const scc = Math.round(85 + rnd() * 330 + healthCount * 75);

    /* -- transitions ------------------------------------------------- */
    let dryOffDate: string | null = null;
    let expectedCalving: string | null = null;
    let lastCalving: string | null = null;
    let transitionConfirmed = false;

    if (prodState === 'Milking') {
      lastCalving = isoDate(addDays(TODAY, -dim));
      // Dry-off targeted at 305 DIM, with recording noise.
      dryOffDate = isoDate(addDays(TODAY, clamp(305 - dim + Math.floor(rnd() * 24) - 12, 3, 330)));
      transitionConfirmed = rnd() < 0.55;
    } else if (prodState === 'Dry') {
      lastCalving = isoDate(addDays(TODAY, -(320 + Math.floor(rnd() * 70))));
      expectedCalving = isoDate(addDays(TODAY, 5 + Math.floor(rnd() * 150)));
      transitionConfirmed = rnd() < 0.72;
    } else if (prodState === 'Heifer' && ageMonths >= 18 && rnd() < 0.55) {
      expectedCalving = isoDate(addDays(TODAY, 30 + Math.floor(rnd() * 210)));
      transitionConfirmed = rnd() < 0.35;
    }

    /* -- reproduction ------------------------------------------------ */
    const aiEvents: AiEvent[] = [];
    let reproState: ReproState = 'Not applicable';
    let daysSinceLastAI: number | null = null;

    if (prodState === 'Dry') {
      reproState = 'Pregnant';
      const n = 1 + Math.floor(rnd() * 3);
      for (let k = 0; k < n; k++)
        aiEvents.push({
          date: isoDate(addDays(TODAY, -(200 + k * 22 + Math.floor(rnd() * 30)))),
          sire: SIRES[Math.floor(rnd() * SIRES.length)],
          outcome: k === n - 1 ? 'Confirmed pregnant' : 'Returned to heat',
        });
    } else if (prodState === 'Milking') {
      if (dim < 55) reproState = 'Voluntary wait';
      else if (dim > 150 && rnd() < 0.6) reproState = 'Pregnant';
      else {
        const r = rnd();
        reproState =
          r < 0.3 ? 'Bred — awaiting check'
          : r < 0.45 ? 'Repeat breeder'
          : r < 0.58 ? 'No service recorded'
          : 'Eligible to breed';
      }

      const n =
        reproState === 'Pregnant' ? 1 + Math.floor(rnd() * 3)
        : reproState === 'Repeat breeder' ? 3 + Math.floor(rnd() * 3)
        : reproState === 'Bred — awaiting check' ? 1 + Math.floor(rnd() * 2)
        : reproState === 'Eligible to breed' ? Math.floor(rnd() * 2)
        : 0;

      for (let k = 0; k < n; k++) {
        const back =
          reproState === 'Pregnant' ? 60 + k * 21 + Math.floor(rnd() * 40)
          : reproState === 'Bred — awaiting check' ? 8 + Math.floor(rnd() * 20)
          : 15 + k * 22 + Math.floor(rnd() * 25);
        aiEvents.push({
          date: isoDate(addDays(TODAY, -back)),
          sire: SIRES[Math.floor(rnd() * SIRES.length)],
          outcome:
            reproState === 'Pregnant' && k === n - 1 ? 'Confirmed pregnant'
            : reproState === 'Bred — awaiting check' && k === n - 1 ? 'Awaiting check'
            : 'Returned to heat',
        });
      }
      aiEvents.sort((x, y) => y.date.localeCompare(x.date));
      if (aiEvents.length) daysSinceLastAI = -dayDiff(new Date(`${aiEvents[0].date}T00:00:00Z`), TODAY);

      if (reproState === 'Pregnant' && !expectedCalving) {
        expectedCalving = isoDate(addDays(TODAY, clamp(283 - (daysSinceLastAI ?? 90), 20, 250)));
        transitionConfirmed = true;
      }
    } else if (prodState === 'Heifer') {
      reproState = ageMonths >= 18 ? (expectedCalving ? 'Pregnant' : 'Eligible to breed') : 'Voluntary wait';
    }

    /* -- conception likelihood (live breeding decisions only) --------- */
    const attempts = aiEvents.length;
    const peerBaseline = 0.58;
    let conceptionProb: number | null = null;
    if (reproState === 'Bred — awaiting check' || reproState === 'Eligible to breed' || reproState === 'Repeat breeder') {
      conceptionProb = round(
        clamp(
          0.62 -
            (parity >= 4 ? 0.07 : 0) -
            Math.min(0.24, attempts * 0.055) -
            (currentYield > 19 ? 0.06 : 0) -
            (healthCount >= 3 ? 0.1 : 0) -
            0.07 /* current THI window */ +
            rnd() * 0.16,
          0.14,
          0.88,
        ),
        2,
      );
    }

    /* -- evidence ----------------------------------------------------- */
    const validLactationDays = prodState === 'Milking' ? Math.min(dim, 8 + Math.floor(rnd() * 260)) : 0;
    const previous305 = parity > 1 && rnd() < 0.82 ? Math.round(projected305 * (0.85 + rnd() * 0.3)) : null;
    const peerCount = 28 + Math.floor(rnd() * 90);

    let evidence: EvidenceSource;
    let confidence: Confidence;
    if (prodState === 'Calf' || prodState === 'Male / bull') {
      evidence = 'Historical only';
      confidence = 'Limited';
    } else if (validLactationDays >= 60 && previous305) {
      evidence = 'Individual';
      confidence = 'High';
    } else if (validLactationDays >= 25) {
      evidence = 'Individual + peer';
      confidence = 'Moderate';
    } else if (peerCount >= 40) {
      evidence = 'Peer';
      confidence = 'Moderate';
    } else {
      evidence = 'Herd';
      confidence = 'Limited';
    }
    if (healthCount >= 3 && confidence === 'High') confidence = 'Moderate';

    /* -- profile ------------------------------------------------------ */
    // Animals only fall into "limited history" when they genuinely lack a
    // record to profile from — youngstock, or a first lactation barely underway
    // with no completed previous lactation to fall back on.
    const noUsableHistory =
      prodState === 'Calf' ||
      prodState === 'Male / bull' ||
      prodState === 'Heifer' ||
      (previous305 === null && validLactationDays < 25);

    const profile: ProfileId =
      noUsableHistory ? 'LH'
      : healthCount >= 3 || scc > 430 ? 'HA'
      : attempts <= 1 && (reproState === 'Pregnant' || reproState === 'Bred — awaiting check') ? 'SR'
      : persistence < 56 ? 'PT'
      : 'HP';

    /* -- mortality / review priority (ranking, never a diagnosis) ----- */
    const mortalityScore = clamp(
      0.018 + healthCount * 0.012 + (parity >= 5 ? 0.02 : 0) + (scc > 450 ? 0.014 : 0) + rnd() * 0.012,
      0.01,
      0.12,
    );
    const showMortality = mortalityScore > 0.045 && adult;

    animals.push({
      id,
      tag: String(1000 + i),
      geneticGroup,
      generation: GENERATION_OF[geneticGroup],
      breedComposition: BREED_COMP[geneticGroup],
      opGroup:
        prodState === 'Calf' || prodState === 'Heifer' ? 'Youngstock'
        : prodState === 'Dry' || prodState === 'Male / bull' ? 'Dry & transition'
        : dim < 100 ? 'Shed 1 — high yield'
        : dim < 210 ? 'Shed 2 — mid lactation'
        : 'Shed 3 — late lactation',
      parity,
      ageMonths,
      sex,
      prodState,
      reproState,
      dim,
      woods,
      peakYield,
      peakDay,
      currentYield,
      persistence,
      projected305,
      previous305,
      stage: prodState === 'Milking' ? stageFor(dim, peakDay) : 'Dry period',
      contribution90: 0,
      contributionType: 'Established milkers',
      lastCalving,
      dryOffDate,
      expectedCalving,
      transitionConfirmed,
      predictedCalving: null,
      entryProbability: 0,
      aiEvents,
      aiAttempts: attempts,
      daysSinceLastAI,
      conceptionProb,
      peerConceptionBaseline: peerBaseline,
      healthEvents,
      scc,
      mortalityRisk90: showMortality
        ? [round(mortalityScore * 100 - 2, 0), round(mortalityScore * 100 + 2, 0)]
        : null,
      mortalityBaseline: 3,
      evidence,
      confidence,
      validLactationDays,
      peerCount,
      profile,
      landscape: { x: 0, y: 0 },
      landscapeDrift: { x: 0, y: 0 },
      damId: null,
      sireCode: adult || prodState === 'Heifer' || prodState === 'Calf'
        ? SIRES[Math.floor(rnd() * SIRES.length)]
        : null,
      flags: [],
    });

    if (sex === 'F' && ageMonths > 20) damPool.push(id);
  }

  /* -- pin the October narrative onto the animals -------------------- */
  const milkers = animals.filter((a) => a.prodState === 'Milking');
  const breeders = animals.filter((a) => a.expectedCalving);
  snapToCount(milkers, 'dryOffDate', EVENT_WINDOW.start, EVENT_WINDOW.end, EVENT_WINDOW.dryOffs);
  snapToCount(breeders, 'expectedCalving', EVENT_WINDOW.start, EVENT_WINDOW.end, EVENT_WINDOW.entries);

  /* -- derived fields that depend on final transition dates ----------- */
  const rnd2 = mulberry32(913377);
  animals.forEach((a, i) => {
    // Lineage: assign a dam from older females recorded before this animal.
    if (i > 30 && rnd2() < 0.74) {
      const pool = damPool.slice(0, Math.max(1, Math.floor(i * 0.5)));
      a.damId = pool[Math.floor(rnd2() * pool.length)] ?? null;
    }
    if (a.geneticGroup === 'Unknown parentage') a.damId = null;

    // Probabilistic re-entry for animals with no confirmed calving date.
    // Jittered so predicted entries spread across the year instead of bunching
    // into one artificial calving wave.
    if (!a.expectedCalving) {
      const gestation = 283 + Math.floor(rnd2() * 80) - 30;
      if (a.reproState === 'Bred — awaiting check' && a.daysSinceLastAI !== null) {
        a.predictedCalving = isoDate(addDays(TODAY, gestation - a.daysSinceLastAI));
        a.entryProbability = a.conceptionProb ?? 0.5;
      } else if (a.reproState === 'Eligible to breed') {
        a.predictedCalving = isoDate(addDays(TODAY, 21 + gestation));
        a.entryProbability = a.conceptionProb ?? 0.5;
      } else if (a.reproState === 'Repeat breeder') {
        a.predictedCalving = isoDate(addDays(TODAY, 30 + gestation));
        a.entryProbability = (a.conceptionProb ?? 0.4) * 0.8;
      } else if (a.reproState === 'No service recorded') {
        a.predictedCalving = isoDate(addDays(TODAY, 45 + gestation));
        a.entryProbability = 0.42;
      } else if (a.reproState === 'Voluntary wait' && a.prodState === 'Milking') {
        a.predictedCalving = isoDate(addDays(TODAY, (60 - a.dim) + 21 + gestation));
        a.entryProbability = 0.5;
      } else if (a.prodState === 'Heifer' && a.ageMonths >= 14) {
        a.predictedCalving = isoDate(addDays(TODAY, Math.max(30, (26 - a.ageMonths) * 30) + 30));
        a.entryProbability = 0.68;
      }
    }

    // 90-day milk contribution, straight off the individual curve.
    a.contribution90 = Math.round(contributionOver(a, 90));

    a.contributionType = classifyContribution(a);

    if (a.reproState === 'No service recorded' && a.dim > 110)
      a.flags.push(`No insemination recorded at ${a.dim} days in milk`);
    if (a.reproState === 'Repeat breeder')
      a.flags.push(`${a.aiAttempts} services without confirmation`);
    if (a.scc > 430) a.flags.push(`Somatic cell count ${a.scc}k — above the 400k review line`);
    if (a.prodState === 'Milking' && a.dim > 305)
      a.flags.push('Past 305 days in milk and still milking');
    if (a.evidence === 'Peer' || a.evidence === 'Herd')
      a.flags.push('Forecast leans on comparable animals rather than own history');
  });

  /* -- 2D profile landscape ------------------------------------------ */
  layoutLandscape(animals);

  return animals;
}

/** Expected litres from one animal over the next `days`, including transitions. */
export function contributionOver(a: Animal, days: number): number {
  if (a.prodState !== 'Milking' && !a.expectedCalving) return 0;
  let total = 0;
  const dryOff = a.dryOffDate ? dayDiff(new Date(`${a.dryOffDate}T00:00:00Z`), TODAY) : null;
  const calve = a.expectedCalving ? dayDiff(new Date(`${a.expectedCalving}T00:00:00Z`), TODAY) : null;

  for (let t = 1; t <= days; t++) {
    if (a.prodState === 'Milking') {
      if (dryOff !== null && t > dryOff) {
        // Dried off; may re-enter after calving inside the horizon.
        if (calve !== null && t > calve) total += woodsYield(a.woods, t - calve);
      } else {
        total += woodsYield(a.woods, a.dim + t);
      }
    } else if (calve !== null && t > calve) {
      total += woodsYield(a.woods, t - calve);
    }
  }
  return total;
}

function classifyContribution(a: Animal): ContributionType {
  if (a.prodState !== 'Milking') {
    return a.transitionConfirmed ? 'New entrants — scheduled' : 'New entrants — predicted';
  }
  if (a.stage === 'Approaching peak' || a.stage === 'Early / rising') return 'Approaching peak';
  if (a.stage === 'Tapering' || a.stage === 'Late lactation') return 'Tapering cows';
  return 'Established milkers';
}

/**
 * Lay out cows in a 2D similarity space. Fixed loadings keep the axes
 * interpretable: x ≈ production scale, y ≈ reproduction / health burden.
 */
function layoutLandscape(animals: Animal[]) {
  const feats = animals.map((a) => [
    a.peakYield,
    a.persistence,
    a.projected305 / 100,
    a.aiAttempts,
    a.healthEvents.length,
    a.scc / 100,
    a.validLactationDays / 50,
  ]);
  const n = feats[0].length;
  const mean = Array.from({ length: n }, (_, j) => feats.reduce((s, f) => s + f[j], 0) / feats.length);
  const sd = Array.from({ length: n }, (_, j) =>
    Math.sqrt(feats.reduce((s, f) => s + (f[j] - mean[j]) ** 2, 0) / feats.length) || 1);

  const pc1 = [0.5, 0.4, 0.54, -0.2, -0.2, -0.16, 0.3];
  const pc2 = [0.1, -0.36, -0.04, 0.58, 0.54, 0.36, -0.28];
  const r = mulberry32(55512);

  animals.forEach((a, i) => {
    const z = feats[i].map((v, j) => (v - mean[j]) / sd[j]);
    a.landscape = {
      x: round(z.reduce((s, v, j) => s + v * pc1[j], 0) + (r() - 0.5) * 0.35, 2),
      y: round(z.reduce((s, v, j) => s + v * pc2[j], 0) + (r() - 0.5) * 0.35, 2),
    };
    // Where the animal drifts to over the next 12 months of the time slider.
    a.landscapeDrift = {
      x: round((r() - 0.35) * 0.9, 2),
      y: round((r() - 0.5) * 0.7, 2),
    };
  });
}

/* ------------------------------------------------------------------ */
/* Exports                                                             */
/* ------------------------------------------------------------------ */

export const HERD = buildHerd();

export const MILKING = HERD.filter((a) => a.prodState === 'Milking');
export const DRY_COWS = HERD.filter((a) => a.prodState === 'Dry');
export const HEIFERS = HERD.filter((a) => a.prodState === 'Heifer');
export const CALVES = HERD.filter((a) => a.prodState === 'Calf');
export const MALES = HERD.filter((a) => a.prodState === 'Male / bull');

export const byId = (id: string) => HERD.find((a) => a.id === id);

export const DAILY_MILK_NOW = Math.round(MILKING.reduce((s, a) => s + a.currentYield, 0));

/** Animals whose transition falls inside an inclusive date window. */
export function inWindow(field: 'dryOffDate' | 'expectedCalving', start: string, end: string) {
  return HERD.filter((a) => {
    const v = a[field];
    return !!v && v >= start && v <= end;
  });
}

export const OCT_DRYOFFS = inWindow('dryOffDate', EVENT_WINDOW.start, EVENT_WINDOW.end);
export const OCT_ENTRIES = inWindow('expectedCalving', EVENT_WINDOW.start, EVENT_WINDOW.end);

export const descendantsOf = (id: string) => HERD.filter((a) => a.damId === id);

export { OPERATIONAL_GROUPS, GENETIC_GROUPS };
export type { GeneticGroup, OperationalGroup };
