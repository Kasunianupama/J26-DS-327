/** Component 1 (PFOI): dates, period keys, formatting and the exact Shapley split. */

import type { Grain } from './contract';

/* ---------------- dates (UTC, ISO yyyy-mm-dd) ---------------- */

const DAY_MS = 86_400_000;

export const toDate = (iso: string) => new Date(`${iso}T00:00:00Z`);
export const isoOf = (d: Date) => d.toISOString().slice(0, 10);

export function addDays(iso: string, n: number) {
  return isoOf(new Date(toDate(iso).getTime() + n * DAY_MS));
}

export function daysBetween(a: string, b: string) {
  return Math.round((toDate(b).getTime() - toDate(a).getTime()) / DAY_MS);
}

/** Start of the period that contains `iso`. Weeks start on Monday. */
export function periodStart(iso: string, grain: Grain) {
  if (grain === 'day') return iso;
  if (grain === 'month') return `${iso.slice(0, 7)}-01`;
  const dow = (toDate(iso).getUTCDay() + 6) % 7;
  return addDays(iso, -dow);
}

export function addPeriods(start: string, grain: Grain, n: number) {
  if (grain === 'day') return addDays(start, n);
  if (grain === 'week') return addDays(start, 7 * n);
  const d = toDate(start);
  return isoOf(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1)));
}

export function periodDays(start: string, grain: Grain) {
  return daysBetween(start, addPeriods(start, grain, 1));
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function longDate(iso: string) {
  const d = toDate(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function periodLabel(start: string, grain: Grain, short = false) {
  const d = toDate(start);
  if (grain === 'month') return short ? `${MONTHS[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}` : `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  if (grain === 'week') return short ? `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}` : `Week of ${longDate(start)}`;
  return short ? `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}` : longDate(start);
}

/* ---------------- numbers ---------------- */

export const fmtInt = (n: number) => Math.round(n).toLocaleString('en-GB');
export const fmt1 = (n: number) => (Math.round(n * 10) / 10).toLocaleString('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const fmtSigned = (n: number, dp = 0) => `${n >= 0 ? '+' : '−'}${Math.abs(n).toFixed(dp)}`;
export const fmtPct = (n: number, dp = 1) => `${(n * 100).toFixed(dp)}%`;
export const round = (n: number, dp = 0) => Math.round(n * 10 ** dp) / 10 ** dp;

/* ---------------- deterministic randomness (demo only) ---------------- */

export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function poisson(rand: () => number, lambda: number) {
  const L = Math.exp(-lambda);
  let k = 0;
  let p = 1;
  do { k += 1; p *= rand(); } while (p > L);
  return k - 1;
}

/* ---------------- Shapley ---------------- */

/**
 * Exact Shapley split of f(after) − f(before) across the inputs of `f`.
 * Every subset is evaluated, so the parts always add up to the total change.
 */
export function shapley(f: (x: number[]) => number, before: number[], after: number[]): number[] {
  const n = before.length;
  const fact = [1];
  for (let i = 1; i <= n; i++) fact[i] = fact[i - 1] * i;
  const parts = new Array<number>(n).fill(0);
  for (let mask = 0; mask < 1 << n; mask++) {
    const size = bitCount(mask);
    const x = before.map((b, i) => (mask & (1 << i) ? after[i] : b));
    const base = f(x);
    for (let i = 0; i < n; i++) {
      if (mask & (1 << i)) continue;
      const withI = [...x];
      withI[i] = after[i];
      const weight = (fact[size] * fact[n - size - 1]) / fact[n];
      parts[i] += weight * (f(withI) - base);
    }
  }
  return parts;
}

function bitCount(m: number) {
  let c = 0;
  while (m) { c += m & 1; m >>= 1; }
  return c;
}
