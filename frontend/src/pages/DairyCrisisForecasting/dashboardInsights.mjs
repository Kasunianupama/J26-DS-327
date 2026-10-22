// Presentation only: never recompute stored scores or mutate API payloads.
const labels = {
  absolute_exceedance: 'Heat Stress (THI)', historical_exceedance: 'Historical THI Anomaly',
  mastitis_episodes: 'Recorded Mastitis Episodes', udder_teat_episodes: 'Recorded Udder/Teat Episodes',
  other_health_episodes: 'Other Recorded Health Episodes', n_sessions: 'Recorded Milking Sessions',
  n_blood_alarms: 'Recorded Blood Alarms', n_conductivity_alarms: 'Recorded Conductivity Alarms',
  blood_alarms_per_session: 'Recorded Blood Alarms per Session',
  conductivity_alarms_per_session: 'Recorded Conductivity Alarms per Session',
};
export const indicatorLabel = feature => labels[feature] ?? 'Recorded Indicator';
const format = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
export function preferredAssessmentVersion(chosen, verifiedV2Count) {
  return chosen ?? (verifiedV2Count > 0 ? 'v2' : 'v1');
}
export function formatChartScore(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : 'Unavailable';
}
export function riskCategoryLabel(category) {
  return ({ low_provisional: 'Low Risk', medium_provisional: 'Medium Risk', high_provisional: 'High Risk' })[category] ?? 'Unavailable';
}
export function indicatorValue(indicator) {
  if (indicator?.value == null) return 'Unavailable';
  const value = format(indicator.value);
  if (indicator.feature.endsWith('_episodes')) return `${value} recorded episodes`;
  if (indicator.feature === 'n_sessions') return `${value} recorded sessions`;
  if (indicator.feature.startsWith('n_') && indicator.feature.endsWith('_alarms')) return `${value} recorded alarms`;
  if (indicator.feature.endsWith('_per_session')) return `${value} alarms per session`;
  if (['absolute_exceedance', 'historical_exceedance'].includes(indicator.feature)) return `${value} THI points above the configured comparison`;
  return value;
}
export function domainInsight(assessment, name) {
  const domain = assessment?.domains.find(d => d.domain === name);
  const indicators = domain?.indicators ?? [];
  const rules = assessment?.scoring_config[`${name}_rules`] ?? [];
  const quality = 'Recording completeness is unverified.';
  if (!domain || domain.score == null || domain.status !== 'available' ||
      indicators.some(i => i.value == null || i.score == null)) {
    return { title: 'Unavailable', value: 'Unavailable', positive: false,
      text: `Some required ${name} indicators are missing or not eligible. No complete domain contribution can be identified. ${quality}` };
  }
  const positive = indicators.filter(i => i.score > 0 && i.value != null)
    .slice().sort((a, b) => b.score - a.score || a.feature.localeCompare(b.feature));
  const strongest = positive[0];
  if (!strongest) {
    const zeroCounts = name === 'biological' && indicators.length > 0 &&
      indicators.every(i => i.feature.endsWith('_episodes') && i.value === 0);
    return { title: 'No positive indicator contribution', value: zeroCounts ? '0 recorded episodes in configured categories' : 'No positive score contribution', positive: false,
      text: zeroCounts ? `No episodes were recorded in the configured health categories on this date. This does not establish absence of disease. ${quality}`
        : `No positive ${name} indicator contribution was recorded under the configured rules. This does not establish absence of risk. ${quality}` };
  }
  const rule = rules.find(r => r.feature === strongest.feature);
  const saturated = strongest.score === 100 && rule &&
    ((rule.direction === 'higher_is_riskier' && strongest.value >= rule.upper) ||
     (rule.direction === 'lower_is_riskier' && strongest.value <= rule.lower));
  const title = indicatorLabel(strongest.feature);
  const value = indicatorValue(strongest);
  let text = `${title}: ${value}; provisional indicator score ${format(strongest.score)}/100.`;
  if (saturated) text += ` This reached the configured scoring limit (${format(rule.direction === 'higher_is_riskier' ? rule.upper : rule.lower)}).`;
  if (name === 'biological') text += ` Recorded episodes are not verified disease incidence. ${quality}`;
  if (name === 'operational') text += ` This does not confirm equipment failure or a crisis. ${quality}`;
  if (name === 'climate') text += ` Recorded conditions contributed to the provisional climate score. ${quality}`;
  return { title, value, text, positive: true };
}
export function domainSummary(assessment, name) {
  const insight = domainInsight(assessment, name);
  if (insight.value === 'Unavailable') return 'Required recorded indicators are missing or not eligible.';
  if (!insight.positive) return insight.value.startsWith('0 recorded')
    ? 'No episodes were recorded in the configured health categories.'
    : 'No positive indicator contribution under the selected scoring rules.';
  const domain = assessment.domains.find(d => d.domain === name);
  const strongest = domain.indicators.filter(i => i.score > 0 && i.value != null)
    .slice().sort((a, b) => b.score - a.score || a.feature.localeCompare(b.feature))[0];
  return `${insight.title}: ${insight.value}${strongest.score === 100 ? ' — at the configured scoring limit.' : '.'}`;
}
export function combinedInsight(assessment) {
  if (!assessment) return 'Select an available assessment to see its recorded contributors.';
  if (assessment.combined_score == null) return 'The farm score is unavailable because required domain inputs are not eligible.';
  const positive = assessment.domains.filter(d => d.score != null && d.score > 0 &&
    Number.isFinite(assessment.contributions[d.domain]) && assessment.contributions[d.domain] > 0)
    .slice().sort((a, b) => assessment.contributions[b.domain] - assessment.contributions[a.domain] || a.domain.localeCompare(b.domain));
  if (!positive.length) return 'No positive recorded indicator contribution under the selected scoring rules.';
  return positive.map(d => domainSummary(assessment, d.domain))
    .join(' ');
}
export function historyForAssessment(rows, selected, range = '30') {
  if (!selected) return { rows: [], duplicateDates: 0 };
  if (!['7', '30', '90', 'all'].includes(range)) throw new Error('Unsupported history window');
  const end = Date.parse(selected.assessment_date);
  const eligible = rows.filter(r => r.scoring_config.version === selected.scoring_config.version &&
    Date.parse(r.assessment_date) <= end && (range === 'all' || end - Date.parse(r.assessment_date) < Number(range) * 86400000));
  const counts = new Map();
  eligible.forEach(r => counts.set(r.assessment_date, (counts.get(r.assessment_date) ?? 0) + 1));
  return { rows: eligible.filter(r => counts.get(r.assessment_date) === 1)
    .slice().sort((a, b) => a.assessment_date.localeCompare(b.assessment_date)),
    duplicateDates: [...counts.values()].filter(count => count > 1).length };
}
export function dailyChartRows(rows) {
  if (!rows.length) return [];
  const sorted = rows.slice().sort((a, b) => a.assessment_date.localeCompare(b.assessment_date));
  const byDate = new Map(sorted.map(r => [r.assessment_date, r]));
  const data = [];
  for (let time = Date.parse(sorted[0].assessment_date); time <= Date.parse(sorted[sorted.length - 1].assessment_date); time += 86400000) {
    const date = new Date(time).toISOString().slice(0, 10), row = byDate.get(date);
    data.push({ date, Combined: row?.combined_score ?? null,
      Climate: row?.domains.find(d => d.domain === 'climate')?.score ?? null,
      Biological: row?.domains.find(d => d.domain === 'biological')?.score ?? null,
      Operational: row?.domains.find(d => d.domain === 'operational')?.score ?? null });
  }
  return data;
}
