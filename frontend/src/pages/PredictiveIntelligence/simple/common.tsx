/**
 * Component 1 (PFOI): shared pieces of the simple view.
 *
 * Plain words for the model's labels (English keys, translated by useT),
 * rounding rules, the tab navigation, and small layout pieces.
 */

import { createContext, useContext, useState, type ReactNode } from 'react';
import { addPeriods, fmtInt, type Confidence, type EvidenceStatus, type Grain, type MilkFactor, type PfoiRun } from '../../../data/pfoi';
import { useT } from './i18n';

/** Milk to the nearest 10 litres; cows and events to whole numbers. */
export const litres = (n: number) => fmtInt(Math.round(n / 10) * 10);
export const whole = (n: number) => fmtInt(n);
/** Small counts: "3", "<1". */
export const about = (n: number) => (n > 0 && n < 0.5 ? '<1' : fmtInt(n));
export const pct = (share: number) => `${Math.round(share * 100)}%`;
/** A range is worth showing only when it has some width. */
export const hasRange = (lo: number | null | undefined, hi: number | null | undefined) =>
  lo != null && hi != null && Math.abs(hi - lo) >= 0.5;

/** How much history the simple charts show at each grain. */
export const HISTORY: Record<Grain, number> = { day: 60, week: 26, month: 12 };
/** The same period a year earlier. */
export const yearBefore = (p: string, grain: Grain) => addPeriods(p, grain, grain === 'month' ? -12 : grain === 'week' ? -52 : -364);

export const PLAIN_CONFIDENCE: Record<Confidence, { label: string; dots: string; help: string }> = {
  High: { label: 'Reliable', dots: '●●●', help: 'Good records and a short look ahead.' },
  Moderate: { label: 'Fairly reliable', dots: '●●○', help: 'Some records are missing or the look ahead is longer.' },
  Limited: { label: 'Rough guide only', dots: '●○○', help: 'Few records or a long look ahead. Use the likely range.' },
};

/** What pulls milk down, in farm words. */
export const PLAIN_PULL: Record<MilkFactor, string> = {
  herd_size: 'fewer cows in milk',
  stage_mix: 'more cows late in their lactation',
  parity_mix: 'more first-lactation cows',
  pregnancy_mix: 'more cows late in pregnancy',
  yield_level: 'lower yield per cow',
  thi: 'heat stress',
  mastitis: 'mastitis',
  residual: 'other causes',
};

export const PLAIN_SERIES: Record<string, string> = {
  milk_litres: 'Milk (litres a day)',
  milking: 'Cows in milk',
  dry: 'Dry cows',
  heifers: 'Heifers',
  calves: 'Calves',
  other: 'Bulls and other animals',
  total_herd: 'Whole herd',
  calvings: 'Calvings',
  dry_offs: 'Cows dried off',
  abortions: 'Pregnancies lost',
  deaths: 'Deaths',
  culls_sales: 'Culled or sold',
  entries: 'Born or bought in',
  mastitis_episodes: 'Mastitis cases',
};

export const PLAIN_STATUS: Record<EvidenceStatus, { label: string; tone: 'ok' | 'caution' | 'muted' | 'concern' }> = {
  development: { label: 'Tested', tone: 'ok' },
  'post-test development': { label: 'Tested on years already looked at', tone: 'caution' },
  'not interpretable': { label: 'Too few cases to say', tone: 'muted' },
  oracle: { label: 'Best case only, not usable', tone: 'concern' },
  'implemented, not yet evaluated': { label: 'Not tested yet', tone: 'muted' },
  'cannot be validated with current data': { label: 'Cannot be checked yet', tone: 'muted' },
};

/* ------------------------------------------------------------------ tabs */

export type TabId = 'watch' | 'reasons' | 'period' | 'herd' | 'events' | 'heat' | 'breeding' | 'trust' | 'tests';

const NavCtx = createContext<{ tab: TabId; go: (t: TabId) => void } | undefined>(undefined);

export function NavProvider({ children }: { children: ReactNode }) {
  const [tab, setTab] = useState<TabId>('watch');
  const go = (t: TabId) => {
    setTab(t);
    window.setTimeout(() => document.getElementById('mgr-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 30);
  };
  return <NavCtx.Provider value={{ tab, go }}>{children}</NavCtx.Provider>;
}

export function useNav() {
  const c = useContext(NavCtx);
  return c ?? { tab: 'watch' as TabId, go: () => undefined };
}

/* ------------------------------------------------------------------ layout */

/** A white box. */
export function Box({ title, sub, actions, children }: { title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="pfie-mgr-card">
      {(title || actions) && (
        <div className="pfie-mgr-card-head">
          <div>
            {title && <h3>{title}</h3>}
            {sub && <p className="sub">{sub}</p>}
          </div>
          {actions && <div className="pfie-row tight pfie-noprint">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/** A short explanation that can be opened. */
export function Explain({ title, children }: { title?: string; children: ReactNode }) {
  const t = useT();
  return (
    <details className="pfie-mgr-explain">
      <summary>{title ?? t('What does this mean?')}</summary>
      <div>{children}</div>
    </details>
  );
}

/** Chart / Table switch with its state. */
export function useChartOrTable() {
  const t = useT();
  const [asTable, setAsTable] = useState(false);
  const toggle = (
    <span className="pfie-mgr-switch" role="group" aria-label={t('Show as')}>
      <button aria-pressed={!asTable} onClick={() => setAsTable(false)}>{t('Chart')}</button>
      <button aria-pressed={asTable} onClick={() => setAsTable(true)}>{t('Table')}</button>
    </span>
  );
  return { asTable, toggle };
}

export function Legend({ items }: { items: { label: string; color?: string; kind?: 'line' | 'dash' | 'band' | 'dot' | 'bar' }[] }) {
  return (
    <ul className="pfie-mgr-legend">
      {items.map((i) => (
        <li key={i.label}>
          <i className={i.kind ?? 'line'} style={i.kind === 'dash' ? { borderColor: i.color } : i.color ? { background: i.color } : undefined} />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

/** A plain table: numbers right-aligned, the first column and any `textCols` left-aligned. */
export function SimpleTable({ head, rows, textCols = [], onRow, selected }: {
  head: ReactNode[]; rows: ReactNode[][]; textCols?: number[];
  /** Makes rows clickable (for explanations); `selected` highlights one. */
  onRow?: (i: number) => void; selected?: number;
}) {
  const cls = (j: number) => (textCols.includes(j) ? 'text' : undefined);
  return (
    <div className="pfie-mgr-tablewrap">
      <table className="pfie-mgr-table">
        <thead><tr>{head.map((h, j) => <th key={j} className={cls(j)}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              className={`${onRow ? 'clickable' : ''}${selected === i ? ' selected' : ''}`}
              onClick={onRow ? () => onRow(i) : undefined}
              tabIndex={onRow ? 0 : undefined}
              onKeyDown={onRow ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRow(i); } } : undefined}
            >
              {r.map((c, j) => <td key={j} className={cls(j)}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DemoLine({ run }: { run: PfoiRun }) {
  const t = useT();
  return run.source === 'demo' ? <p className="pfie-mgr-note">{t('Practice data: made-up numbers, not a real result.')}</p> : null;
}

export function NotInRun() {
  const t = useT();
  return <p className="pfie-mgr-note">{t('Not included in this forecast run.')}</p>;
}

/** Note shown on monthly-only parts while Daily or Weekly is selected. */
export function MonthlyOnlyNote({ grain }: { grain: Grain }) {
  const t = useT();
  return grain === 'month' ? null : <p className="pfie-mgr-tagline">{t('This part is worked out by month.')}</p>;
}

export const CHART_TICK = { fontSize: 12, fill: '#52665d' };
export const MILK_COLOR = '#9a4f27';
export const FORECAST_COLOR = '#5b7fa6';
