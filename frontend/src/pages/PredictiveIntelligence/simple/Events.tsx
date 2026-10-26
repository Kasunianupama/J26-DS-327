/**
 * Simple view, "Herd events" tab: totals over the look ahead against a year
 * before and the expected events per day / week / month.
 */

import { useState } from 'react';
import {
  EVENT_SERIES, actualRow, forecastRow, isForecast, targetPeriod, type SeriesId,
} from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { aheadText, periodText, useLang, useT } from './i18n';
import { PickHint, PointExplanation, usePointPick } from './PointExplain';
import { Box, NotInRun, PLAIN_SERIES, SimpleTable, about, yearBefore } from './common';

const COLS: SeriesId[] = [...EVENT_SERIES, 'mastitis_episodes'];

export function EventsTab() {
  const run = useRun();
  const t = useT();
  const { grain } = usePfoi();
  if (!isForecast(run, grain, 'calvings')) return <Box title={t('Herd events')}><NotInRun /></Box>;
  return (
    <>
      <Totals />
      <ByPeriod />
    </>
  );
}

function Totals() {
  const run = useRun();
  const t = useT();
  const { grain, horizon } = usePfoi();
  const rows = EVENT_SERIES.map((s) => {
    let f = 0; let lo = 0; let hi = 0; let ly = 0; let lyKnown = true;
    for (let h = 1; h <= horizon; h++) {
      const p = targetPeriod(run, grain, h);
      const r = forecastRow(run, grain, p, s);
      if (r) { f += r.forecast; lo += r.lower; hi += r.upper; }
      const a = actualRow(run, grain, yearBefore(p, grain), s);
      if (a?.value != null) ly += a.value; else lyKnown = false;
    }
    return [<b>{t(PLAIN_SERIES[s])}</b>, <b>{about(f)}</b>, `${about(lo)} – ${about(hi)}`, lyKnown ? about(ly) : '—'];
  });
  return (
    <Box title={`${t('Herd events')} · ${aheadText(t, grain, horizon)}`}>
      <SimpleTable head={[t('Event'), t('Expected'), t('Likely range'), t('A year before')]} rows={rows} />
    </Box>
  );
}

function ByPeriod() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();
  const [all, setAll] = useState(false);
  const periods = Array.from({ length: horizon }, (_, i) => targetPeriod(run, grain, i + 1));
  const listed = all ? periods : periods.slice(0, 14);
  const { picked, pick, clear } = usePointPick();
  return (
    <Box
      title={`${t('Expected events by date')}`}
      actions={periods.length > 14 ? <button className="pfie-btn" onClick={() => setAll((x) => !x)}>{all ? t('Show fewer') : t('Show all')}</button> : undefined}
    >
      <SimpleTable
        head={[t('Date'), ...COLS.map((s) => t(PLAIN_SERIES[s]))]}
        onRow={(i) => pick(listed[i] === picked ? null : listed[i])}
        selected={listed.indexOf(picked ?? '')}
        rows={listed.map((m) => [
          periodText(m, grain, lang),
          ...COLS.map((s) => { const r = forecastRow(run, grain, m, s); return r ? about(r.forecast) : '—'; }),
        ])}
      />
      <PickHint picked={picked} />
      {picked && <PointExplanation kind="events" at={picked} onClose={clear} />}
    </Box>
  );
}
