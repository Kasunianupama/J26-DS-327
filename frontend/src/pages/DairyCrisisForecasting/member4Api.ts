import { api } from '../../services/api';
import { validatePublishedV3Rows } from './publishedV3.mjs';

// OFF until the owner verifies publication and deliberately enables the local build.
export const publishedV3Mode = import.meta.env.VITE_C4_PUBLISHED_V3_ENABLED === 'true';

export type DomainName = 'climate' | 'biological' | 'operational';
export interface Rule { feature: string; lower: number; upper: number; direction: string; rationale: string }
export interface Domain {
  domain: DomainName; status: string; score: number | null; explanation: string;
  indicators: { feature: string; value: number | null; score: number | null; explanation: string }[];
}
export interface Assessment {
  output_id: string; assessment_date: string; contract_version: string;
  combined_score: number | null; risk_category: string; data_completeness: string;
  domains: Domain[]; explanations: string[]; contributions: Partial<Record<DomainName, number | null>>;
  score_basis?: string; recording_quality?: string; assumptions?: string;
  provenance: { source: string; core_version: string | null; availability: string };
  scoring_config: { version: string; rationale: string; climate_rules: Rule[]; biological_rules: Rule[];
    operational_rules: Rule[]; climate_weight: number; biological_weight: number; operational_weight: number;
    medium_starts_at: number; high_starts_at: number };
}
export interface Prediction {
  prediction_id: string; assessment_date: string; predicted_decline_probability: number;
  actual_outcome: boolean | null; saved_threshold: number | null; predicted_decline: boolean | null;
  model_status: string; artifact_version: string; classification_status: string; experiment_partition: string;
}
export interface C1Forecast { target_period: string; horizon: number; forecast: number;
  quality_flag: string; model_version: string; core_version: string; origin_date: string;
  lower?: number | null; upper?: number | null; created_at?: string | null }
type Obj = Record<string, unknown>;
function object(v: unknown): Obj {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('Invalid API contract.');
  return v as Obj;
}
const numeric = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const score = (v: unknown) => v === null || (numeric(v) && v >= 0 && v <= 100);
const date = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v));
const strings = (v: unknown) => Array.isArray(v) && v.every(x => typeof x === 'string');
function research(r: Obj) {
  if (r.farm_id !== 'FARM_X' || r.research_only !== true || r.live_warning_allowed !== false)
    throw new Error('Unsupported research output or farm.');
}
// Proposed endpoints, NOT the existing demo risks route. Disabled until team approval.
async function collection(path: string, signal: AbortSignal): Promise<unknown[]> {
  if (import.meta.env.VITE_C4_RESEARCH_API_ENABLED !== 'true')
    throw new Error('Published Member 4 API is not enabled. Backend integration approval is required.');
  const { data } = await api.get<unknown>(path, { signal, timeout: 15000, withCredentials: true });
  const envelope = object(data);
  if (envelope.source !== 'published' || envelope.contract_version !== '1.0.0' || !Array.isArray(envelope.items))
    throw new Error('Published API contract unavailable. Demo data is not accepted.');
  return envelope.items;
}
export async function loadAssessments(signal: AbortSignal): Promise<Assessment[]> {
  return loadAssessmentVersion(signal, 'v1');
}
export async function loadV2Assessments(signal: AbortSignal): Promise<Assessment[]> {
  return loadAssessmentVersion(signal, 'v2');
}
export async function loadPublishedV3Assessments(signal: AbortSignal): Promise<Assessment[]> {
  if (!publishedV3Mode) return [];
  return validatePublishedV3Rows(await collection('/risks/research/farms/FARM_X/assessments?scoring_version=v3', signal));
}
export const loadLegacyV1 = (signal: AbortSignal) => publishedV3Mode ? Promise.resolve([] as Assessment[]) : loadAssessments(signal);
export const loadLegacyV2 = (signal: AbortSignal) => publishedV3Mode ? Promise.resolve([] as Assessment[]) : loadV2Assessments(signal);
async function loadAssessmentVersion(signal: AbortSignal, generation: 'v1' | 'v2'): Promise<Assessment[]> {
  const rows = await collection(`/risks/research/farms/FARM_X/assessments?scoring_version=${generation}`, signal);
  const ids = new Set<string>();
  const result = rows.map(value => {
    const r = object(value); research(r);
    const p = object(r.provenance), c = object(r.scoring_config);
    if (!['1.0.0', '1.1.0'].includes(String(r.contract_version)) || !date(r.assessment_date) ||
        !['2025', '2026'].includes(r.assessment_date.slice(0, 4)) || typeof r.output_id !== 'string' ||
        ids.has(r.output_id) || !score(r.combined_score) || !strings(r.explanations) ||
        p.source !== 'published' || !Array.isArray(r.domains) || r.domains.length !== 3 ||
        !['low_provisional', 'medium_provisional', 'high_provisional', 'unavailable'].includes(String(r.risk_category)) ||
        typeof c.version !== 'string' || typeof c.rationale !== 'string') throw new Error('Invalid assessment contract.');
    ids.add(r.output_id);
    const names = new Set<string>();
    r.domains.forEach(value => {
      const d = object(value);
      if (!['climate', 'biological', 'operational'].includes(String(d.domain)) || names.has(String(d.domain)) ||
          !score(d.score) || !['available', 'partial', 'unavailable'].includes(String(d.status)) ||
          typeof d.explanation !== 'string' || !Array.isArray(d.indicators)) throw new Error('Invalid domain.');
      names.add(String(d.domain));
      d.indicators.forEach(value => {
        const i = object(value);
        if (typeof i.feature !== 'string' || !(i.value === null || numeric(i.value)) || !score(i.score) ||
            typeof i.explanation !== 'string') throw new Error('Invalid indicator.');
      });
      const rules = c[`${d.domain}_rules`];
      if (!Array.isArray(rules) || !rules.every(value => {
        const rule = object(value);
        return typeof rule.feature === 'string' && numeric(rule.lower) && numeric(rule.upper) &&
          rule.lower < rule.upper && typeof rule.rationale === 'string' && typeof rule.direction === 'string';
      })) throw new Error('Missing scoring rules.');
    });
    const contributions = object(r.contributions);
    if (!['climate', 'biological', 'operational'].every(d => score(contributions[d]) && numeric(c[`${d}_weight`])) ||
        !numeric(c.medium_starts_at) || !numeric(c.high_starts_at) || typeof r.data_completeness !== 'string')
      throw new Error('Missing scoring metadata.');
    return r as unknown as Assessment;
  }).sort((a, b) => a.assessment_date.localeCompare(b.assessment_date) || a.output_id.localeCompare(b.output_id));
  if (generation === 'v2' && (result.some(r => r.contract_version !== '1.1.0' || r.assessment_date < '2026-01-01' || r.assessment_date > '2026-08-20') ||
      new Set(result.map(r => r.scoring_config.version)).size > 1 || new Set(result.map(r => r.assessment_date)).size !== result.length))
    throw new Error('V2 scoring-version consistency could not be verified.');
  return result;
}
export async function loadPredictions(signal: AbortSignal): Promise<Prediction[]> {
  const rows = await collection('/risks/research/farms/FARM_X/milk-decline-predictions', signal);
  return rows.map(value => {
    const r = object(value); research(r);
    if (!date(r.assessment_date) || !r.assessment_date.startsWith('2022-') || typeof r.prediction_id !== 'string' ||
        !numeric(r.predicted_decline_probability) || r.predicted_decline_probability < 0 || r.predicted_decline_probability > 1 ||
        r.model_status !== 'random_forest_experimental_not_live_validated' ||
        !(r.actual_outcome === null || typeof r.actual_outcome === 'boolean') ||
        !(r.saved_threshold === null || (numeric(r.saved_threshold) && r.saved_threshold >= 0 && r.saved_threshold <= 1)) ||
        !(r.predicted_decline === null || typeof r.predicted_decline === 'boolean') ||
        (r.saved_threshold === null && r.predicted_decline !== null) || r.artifact_version !== '1.0.0' ||
        typeof r.classification_status !== 'string' || typeof r.experiment_partition !== 'string')
      throw new Error('Invalid experimental prediction contract.');
    return r as unknown as Prediction;
  }).sort((a, b) => a.assessment_date.localeCompare(b.assessment_date));
}
export async function loadC1(signal: AbortSignal): Promise<C1Forecast[]> {
  const { data } = await api.get<unknown>('/predictive/pfoi/outlook', {
    params: { grain: 'daily', series: 'herd_milk' }, signal, timeout: 15000,
  });
  const r = object(data);
  if (r.source !== 'model' || r.contract_version !== '1.0' || r.model_version !== 'pfoi-1.2.0-dev' ||
      typeof r.core_version !== 'string' || !r.core_version.trim() || !date(r.origin_date) || !Array.isArray(r.outlook))
    throw new Error('Verified C1 model context unavailable. Demo and other versions are not displayed.');
  const seen = new Set<string>();
  return r.outlook.map(value => {
    const row = object(value);
    if (row.model_version !== r.model_version || row.core_version !== r.core_version || row.origin_date !== r.origin_date ||
        row.grain !== 'daily' || row.series !== 'herd_milk' || row.quality_flag !== 'ok' ||
        !date(row.target_period) || !numeric(row.forecast) || row.forecast < 0 || !numeric(row.horizon) ||
        !Number.isInteger(row.horizon) || row.horizon < 1 || seen.has(row.target_period) ||
        (Date.parse(row.target_period) - Date.parse(String(r.origin_date))) / 86400000 !== row.horizon - 1 ||
        !((row.lower == null && row.upper == null) || (numeric(row.lower) && numeric(row.upper) &&
          row.lower >= 0 && row.lower <= row.forecast && row.forecast <= row.upper)) ||
        !(row.created_at == null || (typeof row.created_at === 'string' &&
          /(?:Z|[+-]\d{2}:\d{2})$/.test(row.created_at) && !Number.isNaN(Date.parse(row.created_at)))))
      throw new Error('C1 dates, horizon, quality or provenance could not be verified.');
    seen.add(row.target_period);
    return row as unknown as C1Forecast;
  }).sort((a, b) => a.target_period.localeCompare(b.target_period));
}
