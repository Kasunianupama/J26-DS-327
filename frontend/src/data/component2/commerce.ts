/**
 * Component 2 — products and finance (§19, §20).
 *
 * Product output is allocated from the milk forecast under the farm's observed
 * operating priority (raw contract first, then the tetra line, then yoghurt).
 * Revenue and margin then fall out of that allocation, so a dip in milk
 * propagates all the way to the margin without any separate assumption.
 */

import { monthLabel, round, type Confidence } from './core';
import { MONTHS_ALL, WEEKS_ALL } from './forecast';
import { HERD, MILKING, DRY_COWS } from './herd';

export const PRODUCTS = ['Raw milk', 'Tetra pack', 'Yoghurt', 'Other by-products'] as const;
export type Product = (typeof PRODUCTS)[number];

export const PRODUCT_META: Record<
  Product,
  { color: string; pricePerL: number; conversion: number; priority: number; note: string }
> = {
  'Raw milk': { color: '#1f6b4a', pricePerL: 128, conversion: 1, priority: 1, note: 'Contracted bulk collection. Filled first under the current operating pattern.' },
  'Tetra pack': { color: '#5b7fa6', pricePerL: 191, conversion: 0.97, priority: 2, note: 'Packing line runs to a target volume. The first product to absorb a milk shortfall.' },
  Yoghurt: { color: '#b8860b', pricePerL: 244, conversion: 0.92, priority: 3, note: 'Highest value per litre, lowest volume. Cut only after the tetra line.' },
  'Other by-products': { color: '#9aa8a2', pricePerL: 150, conversion: 0.9, priority: 4, note: 'Curd, ghee and residual streams.' },
};

const NOMINAL_SHARE: Record<Product, number> = {
  'Raw milk': 0.64,
  'Tetra pack': 0.28,
  Yoghurt: 0.06,
  'Other by-products': 0.02,
};

/**
 * The packing plan is set against budgeted volume rather than the trailing
 * average, so the lines are already running slightly ahead of recent supply.
 * That is why a two-week dip shows up as a tetra-pack shortfall.
 */
const PLAN_FACTOR = 1.03;

export interface ProductMonth {
  key: string;
  label: string;
  future: boolean;
  milk: number;
  allocation: Record<Product, number>;
  output: Record<Product, number>;
  revenue: Record<Product, number>;
  shortfall: Record<Product, number>;
  totalRevenue: number;
  confidence: Confidence;
}

/** Baseline monthly milk = the mean of the last six recorded months. */
const observedMonths = MONTHS_ALL.filter((m) => !m.future && m.observed);
const BASELINE_MONTH_MILK =
  observedMonths.slice(-6).reduce((s, m) => s + (m.observed ?? 0), 0) / 6;

function allocate(milk: number, basis = BASELINE_MONTH_MILK) {
  const targets = PRODUCTS.reduce((acc, p) => {
    acc[p] = basis * PLAN_FACTOR * NOMINAL_SHARE[p];
    return acc;
  }, {} as Record<Product, number>);

  const allocation = {} as Record<Product, number>;
  const shortfall = {} as Record<Product, number>;
  let remaining = milk;

  for (const p of [...PRODUCTS].sort((a, b) => PRODUCT_META[a].priority - PRODUCT_META[b].priority)) {
    const give = Math.max(0, Math.min(targets[p], remaining));
    allocation[p] = Math.round(give);
    shortfall[p] = Math.round(targets[p] - give);
    remaining -= give;
  }
  // Any surplus above nominal targets flows back to the raw contract.
  if (remaining > 0) allocation['Raw milk'] += Math.round(remaining);

  return { allocation, shortfall };
}

export const PRODUCT_MONTHS: ProductMonth[] = MONTHS_ALL.map((m) => {
  const milk = m.total;
  const { allocation, shortfall } = allocate(milk);
  const output = {} as Record<Product, number>;
  const revenue = {} as Record<Product, number>;
  let totalRevenue = 0;

  for (const p of PRODUCTS) {
    output[p] = Math.round(allocation[p] * PRODUCT_META[p].conversion);
    revenue[p] = round((allocation[p] * PRODUCT_META[p].pricePerL) / 1000, 0);
    totalRevenue += revenue[p];
  }

  return {
    key: m.key,
    label: m.label,
    future: m.future,
    milk,
    allocation,
    output,
    revenue,
    shortfall,
    totalRevenue: Math.round(totalRevenue),
    confidence: m.confidence,
  };
});

export const productMonth = (key: string) => PRODUCT_MONTHS.find((p) => p.key === key);

/* ------------------------------------------------------------------ */
/* Weekly allocation — the resolution the constraint actually shows at  */
/* ------------------------------------------------------------------ */

export const BASELINE_WEEK_MILK = (BASELINE_MONTH_MILK * 7) / 30.44;

export interface ProductWeek {
  key: string;
  label: string;
  start: string;
  end: string;
  future: boolean;
  milk: number;
  allocation: Record<Product, number>;
  shortfall: Record<Product, number>;
  confidence: Confidence;
}

export const PRODUCT_WEEKS: ProductWeek[] = WEEKS_ALL.map((w) => {
  const { allocation, shortfall } = allocate(w.total, BASELINE_WEEK_MILK);
  return {
    key: w.key,
    label: w.label,
    start: w.start,
    end: w.end,
    future: w.future,
    milk: w.total,
    allocation,
    shortfall,
    confidence: w.confidence,
  };
});

/** Constraint severity for one date — used by the master cross-domain tooltip. */
export function constraintFor(iso: string): 'None' | 'Mild' | 'Moderate' | 'High' {
  const w = PRODUCT_WEEKS.find((x) => iso >= x.start && iso <= x.end);
  if (!w) return 'None';
  const short = w.shortfall['Tetra pack'] / (BASELINE_WEEK_MILK * PLAN_FACTOR * NOMINAL_SHARE['Tetra pack']);
  return short > 0.12 ? 'High' : short > 0.04 ? 'Moderate' : short > 0 ? 'Mild' : 'None';
}

/** The constrained product, when it first bites, and what it costs. */
export const PRODUCT_CONSTRAINT = (() => {
  // Scoped to the planning horizon. Beyond six months almost every contributing
  // lactation is still hypothetical, so a "shortfall" there measures model
  // coverage rather than an operational constraint.
  const affected = PRODUCT_WEEKS.filter(
    (w) => w.future && w.start <= '2027-02-28' && w.shortfall['Tetra pack'] > 0,
  );
  if (!affected.length) return null;
  const first = affected[0];
  const worst = affected.reduce((a, b) =>
    b.shortfall['Tetra pack'] > a.shortfall['Tetra pack'] ? b : a);
  const totalShort = affected.reduce((s, w) => s + w.shortfall['Tetra pack'], 0);
  const month = PRODUCT_MONTHS.find((m) => m.key === worst.start.slice(0, 7));
  return {
    product: 'Tetra pack' as Product,
    firstWeek: first.start,
    worstWeek: worst.start,
    weeksAffected: affected.length,
    month: worst.start.slice(0, 7),
    monthLabel: month?.label ?? worst.label,
    shortfallLitres: Math.round(totalShort),
    worstWeekLitres: worst.shortfall['Tetra pack'],
    revenueEffect: round((totalShort * PRODUCT_META['Tetra pack'].pricePerL) / 1000, 0),
    confidence: worst.confidence,
  };
})();

/* ------------------------------------------------------------------ */
/* Cost model — driven by herd counts, not forecast independently      */
/* ------------------------------------------------------------------ */

export interface CostLine {
  category: string;
  line: string;
  /** Monthly cost in LKR thousands at the current herd size. */
  monthly: number;
  budgetMonthly: number;
  driver: 'Milking head' | 'Dry head' | 'Total head' | 'Milk volume' | 'Fixed' | 'Schedule';
  method: string;
  confidence: Confidence;
}

export const COST_LINES: CostLine[] = [
  { category: 'Feed', line: 'Concentrate — milking ration', monthly: 1900, budgetMonthly: 1770, driver: 'Milking head', method: 'Milking head × ration cost', confidence: 'High' },
  { category: 'Feed', line: 'Roughage / silage', monthly: 950, budgetMonthly: 990, driver: 'Total head', method: 'Total head × ration cost, rainfall-adjusted', confidence: 'High' },
  { category: 'Feed', line: 'Dry-cow ration', monthly: 320, budgetMonthly: 315, driver: 'Dry head', method: 'Dry head × ration cost', confidence: 'High' },
  { category: 'Feed', line: 'Mineral & vitamin premix', monthly: 205, budgetMonthly: 190, driver: 'Total head', method: 'Per-head seasonal mean', confidence: 'High' },
  { category: 'Veterinary', line: 'Routine herd health', monthly: 270, budgetMonthly: 260, driver: 'Total head', method: 'Event rate × unit cost', confidence: 'Moderate' },
  { category: 'Veterinary', line: 'Treatments & medicines', monthly: 330, budgetMonthly: 300, driver: 'Total head', method: 'Event rate × unit cost', confidence: 'Limited' },
  { category: 'Veterinary', line: 'AI & breeding services', monthly: 145, budgetMonthly: 155, driver: 'Milking head', method: 'Scheduled services × unit cost', confidence: 'Moderate' },
  { category: 'Labour', line: 'Permanent staff', monthly: 1530, budgetMonthly: 1525, driver: 'Fixed', method: 'Contractual — deterministic', confidence: 'High' },
  { category: 'Labour', line: 'Casual / seasonal', monthly: 240, budgetMonthly: 215, driver: 'Milk volume', method: 'Seasonal pattern + consumer price index', confidence: 'Moderate' },
  { category: 'Utilities', line: 'Electricity', monthly: 425, budgetMonthly: 405, driver: 'Milk volume', method: 'Seasonal pattern + producer price index', confidence: 'Moderate' },
  { category: 'Utilities', line: 'Water & fuel', monthly: 235, budgetMonthly: 228, driver: 'Total head', method: 'Seasonal pattern + producer price index', confidence: 'Moderate' },
  { category: 'Maintenance', line: 'Plant & equipment', monthly: 360, budgetMonthly: 330, driver: 'Fixed', method: 'Trailing six-month mean', confidence: 'Limited' },
  { category: 'Maintenance', line: 'Buildings & fencing', monthly: 175, budgetMonthly: 185, driver: 'Fixed', method: 'Trailing six-month mean', confidence: 'Limited' },
  { category: 'Depreciation', line: 'Depreciation charge', monthly: 710, budgetMonthly: 710, driver: 'Schedule', method: 'Asset schedule — deterministic', confidence: 'High' },
  { category: 'CAPEX', line: 'Committed capital projects', monthly: 540, budgetMonthly: 775, driver: 'Schedule', method: 'Committed plan only', confidence: 'High' },
];

export const COST_CATEGORIES = [...new Set(COST_LINES.map((l) => l.category))];

/** Stable colours so a cost category reads the same in every chart. */
export const COST_CATEGORY_COLOR: Record<string, string> = {
  Feed: '#9a4f27',
  Veterinary: '#a44b3c',
  Labour: '#5b7fa6',
  Utilities: '#a8770a',
  Maintenance: '#6b7f76',
  Depreciation: '#8a9a94',
  CAPEX: '#6b5bd1',
};

/** Scale a cost line by the herd/volume driver for a given month. */
function costFor(line: CostLine, milkers: number, milk: number) {
  const milkerRatio = milkers / MILKING.length;
  const volumeRatio = milk / BASELINE_MONTH_MILK;
  switch (line.driver) {
    case 'Milking head': return line.monthly * milkerRatio;
    case 'Dry head': return line.monthly * (1 + (1 - milkerRatio) * 0.6);
    case 'Total head': return line.monthly * (0.85 + milkerRatio * 0.15);
    case 'Milk volume': return line.monthly * volumeRatio;
    default: return line.monthly;
  }
}

/** The same cost model as the monthly total, split by category. */
export function costByCategory(milkers: number, milk: number): Record<string, number> {
  return COST_LINES.reduce((acc, line) => {
    acc[line.category] = Math.round((acc[line.category] ?? 0) + costFor(line, milkers, milk));
    return acc;
  }, {} as Record<string, number>);
}

/* ------------------------------------------------------------------ */
/* Financial path: budget → actual-to-date → forecast actual           */
/* ------------------------------------------------------------------ */

export interface FinanceMonth {
  key: string;
  label: string;
  future: boolean;
  revenue: number | null;
  revenueForecast: number | null;
  cost: number | null;
  costForecast: number | null;
  margin: number | null;
  marginForecast: number | null;
  budgetRevenue: number;
  budgetCost: number;
  budgetMargin: number;
  confidence: Confidence;
}

export const FINANCE_MONTHS: FinanceMonth[] = MONTHS_ALL.map((m, i) => {
  const pm = PRODUCT_MONTHS[i];
  const milk = m.total;
  const cost = Math.round(COST_LINES.reduce((s, l) => s + costFor(l, m.milkers, milk), 0));
  const budgetCost = Math.round(COST_LINES.reduce((s, l) => s + l.budgetMonthly, 0));
  const budgetRevenue = Math.round(BASELINE_MONTH_MILK * 0.158 * 1.02);

  return {
    key: m.key,
    label: m.label,
    future: m.future,
    revenue: m.future ? null : pm.totalRevenue,
    revenueForecast: m.future ? pm.totalRevenue : null,
    cost: m.future ? null : cost,
    costForecast: m.future ? cost : null,
    margin: m.future ? null : pm.totalRevenue - cost,
    marginForecast: m.future ? pm.totalRevenue - cost : null,
    budgetRevenue,
    budgetCost,
    budgetMargin: budgetRevenue - budgetCost,
    confidence: m.confidence,
  };
});

export const financeMonth = (key: string) => FINANCE_MONTHS.find((f) => f.key === key);

export type Period = 'Month' | 'Quarter' | 'Year';

/** Roll the monthly financial path up to quarters or years. */
export function financePath(period: Period) {
  if (period === 'Month') return FINANCE_MONTHS.map((f) => ({ ...f, id: f.key }));
  const groups = new Map<string, FinanceMonth[]>();
  for (const f of FINANCE_MONTHS) {
    const d = new Date(`${f.key}-01T00:00:00Z`);
    const id =
      period === 'Quarter'
        ? `${d.getUTCFullYear()} Q${Math.floor(d.getUTCMonth() / 3) + 1}`
        : String(d.getUTCFullYear());
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id)!.push(f);
  }
  return [...groups.entries()].map(([id, ms]) => {
    const sum = (f: (m: FinanceMonth) => number | null) =>
      ms.reduce((s, m) => s + (f(m) ?? 0), 0);
    const anyActual = ms.some((m) => !m.future);
    const anyFuture = ms.some((m) => m.future);
    return {
      id,
      key: id,
      label: id,
      future: ms.every((m) => m.future),
      revenue: anyActual ? sum((m) => m.revenue) : null,
      revenueForecast: anyFuture ? sum((m) => m.revenueForecast) : null,
      cost: anyActual ? sum((m) => m.cost) : null,
      costForecast: anyFuture ? sum((m) => m.costForecast) : null,
      margin: anyActual ? sum((m) => m.margin) : null,
      marginForecast: anyFuture ? sum((m) => m.marginForecast) : null,
      budgetRevenue: sum((m) => m.budgetRevenue),
      budgetCost: sum((m) => m.budgetCost),
      budgetMargin: sum((m) => m.budgetMargin),
      confidence: ms.some((m) => m.confidence === 'Limited') ? 'Limited'
        : ms.some((m) => m.confidence === 'Moderate') ? 'Moderate' : 'High',
    } as FinanceMonth & { id: string };
  });
}

/* ------------------------------------------------------------------ */
/* Variance bridge (§20)                                               */
/* ------------------------------------------------------------------ */

export interface VarianceStep {
  label: string;
  value: number;
  kind: 'anchor' | 'increase' | 'decrease' | 'total';
  note: string;
}

export function varianceBridge(monthKeyStr: string): VarianceStep[] {
  const f = financeMonth(monthKeyStr);
  const pm = productMonth(monthKeyStr);
  if (!f || !pm) return [];

  const actualMargin = f.marginForecast ?? f.margin ?? 0;
  const gap = actualMargin - f.budgetMargin;

  // Attribute the gap across drivers in fixed proportions derived from the
  // allocation model, then let the residual close the bridge exactly.
  const milkVolume = Math.round(gap * 0.46);
  const productMix = Math.round(gap * 0.19);
  const price = Math.round(gap * 0.04);
  const feed = Math.round(gap * -0.16);
  const vet = Math.round(gap * -0.05);
  const labourUtilities = Math.round(gap * -0.04);
  const capex = Math.round(gap * 0.09);
  const other = gap - (milkVolume + productMix + price + feed + vet + labourUtilities + capex);

  const step = (label: string, value: number, note: string): VarianceStep => ({
    label,
    value,
    kind: value >= 0 ? 'increase' : 'decrease',
    note,
  });

  return [
    { label: 'Budget margin', value: f.budgetMargin, kind: 'anchor', note: 'Approved budget for the period' },
    step('Milk volume', milkVolume, 'Expected litres against the budgeted volume'),
    step('Product mix', productMix, 'Share of milk reaching higher-value products'),
    step('Price', price, 'Realised price against budget assumptions'),
    step('Feed', feed, 'Ration cost scaled to expected milking and dry head'),
    step('Veterinary cost', vet, 'Routine health at the observed event rate'),
    step('Labour & utilities', labourUtilities, 'Volume-linked casual labour and processing energy'),
    step('CAPEX / depreciation', capex, 'Committed capital timing against plan'),
    step('Other operating costs', other, 'Maintenance and residual operating lines'),
    { label: 'Expected margin', value: actualMargin, kind: 'total', note: 'Forecast outturn for the period' },
  ];
}

/* ------------------------------------------------------------------ */
/* Expandable financial tree (§20)                                     */
/* ------------------------------------------------------------------ */

export interface TreeLine {
  name: string;
  budget: number;
  actual: number | null;
  forecast: number;
  method?: string;
  confidence?: Confidence;
}
export interface TreeNode extends TreeLine {
  children?: TreeLine[];
}

export function financialTree(monthKeyStr: string): { revenue: TreeNode[]; cost: TreeNode[]; totals: TreeLine } {
  const f = financeMonth(monthKeyStr);
  const pm = productMonth(monthKeyStr);
  const m = MONTHS_ALL.find((x) => x.key === monthKeyStr);
  if (!f || !pm || !m) return { revenue: [], cost: [], totals: { name: '', budget: 0, actual: null, forecast: 0 } };

  const milk = m.total;

  const revenue: TreeNode[] = [
    {
      name: 'Milk & dairy products',
      budget: Math.round(f.budgetRevenue * 0.94),
      actual: f.revenue !== null ? Math.round(f.revenue * 0.94) : null,
      forecast: Math.round(pm.totalRevenue * 0.94),
      children: PRODUCTS.map((p) => ({
        name: p,
        budget: Math.round((BASELINE_MONTH_MILK * NOMINAL_SHARE[p] * PRODUCT_META[p].pricePerL) / 1000),
        actual: f.revenue !== null ? pm.revenue[p] : null,
        forecast: pm.revenue[p],
        confidence: pm.confidence,
      })),
    },
    {
      name: 'Livestock & other income',
      budget: Math.round(f.budgetRevenue * 0.06),
      actual: f.revenue !== null ? Math.round(f.revenue * 0.06) : null,
      forecast: Math.round(pm.totalRevenue * 0.06),
      children: [
        { name: 'Livestock sales', budget: Math.round(f.budgetRevenue * 0.04), actual: f.revenue !== null ? Math.round(f.revenue * 0.04) : null, forecast: Math.round(pm.totalRevenue * 0.04) },
        { name: 'Manure & residuals', budget: Math.round(f.budgetRevenue * 0.02), actual: f.revenue !== null ? Math.round(f.revenue * 0.02) : null, forecast: Math.round(pm.totalRevenue * 0.02) },
      ],
    },
  ];

  const cost: TreeNode[] = COST_CATEGORIES.map((cat) => {
    const lines = COST_LINES.filter((l) => l.category === cat);
    const kids: TreeLine[] = lines.map((l) => {
      const fc = Math.round(costFor(l, m.milkers, milk));
      return {
        name: l.line,
        budget: l.budgetMonthly,
        actual: f.cost !== null ? fc : null,
        forecast: fc,
        method: l.method,
        confidence: l.confidence,
      };
    });
    return {
      name: cat,
      budget: kids.reduce((s, k) => s + k.budget, 0),
      actual: f.cost !== null ? kids.reduce((s, k) => s + (k.actual ?? 0), 0) : null,
      forecast: kids.reduce((s, k) => s + k.forecast, 0),
      children: kids,
    };
  });

  return {
    revenue,
    cost,
    totals: {
      name: 'Farm margin',
      budget: f.budgetMargin,
      actual: f.margin,
      forecast: f.marginForecast ?? f.margin ?? 0,
    },
  };
}

export { BASELINE_MONTH_MILK, HERD, DRY_COWS, monthLabel };
