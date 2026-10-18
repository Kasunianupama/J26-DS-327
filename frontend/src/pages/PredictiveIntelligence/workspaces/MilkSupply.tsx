/**
 * Component 1 (PFOI): Herd & Production → Milk supply.
 *
 * The milk band of the timeline, two waterfalls (one past month, one future
 * month) and the month-by-month change split by factor. All of it reads the
 * attribution rows, whose parts add up exactly to each month's change.
 */

import { useMemo, useState } from 'react';
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
  FACTOR_META,
  MILK_FACTORS,
  attributionMonths,
  firstTarget,
  fmtSigned,
  milkBreakdown,
  periodLabel,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, KindTag, Note, TipShell, type TipRow } from '../ui';
import { MasterTimeline } from '../panels/MasterTimeline';
import { Waterfall } from '../panels/Waterfall';

const FACTOR_COLORS: Record<string, string> = {
  herd_size: '#9a4f27',
  stage_mix: '#5b7fa6',
  parity_mix: '#93aec9',
  thi: '#a8770a',
  mastitis: '#a44b3c',
  residual: '#b9c7c0',
};

export function MilkSupply() {
  const { breakdownMonth } = usePfoi();
  const run = useRun();
  const months = attributionMonths(run);
  const origin = firstTarget(run, 'month');
  const past = months.filter((m) => m < origin);
  const future = months.filter((m) => m >= origin);
  const [pastMonth, setPastMonth] = useState(
    breakdownMonth && breakdownMonth < origin ? breakdownMonth : past[past.length - 1],
  );
  const [futureMonth, setFutureMonth] = useState(
    breakdownMonth && breakdownMonth >= origin ? breakdownMonth : future[Math.min(future.length - 1, 2)],
  );
  const pastBd = pastMonth ? milkBreakdown(run, pastMonth) : null;
  const futureBd = futureMonth ? milkBreakdown(run, futureMonth) : null;

  const river = useMemo(() => months.map((m) => {
    const bd = milkBreakdown(run, m);
    const row: Record<string, number | string | boolean> = { period: m, short: periodLabel(m, 'month', true), future: m >= origin };
    bd?.parts.forEach((p) => { row[p.factor] = Math.round(p.value * 10) / 10; });
    row.total = bd ? Math.round((bd.end - bd.start) * 10) / 10 : 0;
    return row;
  }), [run, months, origin]);

  const picker = (value: string | undefined, options: string[], onChange: (m: string) => void) => (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((m) => <option key={m} value={m}>{periodLabel(m, 'month')}</option>)}
    </select>
  );

  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <MasterTimeline bands={['milk']} />

      <div className="pfie-grid c2">
        <Card title="A past month" sub="Recorded change, explained by the model, with what it could not explain" actions={picker(pastMonth, past, setPastMonth)}>
          {pastBd ? <Waterfall breakdown={pastBd} /> : <p className="pfie-chart-note">No breakdown for this month.</p>}
        </Card>
        <Card title="A future month" sub="Forecast change, fully explained by construction" actions={picker(futureMonth, future, setFutureMonth)}>
          {futureBd ? <Waterfall breakdown={futureBd} /> : <p className="pfie-chart-note">No breakdown for this month.</p>}
        </Card>
      </div>

      <Card title="Month-by-month change, by factor" sub="Each bar is one month's change from the month before (L/day); the line is the total change">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={river} stackOffset="sign" margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#eef2f0" vertical={false} />
            <XAxis dataKey="short" tick={{ fontSize: 11, fill: '#70827a' }} minTickGap={16} />
            <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={48} />
            <ReferenceLine y={0} stroke="#93a29b" />
            <ReferenceLine x={periodLabel(origin, 'month', true)} stroke="#5b7fa6" strokeDasharray="4 3" label={{ value: 'Origin', position: 'insideTopRight', fontSize: 10, fill: '#5b7fa6' }} />
            {MILK_FACTORS.map((f) => (
              <Bar key={f} dataKey={f} stackId="s" fill={FACTOR_COLORS[f]} isAnimationActive={false} />
            ))}
            <Line dataKey="total" stroke="#17231f" strokeWidth={1.5} dot={{ r: 2 }} isAnimationActive={false} />
            <Tooltip
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as Record<string, number | string | boolean> | undefined;
                if (!active || !p) return null;
                const rows: TipRow[] = MILK_FACTORS
                  .filter((f) => p.future !== true || f !== 'residual')
                  .map((f) => [FACTOR_META[f].label, fmtSigned(Number(p[f] ?? 0), 1), FACTOR_COLORS[f]]);
                rows.push(['Total change', fmtSigned(Number(p.total), 1)]);
                return <TipShell title={periodLabel(String(p.period), 'month')} rows={rows} note={p.future ? 'Forecast month.' : 'Recorded month.'} />;
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <div className="pfie-legend">
          {MILK_FACTORS.map((f) => (
            <span key={f}><i style={{ background: FACTOR_COLORS[f] }} />{FACTOR_META[f].label} <KindTag kind={FACTOR_META[f].kind} /></span>
          ))}
        </div>
      </Card>

      <Note tone="info" title="Not shown yet: milk by parity and lactation stage.">
        The planned outputs carry the factor split above but not milk per parity or stage group. Showing that
        needs one more output table from the model (a decision for Step 6).
      </Note>
    </div>
  );
}
