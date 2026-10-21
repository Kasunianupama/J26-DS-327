const finite = (value) => typeof value === 'number' && Number.isFinite(value);

const repeatedScenarioDisclaimerPatterns = [
  /model-input perturbation.*causal intervention effect/i,
  /predicted difference may not occur in the real world/i,
  /thi value is an exposure what-if.*cooling action/i,
  /changing thi represents an exposure what-if.*cooling action/i,
  /farm operational feasibility has not been validated/i,
  /operational feasibility is not validated/i,
  /operational feasibility are not assessed/i,
  /observational prediction difference.*verified intervention effect/i,
  /observational.*does not identify causal/i,
  /model-based ranking, not a causal optimum/i,
  /not a verified causal intervention effect/i,
  /not evidence that an intervention will cause a real-world yield change/i,
];

export function filterScenarioMessages(messages, baselineLimitations = []) {
  const baseline = new Set(baselineLimitations);
  const seen = new Set();
  return (Array.isArray(messages) ? messages : []).filter((message) => {
    if (typeof message !== 'string' || baseline.has(message)) return false;
    const normalized = message.trim();
    if (!normalized || repeatedScenarioDisclaimerPatterns.some((pattern) => pattern.test(normalized))) return false;
    if (seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

export function conciseRecommendationExplanation(explanation) {
  if (typeof explanation !== 'string') return '';
  return explanation
    .split(/(?<=\.)\s+/)
    .filter((sentence) => !repeatedScenarioDisclaimerPatterns.some((pattern) => pattern.test(sentence)))
    .join(' ');
}

export function validatedModelRange(range) {
  if (!range || !finite(range.minimum) || !finite(range.maximum) || range.minimum > range.maximum) return null;
  return { minimum: range.minimum, maximum: range.maximum };
}

export function sliderBounds(feature, range) {
  const supported = validatedModelRange(range);
  if (!supported) return null;
  if (feature === 'thi_mean') return { ...supported, step: 'any' };
  if (feature === 'milkings_per_day') {
    const minimum = Math.max(1, Math.ceil(supported.minimum));
    const maximum = Math.floor(supported.maximum);
    return minimum <= maximum ? { minimum, maximum, step: 1 } : null;
  }
  return null;
}

export function isSupportedSliderValue(feature, value, range) {
  const supported = validatedModelRange(range);
  const bounds = sliderBounds(feature, range);
  if (!supported || !bounds || !finite(value) || value < supported.minimum || value > supported.maximum) return false;
  if (feature === 'milkings_per_day') return value > 0 && Number.isInteger(value) && value >= bounds.minimum && value <= bounds.maximum;
  return feature === 'thi_mean';
}

export function initialSliderValue(feature, currentValue, range) {
  const bounds = sliderBounds(feature, range);
  if (!bounds) return '';
  if (isSupportedSliderValue(feature, currentValue, range)) return String(currentValue);
  return String(bounds.minimum);
}

export function formatNumber(value) {
  if (!finite(value)) return 'Unavailable';
  const rounded = Number(value.toFixed(3));
  return rounded === 0 ? '0.000' : rounded.toFixed(3);
}

export function formatMilkYield(value) {
  return finite(value) ? `${formatNumber(value)} L/day` : 'Unavailable';
}

export function formatChange(change, percentage) {
  if (!finite(change)) return { kind: 'unavailable', text: 'Unavailable' };

  const roundedChange = Number(change.toFixed(3));
  if (roundedChange === 0) return { kind: 'zero', text: 'No predicted change' };

  const sign = roundedChange > 0 ? '+' : '−';
  const amount = `${sign}${Math.abs(roundedChange).toFixed(3)} L/day`;
  const percent = finite(percentage)
    ? ` (${percentage > 0 ? '+' : percentage < 0 ? '−' : ''}${Math.abs(percentage).toFixed(1)}%)`
    : '';
  return {
    kind: roundedChange > 0 ? 'positive' : 'negative',
    text: `${amount}${percent}`,
  };
}

export function scenarioLabel(alternativeType, feature) {
  if (alternativeType === 'combined') return 'Combined scenario';
  if (feature === 'thi_mean') return 'Heat-stress scenario';
  if (feature === 'milkings_per_day') return 'Milking-frequency scenario';
  return 'Scenario alternative';
}

export function supportLabel(scenarioStatus, modelSupportStatus, hasPrediction) {
  if (!hasPrediction) {
    if (scenarioStatus === 'OUTSIDE_TRAINING_SUPPORT' || modelSupportStatus === 'OUTSIDE_TRAINING_SUPPORT') {
      return 'Outside the model’s observed training range';
    }
    if (scenarioStatus === 'BASELINE_FEATURE_UNAVAILABLE') return 'Baseline value unavailable';
    return 'Prediction unavailable';
  }

  if (modelSupportStatus === 'PASSED') return 'Within model-supported range';
  if (modelSupportStatus === 'OUTSIDE_TRAINING_SUPPORT') return 'Outside the model’s observed training range';
  if (modelSupportStatus === 'RANGE_UNAVAILABLE') return 'Training range could not be checked';
  return 'Model support not assessed';
}

export function describeIntervention(feature, baseline, proposed) {
  const values = `${formatNumber(baseline)} → ${formatNumber(proposed)}`;
  if (feature === 'thi_mean') return `THI: ${values} THI`;
  if (feature === 'milkings_per_day') return `Milking frequency: ${values} milkings/day`;
  return 'Proposed changes unavailable';
}

export function describeCombinedIntervention(baselineThi, proposedThi, baselineMilkings, proposedMilkings) {
  return [
    describeIntervention('thi_mean', baselineThi, proposedThi),
    describeIntervention('milkings_per_day', baselineMilkings, proposedMilkings),
  ];
}
