/**
 * Component 1 (PFOI): ranked attribution parts, in plain language.
 *
 * A diverging bar chart around zero: which reasons push milk up, which pull it
 * down, and by how much. Each row says in farm words what happened ("more cows
 * in milk", "more cows late in lactation") and why it matters. The parts come
 * straight from the attribution rows, so they add up to the change in the
 * summary sentence. Parts with no effect are listed once, not drawn.
 */

import { FACTOR_META, fmtInt, fmtSigned, type Factor } from '../../../data/pfoi';

export interface Contributor {
  factor: Factor;
  value: number;
}

/** What a part means for a farm manager: a name, what an increase / decrease says, and why it matters. */
export const PLAIN_FACTOR: Partial<Record<Factor, { name: string; up: string; down: string; why: string }>> = {
  herd_size: {
    name: 'Cows in milk',
    up: 'More cows in milk',
    down: 'Fewer cows in milk',
    why: 'Each extra cow in milk adds her daily yield to the tank.',
  },
  stage_mix: {
    name: 'Stage of lactation',
    up: 'More cows early in lactation',
    down: 'More cows late in lactation',
    why: 'A cow gives the most milk in the first weeks after calving and less as her lactation goes on.',
  },
  parity_mix: {
    name: 'Age of the cows',
    up: 'More older cows',
    down: 'More first-lactation cows',
    why: 'Cows in their first lactation give less milk than cows that have calved before.',
  },
  pregnancy_mix: {
    name: 'Late pregnancy',
    up: 'Fewer cows in late pregnancy',
    down: 'More cows in late pregnancy',
    why: 'Cows more than about five months pregnant give less milk.',
  },
  yield_level: {
    name: 'Yield per cow',
    up: 'Cows milking above their expected level',
    down: 'Cows milking below their expected level',
    why: 'How well the cows milk compared with what their stage and age predict. A forecast keeps it at the last recorded level.',
  },
  thi: {
    name: 'Heat stress',
    up: 'Less heat stress',
    down: 'More heat stress',
    why: 'Hot, humid days lower feed intake and milk. Forecasts use the usual weather for the month, not a weather forecast.',
  },
  mastitis: {
    name: 'Mastitis',
    up: 'Fewer mastitis cases',
    down: 'More mastitis cases',
    why: 'Udder infections cut the yield of the cows affected.',
  },
  residual: {
    name: 'Not explained by the model',
    up: 'More milk than the model expected',
    down: 'Less milk than the model expected',
    why: 'Recorded milk minus the model: feeding, management, recording and anything else the model does not see.',
  },
};

const NO_EFFECT = 0.05;

export interface ChangeSummary {
  fromLabel: string;
  toLabel: string;
  start: number;
  end: number;
  isPast: boolean;
}

export function ContributionChart({
  parts,
  unit = 'L/day',
  caption,
  summary,
  facts,
}: {
  parts: Contributor[];
  unit?: string;
  caption?: string;
  /** When given, the chart opens with one sentence: from what, to what, by how much. */
  summary?: ChangeSummary;
  /** Extra plain facts per part, e.g. "about 4 more cows in milk". */
  facts?: Partial<Record<Factor, string>>;
}) {
  const ranked = [...parts].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  const shown = ranked.filter((c) => Math.abs(c.value) >= NO_EFFECT);
  const quiet = ranked.filter((c) => Math.abs(c.value) < NO_EFFECT);
  const largest = Math.max(1e-6, ...shown.map((c) => Math.abs(c.value)));
  const total = parts.reduce((s, p) => s + p.value, 0);

  return (
    <figure className="pfie-contrib-chart">
      {summary ? <SummaryLine s={summary} unit={unit} /> : caption && <figcaption>{caption}</figcaption>}
      {summary && <p className="pfie-contrib-lead">The reasons, biggest first:</p>}

      <div className="pfie-contrib-plot">
        <div className="pfie-contrib-row pfie-contrib-head" aria-hidden>
          <span />
          <span className="track"><em className="l">◀ pulls milk down</em><em className="r">pushes milk up ▶</em></span>
          <span />
        </div>
        {shown.map((c, i) => {
          const direction = c.value < 0 ? 'negative' : 'positive';
          const width = Math.max(1.5, (Math.abs(c.value) / largest) * 50);
          const plain = PLAIN_FACTOR[c.factor];
          const headline = plain ? (c.value < 0 ? plain.down : plain.up) : FACTOR_META[c.factor].label;
          return (
            <div className="pfie-contrib-row" key={c.factor} style={{ animationDelay: `${0.05 + i * 0.05}s` }}>
              <span className="nm" title={FACTOR_META[c.factor].blurb}>
                <b>{headline}</b>
                <small>{facts?.[c.factor] ? `${facts[c.factor]}. ` : ''}{plain?.why ?? FACTOR_META[c.factor].blurb}</small>
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

      {quiet.length > 0 && (
        <p className="pfie-contrib-quiet">
          No effect this time: {quiet.map((c) => PLAIN_FACTOR[c.factor]?.name ?? FACTOR_META[c.factor].label).join(', ')}
          {quiet.some((c) => c.factor === 'yield_level') && summary && !summary.isPast && ' (a forecast keeps yield per cow at the last recorded level)'}.
        </p>
      )}
      <p className="pfie-contrib-total">
        Together these add up to <b>{fmtSigned(total, 1)} {unit}</b>.
      </p>
    </figure>
  );
}

function SummaryLine({ s, unit }: { s: ChangeSummary; unit: string }) {
  const change = s.end - s.start;
  const pct = s.start ? (change / s.start) * 100 : 0;
  const dir = Math.abs(change) < NO_EFFECT ? 'flat' : change > 0 ? 'up' : 'down';
  const verb = s.isPast ? (dir === 'up' ? 'rose' : dir === 'down' ? 'fell' : 'held') : dir === 'up' ? 'is expected to rise' : dir === 'down' ? 'is expected to fall' : 'is expected to hold';
  return (
    <p className={`pfie-contrib-summary ${dir}`}>
      Milk {verb} from <b>{fmtInt(s.start)} {unit}</b> in {s.fromLabel} to <b>{fmtInt(s.end)} {unit}</b> in {s.toLabel}
      {dir !== 'flat' && <> — <b className="chg">{fmtSigned(change, 1)} {unit} ({fmtSigned(pct, 1)}%)</b></>}.
    </p>
  );
}
