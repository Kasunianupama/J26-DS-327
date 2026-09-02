export type HealthStatus = 'Healthy' | 'At-risk' | 'Mild mastitis risk';
export type LactationStage = 'Early Lactation' | 'Mid Lactation' | 'Late Lactation';
export type ReproductiveStatus = 'Open' | 'Bred - awaiting check' | 'Pregnant' | 'Voluntary waiting period';
export type InterventionType =
  | 'feed'
  | 'supplement'
  | 'heat'
  | 'health'
  | 'reproduction';
export type ValidationStatus = 'Validated' | 'Rejected';
export type Qualitative = 'Low' | 'Medium' | 'High';
export type WelfareImpact = 'Moderate' | 'Good' | 'Excellent';

export interface BiologicalState {
  milkYield: number;
  feedIntake: number;
  energyDensity: number;
  bcs: number;
  thi: number;
  healthRisk: 'Low' | 'Moderate' | 'Elevated';
  milkingFrequency: string;
}

export interface CowProfile {
  id: string;
  breed: string;
  ageYears: number;
  parity: number;
  lactationStage: LactationStage;
  daysInMilk: number;
  healthStatus: HealthStatus;
  reproductiveStatus: ReproductiveStatus;
  baselineMilkYield: number;
  expectedRange: [number, number];
  confidence: number;
  state: BiologicalState;
}

export interface InterventionSettings {
  feedQuantity: number;
  energyDensity: number;
  supplement: 'None' | 'Protein Supplement' | 'Energy Supplement';
  dosage: number;
  cooling: 'None' | 'Fans' | 'Fans + sprinklers';
  targetThi: number;
  treatment: 'No treatment' | 'Early treatment';
  reproductiveAction: 'No change' | 'Breeding timing review' | 'Pregnancy check scheduling';
  effectWindow: '7 days' | '14 days' | '21 days';
}

export interface ValidationResult {
  status: ValidationStatus;
  checks: { label: string; passed: boolean }[];
  message: string;
}

export interface InterventionScenario {
  id: string;
  label: string;
  interventionType: InterventionType;
  interventionLabel: string;
  baselineMilk: number;
  predictedMilk: number;
  milkDelta: number;
  percentDelta: number;
  cost: Qualitative;
  welfare: WelfareImpact;
  feasibility: Qualitative;
  resourceAvailability: Qualitative;
  confidence: number;
  validation: ValidationResult;
  explanation: string;
}

export interface OptimizationWeights {
  milk: number;
  welfare: number;
  cost: number;
  feasibility: number;
  resources: number;
}

export interface RankedScenario extends InterventionScenario {
  score: number;
}

export const cows: CowProfile[] = [
  {
    id: 'COW-1047',
    breed: 'Holstein Friesian',
    ageYears: 4.2,
    parity: 2,
    lactationStage: 'Mid Lactation',
    daysInMilk: 102,
    healthStatus: 'Healthy',
    reproductiveStatus: 'Open',
    baselineMilkYield: 25.8,
    expectedRange: [24.9, 26.7],
    confidence: 84,
    state: {
      milkYield: 25.4,
      feedIntake: 20,
      energyDensity: 10.8,
      bcs: 3.1,
      thi: 72,
      healthRisk: 'Low',
      milkingFrequency: '2x / day',
    },
  },
  {
    id: 'COW-1082',
    breed: 'Jersey cross',
    ageYears: 3.6,
    parity: 1,
    lactationStage: 'Early Lactation',
    daysInMilk: 46,
    healthStatus: 'At-risk',
    reproductiveStatus: 'Voluntary waiting period',
    baselineMilkYield: 20.9,
    expectedRange: [19.6, 22.1],
    confidence: 76,
    state: {
      milkYield: 20.3,
      feedIntake: 17.8,
      energyDensity: 10.4,
      bcs: 2.8,
      thi: 74,
      healthRisk: 'Moderate',
      milkingFrequency: '2x / day',
    },
  },
  {
    id: 'COW-1134',
    breed: 'Sahiwal cross',
    ageYears: 5.1,
    parity: 3,
    lactationStage: 'Late Lactation',
    daysInMilk: 221,
    healthStatus: 'Mild mastitis risk',
    reproductiveStatus: 'Pregnant',
    baselineMilkYield: 18.7,
    expectedRange: [17.6, 19.5],
    confidence: 79,
    state: {
      milkYield: 18.2,
      feedIntake: 18.4,
      energyDensity: 10.2,
      bcs: 3.3,
      thi: 70,
      healthRisk: 'Elevated',
      milkingFrequency: '2x / day',
    },
  },
  {
    id: 'COW-1191',
    breed: 'Holstein Friesian',
    ageYears: 6.4,
    parity: 4,
    lactationStage: 'Mid Lactation',
    daysInMilk: 138,
    healthStatus: 'Healthy',
    reproductiveStatus: 'Bred - awaiting check',
    baselineMilkYield: 27.2,
    expectedRange: [26.1, 28.0],
    confidence: 81,
    state: {
      milkYield: 26.8,
      feedIntake: 21.1,
      energyDensity: 10.9,
      bcs: 3,
      thi: 76,
      healthRisk: 'Low',
      milkingFrequency: '3x / day',
    },
  },
];

export const defaultSettings: InterventionSettings = {
  feedQuantity: 22,
  energyDensity: 10.8,
  supplement: 'None',
  dosage: 0,
  cooling: 'Fans + sprinklers',
  targetThi: 68,
  treatment: 'No treatment',
  reproductiveAction: 'No change',
  effectWindow: '14 days',
};

export const featureInfluence = [
  { name: 'Feed intake', value: 92 },
  { name: 'Lactation stage', value: 78 },
  { name: 'THI', value: 62 },
  { name: 'Health status', value: 46 },
  { name: 'Milking frequency', value: 34 },
];

export const defaultWeights: OptimizationWeights = {
  milk: 40,
  welfare: 25,
  cost: 15,
  feasibility: 10,
  resources: 10,
};

const round = (value: number, digits = 1) => Number(value.toFixed(digits));
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

function qualitativeScore(value: Qualitative) {
  return value === 'High' ? 100 : value === 'Medium' ? 68 : 36;
}

function costScore(value: Qualitative) {
  return value === 'Low' ? 100 : value === 'Medium' ? 70 : 38;
}

function welfareScore(value: WelfareImpact) {
  return value === 'Excellent' ? 100 : value === 'Good' ? 78 : 52;
}

export function validateScenario(cow: CowProfile, type: InterventionType, settings: InterventionSettings): ValidationResult {
  const feedChange = settings.feedQuantity - cow.state.feedIntake;
  const checks = [
    { label: 'Lactation stage compatible', passed: cow.daysInMilk > 20 && cow.daysInMilk < 305 },
    { label: 'Feed intervention within allowed range', passed: type !== 'feed' || (settings.feedQuantity <= 23.5 && feedChange <= 3.5) },
    { label: 'Health state compatible', passed: type !== 'health' || cow.healthStatus !== 'Healthy' || settings.treatment === 'No treatment' },
    { label: 'Reproductive state unchanged unless selected', passed: type === 'reproduction' || settings.reproductiveAction === 'No change' },
    { label: 'THI dependency preserved', passed: type !== 'heat' || settings.targetThi <= cow.state.thi },
    { label: 'Intervention affects only controllable variable', passed: true },
  ];
  const rejected = checks.some((check) => !check.passed);
  return {
    status: rejected ? 'Rejected' : 'Validated',
    checks,
    message: rejected
      ? 'This scenario cannot proceed to intervention optimization.'
      : 'Scenario passed the prototype biological consistency gate.',
  };
}

function scenarioMeta(type: InterventionType, settings: InterventionSettings) {
  if (type === 'feed') {
    const feedDelta = settings.feedQuantity - 20;
    return {
      interventionLabel: `Feed ${feedDelta >= 0 ? '+' : ''}${round((feedDelta / 20) * 100, 0)}%`,
      cost: settings.feedQuantity > 22.7 ? 'High' as const : settings.feedQuantity > 21 ? 'Medium' as const : 'Low' as const,
      welfare: settings.feedQuantity > 23 ? 'Moderate' as const : 'Good' as const,
      feasibility: settings.feedQuantity > 23 ? 'Medium' as const : 'High' as const,
      resourceAvailability: settings.feedQuantity > 22.8 ? 'Medium' as const : 'High' as const,
    };
  }
  if (type === 'supplement') return {
    interventionLabel: settings.supplement === 'None' ? 'No supplement' : `${settings.supplement} ${settings.dosage} kg/day`,
    cost: settings.supplement === 'None' ? 'Low' as const : 'High' as const,
    welfare: 'Good' as const,
    feasibility: settings.dosage > 1.8 ? 'Medium' as const : 'High' as const,
    resourceAvailability: 'Medium' as const,
  };
  if (type === 'heat') return {
    interventionLabel: settings.cooling === 'None' ? 'No cooling change' : settings.cooling,
    cost: settings.cooling === 'Fans + sprinklers' ? 'Medium' as const : 'Low' as const,
    welfare: settings.cooling === 'None' ? 'Moderate' as const : 'Excellent' as const,
    feasibility: 'High' as const,
    resourceAvailability: settings.cooling === 'Fans + sprinklers' ? 'Medium' as const : 'High' as const,
  };
  if (type === 'health') return {
    interventionLabel: settings.treatment,
    cost: settings.treatment === 'Early treatment' ? 'Medium' as const : 'Low' as const,
    welfare: settings.treatment === 'Early treatment' ? 'Excellent' as const : 'Good' as const,
    feasibility: 'High' as const,
    resourceAvailability: 'High' as const,
  };
  return {
    interventionLabel: settings.reproductiveAction,
    cost: 'Low' as const,
    welfare: 'Good' as const,
    feasibility: settings.reproductiveAction === 'No change' ? 'High' as const : 'Medium' as const,
    resourceAvailability: 'High' as const,
  };
}

export function simulateScenario(cow: CowProfile, type: InterventionType, settings: InterventionSettings, id = 'custom'): InterventionScenario {
  const baseline = cow.baselineMilkYield;
  let uplift = 0;
  let confidencePenalty = 0;

  // Prototype-only simulated counterfactual effect.
  // Replace with validated model output when backend/ML service is available.
  if (type === 'feed') {
    const feedDelta = settings.feedQuantity - cow.state.feedIntake;
    const energyDelta = settings.energyDensity - cow.state.energyDensity;
    uplift = feedDelta * 0.65 + energyDelta * 0.42;
    if (settings.feedQuantity > 22.5) uplift -= (settings.feedQuantity - 22.5) * 0.12;
    confidencePenalty = Math.max(0, feedDelta - 2) * 2;
  } else if (type === 'supplement') {
    const base = settings.supplement === 'Protein Supplement' ? 0.72 : settings.supplement === 'Energy Supplement' ? 0.92 : 0;
    uplift = base + settings.dosage * 0.22;
    confidencePenalty = settings.dosage > 1.6 ? 5 : 2;
  } else if (type === 'heat') {
    uplift = Math.max(0, cow.state.thi - settings.targetThi) * 0.31;
    confidencePenalty = settings.cooling === 'Fans + sprinklers' ? 2 : 4;
  } else if (type === 'health') {
    uplift = settings.treatment === 'Early treatment' && cow.healthStatus !== 'Healthy' ? 1.15 : 0.18;
    confidencePenalty = cow.healthStatus === 'Mild mastitis risk' ? 8 : 4;
  } else {
    uplift = settings.reproductiveAction === 'No change' ? 0.05 : 0.55;
    confidencePenalty = 7;
  }

  const validation = validateScenario(cow, type, settings);
  const meta = scenarioMeta(type, settings);
  const predictedMilk = round(baseline + Math.max(-1.2, uplift), 1);
  const milkDelta = round(predictedMilk - baseline, 1);

  return {
    id,
    label: id === 'custom' ? 'Selected what-if scenario' : id,
    interventionType: type,
    interventionLabel: meta.interventionLabel,
    baselineMilk: baseline,
    predictedMilk,
    milkDelta,
    percentDelta: round((milkDelta / baseline) * 100, 1),
    cost: meta.cost,
    welfare: meta.welfare,
    feasibility: meta.feasibility,
    resourceAvailability: meta.resourceAvailability,
    confidence: clamp(Math.round(cow.confidence - confidencePenalty), 58, 90),
    validation,
    explanation: 'Prototype demonstration data: estimated outcome under an alternative intervention while keeping the observed biological state fixed.',
  };
}

export function generateScenarioSet(cow: CowProfile): InterventionScenario[] {
  const feed5 = simulateScenario(cow, 'feed', { ...defaultSettings, feedQuantity: round(cow.state.feedIntake * 1.05, 1) }, 'Scenario A');
  const feed10 = simulateScenario(cow, 'feed', { ...defaultSettings, feedQuantity: round(cow.state.feedIntake * 1.1, 1) }, 'Scenario B');
  const feed15 = simulateScenario(cow, 'feed', { ...defaultSettings, feedQuantity: round(cow.state.feedIntake * 1.15, 1) }, 'Scenario C');
  const heat = simulateScenario(cow, 'heat', { ...defaultSettings, targetThi: Math.max(66, cow.state.thi - 5), cooling: 'Fans + sprinklers' }, 'Scenario D');
  const supplement = simulateScenario(cow, 'supplement', { ...defaultSettings, supplement: 'Energy Supplement', dosage: 1.2 }, 'Scenario E');
  return [
    { ...feed5, label: 'Scenario A', interventionLabel: 'Feed +5%' },
    { ...feed10, label: 'Scenario B', interventionLabel: 'Feed +10%' },
    { ...feed15, label: 'Scenario C', interventionLabel: 'Feed +15%' },
    { ...heat, label: 'Scenario D', interventionLabel: 'Reduce heat stress' },
    { ...supplement, label: 'Scenario E', interventionLabel: 'Nutritional supplement' },
  ];
}

export function rankScenarios(scenarios: InterventionScenario[], rawWeights: OptimizationWeights): RankedScenario[] {
  const total = Object.values(rawWeights).reduce((sum, value) => sum + value, 0) || 1;
  const weights = {
    milk: rawWeights.milk / total,
    welfare: rawWeights.welfare / total,
    cost: rawWeights.cost / total,
    feasibility: rawWeights.feasibility / total,
    resources: rawWeights.resources / total,
  };
  const maxDelta = Math.max(1, ...scenarios.map((scenario) => Math.max(0, scenario.milkDelta)));

  return scenarios
    .filter((scenario) => scenario.validation.status === 'Validated')
    .map((scenario) => {
      const milkScore = clamp((Math.max(0, scenario.milkDelta) / maxDelta) * 100, 0, 100);
      const score =
        milkScore * weights.milk +
        welfareScore(scenario.welfare) * weights.welfare +
        costScore(scenario.cost) * weights.cost +
        qualitativeScore(scenario.feasibility) * weights.feasibility +
        qualitativeScore(scenario.resourceAvailability) * weights.resources;
      return { ...scenario, score: Math.round(score) };
    })
    .sort((a, b) => b.score - a.score);
}
