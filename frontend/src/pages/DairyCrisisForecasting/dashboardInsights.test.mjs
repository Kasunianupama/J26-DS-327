// Fictional assessment fragments only; Node's built-in runner, no API or DB.
import test from 'node:test';
import assert from 'node:assert/strict';
import { riskCategoryLabel, preferredAssessmentVersion, combinedInsight, domainSummary, domainInsight, indicatorValue, historyForAssessment, dailyChartRows } from './dashboardInsights.mjs';

test('risk labels are presentation-only and do not expose provisional category suffixes', () => {
  const stored = ['low_provisional', 'medium_provisional', 'high_provisional'];
  const before = JSON.stringify(stored);
  assert.deepEqual(stored.map(riskCategoryLabel), ['Low Risk', 'Medium Risk', 'High Risk']);
  assert.equal(JSON.stringify(stored), before);
  assert.equal(riskCategoryLabel('unavailable'), 'Unavailable');
  assert.equal(riskCategoryLabel(undefined), 'Unavailable');
});

test('V2 defaults only after verified data; explicit V1 selection remains stable', () => {
  assert.equal(preferredAssessmentVersion(null, 0), 'v1');
  assert.equal(preferredAssessmentVersion(null, 232), 'v2');
  assert.equal(preferredAssessmentVersion('v1', 232), 'v1');
  assert.equal(preferredAssessmentVersion('v2', 0), 'v2');
});

function fixture(name = 'biological', value = 0, score = 0) {
  const feature = name === 'biological' ? 'mastitis_episodes' : name === 'operational' ? 'n_blood_alarms' : 'absolute_exceedance';
  return { assessment_date: '2025-09-10', combined_score: 50,
    recording_quality: 'unknown', scoring_config: { version: 'fictional-v1',
      [`${name}_rules`]: [{ feature, lower: 0, upper: 12, direction: 'higher_is_riskier' }] },
    domains: [{ domain: name, status: value === null ? 'partial' : 'available', score,
      indicators: [{ feature, value, score }] }] };
}
test('recorded zero health counts are not absence of disease or positive drivers', () => {
  const r = domainInsight(fixture(), 'biological');
  assert.equal(r.positive, false);
  assert.match(r.text, /does not establish absence of disease/);
  assert.match(r.text, /completeness is unverified/);
  assert.match(r.value, /0 recorded episodes/);
});
test('missing or partial values do not become zero', () => {
  const r = domainInsight(fixture('biological', null, null), 'biological');
  assert.equal(r.value, 'Unavailable'); assert.equal(r.positive, false);
  assert.equal(indicatorValue({ feature: 'mastitis_episodes', value: null }), 'Unavailable');
  assert.equal(domainInsight(undefined, 'climate').positive, false);
});
test('alarm saturation uses stored upper bound and does not diagnose failure', () => {
  const r = domainInsight(fixture('operational', 20, 100), 'operational');
  assert.match(r.text, /scoring limit \(12\)/);
  assert.match(r.text, /does not confirm equipment failure/);
  assert.equal(r.value, '20 recorded alarms');
});
test('strongest positive contributor selected without mutating source', () => {
  const row = fixture('operational', 0, 0);
  row.domains[0].indicators.push({ feature: 'n_conductivity_alarms', value: 6, score: 50 });
  const before = JSON.stringify(row);
  const r = domainInsight(row, 'operational');
  assert.equal(r.title, 'Recorded Conductivity Alarms');
  assert.equal(r.positive, true); assert.equal(JSON.stringify(row), before);
  assert.doesNotMatch(r.text, /clipped|higher_is_riskier/);
});
test('boundaries follow stored score, not an invented recalculation', () => {
  assert.equal(domainInsight(fixture('operational', 0, 0), 'operational').positive, false);
  assert.doesNotMatch(domainInsight(fixture('operational', 11, 99), 'operational').text, /scoring limit/);
  assert.match(domainInsight(fixture('operational', 12, 100), 'operational').text, /scoring limit/);
});
test('nonzero health values scoring zero are not called no recorded episodes', () => {
  const r = domainInsight(fixture('biological', 1, 0), 'biological');
  assert.equal(r.positive, false); assert.doesNotMatch(r.text, /No episodes were recorded/);
});
test('seven-day window includes origin and previous six only, excludes future/version', () => {
  const selected = fixture();
  const rows = ['2025-09-03', '2025-09-04', '2025-09-10', '2025-09-11'].map(assessment_date => ({ ...selected, assessment_date }));
  rows.push({ ...selected, assessment_date: '2025-09-09', scoring_config: { version: 'other' } });
  assert.deepEqual(historyForAssessment(rows, selected, '7').rows.map(r => r.assessment_date), ['2025-09-04', '2025-09-10']);
});
test('default thirty-day window and duplicate dates are withheld', () => {
  const selected = fixture();
  const rows = ['2025-08-11', '2025-08-12', '2025-09-09', '2025-09-09', '2025-09-10'].map(assessment_date => ({ ...selected, assessment_date }));
  const result = historyForAssessment(rows, selected);
  assert.equal(result.duplicateDates, 1);
  assert.deepEqual(result.rows.map(r => r.assessment_date), ['2025-08-12', '2025-09-10']);
  assert.equal(historyForAssessment([], undefined).rows.length, 0);
});
test('daily chart retains missing dates, null scores and original boundary values', () => {
  const selected = fixture();
  const rows = [{ ...selected, assessment_date: '2025-09-01', combined_score: 0 },
    { ...selected, assessment_date: '2025-09-03', combined_score: null },
    { ...selected, assessment_date: '2025-09-04', combined_score: 100 }];
  assert.deepEqual(dailyChartRows(rows).map(r => r.Combined), [0, null, null, 100]);
});
test('compact summaries retain recorded values without repeating technical disclaimers', () => {
  assert.match(domainSummary(fixture('operational', 20, 100), 'operational'), /20 recorded alarms.*scoring limit/);
  assert.equal(domainSummary(fixture(), 'biological'), 'No episodes were recorded in the configured health categories.');
  assert.doesNotMatch(domainSummary(fixture('climate', 2, 20), 'climate'), /research.only|live.warning|clipped/);
});
test('combined summary uses stored weighted contributions and excludes zero domains', () => {
  const row = fixture('operational', 20, 100);
  row.contributions = { operational: 30, biological: 0, climate: null };
  row.domains.push(fixture().domains[0]);
  const before = JSON.stringify(row);
  assert.match(combinedInsight(row), /Recorded Blood Alarms.*20 recorded alarms/);
  assert.doesNotMatch(combinedInsight(row), /weighted points|30 weighted/);
  assert.doesNotMatch(combinedInsight(row), /Mastitis/);
  assert.equal(JSON.stringify(row), before);
  row.combined_score = null;
  assert.match(combinedInsight(row), /unavailable/);
  assert.match(combinedInsight(undefined), /Select an available/);
});
