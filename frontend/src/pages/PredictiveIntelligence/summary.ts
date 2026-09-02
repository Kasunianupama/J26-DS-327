/**
 * Component 2 — one derivation of the headline numbers.
 *
 * The command-bar metric strip and the Farm Outlook hero must never disagree,
 * so both read the selected horizon through this single function.
 */

import {
  DAILY,
  HORIZONS,
  financeMonth,
  productMonth,
  type Confidence,
  type HorizonId,
} from '../../data/component2';
import type { BackendOverview } from './backend';

export interface HorizonSummary {
  label: string;
  days: number;
  points: typeof DAILY;
  first: typeof DAILY[number];
  last: typeof DAILY[number];
  lowPoint: typeof DAILY[number];
  averageDailyMilk: number;
  averagePerCow: number;
  earlyMilk: number;
  lateMilk: number;
  changePct: number;
  dryOffs: number;
  entries: number;
  netMovement: number;
  confidence: Confidence;
  endMonth: string;
  finance: ReturnType<typeof financeMonth>;
  product: ReturnType<typeof productMonth>;
  marginGap: number;
  /** Down-sampled expected-litre series for the inline sparklines. */
  spark: number[];
}

const mean = <T,>(items: T[], measure: (item: T) => number) =>
  items.reduce((sum, item) => sum + measure(item), 0) / Math.max(1, items.length);

export function horizonSummary(horizon: HorizonId): HorizonSummary {
  const option = HORIZONS.find((h) => h.id === horizon) ?? HORIZONS[1];
  const points = DAILY.filter((p) => p.offset > 0 && p.offset <= option.days);
  const early = points.slice(0, Math.min(7, points.length));
  const late = points.slice(-Math.min(7, points.length));

  const averageDailyMilk = mean(points, (p) => p.expected ?? 0);
  const averagePerCow = mean(points, (p) => (p.expected ?? 0) / Math.max(1, p.milkers));
  const earlyMilk = mean(early, (p) => p.expected ?? 0);
  const lateMilk = mean(late, (p) => p.expected ?? 0);
  const changePct = ((lateMilk - earlyMilk) / Math.max(1, earlyMilk)) * 100;

  const lowPoint = points.reduce(
    (lowest, p) => ((p.expected ?? Infinity) < (lowest.expected ?? Infinity) ? p : lowest),
    points[0],
  );
  const dryOffs = points.reduce((sum, p) => sum + p.dryOffs, 0);
  const entries = points.reduce((sum, p) => sum + p.calvings, 0);

  const confidence: Confidence = points.some((p) => p.confidence === 'Limited')
    ? 'Limited'
    : points.some((p) => p.confidence === 'Moderate')
      ? 'Moderate'
      : 'High';

  const endMonth = points[points.length - 1]?.date.slice(0, 7) ?? '2026-09';
  const finance = financeMonth(endMonth);
  const product = productMonth(lowPoint?.date.slice(0, 7) ?? endMonth);
  const marginGap = finance ? (finance.marginForecast ?? finance.margin ?? 0) - finance.budgetMargin : 0;

  /* ~40 evenly spaced samples keeps every horizon's sparkline the same weight. */
  const step = Math.max(1, Math.floor(points.length / 40));
  const spark = points.filter((_, i) => i % step === 0).map((p) => p.expected ?? 0);

  return {
    label: option.label,
    days: option.days,
    points,
    first: points[0],
    last: points[points.length - 1],
    lowPoint,
    averageDailyMilk,
    averagePerCow,
    earlyMilk,
    lateMilk,
    changePct,
    dryOffs,
    entries,
    netMovement: entries - dryOffs,
    confidence,
    endMonth,
    finance,
    product,
    marginGap,
    spark,
  };
}

/** Overlay the API-owned headline values while retaining rich local points as
 * an explicit prototype fallback for charts that have not loaded yet. */
export function withBackendOverview(local: HorizonSummary, remote?: BackendOverview): HorizonSummary {
  if (!remote) return local;
  return {
    ...local,
    label: remote.label,
    days: remote.days,
    averageDailyMilk: remote.average_daily_milk,
    averagePerCow: remote.average_per_cow,
    earlyMilk: remote.early_milk,
    lateMilk: remote.late_milk,
    changePct: remote.change_percent,
    dryOffs: remote.dry_offs,
    entries: remote.entries,
    netMovement: remote.net_movement,
    confidence: remote.confidence,
    marginGap: remote.margin_gap_lkr_thousands,
    spark: remote.spark,
    first: { ...local.first, date: remote.start_date },
    last: { ...local.last, date: remote.end_date },
    lowPoint: {
      ...local.lowPoint,
      ...remote.low_point,
      observed: null,
    },
  };
}
