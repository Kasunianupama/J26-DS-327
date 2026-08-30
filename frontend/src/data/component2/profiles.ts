/**
 * Interpretable profile-level lactation summaries.
 *
 * The similarity coordinates remain useful for model diagnostics, but these
 * helpers deliberately aggregate quantities a farm user can read directly:
 * days in milk, litres per day, recorded health events and AI attempts.
 */

import { DAY_MS, lactationTotal, round, woodsYield, type Confidence } from './core';
import { HERD, PROFILES, type Animal, type ProfileId } from './herd';

export const PROFILE_IDS = Object.keys(PROFILES) as ProfileId[];

export interface ProfileCurvePoint {
  day: number;
  median: number;
  lower: number;
  upper: number;
}

export interface ProfileSummary {
  id: ProfileId;
  animals: Animal[];
  medianAtDay: number;
  lowerAtDay: number;
  upperAtDay: number;
  medianPeak: number;
  medianPeakDay: number;
  median305: number;
  totalContribution90: number;
  meanHealthEvents: number;
  meanAiAttempts: number;
}

export interface ProfileHologramState extends ProfileCurvePoint {
  healthEvents: number;
  meanAiAttempts: number;
  supportingAnimals: number;
}

/** Adults with an actual current or completed lactation behind the profile. */
export function profileCurveAnimals(profile: ProfileId): Animal[] {
  return HERD.filter(
    (animal) =>
      animal.profile === profile &&
      animal.sex === 'F' &&
      (animal.prodState === 'Milking' || animal.prodState === 'Dry'),
  );
}

function quantile(values: number[], q: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * q;
  const base = Math.floor(position);
  const rest = position - base;
  return sorted[base + 1] === undefined
    ? sorted[base]
    : sorted[base] + rest * (sorted[base + 1] - sorted[base]);
}

function curvePoint(animals: Animal[], day: number): ProfileCurvePoint {
  const values = animals.map((animal) => woodsYield(animal.woods, day));
  return {
    day,
    median: round(quantile(values, 0.5), 1),
    lower: round(quantile(values, 0.25), 1),
    upper: round(quantile(values, 0.75), 1),
  };
}

function mean(values: number[]): number {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function healthEventsByDay(animal: Animal, day: number): number {
  if (!animal.lastCalving) return 0;
  const calving = new Date(`${animal.lastCalving}T00:00:00Z`).getTime();
  return animal.healthEvents.filter((event) => {
    const eventTime = new Date(`${event.date}T00:00:00Z`).getTime();
    const eventDay = Math.round((eventTime - calving) / DAY_MS);
    return eventDay >= 0 && eventDay <= day;
  }).length;
}

export function buildProfileCurveSeries(maxDay: number, step = 5) {
  const days = new Set<number>();
  for (let day = 1; day <= maxDay; day += step) days.add(day);
  days.add(maxDay);

  const animals = new Map(PROFILE_IDS.map((id) => [id, profileCurveAnimals(id)]));
  return [...days].sort((a, b) => a - b).map((day) => {
    const row: Record<string, number | [number, number]> = { day };
    PROFILE_IDS.forEach((id) => {
      const point = curvePoint(animals.get(id) ?? [], day);
      row[id] = point.median;
      row[`${id}Band`] = [point.lower, point.upper];
      row[`${id}Low`] = point.lower;
      row[`${id}High`] = point.upper;
    });
    return row;
  });
}

export function profileSummary(profile: ProfileId, selectedDay: number): ProfileSummary {
  const animals = profileCurveAnimals(profile);
  const selected = curvePoint(animals, selectedDay);
  return {
    id: profile,
    animals,
    medianAtDay: selected.median,
    lowerAtDay: selected.lower,
    upperAtDay: selected.upper,
    medianPeak: round(quantile(animals.map((animal) => animal.peakYield), 0.5), 1),
    medianPeakDay: Math.round(quantile(animals.map((animal) => animal.peakDay), 0.5)),
    median305: Math.round(
      quantile(animals.map((animal) => lactationTotal(animal.woods, 1, 305)), 0.5),
    ),
    totalContribution90: animals.reduce((sum, animal) => sum + animal.contribution90, 0),
    meanHealthEvents: round(mean(animals.map((animal) => animal.healthEvents.length)), 1),
    meanAiAttempts: round(mean(animals.map((animal) => animal.aiAttempts)), 1),
  };
}

export function profileHologramState(profile: ProfileId, selectedDay: number): ProfileHologramState {
  const animals = profileCurveAnimals(profile);
  return {
    ...curvePoint(animals, selectedDay),
    healthEvents: round(mean(animals.map((animal) => healthEventsByDay(animal, selectedDay))), 1),
    meanAiAttempts: round(mean(animals.map((animal) => animal.aiAttempts)), 1),
    supportingAnimals: animals.length,
  };
}

/* ------------------------------------------------------------------ */
/* Profile indicators                                                  */
/* ------------------------------------------------------------------ */

export interface ProfileIndicators {
  /** Animals whose recorded curve supports this profile. */
  animals: number;
  /** Those animals as a share of the milking herd, %. */
  herdShare: number;
  /**
   * Yield at day 240 as a share of peak, %. This is the number that actually
   * separates a persistent group from a fast-tapering one.
   */
  persistence: number;
  /** Share of the herd's expected 90-day litres this group carries, %. */
  milkShare90: number;
  /** Median day of peak, and how far the selected day sits past it. */
  peakDay: number;
  daysPastPeak: number;
  /** Median projected 305-day lactation total, litres. */
  median305: number;
  /** The weakest confidence level found across the group. */
  confidence: Confidence;
  /** Share of the group whose forecast rests on peer data, %. */
  peerDerived: number;
}

const MILKING_HERD = HERD.filter((a) => a.prodState === 'Milking');
const HERD_CONTRIBUTION_90 = HERD.reduce((sum, a) => sum + a.contribution90, 0);

export function profileIndicators(profile: ProfileId, selectedDay: number): ProfileIndicators {
  const animals = profileCurveAnimals(profile);
  const n = Math.max(1, animals.length);
  const summary = profileSummary(profile, selectedDay);

  const persistence = round(mean(animals.map((a) => a.persistence)), 0);
  const peerDerived = round(
    (animals.filter((a) => a.evidence === 'Peer' || a.evidence === 'Herd' || a.evidence === 'Historical only').length / n) * 100,
    0,
  );
  const confidence: Confidence = animals.some((a) => a.confidence === 'Limited')
    ? 'Limited'
    : animals.some((a) => a.confidence === 'Moderate')
      ? 'Moderate'
      : 'High';

  return {
    animals: animals.length,
    herdShare: round((animals.length / Math.max(1, MILKING_HERD.length)) * 100, 0),
    persistence,
    milkShare90: round((summary.totalContribution90 / Math.max(1, HERD_CONTRIBUTION_90)) * 100, 1),
    peakDay: summary.medianPeakDay,
    daysPastPeak: selectedDay - summary.medianPeakDay,
    median305: summary.median305,
    confidence,
    peerDerived,
  };
}

/**
 * The aggregate lactation curve for one profile across a full 305-day
 * lactation, with its interquartile band. Days at or before the selected day
 * are what the group's recorded curves have already established; the rest is
 * the expected remainder of the lactation.
 */
export function profileLactationCurve(profile: ProfileId, step = 5): ProfileCurvePoint[] {
  const animals = profileCurveAnimals(profile);
  const days: number[] = [];
  for (let day = 1; day <= 305; day += step) days.push(day);
  if (days[days.length - 1] !== 305) days.push(305);
  return days.map((day) => curvePoint(animals, day));
}
