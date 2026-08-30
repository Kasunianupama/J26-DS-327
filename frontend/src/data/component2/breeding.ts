/**
 * Component 2 — breeding attention rules.
 *
 * Reproduction problems on a dairy farm are usually *absences*: a service that
 * was never recorded, a return to heat nobody saw, a pregnancy check that never
 * happened. None of those show up in a likelihood ranking, because an animal
 * with no recent event simply has no row worth ranking. These rules surface the
 * absences instead, by comparing each animal against a plain day threshold.
 *
 * The thresholds are prototype defaults chosen to match common dairy practice.
 * They are configurable numbers, not clinical guidance, and every alert states
 * the rule it fired on so a vet can disagree with it.
 */

import { type Confidence } from './core';
import { HERD, type Animal } from './herd';

/** Days after calving before an animal is normally offered for service. */
export const VOLUNTARY_WAIT_DAYS = 60;
/** Days in milk past which a first service should already be on record. */
export const FIRST_SERVICE_OVERDUE_DIM = 110;
/** A bovine oestrus cycle. A return is expected around this many days. */
export const OESTRUS_CYCLE_DAYS = 21;
/** Cycle plus observation slack — past this, a heat was probably missed. */
export const RETURN_WATCH_DAYS = 24;
/** Days after service by which a pregnancy check is normally done. */
export const PREGNANCY_CHECK_DAYS = 35;
/** Services without a confirmed pregnancy that define a repeat breeder. */
export const REPEAT_BREEDER_SERVICES = 3;
/** Days in milk without a confirmed pregnancy that count as extended days open. */
export const EXTENDED_DAYS_OPEN = 150;

export type BreedingAlertId =
  | 'no-service'
  | 'missed-return'
  | 'check-overdue'
  | 'repeat-breeder'
  | 'days-open';

export interface BreedingAlert {
  id: BreedingAlertId;
  label: string;
  severity: 'critical' | 'attention' | 'routine';
  /** The rule, stated so it can be argued with. */
  rule: string;
  /** What it costs if it is real. */
  consequence: string;
  /** What to do about it in DelPro. */
  action: string;
  animals: Animal[];
  confidence: Confidence;
}

const isMilking = (a: Animal) => a.prodState === 'Milking';
const notPregnant = (a: Animal) => a.reproState !== 'Pregnant';
const lastAi = (a: Animal) => a.aiEvents[0] ?? null;

export const BREEDING_ALERTS: BreedingAlert[] = (() => {
  const noService = HERD.filter(
    (a) => isMilking(a) && a.aiEvents.length === 0 && a.dim > FIRST_SERVICE_OVERDUE_DIM,
  );

  /* A recorded return to heat that was never followed by another service means
     at least one cycle has gone by unserved. */
  const missedReturn = HERD.filter((a) => {
    const last = lastAi(a);
    return (
      isMilking(a) && notPregnant(a) && last?.outcome === 'Returned to heat' &&
      (a.daysSinceLastAI ?? 0) > RETURN_WATCH_DAYS
    );
  });

  const checkOverdue = HERD.filter((a) => {
    const last = lastAi(a);
    return (
      isMilking(a) && last?.outcome === 'Awaiting check' &&
      (a.daysSinceLastAI ?? 0) > PREGNANCY_CHECK_DAYS
    );
  });

  const repeatBreeder = HERD.filter(
    (a) => isMilking(a) && notPregnant(a) && a.aiAttempts >= REPEAT_BREEDER_SERVICES,
  );

  const daysOpen = HERD.filter(
    (a) => isMilking(a) && notPregnant(a) && a.dim > EXTENDED_DAYS_OPEN,
  );

  const byDim = (x: Animal, y: Animal) => y.dim - x.dim;
  const bySinceAi = (x: Animal, y: Animal) => (y.daysSinceLastAI ?? 0) - (x.daysSinceLastAI ?? 0);

  return [
    {
      id: 'no-service',
      label: 'No insemination on record',
      severity: 'critical',
      rule: `Milking, past ${FIRST_SERVICE_OVERDUE_DIM} days in milk, and no service of any kind recorded.`,
      consequence:
        'Either a recording gap or a genuinely missed service. Each month of delay pushes a lactation entry out of the current horizon and deepens the next dry-off cluster.',
      action: 'Check the service record in DelPro first — a recording gap and a missed heat need different responses.',
      animals: [...noService].sort(byDim),
      confidence: 'High',
    },
    {
      id: 'missed-return',
      label: 'Return to heat not re-served',
      severity: 'critical',
      rule: `Last service returned to heat and more than ${RETURN_WATCH_DAYS} days have passed — longer than one ${OESTRUS_CYCLE_DAYS}-day cycle.`,
      consequence: 'At least one further heat has probably passed unobserved, adding roughly a cycle to days open.',
      action: 'Review heat detection for these animals and schedule the next service.',
      animals: [...missedReturn].sort(bySinceAi),
      confidence: 'Moderate',
    },
    {
      id: 'check-overdue',
      label: 'Pregnancy check overdue',
      severity: 'attention',
      rule: `Served, still marked awaiting check, and more than ${PREGNANCY_CHECK_DAYS} days since that service.`,
      consequence:
        'The animal is counted as neither pregnant nor open, so the lactation-entry forecast carries her at a wide range instead of a date.',
      action: 'Confirming these checks is the single fastest way to narrow the entry forecast.',
      animals: [...checkOverdue].sort(bySinceAi),
      confidence: 'High',
    },
    {
      id: 'repeat-breeder',
      label: 'Repeat breeder',
      severity: 'attention',
      rule: `${REPEAT_BREEDER_SERVICES} or more services with no confirmed pregnancy.`,
      consequence: 'Conception likelihood for these animals sits below the herd baseline, and semen cost accumulates against a falling return.',
      action: 'Worth a veterinary examination before a further service is scheduled.',
      animals: [...repeatBreeder].sort((x, y) => y.aiAttempts - x.aiAttempts),
      confidence: 'Moderate',
    },
    {
      id: 'days-open',
      label: 'Extended days open',
      severity: 'routine',
      rule: `Past ${EXTENDED_DAYS_OPEN} days in milk with no confirmed pregnancy.`,
      consequence: 'Each of these animals lengthens the calving interval and shifts her next lactation entry beyond the planning horizon.',
      action: 'Review against the culling and breeding plan rather than serving indefinitely.',
      animals: [...daysOpen].sort(byDim),
      confidence: 'High',
    },
  ].filter((alert) => alert.animals.length > 0) as BreedingAlert[];
})();

export const BREEDING_ALERT_SUMMARY = {
  total: BREEDING_ALERTS.reduce((sum, a) => sum + a.animals.length, 0),
  /** An animal can trip more than one rule; this counts each animal once. */
  animals: new Set(BREEDING_ALERTS.flatMap((a) => a.animals.map((x) => x.id))).size,
  critical: BREEDING_ALERTS.filter((a) => a.severity === 'critical').reduce((s, a) => s + a.animals.length, 0),
};
