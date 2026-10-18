/**
 * Component 1 (PFOI): milk change waterfall.
 *
 * Start value, one step per Shapley part, end value. The parts add up exactly
 * to end − start, which is checked here and shown, not assumed. The axis is
 * zoomed to the range the steps cover, and says so.
 */

import { FACTOR_META, fmtInt, fmtSigned, periodLabel, type MilkBreakdown } from '../../../data/pfoi';
import { KindTag } from '../ui';

export function Waterfall({ breakdown }: { breakdown: MilkBreakdown }) {
  const { start, end, parts, isPast, period } = breakdown;
  const steps: { label: string; from: number; to: number; kind: 'anchor' | 'increase' | 'decrease' | 'total'; factor?: MilkBreakdown['parts'][number]['factor'] }[] = [];
  steps.push({ label: isPast ? 'Previous month (actual)' : 'Previous month (model)', from: start, to: start, kind: 'anchor' });
  let at = start;
  parts.forEach((p) => {
    if (!isPast && p.factor === 'residual') return;
    steps.push({ label: FACTOR_META[p.factor].label, from: at, to: at + p.value, kind: p.value < 0 ? 'decrease' : 'increase', factor: p.factor });
    at += p.value;
  });
  steps.push({ label: `${periodLabel(period, 'month')} (${isPast ? 'actual' : 'forecast'})`, from: end, to: end, kind: 'total' });

  const values = steps.flatMap((s) => [s.from, s.to]);
  const span = Math.max(1, Math.max(...values) - Math.min(...values));
  const lo = Math.min(...values) - span * 0.6;
  const hi = Math.max(...values) + span * 0.15;
  const pct = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const gap = Math.abs(at - end);

  return (
    <div>
      <div className="pfie-wf">
        {steps.map((s) => {
          const anchor = s.kind === 'anchor' || s.kind === 'total';
          const left = anchor ? 0 : pct(Math.min(s.from, s.to));
          const width = anchor ? pct(s.to) : Math.max(0.6, pct(Math.max(s.from, s.to)) - pct(Math.min(s.from, s.to)));
          return (
            <div className={`step ${s.kind}`} key={s.label} title={s.factor ? FACTOR_META[s.factor].blurb : undefined}>
              <span className="nm">
                {s.label} {s.factor && <KindTag kind={FACTOR_META[s.factor].kind} />}
              </span>
              <span className="track"><i className={`fill ${s.kind}`} style={{ left: `${left}%`, width: `${width}%` }} /></span>
              <span className="v">{anchor ? `${fmtInt(s.to)} L/day` : `${fmtSigned(s.to - s.from, 1)}`}</span>
            </div>
          );
        })}
      </div>
      <p className="pfie-chart-note">
        Axis starts at {fmtInt(lo)} L/day so the parts are visible.{' '}
        {isPast
          ? 'Past months keep an "Unexplained" part: actual minus model.'
          : 'A forecast has no unexplained part: it is fully explained by construction.'}
        {gap > 0.5 && ` Parts and change differ by ${gap.toFixed(1)} L/day — check the attribution rows.`}
      </p>
    </div>
  );
}
