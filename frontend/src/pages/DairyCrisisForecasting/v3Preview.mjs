// Browser-only VIEW MODEL. Never submit to the published MAX-based contract/API.
const REQUIRED = ['n_blood_alarms', 'n_conductivity_alarms'];
const numeric = value => typeof value === 'number' && Number.isFinite(value);
const score = value => numeric(value) && value >= 0 && value <= 100;

export function previewV3(stored) {
  // Clone the entire JSON payload so cards/charts cannot mutate fetched V2 records.
  const view = JSON.parse(JSON.stringify(stored));
  const original = stored.domains.find(d => d.domain === 'operational');
  const rules = stored.scoring_config.operational_rules;
  let reason = null;
  const expected = [];
  if (stored.contract_version !== '1.1.0' || stored.provenance?.source !== 'published' ||
      stored.research_only !== true || stored.live_warning_allowed !== false ||
      stored.assessment_date < '2026-01-01' || stored.assessment_date > '2026-08-20')
    reason = 'The source record is not an eligible published V2 research assessment.';
  if (!original || original.status !== 'available' || !score(original.score) ||
      original.indicators.length !== 2 || rules.length !== 2 ||
      original.configured_indicators !== 2 || original.available_indicators !== 2 ||
      original.indicators.some((indicator, index) => indicator.feature !== rules[index]?.feature))
    reason = 'Exactly two eligible raw alarm indicators and matching V2 rules are required; additional or missing rules are not silently ignored.';
  for (const feature of REQUIRED) {
    const indicators = original?.indicators.filter(i => i.feature === feature) ?? [];
    const matches = rules.filter(r => r.feature === feature);
    if (indicators.length !== 1 || matches.length !== 1) { reason = 'Both blood and conductivity alarm indicators must be uniquely present.'; continue; }
    const indicator = indicators[0], rule = matches[0];
    if (!numeric(indicator.value) || !Number.isInteger(indicator.value) || indicator.value < 0 || !score(indicator.score) ||
        !numeric(rule.lower) || !numeric(rule.upper) || rule.lower >= rule.upper ||
        !['higher_is_riskier', 'lower_is_riskier'].includes(rule.direction)) {
      reason = 'One or both required alarm values, scores or rules are unavailable or ineligible.'; continue;
    }
    const position = Math.min(1, Math.max(0, (indicator.value - rule.lower) / (rule.upper - rule.lower)));
    const reference = 100 * (rule.direction === 'higher_is_riskier' ? position : 1 - position);
    if (Math.abs(reference - indicator.score) > 1e-8) reason = 'Stored indicator scores do not match their calibrated V2 rules.';
    expected.push(indicator.score);
  }
  if (!reason && Math.abs(original.score - Math.max(...expected)) > 1e-8)
    reason = 'Stored V2 operational score does not match its MAX-based contract.';
  const operational = reason ? null : (expected[0] + expected[1]) / 2;
  const availableIndicators = original?.indicators.filter(i => i.value != null && score(i.score)).length ?? 0;
  view.domains = view.domains.filter(d => ['climate', 'operational'].includes(d.domain)).map(d => d.domain !== 'operational' ? d : {
    ...d, score: operational, status: operational === null ? 'unavailable' : 'available',
    explanation: operational === null ? reason : 'Experimental Preview — Not Published. Arithmetic mean of the two stored V2 alarm indicator scores; calibrated indicator rules unchanged.',
  });
  const cfg = stored.scoring_config;
  const names = ['climate', 'operational'];
  const validBands = numeric(cfg.medium_starts_at) && numeric(cfg.high_starts_at) &&
    0 < cfg.medium_starts_at && cfg.medium_starts_at < cfg.high_starts_at && cfg.high_starts_at < 100;
  view.contributions = Object.fromEntries(names.map(name => {
    const domain = view.domains.find(d => d.domain === name);
    return [name, domain?.status === 'available' && score(domain.score) ? domain.score / 2 : null];
  }));
  const complete = validBands && names.every(name => view.contributions[name] !== null);
  view.combined_score = complete ? names.reduce((sum, name) => sum + view.contributions[name], 0) : null;
  view.risk_category = !complete ? 'unavailable' : view.combined_score >= cfg.high_starts_at ? 'high_provisional'
    : view.combined_score >= cfg.medium_starts_at ? 'medium_provisional' : 'low_provisional';
  view.available_domains = view.domains.filter(d => d.status === 'available' && score(d.score)).length;
  view.data_completeness = complete ? 'complete' : view.domains.some(d => score(d.score)) || availableIndicators > 0 ? 'partial' : 'unavailable';
  view.preview = { kind: 'v3_average', label: 'Experimental Preview — Not Published',
    source_output_id: stored.output_id, source_scoring_version: cfg.version,
    model: 'Climate and Operational Risk Model',
    domain_weights: { climate: 0.5, operational: 0.5 },
    reason: reason ?? (!validBands ? 'Combined category boundaries are ineligible.' : null),
    stored_operational_score: original?.score ?? null, stored_combined_score: stored.combined_score };
  // Source ID/version retained strictly for selection/provenance. This is not a
  // new published payload, scoring configuration, UUID or scientific model.
  view.explanations = ['Experimental Preview — Not Published. Climate and Operational Risk Model: Operational Risk averages the two alarm indicator scores; Combined Risk is (Climate + Operational) / 2.'];
  return view;
}

export function compareV3(rows) {
  const countByDate = new Map();
  rows.forEach(row => countByDate.set(row.assessment_date, (countByDate.get(row.assessment_date) ?? 0) + 1));
  const unique = rows.filter(row => countByDate.get(row.assessment_date) === 1);
  const pairs = unique.map(row => [row.domains.find(d => d.domain === 'operational')?.score, previewV3(row).domains.find(d => d.domain === 'operational')?.score])
    .filter(([v2, v3]) => score(v2) && score(v3));
  const summary = index => ({ days: pairs.length, at100: pairs.filter(pair => pair[index] === 100).length,
    mean: pairs.length ? pairs.reduce((sum, pair) => sum + pair[index], 0) / pairs.length : null });
  return { totalDays: unique.length, eligibleDays: pairs.length, unavailableDays: unique.length - pairs.length,
    duplicateDates: [...countByDate.values()].filter(count => count > 1).length, v2: summary(0), v3: summary(1) };
}
