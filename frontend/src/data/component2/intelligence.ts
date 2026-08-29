/**
 * Component 2 — findings, forecast structure, replay and evidence
 * (§9, §21, §22, §25, §26).
 */

import { EVENT_WINDOW, monthKey, round, type Confidence, type EvidenceSource } from './core';
import { DEFINING_MOVEMENT, MONTHS_ALL, DAILY } from './forecast';
import { HERD, MILKING, OCT_DRYOFFS, OCT_ENTRIES, type Animal } from './herd';
import { PRODUCT_CONSTRAINT, FINANCE_MONTHS, productMonth } from './commerce';

/* ------------------------------------------------------------------ */
/* Findings inbox (§25)                                                */
/* ------------------------------------------------------------------ */

export type FindingKind =
  | 'Action needed'
  | 'Upcoming'
  | 'Forecast change'
  | 'Data limitation'
  | 'Opportunity'
  | 'Confidence change';

export type Severity = 'critical' | 'attention' | 'routine';

export interface FindingLink {
  label: string;
  workspace: 'future' | 'capacity' | 'commerce' | 'evidence';
  tab?: 'milk' | 'reproduction' | 'genetics';
  date?: string;
  month?: string;
  animalId?: string;
}

export interface Finding {
  id: string;
  kind: FindingKind;
  severity: Severity;
  title: string;
  summary: string;
  /** The downstream consequence chain, kept in one finding rather than three. */
  chain?: { step: string; detail: string }[];
  confidence: Confidence;
  links: FindingLink[];
}

const octRevenue = FINANCE_MONTHS.find((f) => f.key === '2026-10');
const novMonth = MONTHS_ALL.find((m) => m.key === '2026-11');

export const FINDINGS: Finding[] = [
  {
    id: 'F1',
    kind: 'Forecast change',
    severity: 'critical',
    title: `Milk capacity expected to fall ${DEFINING_MOVEMENT.dropBand[0]}–${DEFINING_MOVEMENT.dropBand[1]}% between ${EVENT_WINDOW.label}`,
    summary: `${OCT_DRYOFFS.length} expected dry-offs are only partly offset by ${OCT_ENTRIES.length} likely lactation entries. The shortfall reaches the packing line before it reaches the margin.`,
    chain: [
      {
        step: 'Herd',
        detail: `${OCT_DRYOFFS.length} milking cows reach their dry-off window against ${OCT_ENTRIES.length} expected calvings, a net loss of ${OCT_DRYOFFS.length - OCT_ENTRIES.length} milking animals.`,
      },
      {
        step: 'Milk',
        detail: `Expected daily milk moves from about ${DEFINING_MOVEMENT.baselineDaily.toLocaleString()} L to about ${DEFINING_MOVEMENT.troughDaily.toLocaleString()} L across the window.`,
      },
      {
        step: 'Products',
        detail: PRODUCT_CONSTRAINT
          ? `The tetra-pack line is short about ${PRODUCT_CONSTRAINT.shortfallLitres.toLocaleString()} L in ${PRODUCT_CONSTRAINT.monthLabel}, because the raw-milk contract is filled first.`
          : 'No product line is expected to be constrained.',
      },
      {
        step: 'Finance',
        detail: octRevenue
          ? `Expected October margin sits about ${Math.abs(Math.round(((octRevenue.marginForecast ?? 0) - octRevenue.budgetMargin) / Math.max(1, octRevenue.budgetMargin) * 100))}% ${((octRevenue.marginForecast ?? 0) - octRevenue.budgetMargin) < 0 ? 'below' : 'above'} budget.`
          : 'Financial effect not yet quantified.',
      },
    ],
    confidence: 'Moderate',
    links: [
      { label: 'Open the October window', workspace: 'future', date: EVENT_WINDOW.start },
      { label: 'See which cows dry off', workspace: 'capacity', tab: 'milk', date: EVENT_WINDOW.start },
      { label: 'Product and margin effect', workspace: 'commerce', month: '2026-10' },
    ],
  },
  {
    id: 'F2',
    kind: 'Action needed',
    severity: 'critical',
    title: `${HERD.filter((a) => a.reproState === 'No service recorded' && a.dim > 110).length} cows past 110 days in milk with no insemination on record`,
    summary:
      'Either a recording gap or missed heats. Each month of delay pushes a lactation entry out of the current horizon and deepens the next dry-off cluster.',
    confidence: 'High',
    links: [
      { label: 'Open reproduction and capacity', workspace: 'capacity', tab: 'reproduction' },
    ],
  },
  {
    id: 'F3',
    kind: 'Confidence change',
    severity: 'attention',
    title: `November forecast confidence is limited`,
    summary: novMonth
      ? `About ${Math.round(novMonth.transitionShare * 100)}% of expected November milk depends on transitions that have not happened yet, so the likely range is wider than usual.`
      : 'Forecast confidence has moved for the coming period.',
    confidence: 'Limited',
    links: [
      { label: 'See what makes up November', workspace: 'future', date: '2026-11-15' },
      { label: 'Evidence and coverage', workspace: 'evidence' },
    ],
  },
  {
    id: 'F4',
    kind: 'Upcoming',
    severity: 'attention',
    title: `${HERD.filter((a) => a.reproState === 'Bred — awaiting check').length} pregnancy checks fall due in the next three weeks`,
    summary:
      'Confirming these moves a large block of expected milk from predicted to scheduled, which is the single fastest way to narrow the October range.',
    confidence: 'High',
    links: [{ label: 'Open the capacity flow', workspace: 'capacity', tab: 'reproduction' }],
  },
  {
    id: 'F5',
    kind: 'Data limitation',
    severity: 'routine',
    title: 'Individual abortion prediction is unavailable',
    summary:
      'Only 17 comparable historical events are recorded. That is too few to publish an animal-level estimate, so the model is held in a reduced state and reports at herd level only.',
    confidence: 'Limited',
    links: [{ label: 'Model and data coverage', workspace: 'evidence' }],
  },
  {
    id: 'F6',
    kind: 'Opportunity',
    severity: 'routine',
    title: 'F3 Jersey cross animals hold their curve about 9% longer',
    summary:
      'Across the recorded lactations, the F3 group keeps a flatter post-peak curve than F1. As its share of the milking herd grows, the same head count is expected to deliver more late-lactation milk.',
    confidence: 'Moderate',
    links: [{ label: 'Herd profile and genetics', workspace: 'capacity', tab: 'genetics' }],
  },
];

export const SEVERITY_META: Record<Severity, { label: string; color: string; bg: string; mark: string }> = {
  critical: { label: 'High priority', color: '#a44b3c', bg: '#fbe9e6', mark: '▲' },
  attention: { label: 'Worth attention', color: '#8a6414', bg: '#faf0d8', mark: '◆' },
  routine: { label: 'For information', color: '#4a6a5c', bg: '#e8efeb', mark: '●' },
};

/* ------------------------------------------------------------------ */
/* "What makes up this forecast?" (§21)                                */
/* ------------------------------------------------------------------ */

export interface ForecastStructure {
  title: string;
  headline: string;
  structure: { label: string; value: number; unit: string; share: number; kind: string }[];
  change: { headline: string; items: string[] };
  observations: string[];
  evidence: {
    individualShare: number;
    peerShare: number;
    transitionDependency: number;
    missing: string[];
    confidence: Confidence;
  };
  variations: ForecastVariation[];
}

export interface ForecastVariation {
  domain: 'Herd & milk' | 'Reproduction & health' | 'Products' | 'Finance & context';
  change: string;
  explanation: string;
  metrics: { label: string; value: string }[];
  verdict: string;
  contributors: ForecastContributor[];
  pathways: ForecastPathway[];
  coverage: { source: string; pct: number; note: string }[];
  residual: { value: string; explanation: string };
  falsifier: string;
}

export interface ForecastContributor {
  label: string;
  effect: string;
  magnitude: number;
  direction: 'positive' | 'negative' | 'neutral';
  source: 'Measured' | 'Derived' | 'Modelled';
  mechanism: string;
  evidence: string;
  confidence: Confidence;
}

export interface ForecastPathway {
  title: string;
  nodes: { stage: string; label: string; detail: string }[];
}

export function structureForDate(iso: string): ForecastStructure {
  const d = DAILY.find((x) => x.date === iso) ?? DAILY.find((x) => x.offset === 30)!;
  const pointIndex = Math.max(0, DAILY.findIndex((x) => x.date === d.date));
  const previous = DAILY[Math.max(0, pointIndex - 7)];
  const value = (point: typeof d) => point.expected ?? point.observed ?? 0;
  const milkNow = value(d);
  const milkBefore = value(previous);
  const milkDelta = milkNow - milkBefore;
  const currentWeek = DAILY.slice(Math.max(0, pointIndex - 6), pointIndex + 1);
  const previousWeek = DAILY.slice(Math.max(0, pointIndex - 13), Math.max(0, pointIndex - 6));
  const sum = (points: typeof DAILY, key: 'calvings' | 'dryOffs') => points.reduce((total, point) => total + point[key], 0);
  const calvings = sum(currentWeek, 'calvings');
  const dryOffs = sum(currentWeek, 'dryOffs');
  const previousCalvings = sum(previousWeek, 'calvings');
  const previousDryOffs = sum(previousWeek, 'dryOffs');
  const product = productMonth(monthKey(new Date(`${d.date}T00:00:00Z`)));
  const productIndex = product ? FINANCE_MONTHS.findIndex((m) => m.key === product.key) : -1;
  const priorProduct = productIndex > 0 ? productMonth(FINANCE_MONTHS[productIndex - 1].key) : undefined;
  const finance = productIndex >= 0 ? FINANCE_MONTHS[productIndex] : undefined;
  const priorFinance = productIndex > 0 ? FINANCE_MONTHS[productIndex - 1] : undefined;
  const margin = finance ? finance.marginForecast ?? finance.margin ?? 0 : 0;
  const priorMargin = priorFinance ? priorFinance.marginForecast ?? priorFinance.margin ?? 0 : 0;
  const rawDelta = product && priorProduct ? product.output['Raw milk'] - priorProduct.output['Raw milk'] : 0;
  const tetraDelta = product && priorProduct ? product.output['Tetra pack'] - priorProduct.output['Tetra pack'] : 0;
  const yoghurtDelta = product && priorProduct ? product.output.Yoghurt - priorProduct.output.Yoghurt : 0;
  const revenueNow = finance ? finance.revenueForecast ?? finance.revenue ?? 0 : 0;
  const revenueBefore = priorFinance ? priorFinance.revenueForecast ?? priorFinance.revenue ?? 0 : 0;
  const costNow = finance ? finance.costForecast ?? finance.cost ?? 0 : 0;
  const costBefore = priorFinance ? priorFinance.costForecast ?? priorFinance.cost ?? 0 : 0;
  const revenueDelta = revenueNow - revenueBefore;
  const costEffect = -(costNow - costBefore);
  const marginDelta = margin - priorMargin;
  const mixEffect = marginDelta - revenueDelta - costEffect;
  const herdHeadEffect = Math.round((d.milkers - previous.milkers) * (milkBefore / Math.max(1, previous.milkers)));
  const lactationEffect = Math.round(milkDelta * 0.62);
  const weatherEffect = Math.round(milkDelta - herdHeadEffect - lactationEffect);
  const healthEvents = Math.round(d.milkers * 0.04);
  const reproductionBalanceDelta = (calvings - dryOffs) - (previousCalvings - previousDryOffs);
  const signed = (amount: number, suffix: string) => `${amount >= 0 ? '+' : '−'}${Math.abs(Math.round(amount)).toLocaleString()} ${suffix}`;
  const total = d.expected ?? d.observed ?? 1;
  const entries = Object.entries(d.layers) as [string, number][];

  const individualShare = round(
    (MILKING.filter((a) => a.evidence === 'Individual' || a.evidence === 'Individual + peer')
      .reduce((s, a) => s + a.currentYield, 0) /
      Math.max(1, MILKING.reduce((s, a) => s + a.currentYield, 0))) * 100,
    0,
  );

  return {
    title: `Expected milk — ${iso}`,
    headline: `${Math.round(total).toLocaleString()} L expected on this day, from ${d.milkers} milking animals.`,
    structure: entries
      .filter(([, v]) => v > 0)
      .map(([label, value]) => ({
        label,
        value,
        unit: 'L/day',
        share: round((value / total) * 100, 1),
        kind: label.startsWith('New entrants') ? 'Depends on a future transition' : 'Already in the milking herd',
      })),
    change: {
      headline: 'October milk forecast decreased 2.8% since last week’s run.',
      items: [
        '3 revised calving dates moved entries later in the month',
        '2 animals left the herd',
        'Recent milk trajectories came in slightly under the fitted curves',
        'Updated heat-and-humidity outlook for late October',
        'New financial actuals through 27 August',
      ],
    },
    observations: [
      `${HERD.filter((a) => a.healthEvents.length >= 3).length} animals carry three or more health events this lactation`,
      'The high-yield shed moved to the revised concentrate ration in July',
      `Heat-and-humidity index for this period is around ${d.thi}`,
      `${HERD.filter((a) => a.reproState === 'Repeat breeder').length} repeat breeders are extending calving intervals`,
      PRODUCT_CONSTRAINT ? `Tetra-pack output is constrained from ${PRODUCT_CONSTRAINT.monthLabel}` : 'No product constraint detected',
    ],
    evidence: {
      individualShare,
      peerShare: 100 - individualShare,
      transitionDependency: Math.round(d.transitionShare * 100),
      missing: [
        'Individual feed intake is not recorded — rations are group-level only',
        'Body condition scoring is recorded irregularly',
        '11 animals have incomplete parentage',
      ],
      confidence: d.confidence,
    },
    variations: [
      {
        domain: 'Herd & milk',
        change: `${milkDelta >= 0 ? '+' : '−'}${Math.abs(Math.round(milkDelta)).toLocaleString()} L/day vs the previous 7 days`,
        explanation: milkDelta >= 0
          ? 'Milk is higher because more animals are moving toward peak production than are tapering or drying off in this period.'
          : 'Milk is lower because tapering cows and dry-offs outweigh the production gained from animals entering or approaching peak lactation.',
        metrics: [
          { label: 'Selected point', value: `${Math.round(milkNow).toLocaleString()} L/day` },
          { label: '7 days earlier', value: `${Math.round(milkBefore).toLocaleString()} L/day` },
          { label: 'Milking herd', value: `${d.milkers} head` },
          { label: 'Likely range', value: d.lower !== null && d.upper !== null ? `${d.lower.toLocaleString()}–${d.upper.toLocaleString()} L/day` : 'Recorded history' },
        ],
        verdict: `${Math.abs(lactationEffect) >= Math.abs(herdHeadEffect) ? 'Lactation stage mix' : 'Milking herd size'} is the largest modelled driver of this point’s movement.`,
        contributors: [
          { label: 'Lactation stage mix', effect: signed(lactationEffect, 'L/day'), magnitude: Math.abs(lactationEffect), direction: lactationEffect >= 0 ? 'positive' : 'negative', source: 'Derived', mechanism: 'Days-in-milk profiles shifted between the selected and comparison periods.', evidence: 'Individual lactation records and fitted yield curves', confidence: d.confidence },
          { label: 'Milking herd size', effect: signed(herdHeadEffect, 'L/day'), magnitude: Math.abs(herdHeadEffect), direction: herdHeadEffect >= 0 ? 'positive' : 'negative', source: 'Measured', mechanism: `${d.milkers} active milkers versus ${previous.milkers} seven days earlier.`, evidence: 'Recorded herd-state transitions', confidence: 'High' },
          { label: 'Season and heat load', effect: signed(weatherEffect, 'L/day'), magnitude: Math.abs(weatherEffect), direction: weatherEffect >= 0 ? 'positive' : 'negative', source: 'Modelled', mechanism: `Seasonal adjustment at a heat-and-humidity index of ${d.thi}.`, evidence: 'Weather station and historical seasonal response', confidence: 'Moderate' },
        ],
        pathways: [
          { title: 'Lactation pathway', nodes: [
            { stage: 'Driver', label: 'Individual lactation records', detail: 'Parity, days in milk and recent yield' },
            { stage: 'Mechanism', label: 'Stage-aware yield curves', detail: 'Peak, persistence and taper are estimated per animal' },
            { stage: 'Outcome', label: 'Expected herd milk', detail: `${Math.round(milkNow).toLocaleString()} L/day at the selected point` },
          ] },
          { title: 'Herd movement pathway', nodes: [
            { stage: 'Driver', label: 'Entries and dry-offs', detail: `${calvings} calvings and ${dryOffs} dry-offs in the surrounding week` },
            { stage: 'Mechanism', label: 'Active milking head', detail: `${d.milkers} animals contribute to the aggregate` },
            { stage: 'Outcome', label: 'Milk capacity', detail: `${signed(herdHeadEffect, 'L/day')} attributed to herd size` },
          ] },
          { title: 'Environmental pathway', nodes: [
            { stage: 'Driver', label: 'Heat and season', detail: `Heat index ${d.thi}` },
            { stage: 'Mechanism', label: 'Expected yield response', detail: 'Applied only where historical response is supported' },
            { stage: 'Outcome', label: 'Milk adjustment', detail: signed(weatherEffect, 'L/day') },
          ] },
        ],
        coverage: [
          { source: 'Milk sessions', pct: 99, note: 'Recorded individual and parlour totals' },
          { source: 'Herd-state records', pct: 98, note: 'Milking, dry and transition status' },
          { source: 'Weather station', pct: 91, note: 'Heat and humidity observations' },
          { source: 'Individual feed intake', pct: 42, note: 'Rations are mostly available at group level' },
        ],
        residual: { value: signed(milkDelta - lactationEffect - herdHeadEffect - weatherEffect, 'L/day'), explanation: 'Any unexplained remainder is kept separate instead of being assigned to the nearest driver.' },
        falsifier: 'A verified feed, health or recording change not present in these inputs could change the ranking of the milk drivers.',
      },
      {
        domain: 'Reproduction & health',
        change: `${calvings} calvings and ${dryOffs} dry-offs in the surrounding week`,
        explanation: calvings - dryOffs >= previousCalvings - previousDryOffs
          ? 'The herd transition balance has improved from the preceding week, supporting milk capacity.'
          : 'The herd transition balance has weakened from the preceding week, putting pressure on milk capacity.',
        metrics: [
          { label: 'Calvings this week', value: `${calvings}` },
          { label: 'Dry-offs this week', value: `${dryOffs}` },
          { label: 'Previous-week balance', value: `${previousCalvings} in / ${previousDryOffs} out` },
          { label: 'Health events flagged', value: `${healthEvents}` },
        ],
        verdict: `${reproductionBalanceDelta >= 0 ? 'Calving entries are offsetting exits more strongly' : 'Dry-offs and health risk are outweighing new entries'} than in the preceding week.`,
        contributors: [
          { label: 'Expected calvings', effect: signed(calvings - previousCalvings, 'events'), magnitude: Math.abs(calvings - previousCalvings), direction: calvings >= previousCalvings ? 'positive' : 'negative', source: 'Derived', mechanism: 'Confirmed pregnancies are converted to dated expected entries.', evidence: 'Services, pregnancy checks and expected calving dates', confidence: 'High' },
          { label: 'Expected dry-offs', effect: signed(-(dryOffs - previousDryOffs), 'events'), magnitude: Math.abs(dryOffs - previousDryOffs), direction: dryOffs <= previousDryOffs ? 'positive' : 'negative', source: 'Derived', mechanism: 'Dry-off dates remove animals from near-term milk capacity.', evidence: 'Lactation stage and planned dry-off records', confidence: 'High' },
          { label: 'Health events flagged', effect: signed(-healthEvents, 'risk flags'), magnitude: healthEvents, direction: healthEvents > 0 ? 'negative' : 'neutral', source: 'Measured', mechanism: 'Recent events increase uncertainty around conception and carrying to term.', evidence: 'Treatment and health-event history', confidence: 'Moderate' },
        ],
        pathways: [
          { title: 'Conception-to-calving pathway', nodes: [
            { stage: 'Driver', label: 'AI and service records', detail: 'Attempts, repeat services and service dates' },
            { stage: 'Checkpoint', label: 'Pregnancy confirmation', detail: 'Positive, negative and pending checks remain distinct' },
            { stage: 'Outcome', label: 'Expected calvings', detail: `${calvings} in the surrounding week` },
          ] },
          { title: 'Carried-to-term risk pathway', nodes: [
            { stage: 'Driver', label: 'Confirmed pregnancies', detail: 'Pregnancies with sufficient historical follow-up' },
            { stage: 'Risk', label: 'Health and abortion risk', detail: `${healthEvents} relevant health flags at this point` },
            { stage: 'Outcome', label: 'Likely herd entries', detail: 'Only pregnancies still expected to carry to term contribute' },
          ] },
          { title: 'Exit pathway', nodes: [
            { stage: 'Driver', label: 'Lactation stage', detail: 'Days in milk and taper determine planned exit timing' },
            { stage: 'Mechanism', label: 'Dry-off schedule', detail: `${dryOffs} expected dry-offs` },
            { stage: 'Outcome', label: 'Capacity pressure', detail: reproductionBalanceDelta >= 0 ? 'Lower than the prior period' : 'Higher than the prior period' },
          ] },
        ],
        coverage: [
          { source: 'AI and service records', pct: 97, note: 'Recorded attempts and dates' },
          { source: 'Pregnancy checks', pct: 92, note: 'Confirmed and pending outcomes' },
          { source: 'Health-event coding', pct: 84, note: 'Relevant recorded treatments and diagnoses' },
          { source: 'Abortion / carried-to-term outcomes', pct: 68, note: 'Historical outcome coding is incomplete' },
        ],
        residual: { value: `${Math.abs(reproductionBalanceDelta)} event${Math.abs(reproductionBalanceDelta) === 1 ? '' : 's'}`, explanation: 'This is the change in net entry/exit balance versus the preceding week, not a causal score.' },
        falsifier: 'Late pregnancy-check results, an unrecorded loss or a revised dry-off decision would change this pathway immediately.',
      },
      {
        domain: 'Products',
        change: product && priorProduct
          ? `Raw milk ${rawDelta >= 0 ? '+' : '−'}${Math.abs(rawDelta).toLocaleString()} L; tetra pack ${tetraDelta >= 0 ? '+' : '−'}${Math.abs(tetraDelta).toLocaleString()} L vs the previous month`
          : 'Product allocation is not available for this selected point.',
        explanation: product?.shortfall['Tetra pack']
          ? 'The raw-milk contract is allocated first, so the tetra-pack line absorbs the supply constraint at this point.'
          : 'All product lines remain within the planned allocation at this point; output changes follow the available milk supply.',
        metrics: product ? [
          { label: 'Raw milk output', value: `${product.output['Raw milk'].toLocaleString()} L` },
          { label: 'Tetra-pack output', value: `${product.output['Tetra pack'].toLocaleString()} L` },
          { label: 'Yoghurt output', value: `${product.output.Yoghurt.toLocaleString()} L` },
          { label: 'Tetra-pack constraint', value: product.shortfall['Tetra pack'] ? `${product.shortfall['Tetra pack'].toLocaleString()} L short` : 'None' },
        ] : [{ label: 'Availability', value: 'No monthly allocation for this point' }],
        verdict: product ? `${Math.abs(rawDelta) >= Math.abs(tetraDelta) ? 'Raw-milk allocation' : 'Tetra-pack allocation'} carries the largest change at this point.` : 'No product allocation is available for this point.',
        contributors: product ? [
          { label: 'Raw-milk allocation', effect: signed(rawDelta, 'L/month'), magnitude: Math.abs(rawDelta), direction: rawDelta >= 0 ? 'positive' : 'negative', source: 'Measured', mechanism: 'The contracted raw-milk requirement is allocated first.', evidence: 'Product allocation and dispatch records', confidence: 'High' },
          { label: 'Tetra-pack allocation', effect: signed(tetraDelta, 'L/month'), magnitude: Math.abs(tetraDelta), direction: tetraDelta >= 0 ? 'positive' : 'negative', source: 'Derived', mechanism: product.shortfall['Tetra pack'] ? 'This line absorbs the remaining supply constraint.' : 'Allocation follows remaining milk after contract priority.', evidence: 'Packing capacity and milk-balance plan', confidence: 'Moderate' },
          { label: 'Yoghurt allocation', effect: signed(yoghurtDelta, 'L/month'), magnitude: Math.abs(yoghurtDelta), direction: yoghurtDelta >= 0 ? 'positive' : 'negative', source: 'Derived', mechanism: 'Output follows remaining milk and line demand.', evidence: 'Product plan and production records', confidence: 'Moderate' },
        ] : [],
        pathways: product ? [
          { title: 'Supply-to-allocation pathway', nodes: [
            { stage: 'Driver', label: 'Available farm milk', detail: `${Math.round(milkNow).toLocaleString()} L/day at the selected point` },
            { stage: 'Priority', label: 'Raw-milk contract', detail: 'Contract volume is filled before discretionary lines' },
            { stage: 'Outcome', label: 'Raw milk', detail: `${product.output['Raw milk'].toLocaleString()} L allocated` },
          ] },
          { title: 'Processing pathway', nodes: [
            { stage: 'Driver', label: 'Milk after contract', detail: 'Remaining supply enters the processing plan' },
            { stage: 'Constraint', label: 'Packing-line capacity', detail: product.shortfall['Tetra pack'] ? `${product.shortfall['Tetra pack'].toLocaleString()} L tetra-pack shortfall` : 'No active tetra-pack constraint' },
            { stage: 'Outcome', label: 'Processed products', detail: `${product.output['Tetra pack'].toLocaleString()} L tetra pack and ${product.output.Yoghurt.toLocaleString()} L yoghurt` },
          ] },
        ] : [],
        coverage: [
          { source: 'Farm milk balance', pct: 99, note: 'Produced, used and unreconciled volume' },
          { source: 'Product allocation', pct: 96, note: 'Monthly output by product line' },
          { source: 'Packing constraints', pct: 91, note: 'Recorded line availability and limits' },
          { source: 'Product demand', pct: 86, note: 'Orders and plan assumptions' },
        ],
        residual: { value: product ? signed(rawDelta + tetraDelta + yoghurtDelta, 'L/month across shown lines') : 'Unavailable', explanation: 'Line effects are shown in their own volumes and are not combined into a single score.' },
        falsifier: 'A contract-priority change, unrecorded downtime or revised demand plan would change the allocation pathway.',
      },
      {
        domain: 'Finance & context',
        change: finance && priorFinance
          ? `Margin ${margin - priorMargin >= 0 ? '+' : '−'}LKR ${Math.abs(Math.round(margin - priorMargin)).toLocaleString()}k vs the previous month`
          : 'Financial variance is not available for this selected point.',
        explanation: margin >= priorMargin
          ? 'The margin movement follows improved milk availability and product revenue relative to the previous month.'
          : 'The margin movement reflects lower product revenue and the cost base continuing while milk availability changes.',
        metrics: finance ? [
          { label: 'Revenue', value: `LKR ${Math.round(finance.revenueForecast ?? finance.revenue ?? 0).toLocaleString()}k` },
          { label: 'Cost', value: `LKR ${Math.round(finance.costForecast ?? finance.cost ?? 0).toLocaleString()}k` },
          { label: 'Margin', value: `LKR ${Math.round(margin).toLocaleString()}k` },
          { label: 'Heat index', value: `${d.thi}` },
        ] : [{ label: 'Availability', value: 'No monthly finance for this point' }],
        verdict: finance ? `${Math.abs(revenueDelta) >= Math.abs(costEffect) ? 'Revenue movement' : 'Cost movement'} is the largest direct contributor to margin change.` : 'No finance period is available for this point.',
        contributors: finance ? [
          { label: 'Revenue movement', effect: signed(revenueDelta, 'LKR k'), magnitude: Math.abs(revenueDelta), direction: revenueDelta >= 0 ? 'positive' : 'negative', source: 'Measured', mechanism: 'Product volume and realised/forecast prices determine revenue.', evidence: 'Finance ledger and product sales plan', confidence: 'High' },
          { label: 'Cost movement', effect: signed(costEffect, 'LKR k margin'), magnitude: Math.abs(costEffect), direction: costEffect >= 0 ? 'positive' : 'negative', source: 'Measured', mechanism: 'A cost increase reduces margin and a cost decrease supports it.', evidence: 'Operating-cost ledger and budget', confidence: 'High' },
          { label: 'Product mix and timing', effect: signed(mixEffect, 'LKR k'), magnitude: Math.abs(mixEffect), direction: mixEffect >= 0 ? 'positive' : 'negative', source: 'Modelled', mechanism: 'Allocation timing and product mix reconcile revenue and cost to expected margin.', evidence: 'Product allocation model', confidence: 'Moderate' },
        ] : [],
        pathways: finance ? [
          { title: 'Revenue pathway', nodes: [
            { stage: 'Driver', label: 'Milk and product output', detail: 'Volume available to sell by product line' },
            { stage: 'Mechanism', label: 'Price and contract mix', detail: 'Realised or forecast rate by product' },
            { stage: 'Outcome', label: 'Revenue', detail: `LKR ${Math.round(revenueNow).toLocaleString()}k` },
          ] },
          { title: 'Cost pathway', nodes: [
            { stage: 'Driver', label: 'Feed and operating inputs', detail: 'Variable and fixed cost records' },
            { stage: 'Mechanism', label: 'Period cost base', detail: 'Costs continue even when milk availability moves' },
            { stage: 'Outcome', label: 'Cost', detail: `LKR ${Math.round(costNow).toLocaleString()}k` },
          ] },
          { title: 'Margin convergence', nodes: [
            { stage: 'Input', label: 'Revenue', detail: `LKR ${Math.round(revenueNow).toLocaleString()}k` },
            { stage: 'Input', label: 'Cost', detail: `LKR ${Math.round(costNow).toLocaleString()}k` },
            { stage: 'Outcome', label: 'Expected margin', detail: `LKR ${Math.round(margin).toLocaleString()}k` },
          ] },
        ] : [],
        coverage: [
          { source: 'Finance ledger', pct: 96, note: 'Recorded revenue and operating cost' },
          { source: 'Product sales and prices', pct: 94, note: 'Actuals and current contract assumptions' },
          { source: 'Budget categories', pct: 90, note: 'Cost plan by category' },
          { source: 'Context / heat index', pct: 91, note: 'Used as context, not merged into financial actuals' },
        ],
        residual: { value: finance ? signed(marginDelta - revenueDelta - costEffect - mixEffect, 'LKR k') : 'Unavailable', explanation: 'Unreconciled margin movement remains visible rather than being assigned to a named factor.' },
        falsifier: 'Late ledger postings, price corrections or costs recorded in another period would change this conclusion.',
      },
    ],
  };
}

/* ------------------------------------------------------------------ */
/* Forecast replay (§9)                                                */
/* ------------------------------------------------------------------ */

export interface ReplayVintage {
  madeOn: string;
  label: string;
  target: string;
  targetLabel: string;
  predicted: number;
  actual: number | null;
  errorPct: number | null;
  knownThen: string[];
  laterInformation: string[];
  confidenceThen: Confidence;
}

export const REPLAY_VINTAGES: ReplayVintage[] = [
  {
    madeOn: '2026-05-01',
    label: '01 May 2026',
    target: '2026-07',
    targetLabel: 'July 2026',
    predicted: 812400,
    actual: 795100,
    errorPct: -2.1,
    knownThen: [
      '138 milking animals on record',
      '29 confirmed pregnancies',
      'Financial actuals through April',
      'No revision to the July calving schedule',
    ],
    laterInformation: [
      '4 calving dates moved later in June',
      '1 animal exit',
      'Heat-and-humidity index ran above the seasonal norm for 11 days',
    ],
    confidenceThen: 'Moderate',
  },
  {
    madeOn: '2026-06-15',
    label: '15 June 2026',
    target: '2026-08',
    targetLabel: 'August 2026',
    predicted: 798600,
    actual: 786200,
    errorPct: -1.6,
    knownThen: [
      '141 milking animals on record',
      '34 confirmed pregnancies',
      'Financial actuals through May',
    ],
    laterInformation: [
      '2 unexpected dry-offs on health grounds',
      '3 pregnancy checks returned negative',
    ],
    confidenceThen: 'Moderate',
  },
  {
    madeOn: '2026-08-01',
    label: '01 August 2026',
    target: '2026-10',
    targetLabel: 'October 2026',
    predicted: 783000,
    actual: null,
    errorPct: null,
    knownThen: [
      `${MILKING.length - 4} milking animals on record`,
      'The October dry-off cluster was only partly visible',
      'Financial actuals through June',
    ],
    laterInformation: [
      '2 animal exits recorded in August',
      '3 revised calving dates pushed entries into November',
      'Recent milk trajectories came in under the fitted curves',
    ],
    confidenceThen: 'Moderate',
  },
  {
    madeOn: '2026-08-22',
    label: '22 August 2026',
    target: '2026-10',
    targetLabel: 'October 2026',
    predicted: 761400,
    actual: null,
    errorPct: null,
    knownThen: [
      `${MILKING.length} milking animals on record`,
      'The full October dry-off cluster was visible',
      'Financial actuals through 20 August',
    ],
    laterInformation: ['This is the previous run. The current forecast is 2.8% lower.'],
    confidenceThen: 'Moderate',
  },
];

/* ------------------------------------------------------------------ */
/* Evidence workspace (§22, §26)                                       */
/* ------------------------------------------------------------------ */

export type ModelStatus = 'Active' | 'Reduced' | 'Disabled';

export interface ModelCard {
  id: string;
  name: string;
  purpose: string;
  status: ModelStatus;
  statusReason: string;
  outputLevel: 'Individual animal' | 'Cohort' | 'Herd' | 'Farm';
  confidence: Confidence;
  advanced: {
    family: string;
    validationPeriod: string;
    mae: string;
    calibration: string;
    trainingSample: string;
    lastValidated: string;
  };
}

export const MODELS: ModelCard[] = [
  {
    id: 'lactation',
    name: 'Lactation trajectory',
    purpose: 'Estimates each cow’s remaining curve, peak timing and taper.',
    status: 'Active',
    statusReason: 'Sufficient recorded test-day observations for most of the milking herd.',
    outputLevel: 'Individual animal',
    confidence: 'High',
    advanced: {
      family: 'Incomplete gamma (Wood’s) curve with hierarchical shrinkage to parity and genetic group',
      validationPeriod: 'Mar 2026 – Aug 2026, rolling origin',
      mae: '1.42 L/day at 30 days ahead; 2.31 L/day at 90 days',
      calibration: 'Well calibrated; 90% interval covered 88.6% of held-out days',
      trainingSample: '412 completed and partial lactations',
      lastValidated: '2026-08-27',
    },
  },
  {
    id: 'herdmilk',
    name: 'Herd milk aggregation',
    purpose: 'Sums individual curves and transitions into the farm milk forecast.',
    status: 'Active',
    statusReason: 'Inherits its inputs from the lactation and transition models.',
    outputLevel: 'Farm',
    confidence: 'Moderate',
    advanced: {
      family: 'Deterministic aggregation with Monte-Carlo transition sampling (2,000 draws)',
      validationPeriod: 'Sep 2025 – Aug 2026',
      mae: '2.1% at 30 days; 4.8% at 90 days',
      calibration: 'Slightly over-confident beyond 120 days',
      trainingSample: '540 herd-days',
      lastValidated: '2026-08-27',
    },
  },
  {
    id: 'conception',
    name: 'Conception likelihood',
    purpose: 'Estimates whether a service is likely to hold.',
    status: 'Active',
    statusReason: 'Enough recorded services across the two-year window.',
    outputLevel: 'Individual animal',
    confidence: 'Moderate',
    advanced: {
      family: 'Penalised logistic regression with genetic-group random effect',
      validationPeriod: 'Jan 2026 – Aug 2026',
      mae: 'Brier score 0.198',
      calibration: 'Reliable between 0.25 and 0.75; extremes are compressed',
      trainingSample: '590 services, 291 confirmed',
      lastValidated: '2026-08-27',
    },
  },
  {
    id: 'calving',
    name: 'Calving date progression',
    purpose: 'Projects when pregnant animals will calve and re-enter milking.',
    status: 'Active',
    statusReason: 'Gestation is well constrained; the uncertainty is in service dating.',
    outputLevel: 'Individual animal',
    confidence: 'High',
    advanced: {
      family: 'Gestation-length distribution conditioned on parity and genetic group',
      validationPeriod: 'Sep 2025 – Aug 2026',
      mae: '4.6 days',
      calibration: 'Well calibrated',
      trainingSample: '188 recorded calvings',
      lastValidated: '2026-08-27',
    },
  },
  {
    id: 'dryperiod',
    name: 'Dry-period recommendation',
    purpose: 'Suggests a rest window balancing welfare, next-lactation yield and capacity.',
    status: 'Reduced',
    statusReason:
      'Published for animals with a completed previous lactation only. Others show schedule dates without a recommendation.',
    outputLevel: 'Individual animal',
    confidence: 'Moderate',
    advanced: {
      family: 'Matched-comparison estimator over historical dry-period lengths',
      validationPeriod: 'Sep 2024 – Aug 2026',
      mae: 'Not applicable — comparison-based',
      calibration: 'Not applicable',
      trainingSample: '163 completed dry periods',
      lastValidated: '2026-08-20',
    },
  },
  {
    id: 'products',
    name: 'Product allocation',
    purpose: 'Splits expected milk across raw, tetra pack, yoghurt and by-products.',
    status: 'Active',
    statusReason: 'Two years of consistent allocation history.',
    outputLevel: 'Farm',
    confidence: 'Moderate',
    advanced: {
      family: 'Priority-fill allocation fitted to observed operating patterns',
      validationPeriod: 'Sep 2024 – Aug 2026',
      mae: '3.4% on tetra-pack volume',
      calibration: 'Not applicable',
      trainingSample: '24 months',
      lastValidated: '2026-08-27',
    },
  },
  {
    id: 'finance',
    name: 'Cost and margin projection',
    purpose: 'Scales cost lines by herd and volume drivers, then closes to margin.',
    status: 'Active',
    statusReason: 'Driver-based rather than a pure time series, so 24 months is workable.',
    outputLevel: 'Farm',
    confidence: 'Moderate',
    advanced: {
      family: 'Driver-based cost model; seasonal-naive with price-index adjustment for volume-linked lines',
      validationPeriod: 'Mar 2026 – Aug 2026',
      mae: '4.1% on total monthly cost',
      calibration: 'Not applicable',
      trainingSample: '24 months of line-item actuals',
      lastValidated: '2026-08-27',
    },
  },
  {
    id: 'vetcost',
    name: 'Veterinary cost',
    purpose: 'Estimates normal veterinary expenditure from the recorded event rate.',
    status: 'Reduced',
    statusReason:
      'Routine health is estimated. Treatment cost is reported as a range only, because event coding is inconsistent before March 2025.',
    outputLevel: 'Farm',
    confidence: 'Limited',
    advanced: {
      family: 'Event-rate × unit-cost with a seasonal adjustment',
      validationPeriod: 'Mar 2025 – Aug 2026',
      mae: '18.7% on monthly treatment cost',
      calibration: 'Not applicable',
      trainingSample: '17 months of usable records',
      lastValidated: '2026-08-20',
    },
  },
  {
    id: 'abortion',
    name: 'Abortion likelihood',
    purpose: 'Would estimate the chance a pregnancy does not reach term.',
    status: 'Disabled',
    statusReason:
      'Only 17 comparable historical events are available. That is too few to publish an animal-level estimate.',
    outputLevel: 'Herd',
    confidence: 'Limited',
    advanced: {
      family: 'Not fitted',
      validationPeriod: 'Not applicable',
      mae: 'Not applicable',
      calibration: 'Not applicable',
      trainingSample: '17 events',
      lastValidated: 'Never',
    },
  },
  {
    id: 'mortality',
    name: 'Mortality review priority',
    purpose: 'Ranks animals for review. Not a diagnosis and not a management recommendation.',
    status: 'Reduced',
    statusReason: 'Published as a ranked priority with a wide range, never as a label.',
    outputLevel: 'Individual animal',
    confidence: 'Limited',
    advanced: {
      family: 'Gradient-boosted ranking over health, parity and cell-count history',
      validationPeriod: 'Sep 2025 – Aug 2026',
      mae: 'Concordance 0.68',
      calibration: 'Poorly calibrated in absolute terms; use the ranking, not the level',
      trainingSample: '31 events',
      lastValidated: '2026-08-20',
    },
  },
  {
    id: 'culling',
    name: 'Culling / sale likelihood',
    purpose: 'Would estimate the chance an animal leaves the herd commercially.',
    status: 'Reduced',
    statusReason:
      'Sale reasons are not consistently coded, so the estimate is reported at cohort level only.',
    outputLevel: 'Cohort',
    confidence: 'Limited',
    advanced: {
      family: 'Discrete-time hazard model',
      validationPeriod: 'Sep 2025 – Aug 2026',
      mae: 'Brier score 0.121',
      calibration: 'Acceptable at cohort level, unreliable per animal',
      trainingSample: '44 exits',
      lastValidated: '2026-08-20',
    },
  },
];

export interface CoverageRow {
  source: string;
  coverage: number;
  through: string;
  gaps: string;
  note: string;
}

export const DATA_COVERAGE: CoverageRow[] = [
  { source: 'Herd & animal records', coverage: 97, through: '2026-08-27', gaps: '11 animals with incomplete parentage', note: 'Strong. Parentage gaps only affect genetic grouping.' },
  { source: 'Milk recording', coverage: 94, through: '2026-08-27', gaps: '6–19 Feb 2026 (meter fault)', note: 'The February gap is interpolated and excluded from model fitting.' },
  { source: 'Reproduction events', coverage: 88, through: '2026-08-26', gaps: 'Heat observations sparse before Mar 2025', note: 'Service dating is the main source of calving-date uncertainty.' },
  { source: 'Health & treatment', coverage: 71, through: '2026-08-25', gaps: 'Inconsistent event coding before Mar 2025', note: 'Limits veterinary cost prediction and rare-event models.' },
  { source: 'Feed & rations', coverage: 82, through: '2026-08-24', gaps: 'Group-level only; no individual intake', note: 'Supports cost modelling, not per-animal nutrition response.' },
  { source: 'Product output', coverage: 96, through: '2026-08-27', gaps: 'None material', note: 'Two full years of allocation history.' },
  { source: 'Finance & budget', coverage: 99, through: '2026-08-27', gaps: 'None material', note: 'Line-item detail available throughout.' },
  { source: 'Weather / heat index', coverage: 100, through: '2026-08-28', gaps: 'None', note: 'Station data with a forward outlook.' },
  { source: 'Price indices', coverage: 100, through: '2026-07-31', gaps: 'Published with a one-month lag', note: 'Used only where it measurably improves a cost line.' },
];

export const CONFIDENCE_BY_HORIZON = [
  { horizon: '0–30 days', confidence: 'High' as Confidence, note: 'Almost entirely animals already milking.', transitionShare: 8 },
  { horizon: '30–90 days', confidence: 'Moderate' as Confidence, note: 'The October transition cluster dominates.', transitionShare: 24 },
  { horizon: '90–180 days', confidence: 'Moderate' as Confidence, note: 'Depends on services not yet confirmed.', transitionShare: 38 },
  { horizon: '180–365 days', confidence: 'Limited' as Confidence, note: 'Most contributing lactations have not started.', transitionShare: 61 },
];

export const RECENT_CONFIDENCE_CHANGES = [
  { when: '2026-08-29', what: 'November milk moved from Moderate to Limited', why: '3 revised calving dates increased dependence on unconfirmed transitions.' },
  { when: '2026-08-27', what: 'Veterinary treatment cost held at Limited', why: 'Event coding before March 2025 remains inconsistent.' },
  { when: '2026-08-20', what: 'Dry-period recommendation reduced in scope', why: 'Published only for animals with a completed previous lactation.' },
];

export const RARE_EVENT_EVIDENCE = [
  { event: 'Abortion', events: 17, verdict: 'Insufficient for animal-level prediction', level: 'Herd rate only' },
  { event: 'Mortality', events: 31, verdict: 'Ranking only, not an absolute likelihood', level: 'Review priority' },
  { event: 'Culling / sale', events: 44, verdict: 'Cohort level only; sale reasons not coded consistently', level: 'Cohort' },
  { event: 'Retained placenta', events: 58, verdict: 'Usable as a predictor, not as an outcome', level: 'Predictor' },
];

/* ------------------------------------------------------------------ */
/* Sensitive outcome framing (§26)                                     */
/* ------------------------------------------------------------------ */

export interface ReviewPriority {
  animal: Animal;
  range: [number, number];
  baseline: number;
  confidence: Confidence;
  drivers: string[];
}

export const REVIEW_PRIORITIES: ReviewPriority[] = HERD.filter((a) => a.mortalityRisk90)
  .sort((x, y) => (y.mortalityRisk90![1] ?? 0) - (x.mortalityRisk90![1] ?? 0))
  .slice(0, 12)
  .map((a) => ({
    animal: a,
    range: a.mortalityRisk90!,
    baseline: a.mortalityBaseline,
    confidence: 'Limited' as Confidence,
    drivers: [
      `${a.healthEvents.length} recorded health events`,
      a.parity >= 5 ? `Parity ${a.parity}` : `Parity ${a.parity}`,
      a.scc > 430 ? `Somatic cell count ${a.scc}k` : `Somatic cell count ${a.scc}k`,
    ],
  }));

export const SENSITIVE_DISCLAIMER =
  'This is a predictive ranking, not a diagnosis or a management recommendation.';

export const OBSERVATION_DISCLAIMER =
  'These observations are related to the forecast. They do not prove that one caused another.';

export type { EvidenceSource };
