import type { Assessment, Domain, DomainName } from './member4Api';
export function preferredAssessmentVersion(chosen: 'v1' | 'v2' | null, verifiedV2Count: number): 'v1' | 'v2';
export function formatChartScore(value: unknown): string;
export function riskCategoryLabel(category: string | undefined): string;
export function indicatorLabel(feature: string): string;
export function domainSummary(assessment: Assessment | undefined, name: DomainName): string;
export function combinedInsight(assessment: Assessment | undefined): string;
export function indicatorValue(indicator: Domain['indicators'][number] | undefined): string;
export function domainInsight(assessment: Assessment | undefined, name: DomainName): {
  title: string; value: string; text: string; positive: boolean;
};
export function historyForAssessment(rows: Assessment[], selected: Assessment | undefined, range?: string): {
  rows: Assessment[]; duplicateDates: number;
};
export function dailyChartRows(rows: Assessment[]): {
  date: string; Combined: number | null; Climate: number | null; Biological: number | null; Operational: number | null;
}[];
