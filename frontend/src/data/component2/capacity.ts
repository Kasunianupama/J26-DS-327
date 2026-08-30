/**
 * Component 2 — reproduction → milking-capacity pipeline (§12–§14).
 *
 * Everything here counts the same animals the milk river uses, so the capacity
 * flow and the production forecast can never disagree.
 */

import { TODAY, addDays, clamp, isoDate, round, type Confidence } from './core';
import {
  DRY_COWS,
  HEIFERS,
  HERD,
  MILKING,
  contributionOver,
  type Animal,
} from './herd';
import { DAILY } from './forecast';

/* ------------------------------------------------------------------ */
/* Capacity flow stages                                                */
/* ------------------------------------------------------------------ */

export type FlowState = 'confirmed' | 'predicted' | 'delayed' | 'missing-evidence';

export interface FlowStage {
  id: string;
  name: string;
  current: number;
  expected: number;
  range: [number, number];
  confirmed: number;
  uncertain: number;
  state: FlowState;
  /** Litres/day this stage is expected to add to the milking herd at 90 days. */
  capacityContribution: number;
  note: string;
  members: () => Animal[];
}

const bred = () => HERD.filter((a) => a.reproState === 'Bred — awaiting check' || a.reproState === 'Repeat breeder');
const pregnant = () => HERD.filter((a) => a.reproState === 'Pregnant');
const calvingSoon = () => HERD.filter((a) => a.expectedCalving && a.expectedCalving <= isoDate(addDays(TODAY, 90)));
const entering = () => calvingSoon().filter((a) => a.prodState !== 'Milking');

export const CAPACITY_FLOW: FlowStage[] = [
  {
    id: 'bred',
    name: 'AI / bred',
    current: bred().length,
    expected: bred().length,
    range: [bred().length - 4, bred().length + 6],
    confirmed: bred().filter((a) => a.reproState === 'Bred — awaiting check').length,
    uncertain: bred().filter((a) => a.reproState === 'Repeat breeder').length,
    state: 'predicted',
    capacityContribution: 0,
    note: 'Served but not yet confirmed. Repeat breeders in this stage push their lactation entry beyond the current horizon.',
    members: bred,
  },
  {
    id: 'evidence',
    name: 'Pregnancy evidence',
    current: pregnant().length,
    expected: pregnant().length + 9,
    range: [pregnant().length + 3, pregnant().length + 16],
    confirmed: pregnant().filter((a) => a.transitionConfirmed).length,
    uncertain: pregnant().filter((a) => !a.transitionConfirmed).length,
    state: 'confirmed',
    capacityContribution: 0,
    note: 'Confirmed pregnant on record. The uncertain share has a pregnancy record but no confirmed calving date.',
    members: pregnant,
  },
  {
    id: 'calving',
    name: 'Expected calving',
    current: calvingSoon().length,
    expected: calvingSoon().length,
    range: [calvingSoon().length - 5, calvingSoon().length + 4],
    confirmed: calvingSoon().filter((a) => a.transitionConfirmed).length,
    uncertain: calvingSoon().filter((a) => !a.transitionConfirmed).length,
    state: 'predicted',
    capacityContribution: 0,
    note: 'Calvings expected within 90 days. Date uncertainty widens this stage — a two-week slip moves the animal out of the horizon.',
    members: calvingSoon,
  },
  {
    id: 'entry',
    name: 'Lactation entry',
    current: entering().length,
    expected: entering().length,
    range: [entering().length - 4, entering().length + 3],
    confirmed: entering().filter((a) => a.transitionConfirmed).length,
    uncertain: entering().filter((a) => !a.transitionConfirmed).length,
    state: 'predicted',
    capacityContribution: Math.round(entering().reduce((s, a) => s + contributionOver(a, 90), 0) / 90),
    note: 'Animals expected to join or rejoin the milking herd. This is the inflow that has to offset October dry-offs.',
    members: entering,
  },
  {
    id: 'milking',
    name: 'Milking',
    current: MILKING.length,
    expected: 0,
    range: [0, 0],
    confirmed: MILKING.filter((a) => a.transitionConfirmed).length,
    uncertain: MILKING.filter((a) => !a.transitionConfirmed).length,
    state: 'confirmed',
    capacityContribution: Math.round(MILKING.reduce((s, a) => s + a.currentYield, 0)),
    note: 'The active milking herd today, and where it is expected to sit at each horizon.',
    members: () => MILKING,
  },
  {
    id: 'dry',
    name: 'Dry',
    current: DRY_COWS.length,
    expected: DRY_COWS.length + 12,
    range: [DRY_COWS.length + 6, DRY_COWS.length + 19],
    confirmed: DRY_COWS.filter((a) => a.transitionConfirmed).length,
    uncertain: DRY_COWS.filter((a) => !a.transitionConfirmed).length,
    state: 'confirmed',
    capacityContribution: 0,
    note: 'The dry group grows through October as scheduled dry-offs land, then unwinds as those animals calve.',
    members: () => DRY_COWS,
  },
];

// Expected milking-herd size at each horizon, read straight off the daily series.
const milkersAt = (d: number) => DAILY.find((x) => x.offset === d)?.milkers ?? MILKING.length;
CAPACITY_FLOW[4].expected = milkersAt(90);
CAPACITY_FLOW[4].range = [milkersAt(90) - 7, milkersAt(90) + 5];

export const EXPECTED_MILKERS = [
  { horizon: '30 days', value: milkersAt(30), range: [milkersAt(30) - 3, milkersAt(30) + 3] as [number, number], confidence: 'High' as Confidence },
  { horizon: '60 days', value: milkersAt(60), range: [milkersAt(60) - 5, milkersAt(60) + 4] as [number, number], confidence: 'Moderate' as Confidence },
  { horizon: '90 days', value: milkersAt(90), range: [milkersAt(90) - 7, milkersAt(90) + 5] as [number, number], confidence: 'Moderate' as Confidence },
];

/** Animals expected to leave the milking herd — drawn as a side branch. */
export const EXPECTED_EXITS = {
  dryOffs90: DAILY.filter((d) => d.offset > 0 && d.offset <= 90).reduce((s, d) => s + d.dryOffs, 0),
  culls90: 6,
  mortality90: 2,
};

/* ------------------------------------------------------------------ */
/* AI success intelligence (§13)                                       */
/* ------------------------------------------------------------------ */

export interface AiInsight {
  animal: Animal;
  likelihood: number;
  peerBaseline: number;
  confidence: Confidence;
  expectedEntry: string;
  reasons: string[];
}

export const AI_INSIGHTS: AiInsight[] = HERD.filter((a) => a.conceptionProb !== null)
  .sort((x, y) => (y.conceptionProb ?? 0) - (x.conceptionProb ?? 0))
  .map((a) => {
    const above = (a.conceptionProb ?? 0) > a.peerConceptionBaseline;
    const reasons: string[] = [];
    if (above) {
      reasons.push(
        'Recorded heat timing and current lactation stage resemble historically successful cases.',
      );
    } else {
      reasons.push('Recent services in comparable animals at this stage have more often returned to heat.');
    }
    if (a.aiAttempts >= 3) reasons.push(`${a.aiAttempts} previous services without confirmation lower the estimate.`);
    if (a.currentYield > 19) reasons.push('Production is high for this stage, which historically coincides with lower conception.');
    if (a.healthEvents.length >= 3) reasons.push(`${a.healthEvents.length} recorded health events this lactation.`);
    reasons.push('The current heat-and-humidity window is the least favourable of the year.');

    return {
      animal: a,
      likelihood: Math.round((a.conceptionProb ?? 0) * 100),
      peerBaseline: Math.round(a.peerConceptionBaseline * 100),
      confidence: a.evidence === 'Individual' ? 'Moderate' : a.evidence === 'Herd' ? 'Limited' : 'Moderate',
      // Conception now → calving ~283 days → lactation entry.
      expectedEntry: isoDate(addDays(TODAY, 283 + (a.daysSinceLastAI ? -a.daysSinceLastAI : 14))),
      reasons,
    };
  });

/** Herd-level reproductive performance, for the secondary panel. */
export const AI_SUMMARY = (() => {
  const served = HERD.filter((a) => a.aiEvents.length > 0);
  const confirmed = served.filter((a) => a.reproState === 'Pregnant');
  const services = served.reduce((s, a) => s + a.aiEvents.length, 0);
  return {
    servedAnimals: served.length,
    services,
    confirmed: confirmed.length,
    successRate: round((confirmed.length / Math.max(1, services)) * 100, 1),
    servicesPerConception: round(services / Math.max(1, confirmed.length), 2),
    peerBaseline: 58,
  };
})();

export const ATTEMPTS_DISTRIBUTION = (() => {
  const buckets = [1, 2, 3, 4, 5];
  const served = HERD.filter((a) => a.aiEvents.length > 0);
  return buckets.map((b) => {
    const n = served.filter((a) => (b === 5 ? a.aiEvents.length >= 5 : a.aiEvents.length === b)).length;
    return { attempts: b === 5 ? '5+' : String(b), animals: n, pct: round((n / served.length) * 100, 1) };
  });
})();

/** Conception rate against the heat-and-humidity index — the clearest signal. */
export const THI_RESPONSE = [
  { band: 'Below 68', label: 'Comfortable', rate: 54, services: 96 },
  { band: '68–72', label: 'Mild', rate: 49, services: 142 },
  { band: '72–78', label: 'Moderate', rate: 39, services: 188 },
  { band: '78–82', label: 'Severe', rate: 28, services: 121 },
  { band: 'Above 82', label: 'Extreme', rate: 21, services: 43 },
];

/* ------------------------------------------------------------------ */
/* Dry planning (§14) — never below the 90-day hard minimum            */
/* ------------------------------------------------------------------ */

export type DryStatus =
  | 'Recommendation available'
  | 'Provisional'
  | 'Schedule only'
  | 'No reliable recommendation';

export interface DryPlanRow {
  animal: Animal;
  stage: string;
  window: [number, number] | null;
  hardMinimum: number;
  confidence: Confidence;
  comparableCases: number;
  capacityConsequence: string;
  status: DryStatus;
}

export const HARD_MINIMUM_DAYS = 90;

export const DRY_PLAN: DryPlanRow[] = MILKING
  .filter((a) => a.dryOffDate && a.dryOffDate <= isoDate(addDays(TODAY, 150)))
  .sort((x, y) => (x.dryOffDate ?? '').localeCompare(y.dryOffDate ?? ''))
  .map((a) => {
    const comparable = a.peerCount;
    const status: DryStatus =
      a.evidence === 'Herd' || comparable < 35 ? 'No reliable recommendation'
      : a.evidence === 'Peer' ? 'Provisional'
      : !a.transitionConfirmed && a.reproState !== 'Pregnant' ? 'Schedule only'
      : 'Recommendation available';

    // Longer rest for older, health-affected or high-persistence animals.
    const base = 98 + (a.parity >= 4 ? 8 : 0) + (a.healthEvents.length >= 3 ? 9 : 0) - (a.persistence > 65 ? 4 : 0);
    const lo = clamp(Math.round(base - 6), HARD_MINIMUM_DAYS, 200);
    const hi = clamp(Math.round(base + 8), lo + 6, 210);

    return {
      animal: a,
      stage: a.stage,
      window: status === 'No reliable recommendation' ? null : [lo, hi],
      hardMinimum: HARD_MINIMUM_DAYS,
      confidence:
        status === 'Recommendation available' ? 'Moderate'
        : status === 'Provisional' ? 'Limited'
        : 'Limited',
      comparableCases: comparable,
      capacityConsequence:
        a.dryOffDate && a.dryOffDate >= '2026-10-14' && a.dryOffDate <= '2026-10-28'
          ? 'Inside the October dry-off cluster — contributes directly to the expected decline'
          : `Leaves the milking herd around ${a.dryOffDate}, removing about ${Math.round(a.currentYield)} L/day`,
      status,
    };
  });

/* ------------------------------------------------------------------ */
/* State matrix (§15)                                                  */
/* ------------------------------------------------------------------ */

export interface MatrixCell {
  prod: string;
  repro: string;
  count: number;
  change: number;
  animals: Animal[];
}

export function stateMatrix(overlay: 'None' | 'Operational group' | 'Parity' | 'Genetic group' | 'Health profile', overlayValue: string): MatrixCell[] {
  const pool = HERD.filter((a) => {
    if (overlay === 'None' || overlayValue === 'All') return true;
    if (overlay === 'Operational group') return a.opGroup === overlayValue;
    if (overlay === 'Parity') return (a.parity === 0 ? 'Youngstock' : `Parity ${a.parity}`) === overlayValue;
    if (overlay === 'Genetic group') return a.geneticGroup === overlayValue;
    return (a.healthEvents.length >= 3 ? 'Health-affected' : 'Unaffected') === overlayValue;
  });

  const prods = ['Milking', 'Dry', 'Heifer', 'Calf', 'Male / bull'];
  const repros = ['Voluntary wait', 'Eligible to breed', 'Bred — awaiting check', 'Pregnant', 'Repeat breeder', 'No service recorded', 'Not applicable'];

  const cells: MatrixCell[] = [];
  for (const p of prods) {
    for (const r of repros) {
      const animals = pool.filter((a) => a.prodState === p && a.reproState === r);
      if (!animals.length) continue;
      // Expected 90-day change: pregnant milkers dry off, pregnant dry cows calve.
      const change =
        p === 'Milking' && r === 'Pregnant' ? -Math.round(animals.length * 0.42)
        : p === 'Dry' && r === 'Pregnant' ? -Math.round(animals.length * 0.55)
        : p === 'Milking' && r === 'Bred — awaiting check' ? Math.round(animals.length * 0.18)
        : p === 'Heifer' && r === 'Pregnant' ? -Math.round(animals.length * 0.3)
        : p === 'Calf' ? Math.round(animals.length * 0.12)
        : 0;
      cells.push({ prod: p, repro: r, count: animals.length, change, animals });
    }
  }
  return cells;
}

export const OVERLAY_OPTIONS: Record<string, string[]> = {
  None: ['All'],
  'Operational group': ['All', 'Shed 1 — high yield', 'Shed 2 — mid lactation', 'Shed 3 — late lactation', 'Dry & transition', 'Youngstock'],
  Parity: ['All', 'Youngstock', 'Parity 1', 'Parity 2', 'Parity 3', 'Parity 4', 'Parity 5', 'Parity 6'],
  'Genetic group': ['All', 'Imported Jersey (founder)', 'F1 Jersey × Local', 'F2 Jersey Cross', 'F3 Jersey Cross', 'Local / Indigenous', 'Unknown parentage'],
  'Health profile': ['All', 'Health-affected', 'Unaffected'],
};

/* ------------------------------------------------------------------ */
/* Genetics summary (§16)                                              */
/* ------------------------------------------------------------------ */

export const GENETICS_SUMMARY = [
  'Imported Jersey (founder)',
  'F1 Jersey × Local',
  'F2 Jersey Cross',
  'F3 Jersey Cross',
  'Local / Indigenous',
  'Unknown parentage',
].map((g) => {
  const set = HERD.filter((a) => a.geneticGroup === g);
  const milkers = set.filter((a) => a.prodState === 'Milking');
  const served = set.filter((a) => a.aiEvents.length > 0);
  const conceived = set.filter((a) => a.reproState === 'Pregnant');
  return {
    group: g,
    animals: set.length,
    share: round((set.length / HERD.length) * 100, 1),
    milkers: milkers.length,
    avgPeak: milkers.length ? round(milkers.reduce((s, a) => s + a.peakYield, 0) / milkers.length, 1) : 0,
    avgPersistence: milkers.length ? Math.round(milkers.reduce((s, a) => s + a.persistence, 0) / milkers.length) : 0,
    milkShare: round(
      (milkers.reduce((s, a) => s + a.contribution90, 0) /
        Math.max(1, HERD.reduce((s, a) => s + a.contribution90, 0))) * 100,
      1,
    ),
    servicesPerConception: conceived.length
      ? round(served.reduce((s, a) => s + a.aiEvents.length, 0) / conceived.length, 2)
      : null,
    confidence: (set.length >= 40 ? 'Moderate' : set.length >= 20 ? 'Limited' : 'Limited') as Confidence,
    sampleNote: set.length < 25 ? `Only ${set.length} animals — treat group comparisons as indicative.` : null,
  };
});

export { HEIFERS };
