import type { C1Forecast } from './member4Api';
export function futureOutlook(rows: C1Forecast[], startDate: string, horizon: number, now?: Date): {
  available: boolean; reason: string; dates: string[]; rows: C1Forecast[];
  origin: string | null; intervalAvailable: boolean;
};
