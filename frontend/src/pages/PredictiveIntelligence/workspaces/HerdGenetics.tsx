/**
 * Component 1 (PFOI): Herd & Production → Generations.
 *
 * Generation = farm-born generations in the maternal line. Shown as herd
 * composition over time (recorded and projected) and fertility by generation
 * within each period. Generation is not a milk multiplier, and this page does
 * not use it as one.
 */

import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { firstTarget, fmtPct, periodLabel } from '../../../data/pfoi';
import { useRun } from '../source';
import { Card, MonthlyOnly, KindTag, Note, TipShell } from '../ui';
import { GenerationOutcomes } from '../panels/Pp1Panels';

const GENS = ['0', '1', '2', '3+'] as const;
const GEN_COLORS: Record<(typeof GENS)[number], string> = { '0': '#34483f', '1': '#9a4f27', '2': '#5b7fa6', '3+': '#a8770a' };

export function HerdGenetics() {
  const run = useRun();
  const origin = firstTarget(run, 'month');

  const composition = useMemo(() => {
    const byPeriod = new Map<string, Record<string, number | string | boolean>>();
    run.generations.forEach((g) => {
      const row = byPeriod.get(g.period) ?? { period: g.period, short: periodLabel(g.period, 'month', true), projected: g.projected };
      row[g.generation] = Math.round(g.share * 1000) / 10;
      byPeriod.set(g.period, row);
    });
    return [...byPeriod.values()];
  }, [run]);

  const periods = [...new Set(run.fertility.map((f) => f.period_label))];
  const fertility = (metric: 'services_per_conception' | 'abortion_pct') => periods.map((p) => {
    const row: Record<string, number | string> = { period: p };
    run.fertility.filter((f) => f.period_label === p).forEach((f) => { row[f.generation] = f[metric]; });
    return row;
  });
  const presentGens = GENS.filter((g) => run.fertility.some((f) => f.generation === g));

  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <Card
        title={<>Herd composition by generation <MonthlyOnly /></>}
        sub={<>Share of the herd, recorded <KindTag kind="measured" /> and projected from births to farm-born dams <KindTag kind="derived" /></>}
      >
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={composition} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#eef2f0" vertical={false} />
            <XAxis dataKey="short" tick={{ fontSize: 11, fill: '#70827a' }} minTickGap={24} />
            <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={40} unit="%" domain={[0, 100]} />
            <ReferenceLine x={periodLabel(origin, 'month', true)} stroke="#5b7fa6" strokeDasharray="4 3" label={{ value: 'Origin', position: 'insideTopRight', fontSize: 10, fill: '#5b7fa6' }} />
            {GENS.map((g) => (
              <Area key={g} dataKey={g} stackId="g" stroke={GEN_COLORS[g]} fill={GEN_COLORS[g]} fillOpacity={0.5} isAnimationActive={false} />
            ))}
            <Tooltip
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as Record<string, number | string | boolean> | undefined;
                if (!active || !p) return null;
                return (
                  <TipShell
                    title={`${periodLabel(String(p.period), 'month')}${p.projected ? ' · projected' : ''}`}
                    rows={GENS.map((g) => [`Generation ${g}`, `${Number(p[g] ?? 0).toFixed(1)}%`, GEN_COLORS[g]])}
                  />
                );
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
        <div className="pfie-legend">
          {GENS.map((g) => <span key={g}><i style={{ background: GEN_COLORS[g] }} />Generation {g}</span>)}
        </div>
      </Card>

      <div className="pfie-grid c2">
        <Card title="Services per conception" sub="By generation, within each period (descriptive)">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={fertility('services_per_conception')} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef2f0" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 11, fill: '#70827a' }} />
              <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={32} />
              {presentGens.map((g) => <Bar key={g} dataKey={g} name={`Generation ${g}`} fill={GEN_COLORS[g]} isAnimationActive={false} />)}
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Tooltip />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Abortion rate" sub="Share of pregnancies lost, by generation within each period (descriptive)">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={fertility('abortion_pct')} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef2f0" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 11, fill: '#70827a' }} />
              <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={32} unit="%" />
              {presentGens.map((g) => <Bar key={g} dataKey={g} name={`Generation ${g}`} fill={GEN_COLORS[g]} isAnimationActive={false} />)}
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => fmtPct(v / 100, 1)} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Note tone="info" title="Compare within a period, not across the pooled data.">
        Pooling all years can reverse the direction of a generation effect (Simpson's paradox), so fertility is
        shown within each period. Generation is used to project the herd's makeup; it is not a milk multiplier.
      </Note>

      <GenerationOutcomes />
    </div>
  );
}
