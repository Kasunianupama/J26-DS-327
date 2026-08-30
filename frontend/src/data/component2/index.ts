/**
 * Component 2 — Predictive Farm Intelligence mock-data layer.
 *
 * All data is fictional synthetic scaffold data. It is not NLDB data, not
 * DelPro data, and does not represent research findings.
 */

export * from './core';
export * from './herd';
export * from './forecast';
export * from './capacity';
export * from './breeding';
export * from './commerce';
export * from './composition';
export * from './budget';
export * from './intelligence';
export * from './outcomes';
export * from './timeline';
export * from './profiles';

/** Farms offered by the persistent farm selector. Only one is populated. */
export const FARMS = [
  { id: 'FARM_01', name: 'Ridiyagama Farm', populated: true },
  { id: 'FARM_02', name: 'Bopaththalawa Farm', populated: false },
  { id: 'FARM_03', name: 'Ambewela Livestock', populated: false },
] as const;
export type FarmId = (typeof FARMS)[number]['id'];
