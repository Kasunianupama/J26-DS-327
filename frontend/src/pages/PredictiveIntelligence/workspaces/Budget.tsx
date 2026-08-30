/**
 * Budget detail (§20) — category → subcategory → line item.
 *
 * Every parent value is summed from its children rather than typed, so the
 * tree reconciles at each level. Pace compares spend against how much of the
 * period has actually elapsed, which is what separates "over budget" from
 * "simply early".
 */

import { useMemo, useState } from 'react';
import {
  BUDGET,
  BUDGET_PRESSURE,
  BUDGET_SHARES,
  BUDGET_TOTAL,
  PERIOD_ELAPSED,
  round,
  type Rolled,
} from '../../../data/component2';
import { Card, ConfidenceBadge, Note } from '../ui';

const rs = (m: number) => `Rs.${m.toFixed(2)}m`;

export function BudgetDetail() {
  const [open, setOpen] = useState<Set<string>>(new Set(['Feed & fodder', 'Feed & fodder/Concentrate']));
  const [focus, setFocus] = useState<string | null>(null);

  const toggle = (path: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(path)) n.delete(path); else n.add(path);
      return n;
    });

  const rows = useMemo(() => flatten(BUDGET, open, focus), [open, focus]);
  const allPaths = useMemo(() => expandablePaths(BUDGET), []);
  const allExpanded = allPaths.every((path) => open.has(path));
  const toggleAll = () => setOpen(allExpanded ? new Set() : new Set(allPaths));

  return (
    <div className="pfie-stack">
      <div className="pfie-grid side">
        <Card
          title="Line items"
          sub="Actuals are recorded through the current date; the end-of-period forecast uses each line's observed run-rate."
          actions={
            <>
              <span className="pfie-badge plain">
                {BUDGET_TOTAL.variance >= 0 ? 'Over' : 'Under'} budget by {rs(Math.abs(BUDGET_TOTAL.variance))}
              </span>
              <button className="pfie-btn" onClick={toggleAll}>{allExpanded ? 'Collapse all' : 'Expand all'}</button>
            </>
          }
        >
          <div className="pfie-budget-summary" aria-label="Budget summary">
            <div><span>Approved budget</span><b>{rs(BUDGET_TOTAL.budget)}</b></div>
            <div><span>Actual to date</span><b>{rs(BUDGET_TOTAL.actual)}</b></div>
            <div><span>Forecast at period end</span><b className={BUDGET_TOTAL.forecast > BUDGET_TOTAL.budget ? 'over' : 'under'}>{rs(BUDGET_TOTAL.forecast)}</b></div>
            <div><span>Remaining forecast</span><b>{rs(BUDGET_TOTAL.remaining)}</b></div>
          </div>
          <div className="pfie-tablewrap">
            <table className="pfie-budget">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Budget</th>
                  <th>Actual</th>
                  <th>Forecast</th>
                  <th>Variance</th>
                  <th style={{ textAlign: 'left', paddingLeft: 16 }}>Pace</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.path}
                    className={`lv${r.depth}${r.depth > 0 ? ' kid' : ''}`}
                    style={{ cursor: r.expandable ? 'pointer' : 'default' }}
                    onClick={() => r.expandable && toggle(r.path)}
                    title={r.node.leaf ? `${r.node.leaf.driver} · ${r.node.leaf.method}` : undefined}
                  >
                    <td>
                      {r.expandable ? (
                        <span className={`tw${open.has(r.path) ? ' open' : ''}`} aria-hidden>▶</span>
                      ) : (
                        <span className="tw" aria-hidden />
                      )}
                      {r.depth === 0 && r.node.color && (
                        <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: r.node.color, marginRight: 8 }} />
                      )}
                      {r.node.name}
                    </td>
                    <td className="n">{rs(r.node.budget)}</td>
                    <td className="n">{rs(r.node.actual)}</td>
                    <td className={`n ${r.node.forecast > r.node.budget ? 'over' : 'under'}`}>{rs(r.node.forecast)}</td>
                    <td className={`n ${r.node.variance >= 0 ? 'over' : 'under'}`}>
                      {r.node.variance >= 0 ? '+' : ''}{r.node.variancePct}%
                    </td>
                    <td style={{ paddingLeft: 16 }}>
                      <PaceBar pace={r.node.pace} />
                    </td>
                  </tr>
                ))}
                <tr className="total">
                  <td>Total operating cost</td>
                  <td className="n">{rs(BUDGET_TOTAL.budget)}</td>
                  <td className="n">{rs(BUDGET_TOTAL.actual)}</td>
                  <td className={`n ${BUDGET_TOTAL.forecast > BUDGET_TOTAL.budget ? 'over' : 'under'}`}>{rs(BUDGET_TOTAL.forecast)}</td>
                  <td className={`n ${BUDGET_TOTAL.variance >= 0 ? 'over' : 'under'}`}>
                    {BUDGET_TOTAL.variance >= 0 ? '+' : ''}{BUDGET_TOTAL.variancePct}%
                  </td>
                  <td style={{ paddingLeft: 16 }}><PaceBar pace={BUDGET_TOTAL.actual / BUDGET_TOTAL.budget} /></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: 16 }}>
            <Note>
              The notch on each pace bar marks how much of the period has elapsed
              ({Math.round(PERIOD_ELAPSED * 100)}%). A fill past the notch means the line is spending faster than
              the calendar, not simply that it is large. Forecast values project the recorded run-rate to period end.
              Hover a line item for its cost driver and method.
            </Note>
          </div>
        </Card>

        <div className="pfie-stack">
          <Card title="Where the budget went" sub="Share of actual spend by category. Current period.">
            <Donut focus={focus} onFocus={setFocus} />
          </Card>

          <Card title="Biggest pressure" sub="The individual lines pulling hardest against budget.">
            {BUDGET_PRESSURE.map((l, i) => (
              <div key={l.name} className={`pfie-rise pfie-rise-${Math.min(i + 1, 6)}`} style={{ marginBottom: 13 }}>
                <div className="pfie-row between" style={{ fontSize: 12.5 }}>
                  <b>{l.name}</b>
                  <span className={l.variance >= 0 ? 'over' : 'under'} style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700, color: l.variance >= 0 ? 'var(--concern)' : 'var(--brand)' }}>
                    {l.variance >= 0 ? '+' : ''}{rs(l.variance)}
                  </span>
                </div>
                <div className="pfie-row" style={{ gap: 10, marginTop: 4 }}>
                  <span style={{ flex: 1 }}><PaceBar pace={l.pace} /></span>
                  <span style={{ fontSize: 11.5, color: 'var(--muted)', width: 96, textAlign: 'right' }}>
                    {rs(l.actual)} of {rs(l.budget)}
                  </span>
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 3 }}>
                  Period-end forecast {rs(l.forecast)} · remaining {rs(l.remaining)}
                </div>
                {l.leaf && (
                  <div className="pfie-row tight" style={{ marginTop: 5 }}>
                    <span className="pfie-badge plain">{l.leaf.driver}</span>
                    <ConfidenceBadge level={l.leaf.confidence} hint={false} />
                  </div>
                )}
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function PaceBar({ pace }: { pace: number }) {
  const pct = Math.min(140, pace * 100);
  const tone = pace > PERIOD_ELAPSED + 0.12 ? 'hot' : pace > PERIOD_ELAPSED + 0.02 ? 'warm' : '';
  return (
    <span className="pfie-pace" title={`${Math.round(pace * 100)}% of budget spent · ${Math.round(PERIOD_ELAPSED * 100)}% of period elapsed`}>
      <i className={tone} style={{ width: `${Math.min(100, pct)}%` }} />
      <span className="notch" style={{ left: `${PERIOD_ELAPSED * 100}%` }} />
    </span>
  );
}

/* ------------------------------------------------------------------ */

function Donut({ focus, onFocus }: { focus: string | null; onFocus: (n: string | null) => void }) {
  const size = 168;
  const r = 66;
  const stroke = 30;
  const c = 2 * Math.PI * r;
  let acc = 0;

  return (
    <div className="pfie-donut">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Share of actual spend by category">
        <g transform={`translate(${size / 2} ${size / 2}) rotate(-90)`}>
          {BUDGET_SHARES.map((s) => {
            const frac = s.actual / BUDGET_TOTAL.actual;
            const dash = frac * c;
            const el = (
              <circle
                key={s.name}
                className={`slice${focus && focus !== s.name ? ' dim' : ''}`}
                r={r}
                fill="none"
                stroke={s.color}
                strokeWidth={focus === s.name ? stroke + 6 : stroke}
                strokeDasharray={`${dash} ${c - dash}`}
                strokeDashoffset={-acc}
                onMouseEnter={() => onFocus(s.name)}
                onMouseLeave={() => onFocus(null)}
              >
                <title>{`${s.name} — Rs.${s.actual.toFixed(2)}m (${s.share}%)`}</title>
              </circle>
            );
            acc += dash;
            return el;
          })}
        </g>
        <text x={size / 2} y={size / 2 - 6} textAnchor="middle" fontSize="9.5" fill="#93a29b" letterSpacing="1" fontWeight="700">
          {focus ? focus.split(' ')[0].toUpperCase() : 'ACTUAL'}
        </text>
        <text x={size / 2} y={size / 2 + 13} textAnchor="middle" fontSize="15" fill="#1d2b26" fontWeight="700">
          {focus
            ? `Rs.${BUDGET_SHARES.find((s) => s.name === focus)!.actual.toFixed(2)}m`
            : `Rs.${BUDGET_TOTAL.actual.toFixed(2)}m`}
        </text>
      </svg>

      <div className="keys">
        {BUDGET_SHARES.map((s) => (
          <div
            key={s.name}
            className="key"
            onMouseEnter={() => onFocus(s.name)}
            onMouseLeave={() => onFocus(null)}
            style={{ opacity: focus && focus !== s.name ? 0.45 : 1 }}
          >
            <i style={{ background: s.color }} />
            {s.name}
            <span className="pc">{s.share}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

interface Row { path: string; depth: number; node: Rolled; expandable: boolean }

function flatten(nodes: Rolled[], open: Set<string>, focus: string | null, prefix = '', depth = 0): Row[] {
  const out: Row[] = [];
  for (const n of nodes) {
    if (depth === 0 && focus && n.name !== focus) continue;
    const path = prefix ? `${prefix}/${n.name}` : n.name;
    out.push({ path, depth, node: n, expandable: !!n.children?.length });
    if (n.children?.length && open.has(path)) {
      out.push(...flatten(n.children, open, null, path, depth + 1));
    }
  }
  return out;
}

function expandablePaths(nodes: Rolled[], prefix = ''): string[] {
  return nodes.flatMap((n) => {
    const path = prefix ? `${prefix}/${n.name}` : n.name;
    return n.children?.length ? [path, ...expandablePaths(n.children, path)] : [];
  });
}

export { round };
