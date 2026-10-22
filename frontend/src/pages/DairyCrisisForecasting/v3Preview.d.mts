import type { Assessment } from './member4Api';
export interface PreviewAssessment extends Assessment {
  preview: { kind: 'v3_average'; label: string; source_output_id: string; source_scoring_version: string;
    reason: string | null; stored_operational_score: number | null; stored_combined_score: number | null;
    model: 'Climate and Operational Risk Model'; domain_weights: { climate: 0.5; operational: 0.5 } };
}
export function previewV3(stored: Assessment): PreviewAssessment;
export function compareV3(rows: Assessment[]): {
  totalDays: number; eligibleDays: number; unavailableDays: number; duplicateDates: number;
  v2: { days: number; at100: number; mean: number | null };
  v3: { days: number; at100: number; mean: number | null };
};
