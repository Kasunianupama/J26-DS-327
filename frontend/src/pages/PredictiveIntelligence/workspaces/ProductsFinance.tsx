/**
 * Products & Finance (§19, §20).
 *
 * Milk → allocation → product output → revenue, then the financial path,
 * variance bridge and the expandable line-item tree. No allocation sliders:
 * editing the split would be scenario analysis, which belongs elsewhere.
 */

import { Fragment, useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  FINANCE_MONTHS,
  PRODUCTS,
  PRODUCT_CONSTRAINT,
  PRODUCT_META,
  PRODUCT_MONTHS,
  financePath,
  financialTree,
  fmtInt,
  fmtLKR,
  longDate,
  monthLabel,
  varianceBridge,
  type Period,
  type Product,
  type TreeNode,
} from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, Meter, Note, Segmented, Tabs, TipShell } from '../ui';
import { BudgetDetail } from './Budget';

type CommerceTab = 'flow' | 'budget';

export function ProductsFinance() {
  const { selectedMonth, setSelectedMonth } = useC2();
  const [tab, setTab] = useState<CommerceTab>('flow');
  const months = PRODUCT_MONTHS.filter((m) => m.key >= '2024-01');

  return (
    <div className="pfie-stack">
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'flow' as CommerceTab, label: 'Production → revenue' },
          { id: 'budget' as CommerceTab, label: 'Budget detail' },
        ]}
      />
      <div className="pfie-row between">
        <label className="pfie-field">
          Period
          <select value={selectedMonth} onChange={(e) => setSelectedMonth(e.target.value)}>
            {months.map((m) => <option key={m.key} value={m.key}>{m.label}{m.future ? ' (expected)' : ''}</option>)}
          </select>
        </label>
        <span className="pfie-badge plain">
          Selection follows the timeline — changing it here also changes it in Future and Capacity
        </span>
      </div>

      {tab === 'budget' ? (
        <BudgetDetail />
      ) : (
        <>
          <ProductFlow />
          <FinancialPath />
          <div className="pfie-grid side">
            <VarianceBridge />
            <FinancialTree />
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ProductFlow() {
  const { selectedMonth, openDrawer } = useC2();
  const pm = PRODUCT_MONTHS.find((m) => m.key === selectedMonth);
  if (!pm) return null;

  const maxAlloc = Math.max(...PRODUCTS.map((p) => pm.allocation[p]));

  return (
    <Card
      title="Expected milk → allocation → product output → revenue"
      sub={`${pm.label}. Expected allocation based on current and historical operating patterns.`}
      actions={<ConfidenceBadge level={pm.confidence} />}
    >
      <div className="pfie-consequence" style={{ marginTop: 0 }}>
        <div>
          <div className="k">Expected milk</div>
          <div className="v">{fmtInt(pm.milk)} L</div>
          <div className="d">Total supply available to allocate in {pm.label}</div>
        </div>
        <div>
          <div className="k">Allocated to product</div>
          <div className="v">{fmtInt(PRODUCTS.reduce((s, p) => s + pm.allocation[p], 0))} L</div>
          <div className="d">Raw contract is filled first, then the packing line</div>
        </div>
        <div>
          <div className="k">Expected revenue</div>
          <div className="v">{fmtLKR(pm.totalRevenue)}</div>
          <div className="d">Derived from the allocation, not forecast separately</div>
        </div>
      </div>

      <div className="pfie-tablewrap" style={{ marginTop: 20 }}>
        <table className="pfie-table">
          <thead>
            <tr>
              <th>Product</th>
              <th className="pfie-num">Expected quantity</th>
              <th>Share of milk</th>
              <th className="pfie-num">Likely range</th>
              <th className="pfie-num">Revenue</th>
              <th>Confidence</th>
              <th>Milk constraint</th>
            </tr>
          </thead>
          <tbody>
            {PRODUCTS.map((p) => {
              const short = pm.shortfall[p] > 0;
              const out = pm.output[p];
              return (
                <tr key={p} className="clickable" onClick={() => openDrawer({ kind: 'product', product: p })}>
                  <td>
                    <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: PRODUCT_META[p].color, marginRight: 7 }} />
                    <b>{p}</b>
                  </td>
                  <td className="pfie-num">{fmtInt(out)} L</td>
                  <td><Meter pct={(pm.allocation[p] / maxAlloc) * 100} tone={short ? 'caution' : 'brand'} /></td>
                  <td className="pfie-num" style={{ color: 'var(--muted)' }}>
                    {fmtInt(Math.round(out * 0.95))}–{fmtInt(Math.round(out * 1.05))} L
                  </td>
                  <td className="pfie-num">{fmtLKR(pm.revenue[p])}</td>
                  <td><ConfidenceBadge level={pm.confidence} hint={false} /></td>
                  <td>
                    {short ? (
                      <span className="pfie-badge conf-Limited">▲ Short {fmtInt(pm.shortfall[p])} L</span>
                    ) : (
                      <span style={{ color: 'var(--muted)' }}>Within plan</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {PRODUCT_CONSTRAINT && (
        <div style={{ marginTop: 14 }}>
          <Note tone="caution" title="Tetra-pack output is expected to be constrained.">
            The shortfall begins in the week of {longDate(PRODUCT_CONSTRAINT.firstWeek)} and runs for{' '}
            {PRODUCT_CONSTRAINT.weeksAffected} weeks, worst in the week of {longDate(PRODUCT_CONSTRAINT.worstWeek)}{' '}
            at {fmtInt(PRODUCT_CONSTRAINT.worstWeekLitres)} L. Estimated revenue effect{' '}
            {fmtLKR(PRODUCT_CONSTRAINT.revenueEffect)}. Select the row for the contributing animals.
          </Note>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function FinancialPath() {
  const { selectedMonth, setSelectedMonth, setSelectedDate, openDrawer } = useC2();
  const [period, setPeriod] = useState<Period>('Month');
  const rows = useMemo(() => financePath(period), [period]);
  const firstFuture = rows.find((r) => r.future);

  /** Quarter and year points open the latest month in that roll-up, so the
   * explanation still lands on a real, inspectable financial period. */
  const monthForPoint = (key: string) => {
    if (period === 'Month') return key;
    const eligible = FINANCE_MONTHS.filter((month) => {
      if (period === 'Year') return month.key.startsWith(`${key}-`);
      const [year, quarter] = key.split(' Q');
      const monthNo = Number(month.key.slice(5, 7));
      return month.key.startsWith(`${year}-`) && Math.ceil(monthNo / 3) === Number(quarter);
    });
    return eligible[eligible.length - 1]?.key ?? selectedMonth;
  };

  const explainPoint = (key: string) => {
    const month = monthForPoint(key);
    setSelectedMonth(month);
    setSelectedDate(`${month}-15`);
    openDrawer({ kind: 'structure', date: `${month}-15`, domain: 'finance' });
  };

  return (
    <Card
      title="Financial path"
      sub="Budget, actual to date, then forecast actual. The boundary marks where recorded data ends."
      actions={
        <>
          <button className="pfie-btn" onClick={() => explainPoint(selectedMonth)}>Explain selected point</button>
          <Segmented
            label="Roll up"
            options={[{ id: 'Month' as Period, label: 'Month' }, { id: 'Quarter' as Period, label: 'Quarter' }, { id: 'Year' as Period, label: 'Year' }]}
            value={period}
            onChange={setPeriod}
          />
        </>
      }
    >
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart
          data={rows}
          margin={{ top: 6, right: 8, left: 0, bottom: 0 }}
          onClick={(e) => {
            const r = rows.find((x) => x.label === String(e?.activeLabel));
            if (r) explainPoint(r.key);
          }}
        >
          <defs>
            <pattern id="pfieFinHatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
              <rect width="6" height="6" fill="#5b7fa6" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="#fff" strokeWidth="2.4" opacity="0.85" />
            </pattern>
          </defs>
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={{ stroke: '#e2e9e5' }} minTickGap={20} />
          <YAxis tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={false} width={54} tickFormatter={(v) => `${Math.round(Number(v) / 1000)}M`} />
          <Tooltip content={<FinTip period={period} />} />
          <Bar dataKey="revenue" fill="#1f6b4a" name="Revenue — recorded" isAnimationActive={false} />
          <Bar dataKey="revenueForecast" fill="url(#pfieFinHatch)" stroke="#5b7fa6" name="Revenue — expected" isAnimationActive={false} />
          <Line dataKey="budgetRevenue" stroke="#1d2b26" strokeWidth={1.4} strokeDasharray="3 3" dot={false} isAnimationActive={false} name="Budget revenue" />
          <Line dataKey="cost" stroke="#a44b3c" strokeWidth={1.8} dot={false} isAnimationActive={false} name="Cost" />
          {firstFuture && (
            <ReferenceLine x={firstFuture.label} stroke="#1d2b26" strokeWidth={1.5}
              label={{ value: 'Recorded data ends', position: 'insideTopRight', fontSize: 10, fontWeight: 700, fill: '#1d2b26' }} />
          )}
          {period === 'Month' && <ReferenceLine x={monthLabel(selectedMonth)} stroke="#5b7fa6" strokeWidth={2} strokeDasharray="4 3" />}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="pfie-legend">
        <span><i style={{ background: '#1f6b4a' }} />Revenue recorded</span>
        <span><i style={{ background: 'repeating-linear-gradient(45deg,#5b7fa6 0 2px,#fff 2px 4.5px)', border: '1px solid #5b7fa6' }} />Revenue expected</span>
        <span><i style={{ background: 'none', borderTop: '2px dashed #1d2b26', height: 0 }} />Budget</span>
        <span><i style={{ background: '#a44b3c' }} />Cost</span>
      </div>
      <p className="sub" style={{ marginTop: 8 }}>
        Click any point to select it and open its finance-specific reasoning. Quarter and year points open the final month in that roll-up.
      </p>
    </Card>
  );
}

function FinTip({ active, label, payload, period }: { active?: boolean; label?: string | number; payload?: { payload?: Record<string, unknown> }[]; period: Period }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload ?? {};
  const rev = Number(p.revenue ?? p.revenueForecast ?? 0);
  const cost = Number(p.cost ?? p.costForecast ?? 0);
  const budget = Number(p.budgetRevenue ?? 0);
  const confidence = typeof p.confidence === 'string' ? p.confidence : 'Moderate';
  return (
    <TipShell
      title={`${label}`}
      rows={[
        [p.revenue != null ? 'Revenue (recorded)' : 'Revenue (expected)', fmtLKR(rev)],
        ['Budget revenue', fmtLKR(budget)],
        ['Cost', fmtLKR(cost)],
        ['Margin', fmtLKR(rev - cost)],
        ['Against budget', fmtLKR(rev - budget)],
        ['Confidence', confidence],
      ]}
      note={`${p.revenue != null ? 'Recorded actuals.' : 'Expected outturn derived from the milk forecast and the driver-based cost model.'} Click to open the finance reasoning${period === 'Month' ? ' for this month' : ' for the final month in this roll-up'}.`}
    />
  );
}

/* ------------------------------------------------------------------ */

function VarianceBridge() {
  const { selectedMonth } = useC2();
  const steps = useMemo(() => varianceBridge(selectedMonth), [selectedMonth]);
  const max = Math.max(1, ...steps.filter((s) => s.kind !== 'anchor' && s.kind !== 'total').map((s) => Math.abs(s.value)));
  const maxEdge = Math.max(1, ...steps.filter((s) => s.kind === 'anchor' || s.kind === 'total').map((s) => Math.abs(s.value)));

  if (!steps.length) return null;

  return (
    <Card
      title="Variance bridge"
      sub={`Why the expected margin for ${monthLabel(selectedMonth)} differs from budget. The steps close exactly.`}
    >
      <div className="pfie-wf">
        {steps.map((s) => {
          const edge = s.kind === 'anchor' || s.kind === 'total';
          const w = edge ? (Math.abs(s.value) / maxEdge) * 100 : (Math.abs(s.value) / max) * 46;
          return (
            <div className={`step ${s.kind}`} key={s.label} title={s.note}>
              <span className="nm">{s.label}</span>
              <span className="track">
                <span
                  className={`fill ${s.kind}`}
                  style={edge ? { left: 0, width: `${w}%` } : s.value >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
                />
              </span>
              <span className="v">{edge ? '' : s.value > 0 ? '+' : ''}{fmtLKR(s.value)}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function FinancialTree() {
  const { selectedMonth } = useC2();
  const tree = useMemo(() => financialTree(selectedMonth), [selectedMonth]);
  const [open, setOpen] = useState<Set<string>>(new Set(['Feed']));

  const toggle = (n: string) =>
    setOpen((s) => {
      const x = new Set(s);
      if (x.has(n)) x.delete(n); else x.add(n);
      return x;
    });

  const Section = ({ title, nodes }: { title: string; nodes: TreeNode[] }) => (
    <>
      <tr className="lvl0" style={{ background: 'var(--ground)' }}>
        <td colSpan={4} style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.6px', color: 'var(--faint)' }}>{title}</td>
      </tr>
      {nodes.map((n) => (
        <Fragment key={n.name}>
          <tr className="lvl0">
            <td>
              {n.children && (
                <button className="tw" onClick={() => toggle(n.name)} aria-expanded={open.has(n.name)}>
                  {open.has(n.name) ? '▼' : '▶'}
                </button>
              )}
              {n.name}
            </td>
            <td className="pfie-num">{fmtLKR(n.budget)}</td>
            <td className="pfie-num">{n.actual !== null ? fmtLKR(n.actual) : '—'}</td>
            <td className="pfie-num">{fmtLKR(n.forecast)}</td>
          </tr>
          {open.has(n.name) &&
            n.children?.map((c) => (
              <tr className="lvl1" key={`${n.name}-${c.name}`} title={c.method}>
                <td>{c.name}</td>
                <td className="pfie-num">{fmtLKR(c.budget)}</td>
                <td className="pfie-num">{c.actual !== null ? fmtLKR(c.actual) : '—'}</td>
                <td className="pfie-num">{fmtLKR(c.forecast)}</td>
              </tr>
            ))}
        </Fragment>
      ))}
    </>
  );

  return (
    <Card
      title="Financial detail"
      sub={`Farm → category → line item for ${monthLabel(selectedMonth)}. Child values sum to their parent.`}
    >
      <div className="pfie-tablewrap pfie-scroll">
        <table className="pfie-tree">
          <thead>
            <tr>
              <th>Line</th>
              <th>Budget</th>
              <th>Actual</th>
              <th>Forecast</th>
            </tr>
          </thead>
          <tbody>
            <Section title="Revenue" nodes={tree.revenue} />
            <Section title="Cost" nodes={tree.cost} />
            <tr className="total">
              <td>{tree.totals.name}</td>
              <td className="pfie-num">{fmtLKR(tree.totals.budget)}</td>
              <td className="pfie-num">{tree.totals.actual !== null ? fmtLKR(tree.totals.actual) : '—'}</td>
              <td className="pfie-num">{fmtLKR(tree.totals.forecast)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 12 }}>
        <Note>
          Hover a line item to see the method behind it. Veterinary treatment cost is the weakest line — event
          coding before March 2025 is inconsistent, so it is reported at Limited confidence.
        </Note>
      </div>
    </Card>
  );
}

export { FINANCE_MONTHS, type Product };
