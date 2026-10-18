/**
 * Component 1 (PFOI): ranked attribution parts.
 *
 * A diverging bar chart around zero: which factors push a change up, which
 * pull it down, and by how much. The parts come straight from the attribution
 * rows, so they add up to the change shown beside the chart.
 */

import { FACTOR_META, fmtSigned, type Factor } from '../../../data/pfoi';
import { KindTag } from '../ui';

export interface Contributor {
  factor: Factor;
  value: number;
}

export function ContributionChart({ parts, unit = 'L/day', caption }: { parts: Contributor[]; unit?: string; caption?: string }) {
  const ranked = [...parts].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  const largest = Math.max(1e-6, ...ranked.map((c) => Math.abs(c.value)));
  const total = parts.reduce((s, p) => s + p.value, 0);

  return (
    <figure className="pfie-contrib-chart">
      <figcaption>
        {caption ?? 'Largest effect first. Bars left of the line reduce the value, bars right of it add to it.'}
      </figcaption>
      <div className="pfie-contrib-plot">
        {ranked.map((c, i) => {
          const direction = Math.abs(c.value) < 0.05 ? 'neutral' : c.value < 0 ? 'negative' : 'positive';
          const width = Math.max(1.5, (Math.abs(c.value) / largest) * 50);
          return (
            <div className="pfie-contrib-row" key={c.factor} style={{ animationDelay: `${0.05 + i * 0.05}s` }}>
              <span className="nm" title={FACTOR_META[c.factor].blurb}>
                {FACTOR_META[c.factor].label} <KindTag kind={FACTOR_META[c.factor].kind} />
              </span>
              <span className="track">
                <i
                  className={direction}
                  style={direction === 'negative' ? { right: '50%', width: `${width}%` } : { left: '50%', width: `${width}%` }}
                />
              </span>
              <span className={`val ${direction}`}>{fmtSigned(c.value, 1)} {unit}</span>
            </div>
          );
        })}
      </div>
      <div className="pfie-legend">
        <span><i style={{ background: 'var(--concern)' }} />Reduces</span>
        <span><i style={{ background: 'var(--brand)' }} />Adds</span>
        <span>Parts add up to <b>{fmtSigned(total, 1)} {unit}</b></span>
      </div>
    </figure>
  );
}
