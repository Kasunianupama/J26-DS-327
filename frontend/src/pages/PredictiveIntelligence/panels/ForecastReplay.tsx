/**
 * Component 1 (PFOI): forecast replay.
 *
 * Pick an earlier monthly origin: what did the model forecast then, what
 * happened, and why did the forecast for a month move between consecutive
 * origins? The revision is split across the same factors as the milk
 * breakdown, so every revision is explained.
 */

import { useMemo, useState } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fmtInt,
  fmtSigned,
  periodLabel,
  replayOrigins,
  replayPath,
  revisionFor,
} from '../../../data/pfoi';
import { useRun } from '../source';
import { Card, TipShell } from '../ui';
import { ContributionChart } from './ContributionChart';

export function ForecastReplay() {
  const run = useRun();
  const origins = replayOrigins(run);
  const [origin, setOrigin] = useState(origins[Math.max(0, origins.length - 7)] ?? '');
  const path = useMemo(() => replayPath(run, origin), [run, origin]);
  const prevOrigin = origins[origins.indexOf(origin) - 1];
  const targets = path.filter((p) => prevOrigin && p.horizon <= 11).map((p) => p.period);
  const [target, setTarget] = useState<string | null>(null);
  const shownTarget = target && targets.includes(target) ? target : targets[0] ?? null;
  const revision = shownTarget ? revisionFor(run, origin, shownTarget) : [];
  const scored = path.filter((p) => p.actual !== null && p.scoreable);
  const inside = scored.filter((p) => p.actual! >= p.band[0] && p.actual! <= p.band[1]).length;
  const mae = scored.length ? scored.reduce((s, p) => s + Math.abs(p.actual! - p.forecast), 0) / scored.length : null;

  if (!origins.length) return null;

  return (
    <Card
      icon="calendar"
      title="Forecast replay"
      sub="What the model said at an earlier origin, what happened, and why each forecast moved"
      actions={
        <label className="pfie-row tight">
          <span className="pfie-field">Origin</span>
          <select value={origin} onChange={(e) => { setOrigin(e.target.value); setTarget(null); }}>
            {origins.map((o) => <option key={o} value={o}>{periodLabel(o, 'month')}</option>)}
          </select>
        </label>
      }
    >
      <div className="pfie-grid side">
        <div>
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={path} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef2f0" vertical={false} />
              <XAxis dataKey="short" tick={{ fontSize: 11, fill: '#70827a' }} />
              <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={52} tickFormatter={(v: number) => fmtInt(v)} domain={['auto', 'auto']} />
              <Area dataKey="band" stroke="none" fill="#5b7fa6" fillOpacity={0.16} isAnimationActive={false} />
              <Line dataKey="forecast" stroke="#5b7fa6" strokeDasharray="5 4" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="actual" stroke="#9a4f27" strokeWidth={2} dot={{ r: 2.5 }} connectNulls={false} isAnimationActive={false} />
              <Tooltip
                content={({ active, payload }) => {
                  const p = payload?.[0]?.payload as (typeof path)[number] | undefined;
                  if (!active || !p) return null;
                  return (
                    <TipShell
                      title={`${periodLabel(p.period, 'month')} · ${p.horizon} month${p.horizon === 1 ? '' : 's'} ahead`}
                      rows={[
                        ['Forecast then', `${fmtInt(p.forecast)} L/day`, '#5b7fa6'],
                        ['5–95% range', `${fmtInt(p.band[0])}–${fmtInt(p.band[1])}`],
                        ['Actual', p.actual !== null ? `${fmtInt(p.actual)} L/day` : 'not yet known', '#9a4f27'],
                      ]}
                    />
                  );
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="pfie-legend">
            <span><i className="dash" />Forecast at {periodLabel(origin, 'month')}</span>
            <span><i style={{ background: '#9a4f27' }} />Actual</span>
            {mae !== null && <span>MAE <b>{fmtInt(mae)} L/day</b> over {scored.length} months · {inside}/{scored.length} inside the range</span>}
          </div>
        </div>

        <div>
          {prevOrigin && shownTarget ? (
            <>
              <label className="pfie-row tight" style={{ marginBottom: 10 }}>
                <span className="pfie-field">Revision for</span>
                <select value={shownTarget} onChange={(e) => setTarget(e.target.value)}>
                  {targets.map((t) => <option key={t} value={t}>{periodLabel(t, 'month')}</option>)}
                </select>
              </label>
              <ContributionChart
                parts={revision}
                caption={`How the forecast for ${periodLabel(shownTarget, 'month')} moved from the ${periodLabel(prevOrigin, 'month')} origin to the ${periodLabel(origin, 'month')} origin (${fmtSigned(revision.reduce((s, r) => s + r.value, 0), 1)} L/day).`}
              />
            </>
          ) : (
            <p className="pfie-chart-note">The first origin has no earlier forecast to revise.</p>
          )}
        </div>
      </div>
    </Card>
  );
}
