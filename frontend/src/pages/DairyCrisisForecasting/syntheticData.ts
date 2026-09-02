export interface FarmData {
  id: string;
  rank: number;
  name: string;
  region: string;
  riskScore: number; // 0-100
  riskLevel: 'Critical' | 'High' | 'Medium' | 'Low';
  milkLossProb: number; // e.g. 63
  expectedLossRange: string; // e.g. "8.4% – 12.6%"
  mainRiskFactor: string;
  mainRiskDesc: string;
  lastUpdated: string;
  model: string;
  confidence: 'High' | 'Medium' | 'Low';
  
  // Sub-risks
  climateRisk: {
    level: 'High' | 'Medium' | 'Low';
    futureThiMax: number;
    forecastTempMax: number;
    forecastHumidityAvg: number;
    rainfall7Days: number;
  };
  operationalRisk: {
    level: 'High' | 'Medium' | 'Low';
    workerReliability: number; // %
    humanErrorFreq: number; // %
    operationalConsistency: number; // %
    milkingDelayAvg: number; // mins
  };
  feedRisk: {
    level: 'High' | 'Medium' | 'Low';
    feedAvailability: number; // %
    feedQuantity: number; // %
    feedSupplyGap: number; // %
    supplementAvailability: string;
  };
  vulnerability: {
    level: 'High' | 'Medium' | 'Low';
    historicalMilkStability: string;
    diseaseIncidence: string;
    biologicalVulnerability: string;
    bodyConditionScore: number;
  };

  // SHAP Contributors (Impact on Risk Score)
  shapContributors: {
    feature: string;
    impact: number;
  }[];

  // 7-Day Climate Forecast (2026)
  climateForecast: {
    date: string;
    dayLabel: string;
    temp: number;
    humidity: number;
    thi: number;
  }[];
  heatStressAlertDays?: string;

  // 30-Day Risk History (2026)
  riskTrend30Days: {
    date: string;
    score: number;
  }[];

  // Warnings & Recommendations
  earlyWarning: {
    level: 'HIGH RISK' | 'CRITICAL RISK' | 'MEDIUM RISK' | 'LOW RISK';
    timeframe: string;
    mainFactor: string;
    otherFactors: string[];
  };
  recommendedActions: {
    action: string;
    completed: boolean;
  }[];
}

export interface RegionalRiskData {
  region: string;
  avgRiskScore: number;
  highCritFarmsCount: number;
  totalFarmsCount: number;
  riskLevel: 'Critical' | 'High' | 'Medium' | 'Low';
}

export interface NationalAlert {
  id: string;
  type: 'critical' | 'high' | 'medium' | 'info';
  title: string;
  subtitle: string;
  time: string;
  isNew: boolean;
}

// 14 Total Farms Dataset (Synthetic, Deterministic, 2026 Dates)
export const SYNTETHIC_FARMS: FarmData[] = [
  {
    id: 'farm-1',
    rank: 1,
    name: 'Green View Farm',
    region: 'Kurunegala',
    riskScore: 82,
    riskLevel: 'Critical',
    milkLossProb: 63,
    expectedLossRange: '8.4% – 12.6%',
    mainRiskFactor: 'High Future THI',
    mainRiskDesc: 'THI expected to exceed threshold for 3 days',
    lastUpdated: 'Today, 08:30 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: {
      level: 'High',
      futureThiMax: 78,
      forecastTempMax: 33.6,
      forecastHumidityAvg: 72,
      rainfall7Days: 12,
    },
    operationalRisk: {
      level: 'Medium',
      workerReliability: 72,
      humanErrorFreq: 18,
      operationalConsistency: 65,
      milkingDelayAvg: 24,
    },
    feedRisk: {
      level: 'Medium',
      feedAvailability: 65,
      feedQuantity: 72,
      feedSupplyGap: 12,
      supplementAvailability: 'Adequate',
    },
    vulnerability: {
      level: 'High',
      historicalMilkStability: 'Low',
      diseaseIncidence: 'Moderate',
      biologicalVulnerability: 'High',
      bodyConditionScore: 2.8,
    },
    shapContributors: [
      { feature: 'High Future THI', impact: 0.36 },
      { feature: 'Feed Availability', impact: 0.24 },
      { feature: 'Water Stress', impact: 0.18 },
      { feature: 'Recent Heat Stress', impact: 0.12 },
      { feature: 'Operational Delay', impact: 0.09 },
    ],
    climateForecast: [
      { date: 'May 25, 2026', dayLabel: 'May 25', temp: 31, humidity: 68, thi: 75 },
      { date: 'May 26, 2026', dayLabel: 'May 26', temp: 30, humidity: 62, thi: 73 },
      { date: 'May 27, 2026', dayLabel: 'May 27', temp: 33, humidity: 65, thi: 77 },
      { date: 'May 28, 2026', dayLabel: 'May 28', temp: 32, humidity: 64, thi: 76 },
      { date: 'May 29, 2026', dayLabel: 'May 29', temp: 34, humidity: 70, thi: 79 },
      { date: 'May 30, 2026', dayLabel: 'May 30', temp: 35, humidity: 74, thi: 81 },
      { date: 'May 31, 2026', dayLabel: 'May 31', temp: 34, humidity: 72, thi: 78 },
    ],
    heatStressAlertDays: 'May 27 – May 30, 2026',
    riskTrend30Days: [
      { date: 'May 25', score: 55 },
      { date: 'May 26', score: 50 },
      { date: 'May 27', score: 68 },
      { date: 'May 28', score: 58 },
      { date: 'May 29', score: 75 },
      { date: 'May 30', score: 75 },
      { date: 'May 31', score: 82 },
    ],
    earlyWarning: {
      level: 'HIGH RISK',
      timeframe: 'May 27 – May 30, 2026',
      mainFactor: 'High Future THI',
      otherFactors: ['Feed availability', 'Operational consistency', 'Humidity'],
    },
    recommendedActions: [
      { action: 'Improve feed management - Ensure quality and quantity', completed: true },
      { action: 'Increase water availability - Check storage and supply', completed: true },
      { action: 'Provide shade and cooling - Reduce heat stress impact', completed: true },
    ],
  },
  {
    id: 'farm-2',
    rank: 2,
    name: 'Happy Milk Dairy',
    region: 'Puttalam',
    riskScore: 76,
    riskLevel: 'Critical',
    milkLossProb: 58,
    expectedLossRange: '7.2% – 11.5%',
    mainRiskFactor: 'Feed Availability',
    mainRiskDesc: 'Feed supply gap exceeding 25% due to dry spell',
    lastUpdated: 'Today, 08:15 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'High', futureThiMax: 76, forecastTempMax: 34.2, forecastHumidityAvg: 68, rainfall7Days: 4 },
    operationalRisk: { level: 'Medium', workerReliability: 68, humanErrorFreq: 22, operationalConsistency: 59, milkingDelayAvg: 31 },
    feedRisk: { level: 'High', feedAvailability: 42, feedQuantity: 50, feedSupplyGap: 28, supplementAvailability: 'Critical Shortage' },
    vulnerability: { level: 'High', historicalMilkStability: 'Low', diseaseIncidence: 'High', biologicalVulnerability: 'High', bodyConditionScore: 2.5 },
    shapContributors: [
      { feature: 'Feed Availability', impact: 0.35 },
      { feature: 'High Future THI', impact: 0.22 },
      { feature: 'Operational Delay', impact: 0.14 },
    ],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 32, humidity: 65, thi: 74 }],
    riskTrend30Days: [{ date: 'May 25', score: 60 }, { date: 'May 31', score: 76 }],
    earlyWarning: { level: 'CRITICAL RISK', timeframe: 'Next 5 days', mainFactor: 'Feed Availability', otherFactors: ['Water scarcity'] },
    recommendedActions: [{ action: 'Source emergency forage supplements', completed: true }],
  },
  {
    id: 'farm-3',
    rank: 3,
    name: 'Udara Dairy Farm',
    region: 'Anuradhapura',
    riskScore: 72,
    riskLevel: 'High',
    milkLossProb: 52,
    expectedLossRange: '6.5% – 9.8%',
    mainRiskFactor: 'High Future THI',
    mainRiskDesc: 'Heat stress forecast over dry zone pastures',
    lastUpdated: 'Today, 08:00 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'High', futureThiMax: 77, forecastTempMax: 33.8, forecastHumidityAvg: 70, rainfall7Days: 8 },
    operationalRisk: { level: 'Medium', workerReliability: 75, humanErrorFreq: 15, operationalConsistency: 68, milkingDelayAvg: 18 },
    feedRisk: { level: 'Medium', feedAvailability: 60, feedQuantity: 68, feedSupplyGap: 15, supplementAvailability: 'Moderate' },
    vulnerability: { level: 'Medium', historicalMilkStability: 'Moderate', diseaseIncidence: 'Low', biologicalVulnerability: 'Moderate', bodyConditionScore: 3.0 },
    shapContributors: [{ feature: 'High Future THI', impact: 0.28 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 31, humidity: 66, thi: 74 }],
    riskTrend30Days: [{ date: 'May 25', score: 55 }, { date: 'May 31', score: 72 }],
    earlyWarning: { level: 'HIGH RISK', timeframe: 'Next 7 days', mainFactor: 'High Future THI', otherFactors: ['Temp spike'] },
    recommendedActions: [{ action: 'Activate misting fans in holding area', completed: true }],
  },
  {
    id: 'farm-4',
    rank: 4,
    name: 'New Hope Farm',
    region: 'Polonnaruwa',
    riskScore: 61,
    riskLevel: 'Medium',
    milkLossProb: 44,
    expectedLossRange: '5.0% – 8.2%',
    mainRiskFactor: 'Operational Consistency',
    mainRiskDesc: 'Fluctuations in feeding and milking schedule',
    lastUpdated: 'Today, 07:45 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Medium', futureThiMax: 74, forecastTempMax: 32.5, forecastHumidityAvg: 65, rainfall7Days: 18 },
    operationalRisk: { level: 'High', workerReliability: 60, humanErrorFreq: 26, operationalConsistency: 54, milkingDelayAvg: 38 },
    feedRisk: { level: 'Medium', feedAvailability: 70, feedQuantity: 75, feedSupplyGap: 10, supplementAvailability: 'Adequate' },
    vulnerability: { level: 'Medium', historicalMilkStability: 'Moderate', diseaseIncidence: 'Low', biologicalVulnerability: 'Moderate', bodyConditionScore: 3.1 },
    shapContributors: [{ feature: 'Operational Consistency', impact: 0.25 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 30, humidity: 62, thi: 72 }],
    riskTrend30Days: [{ date: 'May 25', score: 50 }, { date: 'May 31', score: 61 }],
    earlyWarning: { level: 'MEDIUM RISK', timeframe: 'Next 7 days', mainFactor: 'Operational Delay', otherFactors: ['Worker attendance'] },
    recommendedActions: [{ action: 'Enforce standard operating procedures', completed: true }],
  },
  {
    id: 'farm-5',
    rank: 5,
    name: 'Lakmilk Farm',
    region: 'Matale',
    riskScore: 58,
    riskLevel: 'Medium',
    milkLossProb: 39,
    expectedLossRange: '4.1% – 6.8%',
    mainRiskFactor: 'Feed Supply Gap',
    mainRiskDesc: 'Slight delay in concentrate supply chain',
    lastUpdated: 'Today, 07:30 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Medium', futureThiMax: 72, forecastTempMax: 30.2, forecastHumidityAvg: 70, rainfall7Days: 25 },
    operationalRisk: { level: 'Low', workerReliability: 82, humanErrorFreq: 10, operationalConsistency: 78, milkingDelayAvg: 12 },
    feedRisk: { level: 'High', feedAvailability: 58, feedQuantity: 62, feedSupplyGap: 22, supplementAvailability: 'Delayed' },
    vulnerability: { level: 'Medium', historicalMilkStability: 'Moderate', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.2 },
    shapContributors: [{ feature: 'Feed Supply Gap', impact: 0.26 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 28, humidity: 72, thi: 70 }],
    riskTrend30Days: [{ date: 'May 25', score: 45 }, { date: 'May 31', score: 58 }],
    earlyWarning: { level: 'MEDIUM RISK', timeframe: 'Next 7 days', mainFactor: 'Feed Supply Gap', otherFactors: ['Concentrate delay'] },
    recommendedActions: [{ action: 'Reorder concentrate buffer stock', completed: true }],
  },
  {
    id: 'farm-6',
    rank: 6,
    name: 'Mahaweli Dairy',
    region: 'Kandy',
    riskScore: 54,
    riskLevel: 'Medium',
    milkLossProb: 35,
    expectedLossRange: '3.5% – 5.9%',
    mainRiskFactor: 'Milking Delay',
    mainRiskDesc: 'Equipment maintenance backlog causing shifts',
    lastUpdated: 'Today, 07:15 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 70, forecastTempMax: 28.5, forecastHumidityAvg: 75, rainfall7Days: 32 },
    operationalRisk: { level: 'Medium', workerReliability: 76, humanErrorFreq: 14, operationalConsistency: 70, milkingDelayAvg: 29 },
    feedRisk: { level: 'Low', feedAvailability: 78, feedQuantity: 80, feedSupplyGap: 6, supplementAvailability: 'Adequate' },
    vulnerability: { level: 'Low', historicalMilkStability: 'High', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.3 },
    shapContributors: [{ feature: 'Milking Delay', impact: 0.21 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 26, humidity: 76, thi: 68 }],
    riskTrend30Days: [{ date: 'May 25', score: 40 }, { date: 'May 31', score: 54 }],
    earlyWarning: { level: 'MEDIUM RISK', timeframe: 'Next 7 days', mainFactor: 'Milking Delay', otherFactors: ['Vacuum pump service'] },
    recommendedActions: [{ action: 'Service milking machines', completed: true }],
  },
  {
    id: 'farm-7',
    rank: 7,
    name: 'Lanka Milk Fields',
    region: 'Nuwara Eliya',
    riskScore: 49,
    riskLevel: 'Medium',
    milkLossProb: 28,
    expectedLossRange: '2.8% – 4.5%',
    mainRiskFactor: 'Biological Vulnerability',
    mainRiskDesc: 'Recent calving period stress',
    lastUpdated: 'Today, 07:00 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 65, forecastTempMax: 22.0, forecastHumidityAvg: 80, rainfall7Days: 45 },
    operationalRisk: { level: 'Low', workerReliability: 88, humanErrorFreq: 8, operationalConsistency: 85, milkingDelayAvg: 10 },
    feedRisk: { level: 'Low', feedAvailability: 85, feedQuantity: 88, feedSupplyGap: 4, supplementAvailability: 'Abundant' },
    vulnerability: { level: 'Medium', historicalMilkStability: 'Moderate', diseaseIncidence: 'Low', biologicalVulnerability: 'High', bodyConditionScore: 3.1 },
    shapContributors: [{ feature: 'Biological Vulnerability', impact: 0.22 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 20, humidity: 82, thi: 63 }],
    riskTrend30Days: [{ date: 'May 25', score: 35 }, { date: 'May 31', score: 49 }],
    earlyWarning: { level: 'MEDIUM RISK', timeframe: 'Next 7 days', mainFactor: 'Biological Vulnerability', otherFactors: ['Post-partum care'] },
    recommendedActions: [{ action: 'Provide high-density energy supplements', completed: true }],
  },
  {
    id: 'farm-8',
    rank: 8,
    name: 'Hilltop Pastures',
    region: 'Badulla',
    riskScore: 46,
    riskLevel: 'Medium',
    milkLossProb: 24,
    expectedLossRange: '2.2% – 3.9%',
    mainRiskFactor: 'Disease Incidence',
    mainRiskDesc: 'Minor mastitis case monitoring',
    lastUpdated: 'Today, 06:45 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 68, forecastTempMax: 26.0, forecastHumidityAvg: 72, rainfall7Days: 15 },
    operationalRisk: { level: 'Low', workerReliability: 84, humanErrorFreq: 11, operationalConsistency: 80, milkingDelayAvg: 14 },
    feedRisk: { level: 'Low', feedAvailability: 80, feedQuantity: 82, feedSupplyGap: 5, supplementAvailability: 'Adequate' },
    vulnerability: { level: 'Medium', historicalMilkStability: 'Moderate', diseaseIncidence: 'Moderate', biologicalVulnerability: 'Medium', bodyConditionScore: 3.2 },
    shapContributors: [{ feature: 'Disease Incidence', impact: 0.19 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 24, humidity: 70, thi: 66 }],
    riskTrend30Days: [{ date: 'May 25', score: 38 }, { date: 'May 31', score: 46 }],
    earlyWarning: { level: 'MEDIUM RISK', timeframe: 'Next 7 days', mainFactor: 'Disease Incidence', otherFactors: ['Mastitis screening'] },
    recommendedActions: [{ action: 'Audit teat dipping protocol', completed: true }],
  },
  {
    id: 'farm-9',
    rank: 9,
    name: 'Ruhunu Dairy',
    region: 'Hambantota',
    riskScore: 42,
    riskLevel: 'Medium',
    milkLossProb: 20,
    expectedLossRange: '1.8% – 3.2%',
    mainRiskFactor: 'Water Scarcity',
    mainRiskDesc: 'Dry weather affecting water tank levels',
    lastUpdated: 'Today, 06:30 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Medium', futureThiMax: 75, forecastTempMax: 33.0, forecastHumidityAvg: 66, rainfall7Days: 2 },
    operationalRisk: { level: 'Low', workerReliability: 86, humanErrorFreq: 9, operationalConsistency: 82, milkingDelayAvg: 11 },
    feedRisk: { level: 'Medium', feedAvailability: 72, feedQuantity: 74, feedSupplyGap: 8, supplementAvailability: 'Adequate' },
    vulnerability: { level: 'Low', historicalMilkStability: 'High', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.4 },
    shapContributors: [{ feature: 'Water Stress', impact: 0.18 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 31, humidity: 65, thi: 73 }],
    riskTrend30Days: [{ date: 'May 25', score: 35 }, { date: 'May 31', score: 42 }],
    earlyWarning: { level: 'MEDIUM RISK', timeframe: 'Next 7 days', mainFactor: 'Water Stress', otherFactors: ['Tank levels'] },
    recommendedActions: [{ action: 'Refill backup water storage tanks', completed: true }],
  },
  {
    id: 'farm-10',
    rank: 10,
    name: 'Batalanda Farm',
    region: 'Gampaha',
    riskScore: 38,
    riskLevel: 'Low',
    milkLossProb: 15,
    expectedLossRange: '1.0% – 2.5%',
    mainRiskFactor: 'Humidity',
    mainRiskDesc: 'High relative humidity causing mild discomfort',
    lastUpdated: 'Today, 06:15 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 71, forecastTempMax: 30.0, forecastHumidityAvg: 78, rainfall7Days: 20 },
    operationalRisk: { level: 'Low', workerReliability: 90, humanErrorFreq: 6, operationalConsistency: 88, milkingDelayAvg: 8 },
    feedRisk: { level: 'Low', feedAvailability: 88, feedQuantity: 90, feedSupplyGap: 2, supplementAvailability: 'Abundant' },
    vulnerability: { level: 'Low', historicalMilkStability: 'High', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.5 },
    shapContributors: [{ feature: 'Humidity', impact: 0.09 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 29, humidity: 76, thi: 70 }],
    riskTrend30Days: [{ date: 'May 25', score: 30 }, { date: 'May 31', score: 38 }],
    earlyWarning: { level: 'LOW RISK', timeframe: 'Next 7 days', mainFactor: 'Humidity', otherFactors: ['Ventilation OK'] },
    recommendedActions: [{ action: 'Maintain current ventilation fans', completed: true }],
  },
  {
    id: 'farm-11',
    rank: 11,
    name: 'Wayamba Dairy',
    region: 'Chilaw',
    riskScore: 35,
    riskLevel: 'Low',
    milkLossProb: 12,
    expectedLossRange: '0.8% – 1.9%',
    mainRiskFactor: 'Feed Availability',
    mainRiskDesc: 'Green fodder supply stable',
    lastUpdated: 'Today, 06:00 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 70, forecastTempMax: 30.5, forecastHumidityAvg: 70, rainfall7Days: 14 },
    operationalRisk: { level: 'Low', workerReliability: 92, humanErrorFreq: 5, operationalConsistency: 90, milkingDelayAvg: 6 },
    feedRisk: { level: 'Low', feedAvailability: 90, feedQuantity: 92, feedSupplyGap: 1, supplementAvailability: 'Abundant' },
    vulnerability: { level: 'Low', historicalMilkStability: 'High', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.6 },
    shapContributors: [{ feature: 'Operational Consistency', impact: -0.28 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 29, humidity: 68, thi: 69 }],
    riskTrend30Days: [{ date: 'May 25', score: 28 }, { date: 'May 31', score: 35 }],
    earlyWarning: { level: 'LOW RISK', timeframe: 'Next 7 days', mainFactor: 'Low Risk', otherFactors: ['Stable'] },
    recommendedActions: [{ action: 'Continue routine management', completed: true }],
  },
  {
    id: 'farm-12',
    rank: 12,
    name: 'Kandurata Farms',
    region: 'Matale',
    riskScore: 31,
    riskLevel: 'Low',
    milkLossProb: 9,
    expectedLossRange: '0.5% – 1.4%',
    mainRiskFactor: 'Temp Fluctuations',
    mainRiskDesc: 'Mild day/night temperature variation',
    lastUpdated: 'Today, 05:45 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 68, forecastTempMax: 27.0, forecastHumidityAvg: 72, rainfall7Days: 28 },
    operationalRisk: { level: 'Low', workerReliability: 94, humanErrorFreq: 4, operationalConsistency: 92, milkingDelayAvg: 5 },
    feedRisk: { level: 'Low', feedAvailability: 92, feedQuantity: 95, feedSupplyGap: 0, supplementAvailability: 'Abundant' },
    vulnerability: { level: 'Low', historicalMilkStability: 'High', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.7 },
    shapContributors: [{ feature: 'Worker Reliability', impact: -0.31 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 26, humidity: 70, thi: 67 }],
    riskTrend30Days: [{ date: 'May 25', score: 25 }, { date: 'May 31', score: 31 }],
    earlyWarning: { level: 'LOW RISK', timeframe: 'Next 7 days', mainFactor: 'Low Risk', otherFactors: ['Optimal'] },
    recommendedActions: [{ action: 'Routine monitoring', completed: true }],
  },
  {
    id: 'farm-13',
    rank: 13,
    name: 'Highland Pastures',
    region: 'Nuwara Eliya',
    riskScore: 27,
    riskLevel: 'Low',
    milkLossProb: 6,
    expectedLossRange: '0.2% – 1.0%',
    mainRiskFactor: 'Low Risk',
    mainRiskDesc: 'Ideal climate and excellent herd management',
    lastUpdated: 'Today, 05:30 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 62, forecastTempMax: 20.0, forecastHumidityAvg: 78, rainfall7Days: 40 },
    operationalRisk: { level: 'Low', workerReliability: 96, humanErrorFreq: 3, operationalConsistency: 95, milkingDelayAvg: 4 },
    feedRisk: { level: 'Low', feedAvailability: 95, feedQuantity: 98, feedSupplyGap: 0, supplementAvailability: 'Abundant' },
    vulnerability: { level: 'Low', historicalMilkStability: 'High', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.8 },
    shapContributors: [{ feature: 'High Future THI', impact: -0.42 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 19, humidity: 76, thi: 61 }],
    riskTrend30Days: [{ date: 'May 25', score: 22 }, { date: 'May 31', score: 27 }],
    earlyWarning: { level: 'LOW RISK', timeframe: 'Next 7 days', mainFactor: 'Low Risk', otherFactors: ['High performance'] },
    recommendedActions: [{ action: 'Maintain current feeding schedule', completed: true }],
  },
  {
    id: 'farm-14',
    rank: 14,
    name: 'Ruwan Dairy',
    region: 'Hambantota',
    riskScore: 23,
    riskLevel: 'Low',
    milkLossProb: 4,
    expectedLossRange: '0.1% – 0.8%',
    mainRiskFactor: 'Low Risk',
    mainRiskDesc: 'Stable operational consistency and fodder availability',
    lastUpdated: 'Today, 05:15 AM',
    model: 'XGBoost',
    confidence: 'High',
    climateRisk: { level: 'Low', futureThiMax: 66, forecastTempMax: 28.0, forecastHumidityAvg: 68, rainfall7Days: 10 },
    operationalRisk: { level: 'Low', workerReliability: 98, humanErrorFreq: 2, operationalConsistency: 96, milkingDelayAvg: 3 },
    feedRisk: { level: 'Low', feedAvailability: 96, feedQuantity: 98, feedSupplyGap: 0, supplementAvailability: 'Abundant' },
    vulnerability: { level: 'Low', historicalMilkStability: 'High', diseaseIncidence: 'Low', biologicalVulnerability: 'Low', bodyConditionScore: 3.9 },
    shapContributors: [{ feature: 'Operational Consistency', impact: -0.45 }],
    climateForecast: [{ date: 'May 25, 2026', dayLabel: 'May 25', temp: 27, humidity: 66, thi: 64 }],
    riskTrend30Days: [{ date: 'May 25', score: 20 }, { date: 'May 31', score: 23 }],
    earlyWarning: { level: 'LOW RISK', timeframe: 'Next 7 days', mainFactor: 'Low Risk', otherFactors: ['Zero warnings'] },
    recommendedActions: [{ action: 'No action needed', completed: true }],
  },
];

// Regional Aggregation Data (Sri Lanka Regions covering all 14 farms)
export const REGIONAL_RISKS: RegionalRiskData[] = [
  { region: 'North Western', avgRiskScore: 71, highCritFarmsCount: 3, totalFarmsCount: 4, riskLevel: 'High' },
  { region: 'North Central', avgRiskScore: 68, highCritFarmsCount: 2, totalFarmsCount: 3, riskLevel: 'High' },
  { region: 'Central', avgRiskScore: 55, highCritFarmsCount: 1, totalFarmsCount: 3, riskLevel: 'Medium' },
  { region: 'Uva', avgRiskScore: 48, highCritFarmsCount: 0, totalFarmsCount: 2, riskLevel: 'Medium' },
  { region: 'Sabaragamuwa', avgRiskScore: 46, highCritFarmsCount: 0, totalFarmsCount: 1, riskLevel: 'Medium' },
  { region: 'Western', avgRiskScore: 42, highCritFarmsCount: 0, totalFarmsCount: 2, riskLevel: 'Medium' },
  { region: 'Southern', avgRiskScore: 34, highCritFarmsCount: 0, totalFarmsCount: 2, riskLevel: 'Low' },
  { region: 'Eastern', avgRiskScore: 29, highCritFarmsCount: 0, totalFarmsCount: 1, riskLevel: 'Low' },
];

// National Real-Time Alerts Feed (2026)
export const NATIONAL_ALERTS: NationalAlert[] = [
  {
    id: 'alt-1',
    type: 'critical',
    title: 'High heat stress expected in North Central region',
    subtitle: 'May 27 – May 30, 2026',
    time: '08:30 AM',
    isNew: true,
  },
  {
    id: 'alt-2',
    type: 'critical',
    title: 'Feed availability may drop in 5 farms',
    subtitle: 'Next 5 days',
    time: '08:15 AM',
    isNew: true,
  },
  {
    id: 'alt-3',
    type: 'high',
    title: 'Water availability is low in Uva region',
    subtitle: 'Next 3 days',
    time: '07:45 AM',
    isNew: true,
  },
];
