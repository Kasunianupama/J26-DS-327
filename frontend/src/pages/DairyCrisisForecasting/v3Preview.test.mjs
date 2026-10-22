// Fictional JSON payloads only; no network, database or private configuration.
import test from 'node:test';
import assert from 'node:assert/strict';
import { previewV3, compareV3 } from './v3Preview.mjs';
import { combinedInsight, dailyChartRows, historyForAssessment, formatChartScore } from './dashboardInsights.mjs';

function fixture(blood = 100, conductivity = 20) {
  const rule = feature => ({ feature, lower: 0, upper: 10, direction: 'higher_is_riskier', rationale: 'Synthetic rule.' });
  const indicator = (feature, value) => ({ feature, value: value === null ? null : value / 10, score: value, explanation: 'Synthetic input.' });
  return { output_id: 'fictional-v2-id', assessment_date: '2026-01-01', contract_version: '1.1.0',
    research_only: true, live_warning_allowed: false, recording_quality: 'unknown',
    provenance: { source: 'published', availability: 'unknown', core_version: null },
    domains: [
      { domain: 'climate', status: 'available', score: 50, indicators: [] },
      { domain: 'biological', status: 'available', score: 0, indicators: [] },
      { domain: 'operational', status: blood === null || conductivity === null ? 'partial' : 'available',
        configured_indicators: 2, available_indicators: Number(blood !== null) + Number(conductivity !== null),
        score: blood === null || conductivity === null ? null : Math.max(blood, conductivity),
        indicators: [indicator('n_blood_alarms', blood), indicator('n_conductivity_alarms', conductivity)] },
    ], scoring_config: { version: 'fictional-calibrated-v2', operational_rules: [rule('n_blood_alarms'), rule('n_conductivity_alarms')],
      climate_weight: .4, biological_weight: .3, operational_weight: .3, medium_starts_at: 30, high_starts_at: 70 },
    combined_score: 50, risk_category: 'medium_provisional', contributions: { climate: 20, biological: 0, operational: 30 },
  };
}
const operational = view => view.domains.find(d => d.domain === 'operational').score;

test('V3 uses exactly Climate and Operational with equal weights', () => {
  const view = previewV3(fixture());
  assert.equal(operational(view), 60); assert.equal(view.combined_score, 55);
  assert.deepEqual(view.contributions, { climate: 25, operational: 30 });
  assert.deepEqual(view.domains.map(d => d.domain), ['climate', 'operational']);
  assert.equal(view.available_domains, 2);
  assert.equal(view.preview.model, 'Climate and Operational Risk Model');
  assert.equal(view.risk_category, 'medium_provisional');
  assert.equal(view.preview.label, 'Experimental Preview — Not Published');
});

test('unrounded synthetic values near the supplied example yield 72.6, never three-factor 48.4', () => {
  const row = fixture();
  row.assessment_date = '2026-08-20';
  row.domains[0].score = 82.34567;
  row.domains[2].indicators[1] = { feature: 'n_conductivity_alarms', value: 1, score: 25.678 };
  row.scoring_config.operational_rules[1].upper = 100 / 25.678;
  const view = previewV3(row);
  assert.equal(operational(view), 62.839);
  assert.ok(Math.abs(view.combined_score - 72.592335) < 1e-10);
  assert.equal(formatChartScore(view.combined_score), '72.6');
  assert.equal(view.risk_category, 'high_provisional');
});

test('missing Biological inputs and changed V2 weights never affect V3', () => {
  const row = fixture();
  row.domains[1].score = null; row.domains[1].status = 'unavailable';
  row.scoring_config.climate_weight = .1; row.scoring_config.biological_weight = .1;
  row.scoring_config.operational_weight = .8;
  const view = previewV3(row);
  assert.equal(view.combined_score, 55);
  assert.equal(Object.hasOwn(view.contributions, 'biological'), false);
  assert.equal(Object.hasOwn(view.preview, 'biological_interpretation'), false);
});

test('zero and 100 boundaries preserve valid zero rather than missing', () => {
  assert.equal(operational(previewV3(fixture(0, 0))), 0);
  assert.equal(operational(previewV3(fixture(100, 100))), 100);
  assert.equal(operational(previewV3(fixture(0, 100))), 50);
  const row = fixture(0, 0); row.domains[0].score = 0;
  assert.equal(previewV3(row).combined_score, 0);
});

test('missing either required domain withholds combined without zero filling', () => {
  for (const row of [fixture(null, 20), fixture(100, null)]) {
    const result = previewV3(row);
    assert.equal(operational(result), null); assert.equal(result.combined_score, null);
    assert.equal(result.risk_category, 'unavailable');
  }
  const row = fixture(); row.domains[0].score = null; row.domains[0].status = 'unavailable';
  const view = previewV3(row);
  assert.equal(operational(view), 60); assert.equal(view.combined_score, null);
  assert.equal(view.contributions.climate, null);
});

test('ineligible source indicators, rules and flags remain withheld', () => {
  for (const change of [
    x => x.domains[2].indicators.push({ ...x.domains[2].indicators[0] }),
    x => { x.domains[2].indicators[0].score = 99; },
    x => { x.domains[2].indicators[0].value = 1.5; },
    x => { x.live_warning_allowed = true; },
    x => { x.domains[2].score = 20; },
    x => { x.domains[2].status = 'partial'; },
    x => { x.scoring_config.operational_rules.pop(); },
  ]) { const row = fixture(); change(row); assert.equal(operational(previewV3(row)), null); }
});

test('stored source payload, nested rules, V2 score and provenance are untouched', () => {
  const row = fixture(); const before = JSON.stringify(row); const view = previewV3(row);
  view.domains[0].score = 99; view.scoring_config.operational_rules[0].upper = 999;
  assert.equal(JSON.stringify(row), before);
  assert.equal(row.domains[1].domain, 'biological');
  assert.equal(row.combined_score, 50);
  assert.equal(view.preview.source_output_id, row.output_id);
  assert.equal(view.recording_quality, 'unknown'); assert.equal(view.live_warning_allowed, false);
});

test('categories use the new combined value and inclusive existing boundaries', () => {
  const row = fixture(100, 100);
  row.scoring_config.high_starts_at = 75;
  assert.equal(previewV3(row).combined_score, 75);
  assert.equal(previewV3(row).risk_category, 'high_provisional');
  row.scoring_config.high_starts_at = 90; row.scoring_config.medium_starts_at = 75;
  assert.equal(previewV3(row).risk_category, 'medium_provisional');
});

test('history/date selection uses preview values, original gaps and no V2 fallback', () => {
  const a = fixture(), b = fixture(null, 20);
  a.assessment_date = '2026-01-01'; b.assessment_date = '2026-01-03';
  const views = [a, b].map(previewV3);
  const history = historyForAssessment(views, views[1], '7');
  assert.deepEqual(dailyChartRows(history.rows).map(r => r.Combined), [55, null, null]);
  assert.doesNotMatch(combinedInsight(views[0]), /Biological|Mastitis/);
  const earlier = historyForAssessment(views, views[0], '7');
  assert.equal(earlier.rows.length, 1); assert.equal(earlier.rows[0].combined_score, 55);
});

test('paired operational MAX/average comparison remains unchanged', () => {
  const a = fixture(), b = fixture(100, 100), missing = fixture(null, 20);
  b.assessment_date = '2026-01-02'; missing.assessment_date = '2026-01-03';
  const result = compareV3([a, b, missing]);
  assert.equal(result.eligibleDays, 2); assert.equal(result.unavailableDays, 1);
  assert.equal(result.v2.at100, 2); assert.equal(result.v3.at100, 1);
  assert.equal(result.v2.mean, 100); assert.equal(result.v3.mean, 80);
  assert.equal(compareV3([a, a]).eligibleDays, 0);
});

test('chart tooltip formatting is exactly one decimal without changing calculation', () => {
  assert.equal(formatChartScore(54.34197907412344), '54.3');
  assert.equal(formatChartScore(0), '0.0');
  assert.equal(formatChartScore(null), 'Unavailable');
});
