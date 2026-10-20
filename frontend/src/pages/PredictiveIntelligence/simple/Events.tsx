/**
 * Simple view, "Herd events" tab: totals over the look ahead against a year
 * before, the expected events per day / week / month, and expected vs recorded
 * mastitis by month (so a recording gap shows).
 */

import { useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  EVENT_SERIES, actualRow, firstTarget, forecastRow, isForecast, periodDays, targetPeriod, timeline, type SeriesId,
} from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { TipShell } from '../ui';
import { aheadText, periodText, useLang, useT } from './i18n';
import { PickHint, PointExplanation, usePointPick } from './PointExplain';
import { Box, CHART_TICK, Explain, FORECAST_COLOR, Legend, NotInRun, PLAIN_SERIES, SimpleTable, about, useChartOrTable, yearBefore } from './common';

const MASTITIS_COLOR = '#a44b3c';
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
      <Mastitis />
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

function Mastitis() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { asTable, toggle } = useChartOrTable();
  /* Expected cases for past months: the first forecast month's rate per cow-day, applied to the recorded herd. */
  const first = firstTarget(run, 'month');
  const mF = forecastRow(run, 'month', first, 'mastitis_episodes');
  const cF = forecastRow(run, 'month', first, 'milking');
  const rate = mF && cF ? mF.forecast / (cF.forecast * periodDays(first, 'month')) : null;
  const rows = timeline(run, 'month', 12, 24).map((p) => ({
    period: p.period,
    label: periodText(p.period, 'month', lang, true),
    future: p.future,
    recorded: typeof p.mastitis_episodes === 'number' ? p.mastitis_episodes : null,
    expected: typeof p.mastitis_episodes_f === 'number'
      ? p.mastitis_episodes_f
      : rate !== null && typeof p.milking === 'number' ? p.milking * periodDays(p.period, 'month') * rate : null,
  }));
  const start = periodText(first, 'month', lang, true);
  const { picked, pick, clear, onChartClick } = usePointPick();
  const pickedLabel = rows.find((r) => r.period === picked)?.label;

  return (
    <Box title={`${t('Mastitis: expected and recorded')}`} sub={`${t('By month')}`} actions={toggle}>
      {!asTable ? (
        <>
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
                <CartesianGrid stroke="#eef2f0" vertical={false} />
                <XAxis dataKey="label" tick={CHART_TICK} interval="preserveStartEnd" />
                <YAxis tick={CHART_TICK} width={36} allowDecimals={false} />
                <ReferenceLine x={start} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12, fill: '#34483f' }} />
                {pickedLabel && <ReferenceLine x={pickedLabel} stroke="#9a4f27" strokeWidth={8} strokeOpacity={0.18} />}
                <Bar dataKey="recorded" fill={MASTITIS_COLOR} isAnimationActive={false} />
                <Line dataKey="expected" stroke={FORECAST_COLOR} strokeDasharray="6 4" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                <Tooltip content={({ active, payload }) => {
                  const r = payload?.[0]?.payload as (typeof rows)[number] | undefined;
                  if (!active || !r) return null;
                  return <TipShell title={periodText(r.period, 'month', lang)} rows={[
                    [t('Recorded cases'), r.recorded !== null ? about(r.recorded) : '—', MASTITIS_COLOR],
                    [t('Expected cases'), r.expected !== null ? about(r.expected) : '—', FORECAST_COLOR],
                  ]} note={t('Click to explain')} />;
                }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <Legend items={[{ label: t('Recorded cases'), color: MASTITIS_COLOR, kind: 'bar' }, { label: t('Expected cases'), color: FORECAST_COLOR, kind: 'dash' }]} />
        </>
      ) : (
        <SimpleTable
          head={[t('Month'), t('Recorded cases'), t('Expected cases')]}
          onRow={(i) => pick(rows[i].period === picked ? null : rows[i].period)}
          selected={rows.findIndex((r) => r.period === picked)}
          rows={rows.map((r) => [
            <>{periodText(r.period, 'month', lang)}{r.future && <span className="pfie-mgr-tag">{t('expected')}</span>}</>,
            r.recorded !== null ? about(r.recorded) : '—',
            r.expected !== null ? about(r.expected) : '—',
          ])}
        />
      )}
      <PickHint picked={picked} />
      {picked && <PointExplanation kind="mastitis" at={picked} onClose={clear} />}
      <Explain>{t('Red bars far below the dashed line usually mean not every case is written down. This does not find sick cows; that is Component 3.')}</Explain>
    </Box>
  );
}
