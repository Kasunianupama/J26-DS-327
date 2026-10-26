/**
 * Component 1 (PFOI): Herd & Production → Herd events.
 *
 * Herd events forecast vs recorded, totals over the horizon against the same
 * span a year earlier, and expected mastitis episodes beside what was actually
 * recorded, so a recording gap is visible rather than hidden.
 */

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
  EVENT_SERIES,
  SERIES_META,
  actualRow,
  addPeriods,
  fmt1,
  forecastRow,
  isForecast,
  periodDays,
  periodLabel,
  targetPeriod,
  timeline,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, MonthlyOnly, EmptyState, KindTag, Note, TipShell } from '../ui';
import { MasterTimeline } from '../panels/MasterTimeline';

export function HerdOutcomes() {
  const { grain, horizon } = usePfoi();
  const run = useRun();

  const eventsForecast = isForecast(run, grain, 'calvings');
  const totals = !eventsForecast ? [] : EVENT_SERIES.map((s) => {
    let f = 0; let lo = 0; let hi = 0; let lastYear = 0; let lastYearKnown = true;
    for (let h = 1; h <= horizon; h++) {
      const p = targetPeriod(run, grain, h);
      const r = forecastRow(run, grain, p, s);
      if (r) { f += r.forecast; lo += r.lower; hi += r.upper; }
      const ly = actualRow(run, grain, addPeriods(p, grain, grain === 'month' ? -12 : grain === 'week' ? -52 : -364), s);
      if (ly?.value != null) lastYear += ly.value; else lastYearKnown = false;
    }
    return { s, f, lo, hi, lastYear: lastYearKnown ? lastYear : null };
  });

  /* The rate per cow-day implied by the first forecast month, applied to the
     recorded herd, so the past has an expectation to compare the records with. */
  const first = targetPeriod(run, 'month', 1);
  const mF = forecastRow(run, 'month', first, 'mastitis_episodes');
  const cF = forecastRow(run, 'month', first, 'milking');
  const rate = mF && cF ? mF.forecast / (cF.forecast * periodDays(first, 'month')) : null;
  const mastitis = timeline(run, 'month', 12, 36).map((p) => ({
    period: p.period,
    short: p.short,
    recorded: typeof p.mastitis_episodes === 'number' ? p.mastitis_episodes : null,
    expected: typeof p.mastitis_episodes_f === 'number'
      ? p.mastitis_episodes_f
      : rate !== null && typeof p.milking === 'number' ? Math.round(p.milking * periodDays(p.period, 'month') * rate * 10) / 10 : null,
  }));
  const originShort = periodLabel(targetPeriod(run, 'month', 1), 'month', true);

  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <MasterTimeline bands={['events']} />

      <Card
        title={`Herd events over the next ${horizon} ${grain === 'week' ? 'weeks' : grain === 'month' ? 'months' : 'days'}`}
        sub="Forecast totals with a summed 5–95% range (conservative), against the same span a year earlier"
      >
        {!eventsForecast ? (
          <EmptyState title="Herd events are forecast weekly and monthly">Switch the grain to Week or Month.</EmptyState>
        ) : (
          <div className="pfie-tablewrap">
            <table className="pfie-table">
              <thead>
                <tr><th>Event</th><th className="num">Forecast</th><th className="num">Range</th><th className="num">Same span last year</th></tr>
              </thead>
              <tbody>
                {totals.map((t) => (
                  <tr key={t.s}>
                    <td><i className="sw" style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: SERIES_META[t.s].color, marginRight: 6 }} />{SERIES_META[t.s].label}</td>
                    <td className="num">{fmt1(t.f)}</td>
                    <td className="num">{fmt1(t.lo)}–{fmt1(t.hi)}</td>
                    <td className="num">{t.lastYear !== null ? fmt1(t.lastYear) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title={<>Mastitis: expected vs recorded <MonthlyOnly /></>}
        sub={<>{run.mastitis_rate_period
          ? <>Expected episodes = cows at risk × rate from {run.mastitis_rate_period} <KindTag kind="derived" /></>
          : <>No expected episodes: no mastitis rate from the validation start on</>} · recorded = diagnoses in the records <KindTag kind="measured" /></>}
      >
        <ResponsiveContainer width="100%" height={230}>
          <ComposedChart data={mastitis} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#eef2f0" vertical={false} />
            <XAxis dataKey="short" tick={{ fontSize: 11, fill: '#70827a' }} minTickGap={16} />
            <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={40} />
            <ReferenceLine x={originShort} stroke="#5b7fa6" strokeDasharray="4 3" label={{ value: 'Origin', position: 'insideTopRight', fontSize: 10, fill: '#5b7fa6' }} />
            <Bar dataKey="recorded" fill="#a44b3c" isAnimationActive={false} />
            <Line dataKey="expected" stroke="#5b7fa6" strokeDasharray="5 4" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Tooltip
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as (typeof mastitis)[number] | undefined;
                if (!active || !p) return null;
                return (
                  <TipShell
                    title={periodLabel(p.period, 'month')}
                    rows={[
                      ['Recorded episodes', p.recorded !== null ? fmt1(p.recorded) : '—', '#a44b3c'],
                      ['Expected episodes', p.expected !== null ? fmt1(p.expected) : '—', '#5b7fa6'],
                    ]}
                  />
                );
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <Note tone="caution" title="Herd level only.">
          This is an expectation for the herd, not detection. Individual mastitis detection belongs to Component 3.
        </Note>
      </Card>
    </div>
  );
}
