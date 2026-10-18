/**
 * Component 1 (PFOI): Herd & Production → Herd flow & reproduction.
 *
 * Reproduction shown as what feeds future milking capacity: head by state,
 * the flows between states, and how much of the coming calvings and dry-offs
 * is already fixed at the origin. Herd level only.
 */

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { HORIZONS, fmt1, flowSplit, periodLabel, targetPeriod, type SeriesId } from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, EmptyState, TipShell } from '../ui';
import { HerdStrip } from '../panels/HerdFlow';
import { MasterTimeline } from '../panels/MasterTimeline';

const PIPELINE: SeriesId[] = ['calvings', 'dry_offs'];

export function Reproduction() {
  const { grain } = usePfoi();
  const run = useRun();
  const maxH = HORIZONS[grain][HORIZONS[grain].length - 1];

  const rows = grain === 'day' ? [] : Array.from({ length: maxH }, (_, i) => {
    const period = targetPeriod(run, grain, i + 1);
    const row: Record<string, number | string> = { period, short: periodLabel(period, grain, true) };
    PIPELINE.forEach((s) => {
      const split = flowSplit(run, grain, period, s);
      row[`${s}_det`] = split ? Math.round(split.determined * 10) / 10 : 0;
      row[`${s}_rate`] = split ? Math.round(split.rate_driven * 10) / 10 : 0;
    });
    return row;
  });

  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <HerdStrip />
      <MasterTimeline bands={['herd']} />

      <Card
        title="Calvings and dry-offs ahead"
        sub="Solid: already determined at the origin (recorded conceptions, scheduled dry-offs). Hatched: rate-driven."
      >
        {grain === 'day' ? (
          <EmptyState title="Forecast weekly and monthly">Switch the grain to Week or Month.</EmptyState>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <defs>
                <pattern id="pfieRateCalv" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
                  <rect width="6" height="6" fill="#e3efe8" /><line x1="0" y1="0" x2="0" y2="6" stroke="#3f8c62" strokeWidth="2" />
                </pattern>
                <pattern id="pfieRateDry" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
                  <rect width="6" height="6" fill="#f5ece4" /><line x1="0" y1="0" x2="0" y2="6" stroke="#c99a77" strokeWidth="2" />
                </pattern>
              </defs>
              <CartesianGrid stroke="#eef2f0" vertical={false} />
              <XAxis dataKey="short" tick={{ fontSize: 11, fill: '#70827a' }} />
              <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={40} />
              <Bar dataKey="calvings_det" stackId="c" fill="#3f8c62" isAnimationActive={false} />
              <Bar dataKey="calvings_rate" stackId="c" fill="url(#pfieRateCalv)" isAnimationActive={false} />
              <Bar dataKey="dry_offs_det" stackId="d" fill="#c99a77" isAnimationActive={false} />
              <Bar dataKey="dry_offs_rate" stackId="d" fill="url(#pfieRateDry)" isAnimationActive={false} />
              <Tooltip
                content={({ active, payload }) => {
                  const p = payload?.[0]?.payload as Record<string, number | string> | undefined;
                  if (!active || !p) return null;
                  return (
                    <TipShell
                      title={periodLabel(String(p.period), grain)}
                      rows={[
                        ['Calvings · determined', fmt1(Number(p.calvings_det)), '#3f8c62'],
                        ['Calvings · rate-driven', fmt1(Number(p.calvings_rate))],
                        ['Dry-offs · determined', fmt1(Number(p.dry_offs_det)), '#c99a77'],
                        ['Dry-offs · rate-driven', fmt1(Number(p.dry_offs_rate))],
                      ]}
                    />
                  );
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
        <div className="pfie-legend">
          <span><i style={{ background: '#3f8c62' }} />Calvings</span>
          <span><i style={{ background: '#c99a77' }} />Dry-offs</span>
          <span><i className="hatch" />Rate-driven part</span>
        </div>
      </Card>
    </div>
  );
}
