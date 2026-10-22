/** Present supplied evidence as readable dates, measurements and provenance. */
import type { ReactNode } from 'react';
import { t, LOCALES, type Language } from './i18n';

const labels: Record<string, string> = {
  animal_ref:'Approved cow reference', prediction_horizon_days:'Prediction horizon (days)',
  observed_milk_yield_l_day:'Observed milk yield', baseline_predicted_milk_yield_l_day:'Predicted baseline yield',
  counterfactual_predicted_milk_yield_l_day:'Predicted what-if yield', absolute_yield_change_l_day:'Predicted yield difference',
  percentage_yield_change:'Predicted change (%)', scenario_status:'Scenario status', model_support_status:'Training support',
  original_inputs:'Recorded feature inputs', proposed_inputs:'Your proposed inputs', thi_mean:'THI exposure',
  milkings_per_day:'Milkings per day', operational_feasibility_validated:'Operational feasibility validated', assumptions:'Assumptions',
  observed_date: 'Records through', reference_date: 'Selected as of',
  origin_date: 'Forecast origin', target_period: 'Forecast target',
  assessment_date: 'Assessment date', assessment_cutoff: 'Assessment cutoff',
  generated_at: 'Generated at', core_version: 'Core publication',
  source_core_version: 'Source core publication', model_version: 'Model version',
  contract_version: 'Output contract', scoring_version: 'Scoring method',
  score_basis: 'Assessment basis', model_status: 'Model status',
  source: 'Data source', herd: 'Herd snapshot', total_animals: 'Total animals',
  milking: 'Milking animals', dry: 'Dry animals',
  pregnant_nonmilking: 'Pregnant, not milking', unknown_state: 'Unknown herd state',
  weather: 'Weather observations', mean_daily_thi: 'Mean daily THI',
  max_hourly_thi: 'Maximum hourly THI', complete_days: 'Complete weather days',
  observed_days: 'Recorded days', latest_period: 'Latest recorded period',
  previous_period: 'Previous recorded period', period: 'Observation period',
  start: 'From', end: 'To', milk: 'Milk records', delpro: 'DelPro records',
  shipments: 'Shipment records', current_litres: 'Latest period milk',
  previous_litres: 'Previous period milk', current_observed_days: 'Latest period coverage',
  previous_observed_days: 'Previous period coverage', change_pct: 'Weekly change',
  forecast: 'Point forecast', lower: 'Lower bound', upper: 'Upper bound',
  quality_flags: 'Producer quality flags', grain: 'Forecast period', series: 'Forecast measure',
  combined_score: 'Combined research score', climate_score: 'Climate score',
  biological_score: 'Biological score', operational_score: 'Operational score',
  assessment_count: 'Assessments used', research_only: 'Research only',
  live_warning_allowed: 'Live warnings permitted',
};
const dates = new Set(['observed_date', 'origin_date', 'target_period',
  'assessment_date', 'assessment_cutoff', 'generated_at']);
const hidden = new Set(['warnings', 'demo', 'kind', 'milk_report']);
const humanize = (key: string, language: Language) => t(language, labels[key] ?? key.replace(/_/g, ' ').replace(/^./, s => s.toUpperCase()));
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

function formatDate(value: string, language: Language): string {
  const parsed = new Date(value.length === 10 ? value + 'T00:00:00Z' : value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(LOCALES[language], {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: value.length === 10 ? 'UTC' : 'Asia/Colombo',
    ...(value.length > 10 ? { hour: '2-digit', minute: '2-digit' } as const : {}),
  }).format(parsed) + (value.length > 10 ? ' · '+t(language,'Sri Lanka time') : '');
}

function display(key: string, value: unknown, language: Language): ReactNode {
  if (value === null || value === undefined) return <span className="c3-proof-missing">{t(language,'Not supplied')}</span>;
  if (typeof value === 'boolean') return <span className="c3-proof-tag">{t(language,value ? 'Yes' : 'No')}</span>;
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}(?:$|T)/.test(value)) return <time dateTime={value}>{formatDate(value,language)}</time>;
  const numeric = typeof value === 'number' || (typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value));
  if (numeric && Number.isFinite(Number(value))) {
    const formatted = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 }).format(Number(value));
    const unit = key.endsWith('_l_day') ? ' L/cow/day' : key.endsWith('_litres') ? ' L' : key.endsWith('_pct') ? '%' :
      ['current_observed_days', 'previous_observed_days'].includes(key) ? t(language,' of 7 days') : '';
    return <span title={String(value)}>{formatted}<small className="c3-proof-unit">{unit}</small></span>;
  }
  const sources: Record<string, string> = {
    published_core_aggregates: 'Published farm records', c2_api:'Local C2 simulation API',
    PASSED:'Within checked training support', OUTSIDE_TRAINING_SUPPORT:'Outside training support',
    RANGE_UNAVAILABLE:'Training range unavailable', NOT_ASSESSED:'Not assessed',
    ESTIMATED_MODEL_INPUT_PERTURBATION:'Model-input what-if estimated',
    PREDICTION_UNAVAILABLE:'Prediction unavailable', BASELINE_FEATURE_UNAVAILABLE:'Baseline feature unavailable',
    UNSUPPORTED_INTERVENTION_SEMANTICS:'Unsupported scenario meaning',
    'c4_output.farm_risk_assessment_v1': 'Stored C4 research assessments',
    daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly', herd_milk: 'Herd milk',
    n_herd: 'Total herd', milking: 'Milking animals', calvings: 'Calvings',
    dry_offs: 'Dry-offs', real_abortions: 'Recorded abortions',
  };
  return sources[String(value)] ? t(language,sources[String(value)]) : (['score_basis', 'model_status', 'scoring_version'].includes(key)
    ? String(value).replace(/_/g, ' ') : String(value));
}

function Fields({ data, level = 0, language }: { data: Record<string, unknown>; level?: number; language: Language }) {
  const entries = Object.entries(data).filter(([key]) => !hidden.has(key));
  const simple = entries.filter(([, value]) => !isObject(value) && !Array.isArray(value));
  const groups = entries.filter(([, value]) => isObject(value) || Array.isArray(value));
  return <>
    {!!simple.length && <dl className="c3-proof-grid">{simple.map(([key, value]) =>
      <div className="c3-proof-field" key={key}><dt>{humanize(key,language)}</dt><dd>{display(key, value,language)}</dd></div>)}</dl>}
    {groups.map(([key, value]) => <section className={`c3-proof-group c3-proof-depth-${level}`} key={key} aria-label={humanize(key,language)}>
      <h4>{humanize(key,language)}</h4>
      {isObject(value) ? <Fields data={value} level={level + 1} language={language} /> : <div className="c3-proof-tags">
        {(value as unknown[]).length ? (value as unknown[]).map((item, index) => isObject(item)
          ? <Fields key={index} data={item} level={level + 1} language={language} />
          : <span className="c3-proof-tag" key={index}>{display(key, item,language)}</span>)
          : <span className="c3-proof-missing">{t(language,'None supplied')}</span>}
      </div>}
    </section>)}
  </>;
}

export function EvidencePanel({ evidence, language = 'en' }: { evidence: Record<string, unknown>; language?: Language }) {
  const entries = Object.entries(evidence).filter(([key]) => !hidden.has(key));
  const dateEntries = entries.filter(([key]) => dates.has(key));
  const metadata = new Set(['source', 'core_version', 'source_core_version', 'model_version',
    'contract_version', 'scoring_version', 'score_basis', 'model_status',
    'reference_date', 'research_only', 'live_warning_allowed', 'quality_flags']);
  const measurements = Object.fromEntries(entries.filter(([key]) => !dates.has(key) && !metadata.has(key)));
  const provenance = Object.fromEntries(entries.filter(([key]) => metadata.has(key)));
  return <details className="c3-evidence c3-proof"><summary><span className="c3-proof-summary-icon" aria-hidden="true">◇</span><span>{t(language,"View evidence & dates")}<small>{t(language,"Supporting records, dates and source details")}</small></span><span className="c3-proof-chevron" aria-hidden="true">⌄</span></summary>
    <div className="c3-proof-content">
      {!!dateEntries.length && <section className="c3-proof-dates" aria-label="Evidence dates">{dateEntries.map(([key, value]) =>
        <div key={key}><span className="c3-proof-calendar" aria-hidden="true">◷</span><div><span>{humanize(key,language)}</span><strong>{display(key, value,language)}</strong></div></div>)}</section>}
      <Fields data={measurements} language={language} />
      {!!Object.keys(provenance).length && <details className="c3-proof-provenance"><summary>{t(language,"Technical source details")}</summary><Fields data={provenance} language={language} /></details>}
      <p className="c3-proof-footnote">{t(language,"Values come from the supplied evidence. Decimals are rounded to two places; missing values remain unfilled.")}</p>
    </div>
  </details>;
}
