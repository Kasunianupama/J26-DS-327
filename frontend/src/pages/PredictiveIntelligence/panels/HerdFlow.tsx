/**
 * Component 1 (PFOI): aggregate herd flow.
 *
 * Head counts by state now and at the horizon, and the flows between them over
 * the horizon. Each flow is split into what is already determined at the
 * origin (calvings from recorded conceptions, for example) and what is
 * rate-driven, which is where the uncertainty sits. No individual animals.
 */

import {
  SERIES_META,
  flowTotals,
  fmt1,
  fmtInt,
  headline,
  lastActual,
  periodLabel,
  type SeriesId,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, EmptyState, KindTag } from '../ui';

const NODES: SeriesId[] = ['calves', 'heifers', 'milking', 'dry', 'other', 'total_herd'];
const FLOWS: { series: SeriesId; route: string }[] = [
  { series: 'entries', route: 'Births and entries → calves' },
  { series: 'calvings', route: 'Heifers and dry cows → milking' },
  { series: 'dry_offs', route: 'Milking → dry' },
  { series: 'abortions', route: 'Pregnancies lost' },
  { series: 'culls_sales', route: 'Culls and sales → exit' },
  { series: 'deaths', route: 'Deaths → exit' },
];

export function HerdStrip() {
  const { grain, horizon } = usePfoi();
  const run = useRun();

  if (grain === 'day') {
    return (
      <Card icon="herd" title="Herd flow">
        <EmptyState title="Herd flow is forecast weekly and monthly">
          Switch the grain to Week or Month to see head counts at the horizon and the flows between states.
        </EmptyState>
      </Card>
    );
  }

  const totals = FLOWS.map((f) => ({ ...f, ...flowTotals(run, grain, horizon, f.series) }));
  const largest = Math.max(1, ...totals.map((t) => t.total));
  const target = headline(run, grain, horizon, 'milking')?.period;

  return (
    <Card
      icon="herd"
      title="Herd flow"
      sub={`Head by state now and in ${target ? periodLabel(target, grain) : 'the horizon period'}, and the flows over the next ${horizon} ${grain === 'week' ? 'weeks' : 'months'}`}
    >
      <div className="pfie-flowmap">
        {NODES.map((s) => {
          const now = lastActual(run, grain, s);
          const h = headline(run, grain, horizon, s);
          return (
            <div className="node" key={s} style={{ borderColor: SERIES_META[s].color }}>
              <div className="nm">{SERIES_META[s].label}</div>
              <div className="ct">{h ? fmtInt(h.value) : '—'}</div>
              {h && <div className="rg">range {fmtInt(h.lower)}–{fmtInt(h.upper)}</div>}
              <div className="now">now {now ? fmtInt(now.value) : '—'}</div>
            </div>
          );
        })}
      </div>

      <div className="pfie-flowlinks">
        {totals.map((t) => (
          <div className="pfie-flowlink" key={t.series}>
            <span>
              <b>{SERIES_META[t.series].label}</b>
              <small style={{ display: 'block', color: 'var(--muted)' }}>{t.route}</small>
            </span>
            <span className="bar" title={`${fmt1(t.determined)} already determined · ${fmt1(t.rate)} rate-driven`}>
              <i className="det" style={{ width: `${(t.determined / largest) * 100}%` }} />
              <i className="rate" style={{ width: `${(t.rate / largest) * 100}%` }} />
            </span>
            <span className="v">{fmt1(t.total)}</span>
          </div>
        ))}
      </div>
      <div className="pfie-legend">
        <span><i style={{ background: 'var(--brand)' }} />Already determined at the origin <KindTag kind="measured" /></span>
        <span><i className="hatch" />Rate-driven, from the trailing window <KindTag kind="derived" /></span>
      </div>
    </Card>
  );
}
