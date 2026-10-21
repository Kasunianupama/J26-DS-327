export type ChangeKind = 'positive' | 'negative' | 'zero' | 'unavailable';
export type NumericRange = { minimum: number; maximum: number };
export type SliderBounds = { minimum: number; maximum: number; step: number | 'any' };

export function filterScenarioMessages(messages: string[], baselineLimitations?: string[]): string[];
export function conciseRecommendationExplanation(explanation: string): string;

export function validatedModelRange(range: NumericRange | null | undefined): NumericRange | null;
export function sliderBounds(feature: string, range: NumericRange | null | undefined): SliderBounds | null;
export function isSupportedSliderValue(feature: string, value: number, range: NumericRange | null | undefined): boolean;
export function initialSliderValue(feature: string, currentValue: number | null | undefined, range: NumericRange | null | undefined): string;
export function formatNumber(value: number | null | undefined): string;
export function formatMilkYield(value: number | null | undefined): string;
export function formatChange(
  change: number | null | undefined,
  percentage: number | null | undefined,
): { kind: ChangeKind; text: string };
export function scenarioLabel(alternativeType: string, feature?: string): string;
export function supportLabel(scenarioStatus: string, modelSupportStatus: string, hasPrediction: boolean): string;
export function describeIntervention(
  feature: string,
  baseline: number | null | undefined,
  proposed: number | null | undefined,
): string;
export function describeCombinedIntervention(
  baselineThi: number | null | undefined,
  proposedThi: number | null | undefined,
  baselineMilkings: number | null | undefined,
  proposedMilkings: number | null | undefined,
): string[];
