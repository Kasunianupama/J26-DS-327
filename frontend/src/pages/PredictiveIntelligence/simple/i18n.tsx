/**
 * Simple view: English / Sinhala. English text is the key; the Sinhala table
 * (si.ts) gives the translation, and anything missing falls back to English.
 * `{name}` marks a value to fill in, and `**text**` marks bold in <Rich>.
 * The choice is remembered in this browser only.
 */

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { Grain } from '../../../data/pfoi';
import { SI } from './si';

export type Lang = 'en' | 'si';
type Vars = Record<string, string | number>;
export type T = (key: string, vars?: Vars) => string;

const KEY = 'pfoi.lang';
const Ctx = createContext<{ lang: Lang; setLang: (l: Lang) => void } | undefined>(undefined);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, set] = useState<Lang>(() => {
    try { return window.localStorage.getItem(KEY) === 'si' ? 'si' : 'en'; } catch { return 'en'; }
  });
  const setLang = (l: Lang) => {
    set(l);
    try { window.localStorage.setItem(KEY, l); } catch { /* not remembered */ }
  };
  return <Ctx.Provider value={{ lang, setLang }}>{children}</Ctx.Provider>;
}

export function useLang() {
  const c = useContext(Ctx);
  return c ?? { lang: 'en' as Lang, setLang: () => undefined };
}

export function makeT(lang: Lang): T {
  return (key, vars) => {
    const s = lang === 'si' ? SI[key] ?? key : key;
    return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
  };
}

export function useT(): T {
  const { lang } = useLang();
  return useMemo(() => makeT(lang), [lang]);
}

/** Renders `**bold**` parts of a translated sentence. */
export function Rich({ text }: { text: string }) {
  const parts = text.split('**');
  return <>{parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : <span key={i}>{p}</span>))}</>;
}

/* ------------------------------------------------------------------ dates */

const EN_M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const SI_M = ['ජනවාරි', 'පෙබරවාරි', 'මාර්තු', 'අප්‍රේල්', 'මැයි', 'ජූනි', 'ජූලි', 'අගෝස්තු', 'සැප්තැම්බර්', 'ඔක්තෝබර්', 'නොවැම්බර්', 'දෙසැම්බර්'];
const parts = (iso: string) => ({ y: Number(iso.slice(0, 4)), m: Number(iso.slice(5, 7)) - 1, d: Number(iso.slice(8, 10)) });

/** "1 Jun 2019" / "2019 ජූනි 1". */
export function dateLabel(iso: string, lang: Lang) {
  const { y, m, d } = parts(iso);
  return lang === 'si' ? `${y} ${SI_M[m]} ${d}` : `${d} ${EN_M[m]} ${y}`;
}

/** A period at its grain: "Jun 2024", "Week of 3 Jun 2024", "3 Jun 2024"; `short` for chart axes. */
export function periodText(iso: string, grain: Grain, lang: Lang, short = false) {
  const { y, m, d } = parts(iso);
  const M = lang === 'si' ? SI_M : EN_M;
  if (grain === 'month') {
    if (short) return lang === 'si' ? `${M[m].slice(0, 3)} ${String(y).slice(2)}` : `${M[m]} ${String(y).slice(2)}`;
    return lang === 'si' ? `${y} ${M[m]}` : `${M[m]} ${y}`;
  }
  if (short) return lang === 'si' ? `${M[m].slice(0, 3)} ${d}` : `${d} ${M[m]}`;
  const day = dateLabel(iso, lang);
  return grain === 'week' ? (lang === 'si' ? `${day} සතිය` : `Week of ${day}`) : day;
}

/** Look-ahead button text for a grain and number of steps. */
export function aheadText(t: T, grain: Grain, h: number) {
  if (h === 1) return t(grain === 'month' ? 'Next month' : grain === 'week' ? 'Next week' : 'Tomorrow');
  return t(grain === 'month' ? 'Next {n} months' : grain === 'week' ? 'Next {n} weeks' : 'Next {n} days', { n: h });
}

/** "per month" / "per week" / "per day". */
export const perGrain = (t: T, grain: Grain) => t(grain === 'month' ? 'per month' : grain === 'week' ? 'per week' : 'per day');
