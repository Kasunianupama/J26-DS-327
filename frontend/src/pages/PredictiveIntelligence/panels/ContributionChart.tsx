/**
 * Ranked-contributor chart for a point explanation.
 *
 * A diverging bar chart around a zero axis: it shows at a glance which drivers
 * push the point up and which pull it down, and how far apart they are. The
 * numbered list underneath still carries the mechanism and the evidence — this
 * only makes the shape of the explanation visible before you read it.
 */

import type { ForecastContributor } from '../../../data/component2';

export function ContributionChart({ contributors }: { contributors: ForecastContributor[] }) {
  const ranked = [...contributors].sort((a, b) => b.magnitude - a.magnitude);
  const largest = Math.max(1, ...ranked.map((c) => c.magnitude));

  return (
    <figure className="pfie-contrib-chart">
      <figcaption>
        Effect on this point, largest first. Bars left of the line reduce it, bars right of it add to it.
      </figcaption>
      <div className="pfie-contrib-plot">
        {ranked.map((c, i) => {
          const width = Math.max(3, (c.magnitude / largest) * 50);
          const negative = c.direction === 'negative';
          return (
            <div className="pfie-contrib-row" key={c.label} style={{ animationDelay: `${0.05 + i * 0.05}s` }}>
              <span className="nm" title={c.label}>{c.label}</span>
              <span className="track">
                <i
                  className={c.direction}
                  style={negative
                    ? { right: '50%', width: `${width}%` }
                    : { left: '50%', width: `${c.direction === 'neutral' ? 1.5 : width}%` }}
                />
              </span>
              <span className={`val ${c.direction}`}>{c.effect}</span>
            </div>
          );
        })}
      </div>
      <div className="pfie-legend">
        <span><i style={{ background: 'var(--concern)' }} />Reduces this point</span>
        <span><i style={{ background: 'var(--brand)' }} />Adds to this point</span>
        <span><i style={{ background: 'var(--muted)' }} />No net displayed effect</span>
      </div>
    </figure>
  );
}
