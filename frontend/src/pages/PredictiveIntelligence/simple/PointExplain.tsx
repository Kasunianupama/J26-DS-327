/**
 * Simple view: click a point on a chart (or a row in a table) and get it
 * explained in plain words, right under the chart. Follows the Daily / Weekly /
 * Monthly switch; the milk reasons are worked out by month.
 */

import { useState } from 'react';
import {
  EVENT_SERIES, actualRow, addPeriods, confidenceOf, firstTarget, flowSplit, forecastRow, milkBreakdown, periodDays,
  periodStart, perDay, realisedRow, type Grain, type PfoiRun, type SeriesId,
} from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { Rich, dateLabel, periodText, useLang, useT, type T } from './i18n';
import { Reasons } from './Reasons';
import { PLAIN_CONFIDENCE, PLAIN_SERIES, SimpleTable, about, hasRange, litres, pct, useNav, whole, yearBefore } from './common';

export type PointKind = 'milk' | 'herd' | 'events' | 'mastitis' | 'heat';

/** Which point is picked in one chart, and the handlers that pick it. */
export type PointSelection = { picked: string | null; pick: (at: string | null) => void };

export function usePointPick(controlled?: PointSelection) {
  const [localPicked, setLocalPicked] = useState<string | null>(null);
  const picked = controlled ? controlled.picked : localPicked;
  const setPicked = controlled ? controlled.pick : setLocalPicked;
  /* Recharts passes the clicked category; its row carries `period` (or `date` for days). */
  const onChartClick = (state: { activePayload?: { payload?: Record<string, unknown> }[] } | null) => {
    const row = state?.activePayload?.[0]?.payload;
    const key = (row?.period ?? row?.date) as string | undefined;
    if (key) setPicked(picked === key ? null : key);
  };
  return { picked, pick: setPicked, clear: () => setPicked(null), onChartClick };
}

export function PickHint({ picked }: { picked: string | null }) {
  const t = useT();
  /* Once a point is open, its Close button says how to hide it. */
  return picked ? null : <p className="pfie-mgr-hint pfie-noprint">{t('Click a point or a row to explain it.')}</p>;
}

export function PointExplanation({ kind, at, onClose, series }: { kind: PointKind; at: string; onClose: () => void; series?: SeriesId[] }) {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain: g, setSelectedPeriod } = usePfoi();
  const { go } = useNav();
  /* Mastitis is shown by month; heat by day; the rest at the selected grain. */
  const grain: Grain = kind === 'mastitis' ? 'month' : kind === 'heat' ? 'day' : g;
  const title = kind === 'heat' ? dateLabel(at, lang) : periodText(at, grain, lang);
  return (
    <div className={`pfie-mgr-point pfie-mgr-point-${kind}`} role="region" aria-label={`${t(kind === 'milk' ? 'Total Milk Yield' : kind === 'herd' ? 'Herd population' : kind === 'events' ? 'Herd events' : 'Date')} · ${title}`}>
      <div className="pfie-mgr-point-head">
        <b>{kind === 'milk' ? `${t('Total Milk Yield')} · ` : kind === 'herd' ? `${t('Herd population')} · ` : kind === 'events' ? `${t('Herd events')} · ` : ''}{title}</b>
        <span className="spacer" />
        {kind !== 'heat' && kind !== 'mastitis' && (
          <button className="pfie-btn" onClick={() => { setSelectedPeriod(at); go('period'); }}>{t('All numbers for this date')}</button>
        )}
        <button className="pfie-btn" onClick={onClose}>{t('Close')} ✕</button>
      </div>
      {kind === 'milk' && <MilkPoint run={run} t={t} grain={grain} period={at} />}
      {kind === 'herd' && <HerdPoint run={run} t={t} grain={grain} period={at} />}
      {kind === 'events' && <EventsPoint run={run} t={t} grain={grain} period={at} series={series} />}
      {kind === 'mastitis' && <MastitisPoint run={run} t={t} period={at} />}
      {kind === 'heat' && <HeatPoint run={run} t={t} date={at} />}
    </div>
  );
}

/* ------------------------------------------------------------------ helpers */

export function valueAt(run: PfoiRun, grain: Grain, s: SeriesId, period: string) {
  const future = period >= firstTarget(run, grain);
  if (future) {
    const f = forecastRow(run, grain, period, s);
    return f ? { future, v: perDay(s, f.forecast, grain, period), lo: perDay(s, f.lower, grain, period), hi: perDay(s, f.upper, grain, period), q: f.quality_flag } : null;
  }
  const a = actualRow(run, grain, period, s);
  return a?.value != null ? { future, v: perDay(s, a.value, grain, period), lo: null, hi: null, q: null } : null;
}

type P = { run: PfoiRun; t: T; grain: Grain; period: string };

export function Fact({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="pfie-mgr-fact">
      <span className="lbl">{label}</span>
      <b>{value}</b>
      {sub && <small>{sub}</small>}
    </div>
  );
}

/* ------------------------------------------------------------------ kinds */

function MilkPoint({ run, t, grain, period }: P) {
  const { lang } = useLang();
  const x = valueAt(run, grain, 'milk_litres', period);
  const cows = valueAt(run, grain, 'milking', period);
  const lyP = yearBefore(period, grain);
  const ly = actualRow(run, grain, lyP, 'milk_litres');
  const lastYear = ly?.value != null ? perDay('milk_litres', ly.value, grain, lyP) : null;
  const real = realisedRow(run, grain, period, 'milk_litres');
  const actual = real?.value != null && real.scoreable ? perDay('milk_litres', real.value, grain, period) : null;
  const month = periodStart(period, 'month');
  const bd = milkBreakdown(run, month);
  if (!x) return <p className="pfie-mgr-note">{t('No milk number for this date.')}</p>;
  const conf = x.q ? PLAIN_CONFIDENCE[confidenceOf(x.q)] : null;
  const vsLy = lastYear ? Math.round(((x.v - lastYear) / lastYear) * 100) : null;
  const inside = actual !== null && x.lo != null && x.hi != null && actual >= x.lo && actual <= x.hi;

  return (
    <>
      <div className="pfie-mgr-point-body">
      <div className="pfie-mgr-facts">
        <Fact label={x.future ? t('Expected milk a day') : t('Milk a day (recorded)')} value={`${litres(x.v)} L`}
          sub={x.future ? (hasRange(x.lo, x.hi) ? t('likely {a} – {b}', { a: litres(x.lo!), b: litres(x.hi!) }) : t('no likely range published')) : undefined} />
        {cows && cows.v > 0 && <Fact label={t('Cows in milk')} value={whole(cows.v)} sub={t('{n} L per cow', { n: (x.v / cows.v).toFixed(1) })} />}
        {vsLy !== null && <Fact label={t('A year before')} value={`${litres(lastYear!)} L`} sub={vsLy === 0 ? t('about the same') : vsLy > 0 ? t('{n}% more now', { n: vsLy }) : t('{n}% less now', { n: -vsLy })} />}
        {actual !== null && <Fact label={t('What actually happened')} value={`${litres(actual)} L`} sub={inside ? t('inside the likely range') : t('outside the likely range')} />}
        {conf && <Fact label={t('Reliability')} value={conf.dots} sub={t(conf.label)} />}
      </div>
      <div className="pfie-mgr-point-reasons">
      {bd ? (
        <>
          {grain !== 'month' && <p className="pfie-mgr-tagline">{t('Reasons for the whole month of {m}:', { m: periodText(month, 'month', lang) })}</p>}
          <Reasons
            parts={bd.parts.filter((p) => bd.isPast || p.factor !== 'residual')}
            start={bd.start} end={bd.end} isPast={bd.isPast}
            fromLabel={periodText(addPeriods(month, 'month', -1), 'month', lang)} toLabel={periodText(month, 'month', lang)}
          />
        </>
      ) : <p className="pfie-mgr-note">{t('No reasons are published for this month.')}</p>}
      </div>
      </div>
    </>
  );
}

const GROUPS: SeriesId[] = ['milking', 'dry', 'heifers', 'calves', 'other', 'total_herd'];

function HerdPoint({ run, t, grain, period }: P) {
  const { lang } = useLang();
  const prev = addPeriods(period, grain, -1);
  const calv = valueAt(run, grain, 'calvings', period);
  const dry = valueAt(run, grain, 'dry_offs', period);
  const actuals = GROUPS.map((s) => period >= firstTarget(run, grain) ? realisedRow(run, grain, period, s) : undefined);
  const realised = actuals.some((a) => a?.scoreable && a.value != null);
  return (
    <>
      {calv && dry && <p className="pfie-mgr-lead"><Rich text={t('About **{c}** cows calve and start milking, and about **{d}** are dried off.', { c: about(calv.v), d: about(dry.v) })} /></p>}
      <SimpleTable
        head={[t('Group'), t('Animals'), t('Likely range'), t('Change from {p}', { p: periodText(prev, grain, lang) }), ...(realised ? [t('What actually happened')] : [])]}
        rows={GROUPS.map((s, i) => {
          const now = valueAt(run, grain, s, period);
          const before = valueAt(run, grain, s, prev);
          const d = now && before ? Math.round(now.v - before.v) : null;
          return [
            s === 'total_herd' ? <b>{t(PLAIN_SERIES[s])}</b> : t(PLAIN_SERIES[s]),
            <b>{now ? whole(now.v) : '—'}</b>,
            now && hasRange(now.lo, now.hi) ? `${whole(now.lo!)} – ${whole(now.hi!)}` : '—',
            d === null ? '—' : <span className={d > 0 ? 'up' : d < 0 ? 'down' : ''}>{d > 0 ? '▲ +' : d < 0 ? '▼ −' : ''}{whole(Math.abs(d))}</span>,
            ...(realised ? [actuals[i]?.scoreable && actuals[i]?.value != null ? whole(actuals[i]!.value!) : '—'] : []),
          ];
        })}
      />
    </>
  );
}

function EventsPoint({ run, t, grain, period, series }: P & { series?: SeriesId[] }) {
  const future = period >= firstTarget(run, grain);
  const shown = series ?? [...EVENT_SERIES, 'mastitis_episodes' as SeriesId];
  return (
    <SimpleTable
      head={future ? [t('Event'), t('Expected'), t('Likely range'), t('Already known')] : [t('Event'), t('Recorded')]}
      rows={shown.map((s) => {
        const x = valueAt(run, grain, s, period);
        if (!future) return [t(PLAIN_SERIES[s]), <b>{x ? about(x.v) : '—'}</b>];
        const split = flowSplit(run, grain, period, s);
        const total = split ? split.determined + split.rate_driven : 0;
        return [t(PLAIN_SERIES[s]), <b>{x ? about(x.v) : '—'}</b>, x && hasRange(x.lo, x.hi) ? `${about(x.lo!)} – ${about(x.hi!)}` : '—', split && total ? pct(split.determined / total) : '—'];
      })}
    />
  );
}

function MastitisPoint({ run, t, period }: Omit<P, 'grain'>) {
  const rec = actualRow(run, 'month', period, 'mastitis_episodes')?.value ?? null;
  const f = forecastRow(run, 'month', period, 'mastitis_episodes');
  const first = firstTarget(run, 'month');
  const mF = forecastRow(run, 'month', first, 'mastitis_episodes');
  const cF = forecastRow(run, 'month', first, 'milking');
  const cows = actualRow(run, 'month', period, 'milking')?.value;
  const expected = f ? f.forecast
    : mF && cF && cows != null ? (mF.forecast / (cF.forecast * periodDays(first, 'month'))) * cows * periodDays(period, 'month') : null;
  return (
    <>
      <div className="pfie-mgr-facts">
        {rec !== null && <Fact label={t('Recorded cases')} value={about(rec)} />}
        {expected !== null && <Fact label={t('Expected cases')} value={about(expected)} />}
      </div>
      {rec !== null && expected !== null && (
        <p className="pfie-mgr-lead">
          {rec < expected * 0.5 ? `${t('Far fewer recorded than expected: some cases may not be written down.')}`
            : rec > expected * 1.5 ? `${t('More recorded than expected: worth checking with the vet.')}`
              : `${t('Close to the usual rate.')}`}
        </p>
      )}
    </>
  );
}

function HeatPoint({ run, t, date }: { run: PfoiRun; t: T; date: string }) {
  const h = run.heat;
  if (!h) return null;
  const rec = h.recent.find((d) => d.date === date)?.thi_max ?? null;
  const actual = date >= run.origin_date ? h.realised?.find((d) => d.date === date)?.thi_max ?? null : null;
  const usual = h.climatology.find((c) => c.date === date);
  const day = h.forecast?.status === 'experimental' ? h.forecast.predictions.find((d) => d.date === date) : undefined;
  const predicted = day?.thi_max ?? null;
  const pct = (v: number) => `${Math.round(100 * v)}%`;
  const peak = h.knot_p75;
  const v = actual ?? rec ?? predicted ?? usual?.p50 ?? null;
  return (
    <>
      <div className="pfie-mgr-facts">
        {rec !== null && <Fact label={t('Recorded heat')} value={`${rec.toFixed(1)} THI`} />}
        {actual !== null && <Fact label={t('What actually happened')} value={`${actual.toFixed(1)} THI`} />}
        {predicted !== null && <Fact label={t('Model predicted THI (experimental)')} value={`${predicted.toFixed(1)} THI`}
          sub={day?.lower != null && day.upper != null ? `${day.lower.toFixed(1)} – ${day.upper.toFixed(1)}` : undefined} />}
        {day?.p_above?.p75 != null && <Fact label={t('Chance of a hot day')} value={pct(day.p_above.p75)}
          sub={usual?.share_above_p75 != null ? t('usual {n}', { n: pct(usual.share_above_p75) }) : undefined} />}
        {day?.p_above?.p90 != null && <Fact label={t('Chance of a very hot day')} value={pct(day.p_above.p90)}
          sub={usual?.share_above_p90 != null ? t('usual {n}', { n: pct(usual.share_above_p90) }) : undefined} />}
        {actual !== null && predicted !== null && <Fact label={t('Actual minus model prediction')} value={`${(actual - predicted).toFixed(1)} THI`} />}
        {actual !== null && usual && <Fact label={t('Actual minus outlook')} value={`${(actual - usual.p50).toFixed(1)} THI`} />}
        {usual && <Fact label={t('Usual in past years')} value={String(Math.round(usual.p50))} sub={`${Math.round(usual.p10)} – ${Math.round(usual.p90)}`} />}
        {peak !== null && <Fact label={t('Hot (hotter than 75% of past days)')} value={peak.toFixed(1)} />}
      </div>
      {v !== null && peak !== null && (
        <p className="pfie-mgr-lead">{t(v > peak ? 'Above the hot threshold: greater heat stress risk.' : 'At or below the hot threshold; this does not guarantee no heat stress.')}</p>
      )}
    </>
  );
}
