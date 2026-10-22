// Published V3 validation only. No preview calculation or V1/V2 fallback here.
const numeric = v => typeof v === 'number' && Number.isFinite(v);
const score = v => v === null || (numeric(v) && v >= 0 && v <= 100);
export function validatePublishedV3Rows(rows) {
  const dates = new Set(), ids = new Set(), sources = new Set();
  for (const row of rows) {
    const cfg = row.scoring_config;
    if (row.contract_version !== '3.0.0' || row.farm_id !== 'FARM_X' || row.research_only !== true || row.live_warning_allowed !== false ||
        row.model_status !== 'provisional_two_domain_not_live_validated' || row.provenance?.source !== 'published' ||
        typeof row.output_id !== 'string' || ids.has(row.output_id) || typeof row.assessment_date !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}$/.test(row.assessment_date) || row.assessment_date < '2026-01-01' || row.assessment_date > '2026-08-20' || dates.has(row.assessment_date) ||
        cfg?.version !== 'c4-v3-climate-operational-1' || typeof cfg.source_scoring_version !== 'string' ||
        cfg.climate_weight !== .5 || cfg.operational_weight !== .5 || !numeric(cfg.medium_starts_at) || !numeric(cfg.high_starts_at) ||
        !(0 < cfg.medium_starts_at && cfg.medium_starts_at < cfg.high_starts_at && cfg.high_starts_at < 100) ||
        row.source_object !== 'c4_output.farm_risk_assessment_v2' || typeof row.source_output_id !== 'string' || !/^[a-f0-9]{64}$/.test(row.source_payload_sha256) ||
        !Array.isArray(row.domains) || row.domains.length !== 2 || row.domains[0].domain !== 'climate' || row.domains[1].domain !== 'operational' ||
        !row.contributions || Object.keys(row.contributions).sort().join(',') !== 'climate,operational' ||
        !Array.isArray(row.explanations) || !row.explanations.every(v => typeof v === 'string')) throw new Error('Published V3 contract unavailable or inconsistent.');
    for (const domain of row.domains) {
      const rules = cfg[`${domain.domain}_rules`];
      if (!Array.isArray(rules) || !rules.length || !Array.isArray(domain.indicators) || domain.indicators.length !== rules.length ||
          typeof domain.explanation !== 'string' || !score(domain.score)) throw new Error('Invalid V3 domain evidence.');
      if (domain.domain === 'operational' && (rules.length !== 2 || rules.map(r => r.feature).sort().join(',') !== 'n_blood_alarms,n_conductivity_alarms'))
        throw new Error('Invalid V3 alarm rules.');
      domain.indicators.forEach((i, index) => {
        const rule = rules[index];
        if (typeof i.feature !== 'string' || i.feature !== rule.feature || !numeric(rule.lower) || !numeric(rule.upper) || rule.lower >= rule.upper ||
            !['higher_is_riskier','lower_is_riskier'].includes(rule.direction) || typeof rule.rationale !== 'string' ||
            typeof i.explanation !== 'string' || !score(i.score) || !(i.value === null || numeric(i.value))) throw new Error('Invalid V3 indicator.');
        if (i.value === null) { if (i.score !== null) throw new Error('Missing V3 value cannot score zero.'); }
        else {
          if (domain.domain === 'operational' && (!Number.isInteger(i.value) || i.value < 0)) throw new Error('Invalid alarm count.');
          const position = Math.min(1, Math.max(0, (i.value-rule.lower)/(rule.upper-rule.lower)));
          if (i.score === null || Math.abs(i.score - 100*(rule.direction === 'higher_is_riskier' ? position : 1-position)) > 1e-8)
            throw new Error('V3 indicator-rule mismatch.');
        }
      });
      const values = domain.indicators.filter(i => i.score !== null).map(i => i.score);
      const complete = values.length === rules.length;
      const expected = !complete ? null : domain.domain === 'climate' ? Math.max(...values) : (values[0]+values[1])/2;
      if (domain.configured_indicators !== rules.length || domain.available_indicators !== values.length ||
          domain.score !== expected || domain.status !== (complete ? 'available' : values.length ? 'partial' : 'unavailable') ||
          row.contributions[domain.domain] !== (expected === null ? null : expected/2)) throw new Error('V3 component calculation mismatch.');
    }
    const combined = row.domains.every(d => d.score !== null) ? (row.domains[0].score+row.domains[1].score)/2 : null;
    const category = combined === null ? 'unavailable' : combined >= cfg.high_starts_at ? 'high_provisional' : combined >= cfg.medium_starts_at ? 'medium_provisional' : 'low_provisional';
    const available = row.domains.filter(d => d.score !== null).length;
    const completeness = available === 2 ? 'complete' : row.domains.some(d => d.available_indicators > 0) ? 'partial' : 'unavailable';
    if (row.combined_score !== combined || row.risk_category !== category || row.available_domains !== available || row.data_completeness !== completeness)
      throw new Error('V3 combined calculation mismatch.');
    ids.add(row.output_id); dates.add(row.assessment_date); sources.add(cfg.source_scoring_version);
  }
  if (sources.size > 1) throw new Error('Mixed V3 source versions.');
  return rows.slice().sort((a,b) => a.assessment_date.localeCompare(b.assessment_date));
}
