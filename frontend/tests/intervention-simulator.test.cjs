const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const test = require('node:test');

const page = readFileSync(
  path.join(__dirname, '../src/pages/InterventionSimulator/index.tsx'),
  'utf8',
);

test('What-If scenario selector contains only THI and milking frequency', () => {
  const selector = page.match(/<label>Input category<select[\s\S]*?<\/select>/);
  assert.ok(selector, 'scenario category selector is present');
  const options = [...selector[0].matchAll(/<option value="([^"]+)">/g)].map((match) => match[1]);
  assert.deepEqual(options, ['heat', 'management']);
  assert.match(page, /Available scenarios: hypothetical THI exposure changes and milking frequency changes\./);
  assert.match(page, /Evaluate combined THI and milking-frequency alternative/);
  assert.match(page, /combined_scenario: combinedEnabled \?/);
});

test('ranking presentation formats positive, negative, and effectively zero changes', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  assert.deepEqual(presentation.formatChange(0.4, 7.94), { kind: 'positive', text: '+0.400 L/day (+7.9%)' });
  assert.deepEqual(presentation.formatChange(-0.3, -5.84), { kind: 'negative', text: '−0.300 L/day (−5.8%)' });
  assert.deepEqual(presentation.formatChange(0.0004, 0.02), { kind: 'zero', text: 'No predicted change' });
});

test('ranking presentation handles unavailable predictions and unavailable percentages', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  assert.equal(presentation.formatMilkYield(null), 'Unavailable');
  assert.deepEqual(presentation.formatChange(null, null), { kind: 'unavailable', text: 'Unavailable' });
  assert.deepEqual(presentation.formatChange(0.4, null), { kind: 'positive', text: '+0.400 L/day' });
  assert.equal(presentation.supportLabel('PREDICTION_UNAVAILABLE', 'PASSED', false), 'Prediction unavailable');
  assert.equal(presentation.supportLabel('OUTSIDE_TRAINING_SUPPORT', 'OUTSIDE_TRAINING_SUPPORT', false), 'Outside the model’s observed training range');
});

test('ranking presentation names combined alternatives and formats both proposed changes', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  assert.equal(presentation.scenarioLabel('combined'), 'Combined scenario');
  assert.equal(presentation.scenarioLabel('individual', 'thi_mean'), 'Heat-stress scenario');
  assert.equal(presentation.scenarioLabel('individual', 'milkings_per_day'), 'Milking-frequency scenario');
  assert.deepEqual(presentation.describeCombinedIntervention(78.8638, 75, 2, 3), [
    'THI: 78.864 → 75.000 THI',
    'Milking frequency: 2.000 → 3.000 milkings/day',
  ]);
});

test('rounding is display-only and preserves the underlying prediction value', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  const prediction = 2.5704170655159437;
  assert.equal(presentation.formatMilkYield(prediction), '2.570 L/day');
  assert.equal(prediction, 2.5704170655159437);
  assert.equal(presentation.formatNumber(78.86378958333331), '78.864');
  assert.equal(presentation.formatNumber(-0.0002), '0.000');
});

test('ranking renders backend alternatives in supplied order and has an unsupported empty state', () => {
  const rankingStart = page.indexOf('result.ranked_alternatives.map((alternative) => {');
  const rankingEnd = page.indexOf('No valid alternatives are available to rank.', rankingStart);
  assert.notEqual(rankingStart, -1, 'ranked alternatives are rendered');
  assert.notEqual(rankingEnd, -1, 'empty-ranking state is present');
  const renderedRanking = page.slice(rankingStart, rankingEnd);
  assert.match(renderedRanking, /result\.ranked_alternatives\.map/);
  assert.doesNotMatch(renderedRanking, /\.sort\(/, 'the UI does not recalculate backend ranking order');
  assert.match(page, /No supported scenario could be recommended\./);
  assert.match(page, /Recommended scenario/);
  assert.doesNotMatch(page, /\(\{alternative\.scenario_id\}\)/, 'internal alternative identifiers are not displayed');
});

test('scenario sliders use model-provided ranges and initialize from the cow value when supported', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  const thiRange = { minimum: 58.25, maximum: 81.75 };
  const milkingsRange = { minimum: 1, maximum: 4 };
  assert.deepEqual(presentation.sliderBounds('thi_mean', thiRange), { minimum: 58.25, maximum: 81.75, step: 'any' });
  assert.deepEqual(presentation.sliderBounds('milkings_per_day', milkingsRange), { minimum: 1, maximum: 4, step: 1 });
  assert.equal(presentation.initialSliderValue('thi_mean', 72.5, thiRange), '72.5');
  assert.equal(presentation.initialSliderValue('milkings_per_day', 3, milkingsRange), '3');
  assert.equal(presentation.initialSliderValue('thi_mean', 72.5, null), '');
  assert.equal(presentation.sliderBounds('thi_mean', null), null);
});

test('slider values outside model support and invalid milking values are not valid submissions', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  const thiRange = { minimum: 60, maximum: 80 };
  const milkingsRange = { minimum: 1, maximum: 4 };
  assert.equal(presentation.isSupportedSliderValue('thi_mean', 80.01, thiRange), false);
  assert.equal(presentation.isSupportedSliderValue('milkings_per_day', 0, milkingsRange), false);
  assert.equal(presentation.isSupportedSliderValue('milkings_per_day', 2.5, milkingsRange), false);
  assert.equal(presentation.isSupportedSliderValue('milkings_per_day', 3, milkingsRange), true);
});

test('scenario and combined controls are sliders with independent state and backend range validation', () => {
  assert.match(page, /type="range"/);
  assert.match(page, /currentValue=\{state\[scenario\.feature\]\}/);
  assert.match(page, /proposedValue=\{scenario\.proposed_value\}/);
  assert.match(page, /if \(i !== index\) return row;/, 'updating one scenario leaves every other scenario unchanged');
  assert.match(page, /initialSliderValue\(next\.feature, state\[next\.feature\], modelSupport\.features\[next\.feature\]\)/);
  assert.match(page, /onChange=\{setCombinedThi\}/);
  assert.match(page, /onChange=\{setCombinedMilkings\}/);
  assert.match(page, /isSupportedSliderValue\(scenario\.feature, Number\(scenario\.proposed_value\), modelSupport\.features\[scenario\.feature\]\)/);
  assert.match(page, /thi_mean: Number\(combinedThi\),\s*milkings_per_day: Number\(combinedMilkings\)/);
  assert.doesNotMatch(page, /type="number"/, 'scenario values are not entered through numeric text boxes');
});

test('scenario results suppress repeated disclaimers and cow data limitations are not displayed', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  const bcsLimitation = 'Body-condition score is unavailable for the latest valid day.';
  const repeated = [
    'This is a model-input perturbation, not a verified causal intervention effect.',
    'A predicted difference may not occur in the real world.',
    'Changing THI represents an exposure what-if; it does not model a cooling action.',
    'Farm operational feasibility has not been validated.',
    'The model estimates an observational prediction difference, not a verified intervention effect.',
    bcsLimitation,
  ];
  assert.deepEqual(presentation.filterScenarioMessages(repeated, [bcsLimitation]), []);
  assert.deepEqual(presentation.filterScenarioMessages([
    'The baseline model prediction is unavailable; no counterfactual estimate was returned.',
    'Proposed thi_mean value is outside the model’s observed training range.',
    'Proposed thi_mean value is outside the model’s observed training range.',
  ]), [
    'The baseline model prediction is unavailable; no counterfactual estimate was returned.',
    'Proposed thi_mean value is outside the model’s observed training range.',
  ]);
  assert.doesNotMatch(page, /Data limitations/);
  assert.doesNotMatch(page, /Dry matter intake|Concentrate intake|\bBCS\b/);
  assert.doesNotMatch(page, /state\.data_limitations\.map/);
  assert.match(page, /filterScenarioMessages\(item\.warnings, state\?\.data_limitations\)/);
  assert.match(page, /filterScenarioMessages\(result\.warnings, state\?\.data_limitations\)/);
  assert.match(page, /These are model-based estimates, not guaranteed real-world outcomes/);
});

test('recommendation display keeps the ranking rationale and omits its repeated disclaimer', async () => {
  const presentation = await import(pathToFileURL(path.join(__dirname, '../src/pages/InterventionSimulator/presentation.mjs')));
  assert.equal(
    presentation.conciseRecommendationExplanation('This alternative has the highest predicted next-day milk yield among the evaluated alternatives. It is a model-based ranking, not a causal optimum or a guaranteed real-world improvement.'),
    'This alternative has the highest predicted next-day milk yield among the evaluated alternatives.',
  );
  assert.match(page, /conciseRecommendationExplanation\(result\.recommendation\.explanation\)/);
  assert.doesNotMatch(page, /item\.data_limitations\.map\(\(limitation\)/);
});
