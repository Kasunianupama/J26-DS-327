/**
 * Reproductive outcomes, herd movement and risk over the shared timeline.
 * These are synthetic prototype records. Past values are labelled recorded;
 * future values are modelled from the observed service pattern and herd plan.
 */

import { monthLabel, mulberry32, round, type Confidence } from './core';
import { MONTHS_ALL } from './forecast';
import { HERD } from './herd';

export interface RiskProfile {
  label: string;
  count: number;
  tone: 'stable' | 'review' | 'risk';
  description: string;
  drivers: string[];
}

export interface HerdOutcomePoint {
  key: string;
  label: string;
  start: string;
  future: boolean;
  confidence: Confidence;
  aiAttempts: number;
  aiSuccess: number;
  aiFailure: number;
  carriedToTerm: number;
  abortions: number;
  deaths: number;
  transfersIn: number;
  transfersOut: number;
  riskPoints: number;
  factors: string[];
  profiles: RiskProfile[];
}

const highRiskBase = HERD.filter((animal) =>
  animal.healthEvents.length >= 3 || animal.reproState === 'Repeat breeder' || animal.reproState === 'No service recorded',
).length;
const reviewBase = HERD.filter((animal) =>
  animal.reproState === 'Bred — awaiting check' || animal.reproState === 'Eligible to breed' || animal.healthEvents.length === 2,
).length;

export const HERD_OUTCOMES: HerdOutcomePoint[] = MONTHS_ALL.map((month, index) => {
  const rnd = mulberry32(8119 + index * 31);
  const seasonPressure = Math.max(0, Math.sin(((index + 4) / 12) * Math.PI * 2));
  const futurePenalty = month.future ? Math.min(0.1, Math.max(0, index - MONTHS_ALL.findIndex((item) => item.future)) * 0.006) : 0;
  const aiAttempts = Math.max(7, Math.round(16 + rnd() * 11 - seasonPressure * 3));
  const successRate = 0.49 - seasonPressure * 0.08 - futurePenalty + (rnd() - 0.5) * 0.06;
  const aiSuccess = Math.max(2, Math.round(aiAttempts * successRate));
  const aiFailure = aiAttempts - aiSuccess;
  const abortions = Math.max(0, Math.round((seasonPressure > 0.78 ? 1.3 : 0.45) + rnd() * 0.8));
  const carriedToTerm = Math.max(0, Math.round(aiSuccess * (0.84 - futurePenalty * 0.3) + rnd() * 2 - abortions));
  const deaths = rnd() > 0.82 ? 1 : 0;
  const transfersIn = Math.max(0, Math.round(rnd() * 2 + (month.future && index % 7 === 0 ? 1 : 0)));
  const transfersOut = Math.max(0, Math.round(rnd() * 2 + (month.future && index % 6 === 0 ? 1 : 0)));
  const riskPoints = Math.round(28 + seasonPressure * 26 + aiFailure * 1.1 + abortions * 7 + deaths * 9 + futurePenalty * 100);
  const highRisk = Math.max(4, highRiskBase + Math.round(seasonPressure * 5 + abortions * 2 + futurePenalty * 25));
  const review = Math.max(8, reviewBase + Math.round(aiFailure * 0.55 + seasonPressure * 4));
  const stable = Math.max(0, HERD.length - highRisk - review);

  return {
    key: month.key,
    label: monthLabel(month.key),
    start: month.start,
    future: month.future,
    confidence: month.future ? (futurePenalty > 0.04 ? 'Limited' : month.confidence) : 'High',
    aiAttempts,
    aiSuccess,
    aiFailure,
    carriedToTerm,
    abortions,
    deaths,
    transfersIn,
    transfersOut,
    riskPoints,
    factors: month.future
      ? [
          `${aiAttempts} planned or expected AI services`,
          `${review} animals need confirmation or reproductive review`,
          `Heat and humidity contributes ${Math.round(seasonPressure * 100)}% of the seasonal risk load`,
          `${transfersIn} expected transfers in and ${transfersOut} expected transfers out`,
        ]
      : [
          `${aiAttempts} recorded AI services`,
          `${aiSuccess} recorded conceptions and ${aiFailure} services without a recorded conception`,
          `${carriedToTerm} recorded carried-to-term outcomes and ${abortions} recorded abortions`,
          `${deaths} recorded deaths; ${transfersIn + transfersOut} recorded transfers`,
        ],
    profiles: [
      {
        label: 'Stable profile', count: stable, tone: 'stable',
        description: 'No current reproductive or health trigger affecting capacity.',
        drivers: ['Completed records', 'No repeated health event pattern'],
      },
      {
        label: 'Review profile', count: review, tone: 'review',
        description: 'Needs a pregnancy check, service follow-up, or health review.',
        drivers: ['AI outcome awaiting confirmation', 'Two recent health events or delayed service'],
      },
      {
        label: 'Higher-risk profile', count: highRisk, tone: 'risk',
        description: 'May reduce future capacity without follow-up or a successful transition.',
        drivers: ['Repeat breeding or no service record', 'Three or more health events', 'Pregnancy loss exposure'],
      },
    ],
  };
});

export const outcomeAt = (iso: string) => {
  const index = HERD_OUTCOMES.findIndex((point, i) =>
    point.start <= iso && (!HERD_OUTCOMES[i + 1] || HERD_OUTCOMES[i + 1].start > iso),
  );
  return HERD_OUTCOMES[Math.max(0, index)];
};

export const overallOutcomeSummary = {
  recordedAbortionRate: round(
    (HERD_OUTCOMES.filter((point) => !point.future).reduce((sum, point) => sum + point.abortions, 0) /
      Math.max(1, HERD_OUTCOMES.filter((point) => !point.future).reduce((sum, point) => sum + point.carriedToTerm + point.abortions, 0))) * 100,
    1,
  ),
};
