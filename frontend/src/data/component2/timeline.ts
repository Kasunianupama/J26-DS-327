/**
 * Component 2 — measures that hang off the master timeline.
 *
 * The timeline bands need more than litres: herd population by state, health
 * outcomes and disease by category, preventive care, and the macroeconomic
 * context a margin actually moves against. Everything here is derived from the
 * same synthetic herd and calendar the rest of the prototype uses, so a bucket
 * can never disagree with itself across two bands.
 */

import { isoDate, monthKey, mulberry32, round, thiForMonth } from './core';
import { MONTHS_ALL, type Bucket } from './forecast';
import { HERD } from './herd';
import { herdAt } from './composition';
import { HERD_OUTCOMES } from './outcomes';

/* ------------------------------------------------------------------ */
/* Disease categories                                                  */
/* ------------------------------------------------------------------ */

/** The recorded health-event types, grouped the way a vet report groups them. */
export const DISEASE_CATEGORIES = [
  'Mastitis',
  'Lameness',
  'Reproductive',
  'Metabolic',
  'Other',
] as const;
export type DiseaseCategory = (typeof DISEASE_CATEGORIES)[number];

export const DISEASE_COLOR: Record<DiseaseCategory, string> = {
  Mastitis: '#9a4f27',
  Lameness: '#a8770a',
  Reproductive: '#5b7fa6',
  Metabolic: '#6b7f76',
  Other: '#b9a08f',
};

const CATEGORY_OF: Record<string, DiseaseCategory> = {
  Mastitis: 'Mastitis',
  Lameness: 'Lameness',
  Metritis: 'Reproductive',
  'Retained placenta': 'Reproductive',
  'Milk fever': 'Metabolic',
  Ketosis: 'Metabolic',
};

/** Recorded health events, bucketed by month once at module load. */
const RECORDED_BY_MONTH = (() => {
  const map = new Map<string, Record<DiseaseCategory, number>>();
  for (const animal of HERD) {
    for (const event of animal.healthEvents) {
      const key = event.date.slice(0, 7);
      const category = CATEGORY_OF[event.type] ?? 'Other';
      const entry = map.get(key) ?? blankDisease();
      entry[category] += 1;
      map.set(key, entry);
    }
  }
  return map;
})();

function blankDisease(): Record<DiseaseCategory, number> {
  return { Mastitis: 0, Lameness: 0, Reproductive: 0, Metabolic: 0, Other: 0 };
}

/**
 * Expected disease load for a future month. Incidence tracks herd size and
 * rises with heat, which is the one external driver the recorded data supports.
 */
function expectedDisease(monthIdx0: number, seed: number, milkers: number): Record<DiseaseCategory, number> {
  const rnd = mulberry32(seed);
  const heat = (thiForMonth(monthIdx0) - 72) / 10;
  const base = milkers / 100;
  const out = blankDisease();
  out.Mastitis = Math.max(0, Math.round(base * (2.6 + heat * 1.1) + rnd() * 1.6));
  out.Lameness = Math.max(0, Math.round(base * (1.7 + heat * 0.4) + rnd() * 1.2));
  out.Reproductive = Math.max(0, Math.round(base * (1.4 + heat * 0.5) + rnd() * 1.1));
  out.Metabolic = Math.max(0, Math.round(base * (1.1 + heat * 0.2) + rnd() * 0.9));
  out.Other = Math.max(0, Math.round(base * 0.7 + rnd() * 0.8));
  return out;
}

/* ------------------------------------------------------------------ */
/* Veterinary treatment categories                                     */
/* ------------------------------------------------------------------ */

/**
 * Treatments are grouped the way a medicine cabinet is, not the way a diagnosis
 * is: what was administered. Most follow a recorded disease event, so the mix
 * tracks the disease mix, with a routine floor that does not.
 */
export const TREATMENT_CATEGORIES = [
  'Antibiotic',
  'Anti-inflammatory',
  'Reproductive / hormonal',
  'Metabolic / mineral',
  'Hoof care',
  'Routine / preventive',
] as const;
export type TreatmentCategory = (typeof TREATMENT_CATEGORIES)[number];

export const TREATMENT_COLOR: Record<TreatmentCategory, string> = {
  Antibiotic: '#a44b3c',
  'Anti-inflammatory': '#9a4f27',
  'Reproductive / hormonal': '#5b7fa6',
  'Metabolic / mineral': '#6b7f76',
  'Hoof care': '#a8770a',
  'Routine / preventive': '#8a9a94',
};

function blankTreatment(): Record<TreatmentCategory, number> {
  return {
    Antibiotic: 0,
    'Anti-inflammatory': 0,
    'Reproductive / hormonal': 0,
    'Metabolic / mineral': 0,
    'Hoof care': 0,
    'Routine / preventive': 0,
  };
}

/** Which treatments a disease category typically draws, as rough proportions. */
const TREATMENT_MIX: Record<DiseaseCategory, Partial<Record<TreatmentCategory, number>>> = {
  Mastitis: { Antibiotic: 1.1, 'Anti-inflammatory': 0.4 },
  Lameness: { 'Hoof care': 1.0, 'Anti-inflammatory': 0.5 },
  Reproductive: { 'Reproductive / hormonal': 1.0, Antibiotic: 0.3 },
  Metabolic: { 'Metabolic / mineral': 1.2, 'Anti-inflammatory': 0.2 },
  Other: { 'Anti-inflammatory': 0.5, Antibiotic: 0.3 },
};

/* ------------------------------------------------------------------ */
/* Macroeconomic context                                               */
/* ------------------------------------------------------------------ */

export interface MacroPoint {
  key: string;
  /** Year-on-year consumer price inflation, %. */
  cpiInflation: number;
  /** Compound feed cost index, rebased to 100 at the start of the window. */
  feedPriceIndex: number;
  /** Farmgate milk price index, rebased to 100 at the start of the window. */
  farmgatePriceIndex: number;
}

/**
 * A smooth, deterministic macro series. Feed cost leads the farmgate price,
 * which is the asymmetry that squeezes a dairy margin: input prices move
 * before the price paid for milk catches up.
 */
export const MACRO_SERIES: MacroPoint[] = MONTHS_ALL.map((month, i) => {
  const rnd = mulberry32(4409 + i * 17);
  const wave = Math.sin((i / 14) * Math.PI * 2);
  const cpi = 6.4 + wave * 3.1 + (rnd() - 0.5) * 0.5 + i * 0.012;
  const feed = 100 + i * 0.62 + wave * 4.4 + (rnd() - 0.5) * 1.1;
  /* Farmgate follows feed with a ~4-month lag and a shallower slope. */
  const lagWave = Math.sin(((i - 4) / 14) * Math.PI * 2);
  const farmgate = 100 + i * 0.34 + lagWave * 2.6 + (rnd() - 0.5) * 0.8;
  return {
    key: month.key,
    cpiInflation: round(Math.max(0, cpi), 1),
    feedPriceIndex: round(feed, 1),
    farmgatePriceIndex: round(farmgate, 1),
  };
});

export const macroAt = (key: string) =>
  MACRO_SERIES.find((m) => m.key === key) ?? MACRO_SERIES[MACRO_SERIES.length - 1];

/* ------------------------------------------------------------------ */
/* Per-bucket measures                                                 */
/* ------------------------------------------------------------------ */

export interface TimelineMeasures {
  /* population, at the start of the bucket */
  milking: number;
  dry: number;
  heifer: number;
  calf: number;
  male: number;
  pregnant: number;
  totalHerd: number;

  /* health outcomes over the bucket */
  abortions: number;
  deaths: number;
  disease: Record<DiseaseCategory, number>;
  diseaseTotal: number;
  vaccinations: number;
  vetTreatments: number;
  treatments: Record<TreatmentCategory, number>;

  /* context */
  thi: number;
  cpiInflation: number;
  feedPriceIndex: number;
  farmgatePriceIndex: number;
}

/** herdAt walks the whole herd, so each date is resolved at most once. */
const snapshotCache = new Map<string, ReturnType<typeof herdAt>>();
const snapshotAt = (iso: string) => {
  const hit = snapshotCache.get(iso);
  if (hit) return hit;
  const snap = herdAt(iso);
  snapshotCache.set(iso, snap);
  return snap;
};

export function measuresFor(bucket: Bucket, granularity: 'week' | 'month'): TimelineMeasures {
  const snap = snapshotAt(bucket.start);
  const key = bucket.start.slice(0, 7);
  const monthIdx = MONTHS_ALL.findIndex((m) => m.key === key);
  const monthIdx0 = new Date(`${bucket.start}T00:00:00Z`).getUTCMonth();
  /* A week carries roughly a quarter of a month's events. */
  const share = granularity === 'week' ? 7 / 30.44 : 1;

  const outcome = HERD_OUTCOMES.find((o) => o.key === key);
  const recorded = RECORDED_BY_MONTH.get(key);
  const disease = bucket.future || !recorded
    ? expectedDisease(monthIdx0, 7717 + Math.max(0, monthIdx) * 13, snap.counts.Milking)
    : recorded;

  const scaled = DISEASE_CATEGORIES.reduce((acc, c) => {
    acc[c] = Math.round(disease[c] * share);
    return acc;
  }, blankDisease());
  const diseaseTotal = DISEASE_CATEGORIES.reduce((sum, c) => sum + scaled[c], 0);

  /* Vaccination programme: a herd-wide round each quarter, plus a steady
     trickle of calf doses as animals reach age. */
  const rnd = mulberry32(9931 + Math.max(0, monthIdx) * 29);
  const quarterRound = monthIdx0 % 3 === 0 ? Math.round(snap.total * 0.42) : 0;
  const calfDoses = Math.round(snap.counts.Calf * 0.22 + rnd() * 3);
  const vaccinations = Math.round((quarterRound + calfDoses) * share);

  /* Most treatments follow a disease event; the rest are a routine floor. */
  const treatments = blankTreatment();
  for (const category of DISEASE_CATEGORIES) {
    const mix = TREATMENT_MIX[category];
    for (const [treatment, weight] of Object.entries(mix) as [TreatmentCategory, number][]) {
      treatments[treatment] += scaled[category] * weight;
    }
  }
  treatments['Routine / preventive'] += snap.total * 0.02 * share + rnd() * 2;
  for (const t of TREATMENT_CATEGORIES) treatments[t] = Math.round(treatments[t]);
  const vetTreatments = TREATMENT_CATEGORIES.reduce((sum, t) => sum + treatments[t], 0);

  const macro = macroAt(key);

  return {
    milking: snap.counts.Milking,
    dry: snap.counts.Dry,
    heifer: snap.counts.Heifer,
    calf: snap.counts.Calf,
    male: snap.counts['Male / bull'],
    pregnant: snap.pregnant,
    totalHerd: snap.total,

    abortions: Math.round((outcome?.abortions ?? 0) * share),
    deaths: Math.round((outcome?.deaths ?? 0) * share),
    disease: scaled,
    diseaseTotal,
    vaccinations,
    vetTreatments,
    treatments,

    thi: bucket.thi,
    cpiInflation: macro.cpiInflation,
    feedPriceIndex: macro.feedPriceIndex,
    farmgatePriceIndex: macro.farmgatePriceIndex,
  };
}

/** Series metadata shared by the chart, its legend and its tooltip. */
export const POPULATION_SERIES = [
  { key: 'milking', label: 'Milking', color: '#1f6b4a' },
  { key: 'dry', label: 'Dry', color: '#8a9a94' },
  { key: 'pregnant', label: 'Pregnant', color: '#9a4f27' },
  { key: 'heifer', label: 'Heifers', color: '#b8860b' },
  { key: 'calf', label: 'Calves', color: '#6b5bd1' },
  { key: 'male', label: 'Male / bull', color: '#5b7fa6' },
] as const;
export type PopulationSeriesKey = (typeof POPULATION_SERIES)[number]['key'];

export { monthKey, isoDate };
