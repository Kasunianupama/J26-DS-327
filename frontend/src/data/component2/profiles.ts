/**
 * Interpretable profile-level lactation summaries.
 *
 * The similarity coordinates remain useful for model diagnostics, but these
 * helpers deliberately aggregate quantities a farm user can read directly:
 * days in milk, litres per day, recorded health events and AI attempts.
 */

import { DAY_MS, lactationTotal, round, woodsYield } from './core';
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
