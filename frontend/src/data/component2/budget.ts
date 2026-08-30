/**
 * Component 2 — the deep budget hierarchy (§20).
 *
 * Three levels — category → subcategory → line item — with budget, actual,
 * variance and pace. Every parent is the sum of its children, computed rather
 * than typed, so the tree can never disagree with itself.
 */

import { round, type Confidence } from './core';

export interface BudgetLeaf {
  name: string;
  budget: number; // Rs. millions
  actual: number;
  method: string;
  confidence: Confidence;
  driver: string;
}
export interface BudgetNode {
  name: string;
  color?: string;
  children: (BudgetNode | BudgetLeaf)[];
}
export const isLeaf = (n: BudgetNode | BudgetLeaf): n is BudgetLeaf =>
  !(n as BudgetNode).children;

const L = (
  name: string,
  budget: number,
  actual: number,
  driver: string,
  method: string,
  confidence: Confidence = 'Moderate',
): BudgetLeaf => ({ name, budget, actual, method, confidence, driver });

export const BUDGET_TREE: BudgetNode[] = [
  {
    name: 'Feed & fodder',
    color: '#c2703d',
    children: [
      {
        name: 'Concentrate',
        children: [
          L('Maize', 9.8, 11.4, 'Milking head', 'Head × inclusion rate × contract price', 'High'),
          L('Soya meal', 7.2, 8.1, 'Milking head', 'Head × inclusion rate × contract price', 'High'),
          L('Mineral premix', 2.9, 3.0, 'Total head', 'Per-head seasonal mean', 'High'),
          L('Molasses', 2.5, 2.6, 'Milking head', 'Head × inclusion rate', 'High'),
        ],
      },
      {
        name: 'Roughage & silage',
        children: [
          L('Maize silage', 6.4, 6.7, 'Total head', 'Total head × ration, rainfall-adjusted', 'High'),
          L('Napier & green chop', 3.9, 4.1, 'Total head', 'Total head × ration, rainfall-adjusted', 'Moderate'),
          L('Straw & dry roughage', 2.3, 2.4, 'Total head', 'Total head × ration', 'High'),
        ],
      },
      {
        name: 'Dry-cow & calf rations',
        children: [
          L('Dry-cow ration', 3.1, 3.2, 'Dry head', 'Dry head × ration cost', 'High'),
          L('Calf starter & milk replacer', 2.5, 2.4, 'Calf head', 'Calf head × programme cost', 'Moderate'),
        ],
      },
    ],
  },
  {
    name: 'Labour',
    color: '#6b5bd1',
    children: [
      {
        name: 'Permanent staff',
        children: [
          L('Parlour & herd staff', 9.8, 9.9, 'Fixed', 'Contractual — deterministic', 'High'),
          L('Field & fodder staff', 4.1, 4.2, 'Fixed', 'Contractual — deterministic', 'High'),
          L('Supervision & admin', 2.6, 2.6, 'Fixed', 'Contractual — deterministic', 'High'),
        ],
      },
      {
        name: 'Casual & seasonal',
        children: [
          L('Harvest casuals', 1.4, 1.6, 'Milk volume', 'Seasonal pattern + consumer price index', 'Moderate'),
          L('Relief milking', 0.7, 0.8, 'Milking head', 'Seasonal pattern', 'Moderate'),
        ],
      },
    ],
  },
  {
    name: 'Veterinary & breeding',
    color: '#c0392b',
    children: [
      {
        name: 'Herd health',
        children: [
          L('Routine health & vaccination', 2.5, 2.6, 'Total head', 'Event rate × unit cost', 'Moderate'),
          L('Treatments & medicines', 2.9, 3.3, 'Total head', 'Event rate × unit cost', 'Limited'),
          L('Diagnostics & laboratory', 0.8, 0.9, 'Total head', 'Event rate × unit cost', 'Limited'),
        ],
      },
      {
        name: 'Breeding',
        children: [
          L('Semen & AI consumables', 1.5, 1.4, 'Services', 'Scheduled services × unit cost', 'Moderate'),
          L('Technician services', 0.6, 0.6, 'Services', 'Scheduled services × unit cost', 'Moderate'),
        ],
      },
    ],
  },
  {
    name: 'Energy & utilities',
    color: '#e0a11b',
    children: [
      {
        name: 'Electricity',
        children: [
          L('Parlour & cooling', 4.2, 4.6, 'Milk volume', 'Seasonal pattern + producer price index', 'Moderate'),
          L('Sheds & lighting', 1.5, 1.5, 'Total head', 'Seasonal pattern', 'Moderate'),
        ],
      },
      {
        name: 'Water & fuel',
        children: [
          L('Water', 1.1, 1.1, 'Total head', 'Seasonal pattern', 'Moderate'),
          L('Diesel & tractor fuel', 2.2, 2.4, 'Fixed', 'Seasonal pattern + producer price index', 'Moderate'),
        ],
      },
    ],
  },
  {
    name: 'Maintenance & repair',
    color: '#159c72',
    children: [
      {
        name: 'Plant & equipment',
        children: [
          L('Milking plant', 2.1, 2.3, 'Fixed', 'Trailing six-month mean', 'Limited'),
          L('Cooling & bulk tank', 1.2, 1.5, 'Fixed', 'Trailing six-month mean', 'Limited'),
          L('Vehicles & tractors', 1.4, 1.4, 'Fixed', 'Trailing six-month mean', 'Limited'),
        ],
      },
      {
        name: 'Buildings & land',
        children: [
          L('Sheds & flooring', 1.3, 1.2, 'Fixed', 'Trailing six-month mean', 'Limited'),
          L('Fencing & yards', 0.6, 0.6, 'Fixed', 'Trailing six-month mean', 'Limited'),
        ],
      },
    ],
  },
  {
    name: 'Resilience reserve',
    color: '#8a9a94',
    children: [
      {
        name: 'Contingency',
        children: [
          L('Unallocated contingency', 1.4, 0.7, 'Fixed', 'Committed plan only', 'High'),
          L('Feed price buffer', 0.6, 0.4, 'Fixed', 'Committed plan only', 'High'),
        ],
      },
    ],
  },
];

/* ------------------------------------------------------------------ */
/* Roll-ups                                                            */
/* ------------------------------------------------------------------ */

export interface Rolled {
  name: string;
  color?: string;
  budget: number;
  actual: number;
  variance: number;
  variancePct: number;
  /** Share of budget consumed, against share of period elapsed. */
  pace: number;
  /** Expected total spend by period end, using the observed run-rate. */
  forecast: number;
  /** Forecast still to be spent after the actuals recorded to date. */
  remaining: number;
  children?: Rolled[];
  leaf?: BudgetLeaf;
}

/** Fraction of the financial period elapsed — the pace reference line. */
export const PERIOD_ELAPSED = 0.8;

function roll(node: BudgetNode | BudgetLeaf, color?: string): Rolled {
  if (isLeaf(node)) {
    const variance = node.actual - node.budget;
    return {
      name: node.name,
      color,
      budget: round(node.budget, 2),
      actual: round(node.actual, 2),
      variance: round(variance, 2),
      variancePct: round((variance / Math.max(0.01, node.budget)) * 100, 1),
      pace: node.actual / Math.max(0.01, node.budget),
      forecast: round(node.actual / PERIOD_ELAPSED, 2),
      remaining: round(Math.max(0, node.actual / PERIOD_ELAPSED - node.actual), 2),
      leaf: node,
    };
  }
  const kids = node.children.map((c) => roll(c, color ?? node.color));
  const budget = round(kids.reduce((s, k) => s + k.budget, 0), 2);
  const actual = round(kids.reduce((s, k) => s + k.actual, 0), 2);
  const variance = round(actual - budget, 2);
  return {
    name: node.name,
    color: node.color ?? color,
    budget,
    actual,
    variance,
    variancePct: round((variance / Math.max(0.01, budget)) * 100, 1),
    pace: actual / Math.max(0.01, budget),
    forecast: round(actual / PERIOD_ELAPSED, 2),
    remaining: round(Math.max(0, actual / PERIOD_ELAPSED - actual), 2),
    children: kids,
  };
}

export const BUDGET = BUDGET_TREE.map((n) => roll(n));

export const BUDGET_TOTAL = {
  budget: round(BUDGET.reduce((s, b) => s + b.budget, 0), 2),
  actual: round(BUDGET.reduce((s, b) => s + b.actual, 0), 2),
  forecast: round(BUDGET.reduce((s, b) => s + b.forecast, 0), 2),
  remaining: round(BUDGET.reduce((s, b) => s + b.remaining, 0), 2),
  variance: round(BUDGET.reduce((s, b) => s + b.variance, 0), 2),
  get variancePct() {
    return round((this.variance / this.budget) * 100, 1);
  },
};

/** Donut slices — share of actual spend by category. */
export const BUDGET_SHARES = BUDGET.map((b) => ({
  name: b.name,
  color: b.color!,
  actual: b.actual,
  share: round((b.actual / BUDGET_TOTAL.actual) * 100, 0),
})).sort((a, b) => b.actual - a.actual);

/** The lines pulling hardest against budget, for the callout strip. */
export const BUDGET_PRESSURE = (() => {
  const leaves: Rolled[] = [];
  const walk = (n: Rolled) => (n.children ? n.children.forEach(walk) : leaves.push(n));
  BUDGET.forEach(walk);
  return leaves.sort((a, b) => b.variance - a.variance).slice(0, 5);
})();
