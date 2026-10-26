/**
 * Simple view, "One date" tab: every number for the chosen day, week or month
 * with its likely range. Picking a date also moves the herd movement picture to it.
 */

import { useEffect } from 'react';
import {
  EVENT_SERIES, STOCK_SERIES, confidenceOf, firstTarget, isForecast, type SeriesId,
} from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { useTimelinePoints } from '../panels/MasterTimeline';
import { periodText, useLang, useT } from './i18n';
import { Fact, valueAt } from './PointExplain';
import { Box, Explain, HISTORY, PLAIN_CONFIDENCE, PLAIN_SERIES, SimpleTable, about, hasRange, litres, whole } from './common';

const SERIES: SeriesId[] = [...STOCK_SERIES, ...EVENT_SERIES, 'mastitis_episodes'];

export function PeriodTab() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, selectedPeriod, setSelectedPeriod } = usePfoi();
  const points = useTimelinePoints();
  const start = firstTarget(run, grain);
  const firstFuture = points.findIndex((p) => p.future);
  /* Recent history and the forecast; plus whatever the herd movement player is on. */
  const options = points.filter((p, i) => p.future || i >= firstFuture - HISTORY[grain] || p.period === selectedPeriod);
  const period = selectedPeriod && options.some((p) => p.period === selectedPeriod)
    ? selectedPeriod
    : options.find((p) => p.future)?.period ?? options[options.length - 1]?.period;
  useEffect(() => { if (period && selectedPeriod !== period) setSelectedPeriod(period); }, [period, selectedPeriod, setSelectedPeriod]);
  if (!period) return null;
  const future = period >= start;

  const fmt = (s: SeriesId, v: number) => (STOCK_SERIES.includes(s) ? whole(v) : about(v));
  const milk = valueAt(run, grain, 'milk_litres', period);
  const cows = valueAt(run, grain, 'milking', period);
  const conf = milk?.q ? PLAIN_CONFIDENCE[confidenceOf(milk.q)] : null;

  return (
    <Box
      title={`${periodText(period, grain, lang)}`}
      sub={future ? t('Expected') : t('Recorded')}
      actions={
        <label className="pfie-mgr-select">{t('Date')}
          <select value={period} onChange={(e) => setSelectedPeriod(e.target.value)}>
            {[...options].reverse().map((p) => <option key={p.period} value={p.period}>{periodText(p.period, grain, lang)} {p.future ? `(${t('expected')})` : `(${t('recorded')})`}</option>)}
          </select>
        </label>
      }
    >
      <div className="pfie-mgr-facts">
        <Fact label={t('Milk a day')} value={milk ? `${litres(milk.v)} L` : '—'}
          sub={milk && hasRange(milk.lo, milk.hi) ? t('likely {a} – {b}', { a: litres(milk.lo!), b: litres(milk.hi!) }) : undefined} />
        <Fact label={t('Cows in milk')} value={cows ? whole(cows.v) : '—'} />
        <Fact label={t('Milk per cow')} value={milk && cows?.v ? `${(milk.v / cows.v).toFixed(1)} L` : '—'} />
        {conf && <Fact label={t('Reliability')} value={`${conf.dots} ${t(conf.label)}`} />}
      </div>

      <SimpleTable
        head={future ? ['', t('Expected'), t('Likely low'), t('Likely high')] : ['', t('Recorded')]}
        rows={SERIES.filter((s) => s !== 'milking').map((s) => {
          const x = valueAt(run, grain, s, period);
          const range = x && hasRange(x.lo, x.hi);
          return future
            ? [t(PLAIN_SERIES[s]), <b>{x ? fmt(s, x.v) : '—'}</b>, range ? fmt(s, x!.lo!) : '—', range ? fmt(s, x!.hi!) : '—']
            : [t(PLAIN_SERIES[s]), <b>{x ? fmt(s, x.v) : '—'}</b>];
        })}
      />

      {future && isForecast(run, grain, 'calvings') && (
        <Explain>{t('"Already known" means the records already show it, for example a calving from a confirmed pregnancy. The rest is estimated from recent rates.')}</Explain>
      )}
    </Box>
  );
}
