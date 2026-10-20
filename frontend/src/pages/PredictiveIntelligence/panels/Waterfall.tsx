/**
 * Component 1 (PFOI): milk change, explained.
 *
 * Reads top to bottom: last month → this month → the change, one sentence
 * naming the main reason, then one row per Shapley part with a bar drawn from
 * zero (so no truncated axis), its value and its share of the change. The
 * parts add up exactly to end − start, which is checked here and shown, not
 * assumed.
 */

import { FACTOR_META, addPeriods, fmt1, fmtInt, fmtSigned, periodLabel, type MilkBreakdown } from '../../../data/pfoi';
import { PLAIN_FACTOR } from './ContributionChart';

export function Waterfall({ breakdown }: { breakdown: MilkBreakdown }) {
  const { start, end, parts, isPast, period } = breakdown;
  const change = end - start;
  const before = periodLabel(addPeriods(period, 'month', -1), 'month');
  const now = periodLabel(period, 'month');

  const rows = parts
    .filter((p) => (isPast || p.factor !== 'residual') && Math.abs(p.value) >= 0.05)
    .map((p) => {
      const plain = PLAIN_FACTOR[p.factor];
      return {
        factor: p.factor,
        value: p.value,
        label: plain ? (p.value < 0 ? plain.down : plain.up) : FACTOR_META[p.factor].label,
        why: plain?.why ?? FACTOR_META[p.factor].blurb,
      };
    })
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));

  const maxAbs = Math.max(0.1, ...rows.map((r) => Math.abs(r.value)));
  const gap = Math.abs(rows.reduce((s, r) => s + r.value, 0) - change);
  const direction = Math.abs(change) < 0.5 ? 'flat' : change > 0 ? 'up' : 'down';
  const main = rows.find((r) => r.factor !== 'residual');
  const verb = isPast ? (direction === 'up' ? 'rose' : direction === 'down' ? 'fell' : 'held steady') : direction === 'up' ? 'is expected to rise' : direction === 'down' ? 'is expected to fall' : 'is expected to hold steady';

  // A share of the change only reads cleanly when no reason pushes the other way.
  const mixed = rows.some((r) => Math.sign(r.value) !== Math.sign(change));
  const share = (v: number) => {
    if (direction === 'flat' || mixed) return v >= 0 ? 'adds milk' : 'takes milk away';
    return `${Math.round((v / change) * 100)}% of the change`;
  };

  return (
    <div className="pfie-mx">
      <div className="pfie-mx-sum">
        <div>
          <span className="k">{before}{isPast ? ' (recorded)' : ''}</span>
          <span className="v">{fmtInt(start)}<small> L/day</small></span>
        </div>
        <span className="arrow" aria-hidden>→</span>
        <div>
          <span className="k">{now} ({isPast ? 'recorded' : 'forecast'})</span>
          <span className="v">{fmtInt(end)}<small> L/day</small></span>
        </div>
        <div className={`chg ${direction}`}>
          <span className="k">Change</span>
          <span className="v">{fmtSigned(change, 0)}<small> L/day</small></span>
          <span className="d">{start ? `${fmtSigned((change / start) * 100, 1)}%` : ''}</span>
        </div>
      </div>

      <p className="pfie-mx-lede">
        Milk {verb} by <b>{fmtInt(Math.abs(change))} L/day</b> into {now}.
        {rows[0]?.factor === 'residual' ? (
          <> Most of this is <b>not explained by the model</b>.</>
        ) : main && direction !== 'flat' && Math.sign(main.value) === Math.sign(change) && (
          <> The main reason: <b>{main.label.toLowerCase()}</b> ({fmtSigned(main.value, 0)} L/day).</>
        )}
      </p>

      <div className="pfie-mx-rows">
        {rows.map((r) => {
          const tone = r.factor === 'residual' ? 'other' : r.value >= 0 ? 'up' : 'down';
          const w = (Math.abs(r.value) / maxAbs) * 50;
          return (
            <div className="pfie-mx-row" key={r.factor}>
              <span className="nm">
                <b>{r.factor === 'residual' ? 'Not explained by the model' : r.label}</b>
                <small>{r.factor === 'residual' ? 'Recorded milk minus what the model expected.' : r.why}</small>
              </span>
              <span className="track">
                <i className={tone} style={r.value >= 0 ? { left: '50%', width: `${Math.max(w, 0.8)}%` } : { right: '50%', width: `${Math.max(w, 0.8)}%` }} />
              </span>
              <span className={`val ${tone}`}>
                {fmtSigned(r.value, 1)} L/day
                <small>{r.factor === 'residual' ? '' : share(r.value)}</small>
              </span>
            </div>
          );
        })}
      </div>

      <p className="pfie-chart-note">
        Bars start at zero: right means more milk, left means less. The rows add up to the {fmtSigned(change, 1)} L/day change
        {isPast ? '; the "not explained" row is the gap between recorded milk and the model.' : '; a forecast has no unexplained part.'}
        {gap > 0.5 && ` Rows and change differ by ${fmt1(gap)} L/day — check the attribution rows.`}
      </p>
    </div>
  );
}
