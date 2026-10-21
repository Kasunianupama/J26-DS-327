/**
 * Simple view, "Heat" tab: recent daily heat against this herd's own hot and very hot
 * thresholds, the experimental THI forecast, and the chance of hot days in each coming
 * week. Runs without hot-day chances (v1 forecast) keep the usual-pattern band instead.
 */

import { useMemo } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { HeatSummary } from '../../../data/pfoi/contract';
import { useRun } from '../source';
import { TipShell } from '../ui';
import { Rich, dateLabel, periodText, useLang, useT } from './i18n';
import { PickHint, PointExplanation, usePointPick } from './PointExplain';
import { ChartView, useChartStart } from './ChartView';
import { Box, CHART_TICK, DemoLine, Explain, FORECAST_COLOR, Legend, NotInRun } from './common';

const RECORDED = '#a44b3c';
const LIMIT = '#a8770a';
const VERY_HOT = '#b83b38';
const PREDICTED = '#7254a3';
const ACTUAL = '#17231f';
/** Back-test: a one-day warm or cool spell is nearly gone after a week, so after two
 *  weeks the prediction is mostly the usual season; drawn dotted from here on. */
const SOLID_DAYS = 14;

type Row = {
  date: string; recorded?: number | null; actual?: number | null; near?: number; far?: number;
  range?: [number, number]; usual?: number; band?: [number, number]; p75?: number; p90?: number;
};

const addDays = (iso: string, n: number) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

/** Expected hot / very hot days per coming week (sum of daily chances), with the usual
 *  count for those dates and, for past forecast dates, the recorded count. */
function weeklyRisk(h: HeatSummary, origin: string) {
  const preds = h.forecast?.predictions.filter((p) => p.date >= origin && p.p_above) ?? [];
  const clim = new Map(h.climatology.map((c) => [c.date, c]));
  const real = new Map((h.realised ?? []).map((d) => [d.date, d.thi_max]));
  const weeks = [];
  for (let w = 0; w * 7 < preds.length; w++) {
    const days = preds.slice(w * 7, w * 7 + 7);
    const usual = days.map((d) => clim.get(d.date));
    const rec = days.map((d) => real.get(d.date)).filter((v): v is number => v != null);
    weeks.push({
      start: days[0].date, n: days.length,
      hot: sum(days.map((d) => d.p_above!.p75 ?? 0)), veryHot: sum(days.map((d) => d.p_above!.p90 ?? 0)),
      usualHot: usual.every((c) => c?.share_above_p75 != null) ? sum(usual.map((c) => c!.share_above_p75!)) : null,
      actualHot: rec.length === days.length && h.knot_p75 !== null ? rec.filter((v) => v > h.knot_p75!).length : null,
    });
  }
  return weeks;
}

/** Readable name of the THI forecast model behind a run (`heat.forecast.method`). */
function heatModelName(method: string, t: (k: string) => string) {
  if (method.endsWith('_v2')) return t('v2, seasonal pattern plus learned day-to-day changes');
  if (method.endsWith('_v1')) return t('v1, seasonal pattern plus a fixed 7-day fade');
  return method;
}

export function HeatTab() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const h = run.heat;
  const { history, controls } = useChartStart(run, 'day', run.heat?.recent[0]?.date);
  const forecast = h?.forecast?.status === 'experimental' ? h.forecast : undefined;
  const chances = !!forecast?.predictions.some((p) => p.p_above);
  const rows = useMemo(() => {
    if (!h) return [];
    const byDate = new Map<string, Row>();
    const put = (date: string, r: Partial<Row>) => byDate.set(date, { ...byDate.get(date), date, ...r });
    const from = addDays(run.origin_date, -history);
    h.recent.filter((d) => d.date >= from).forEach((d) => put(d.date, { recorded: d.thi_max }));
    // Days between the last published weather and the forecast date (shaded, no values).
    for (let d = addDays(h.last_weather_day, 1); d < run.origin_date && d >= from; d = addDays(d, 1)) put(d, {});
    h.climatology.filter((c) => c.date >= from).forEach((c) => put(c.date, chances ? { usual: c.p50 } : { usual: c.p50, band: [c.p10, c.p90] }));
    forecast?.predictions.filter((d) => d.date >= run.origin_date).forEach((d, i) => put(d.date, {
      ...(i < SOLID_DAYS ? { near: d.thi_max } : {}), ...(i >= SOLID_DAYS - 1 ? { far: d.thi_max } : {}),
      ...(d.lower != null && d.upper != null ? { range: [d.lower, d.upper] as [number, number] } : {}),
      ...(d.p_above ? { p75: d.p_above.p75, p90: d.p_above.p90 } : {}),
    }));
    (h.realised ?? []).filter((d) => d.date >= run.origin_date && byDate.has(d.date)).forEach((d) => put(d.date, { actual: d.thi_max }));
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [h, forecast, chances, run.origin_date, history]);
  const weeks = useMemo(() => (h && chances ? weeklyRisk(h, run.origin_date) : []), [h, chances, run.origin_date]);
  const { picked, clear, onChartClick } = usePointPick();
  if (!h) return <Box title={t('Heat stress')}><NotInRun /></Box>;
  const hot = h.knot_p75;
  const veryHot = h.knot_p90;
  const observed = rows.some((r) => r.actual != null);
  const predicted = !!forecast;
  const next30 = forecast?.predictions.filter((d) => d.date >= run.origin_date).slice(0, 30) ?? [];
  const clim30 = h.climatology.slice(0, 30);
  const expectedHot = chances ? sum(next30.map((d) => d.p_above?.p75 ?? 0)) : null;
  const usualHot = clim30.length && clim30.every((c) => c.share_above_p75 != null)
    ? sum(clim30.map((c) => c.share_above_p75!)) : null;
  const predictedHotDays = hot !== null ? next30.filter((d) => d.thi_max > hot).length : 0;
  const usualHotDays = hot !== null ? clim30.filter((c) => c.p50 > hot).length : 0;
  const gapStart = addDays(h.last_weather_day, 1);
  const hasGap = gapStart < run.origin_date && rows.some((r) => r.date === run.origin_date);
  const maxWeek = Math.max(1, ...weeks.map((w) => w.hot));
  const shownWeeks = weeks.filter((w) => w.hot >= 0.05 || w.veryHot >= 0.05);

  return (
    <ChartView title={t('Heat stress')} actions={null} controls={controls}>
      {(expanded) => <>
      <p className="pfie-mgr-note">{t('Weather up to {d}', { d: dateLabel(h.last_weather_day, lang) })}</p>
      <Explain><Rich text={t('The value is daily maximum **THI (Temperature–Humidity Index)**, combining temperature and humidity. It has **no unit and is not °C**. Higher values mean greater heat stress risk.')} /></Explain>
      <p className="pfie-mgr-note">{t('These are thresholds from this herd’s past weather, not universal safe limits.')}</p>
      {hot !== null && <p className="pfie-mgr-note">
        {t('Hot: THI > {low} (hotter than 75% of past days).', { low: hot.toFixed(1) })}
        {veryHot !== null && <> {t('Very hot: THI > {high} (hotter than 90% of past days).', { high: veryHot.toFixed(1) })}</>}
      </p>}
      {predicted && !chances && <p className="pfie-mgr-note">{t('Experimental THI forecast: a separate statistical model fitted to past weather. Accuracy on Farm X records has not been validated. It does not change the milk or herd forecast.')}</p>}
      {!predicted && <p className="pfie-mgr-note">{t('No model-predicted THI is included in this run. The seasonal average is shown separately.')}</p>}
      <div className="pfie-mgr-facts">
        <div className={`pfie-mgr-fact ${h.hot_run_days ? 'warn' : ''}`}>
          <span className="lbl">{t('Recent days')}</span>
          <b>{h.hot_run_days == null ? '—' : h.hot_run_days ? t('{n} hot days', { n: h.hot_run_days }) : t('Normal')}</b>
        </div>
        {chances ? (
          <div className="pfie-mgr-fact">
            <span className="lbl">{t('Next 30 days: expected hot days')}</span>
            <b>{expectedHot === null ? '—' : t('about {n}', { n: Math.round(expectedHot) })}</b>
            {usualHot !== null && <small>{t('usual for these dates: about {n}', { n: Math.round(usualHot) })}</small>}
          </div>
        ) : <>
          {predicted && <div className="pfie-mgr-fact">
            <span className="lbl">{t('Next 30 days (model predicted)')}</span>
            <b>{hot === null ? '—' : t('{n} hot days', { n: predictedHotDays })}</b>
          </div>}
          <div className="pfie-mgr-fact">
            <span className="lbl">{t('Next 30 days (usual)')}</span>
            <b>{hot === null || !h.climatology.length ? '—' : t('{n} hot days', { n: usualHotDays })}</b>
          </div>
        </>}
      </div>
      <div style={{ height: expanded ? (picked ? 300 : 'max(320px, calc(100dvh - 300px))') : 280 }}>
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
            <CartesianGrid stroke="#eef2f0" vertical={false} />
            <XAxis dataKey="date" tick={CHART_TICK} minTickGap={40} tickFormatter={(d: string) => periodText(d, 'day', lang, true)} />
            <YAxis tick={CHART_TICK} width={52} domain={['auto', 'auto']} label={{ value: 'THI', angle: -90, position: 'insideLeft', fontSize: 11 }} />
            {hasGap && <ReferenceArea x1={gapStart} x2={run.origin_date} fill="#70827a" fillOpacity={0.1} stroke="none"
              label={{ value: t('Weather not yet published'), position: 'insideBottom', fontSize: 11, fill: '#52665d' }} />}
            {!chances && <Area dataKey="band" stroke="none" fill={FORECAST_COLOR} fillOpacity={0.14} isAnimationActive={false} />}
            {chances && <Area dataKey="range" stroke="none" fill={PREDICTED} fillOpacity={0.14} isAnimationActive={false} />}
            <Line dataKey="usual" stroke={FORECAST_COLOR} strokeDasharray="6 4" strokeWidth={chances ? 1 : 2} strokeOpacity={chances ? 0.45 : 1} dot={false} isAnimationActive={false} />
            {predicted && <Line dataKey="near" stroke={PREDICTED} strokeWidth={3} dot={false} connectNulls={false} isAnimationActive={false} />}
            {predicted && <Line dataKey="far" stroke={PREDICTED} strokeDasharray="2 4" strokeWidth={2.5} dot={false} connectNulls={false} isAnimationActive={false} />}
            <Line dataKey="recorded" stroke={RECORDED} strokeWidth={2.5} dot={false} isAnimationActive={false} />
            {observed && <Line dataKey="actual" stroke={ACTUAL} strokeWidth={2.5} dot={{ r: 2.5, fill: '#fff', stroke: ACTUAL, strokeWidth: 1.5 }} connectNulls={false} isAnimationActive={false} />}
            {rows.some((r) => r.date === run.origin_date) && <ReferenceLine x={run.origin_date} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12 }} />}
            {picked && <ReferenceLine x={picked} stroke="#9a4f27" strokeWidth={6} strokeOpacity={0.2} />}
            {hot !== null && <ReferenceLine y={hot} ifOverflow="extendDomain" stroke={LIMIT} strokeDasharray="4 3" label={{ value: t('Hot'), position: 'insideTopLeft', fontSize: 12, fill: LIMIT }} />}
            {veryHot !== null && <ReferenceLine y={veryHot} ifOverflow="extendDomain" stroke={VERY_HOT} strokeDasharray="4 3" label={{ value: t('Very hot'), position: 'insideTopRight', fontSize: 12, fill: VERY_HOT }} />}
            <Tooltip content={({ active, payload }) => {
              const r = payload?.[0]?.payload as Row | undefined;
              if (!active || !r) return null;
              const pred = r.near ?? r.far;
              const pct = (v: number) => `${Math.round(100 * v)}%`;
              return <TipShell title={dateLabel(r.date, lang)} rows={[
                ...(r.recorded != null ? [[t('Recorded heat'), `${r.recorded.toFixed(1)} THI`, RECORDED] as [string, string, string]] : []),
                ...(r.actual != null ? [[t('What actually happened'), `${r.actual.toFixed(1)} THI`, ACTUAL] as [string, string, string]] : []),
                ...(pred != null ? [[t('Model predicted THI (experimental)'), `${pred.toFixed(1)} THI`, PREDICTED] as [string, string, string]] : []),
                ...(r.range ? [[t('Prediction range (10–90%)'), `${r.range[0].toFixed(1)} – ${r.range[1].toFixed(1)} THI`] as [string, string]] : []),
                ...(r.p75 != null ? [[t('Chance of a hot day'), pct(r.p75)] as [string, string]] : []),
                ...(r.p90 != null ? [[t('Chance of a very hot day'), pct(r.p90)] as [string, string]] : []),
                ...(r.usual != null ? [[t('Usual in past years'), `${r.usual.toFixed(1)} THI`, FORECAST_COLOR] as [string, string, string]] : []),
                ...(r.band ? [[t('Usual range (10–90%)'), `${r.band[0].toFixed(1)} – ${r.band[1].toFixed(1)} THI`] as [string, string]] : []),
                ...(r.actual != null && pred != null ? [[t('Actual minus model prediction'), `${(r.actual - pred).toFixed(1)} THI`] as [string, string]] : []),
                ...(r.recorded == null && r.actual == null && pred == null && r.usual == null ? [[t('Weather not yet published'), '—'] as [string, string]] : []),
              ]} note={t('Click to explain')} />;
            }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[
        { label: t('Recorded heat'), color: RECORDED },
        ...(observed ? [{ label: t('What actually happened'), color: ACTUAL }] : []),
        ...(predicted ? [{ label: t('Predicted THI (dotted after 14 days: mostly the usual season)'), color: PREDICTED }] : []),
        ...(chances ? [{ label: t('Prediction range (10–90%)'), color: 'rgba(114, 84, 163, 0.22)', kind: 'band' as const }] : []),
        { label: t('Usual in past years'), color: FORECAST_COLOR, kind: 'dash' },
        ...(!chances ? [{ label: t('Usual range (10–90%)'), kind: 'band' as const }] : []),
        ...(hot !== null ? [{ label: t('Hot (hotter than 75% of past days)'), color: LIMIT, kind: 'dash' as const }] : []),
        ...(veryHot !== null ? [{ label: t('Very hot (hotter than 90% of past days)'), color: VERY_HOT, kind: 'dash' as const }] : []),
      ]} />
      {shownWeeks.length > 0 && (
        <div className="pfie-mgr-heatrisk">
          <span className="pfie-mgr-heatrisk-title">{t('Expected hot days per week')}</span>
          <ol>
            {shownWeeks.map((w) => (
              <li key={w.start} style={{ background: `rgba(168, 119, 10, ${(0.08 + 0.5 * w.hot / maxWeek).toFixed(2)})` }}
                className={w.veryHot >= 1 ? 'very' : undefined}
                title={t('Week from {d}: about {hot} hot days (usual {usual}), about {very} very hot', {
                  d: dateLabel(w.start, lang), hot: w.hot.toFixed(1),
                  usual: w.usualHot == null ? '—' : w.usualHot.toFixed(1), very: w.veryHot.toFixed(1),
                })}>
                <small>{periodText(w.start, 'day', lang, true)}</small>
                <b>{w.hot.toFixed(1)}</b>
                {w.usualHot != null && <small>{t('usual {n}', { n: w.usualHot.toFixed(1) })}</small>}
                {w.actualHot != null && <small className="act">{t('actual {n}', { n: w.actualHot })}</small>}
              </li>
            ))}
          </ol>
          <span className="pfie-mgr-note">{t('Sum of the daily chances of a hot day in each week of {n} days. A red edge means at least one very hot day is expected.', { n: 7 })} {t('Weeks with no expected hot days are not shown.')}</span>
        </div>
      )}
      <PickHint picked={picked} />
      {(!predicted || !observed) && <p className="pfie-mgr-note" role="status">{t('Missing comparison lines? This published run needs a heat-data refresh. Reload the page after refreshing the run. Actual values stop at the last available weather record.')}</p>}
      {picked && <PointExplanation kind="heat" at={picked} onClose={clear} />}
      {chances
        ? <Explain>{t('The purple line is predicted daily maximum THI: the seasonal pattern plus recent day-to-day changes, which fade within about a week. After 14 days it is dotted because it is then mostly the usual season. The shaded purple range is where 80% of the model’s past errors fell. The grey area marks days whose weather was not yet published at the forecast date.')}</Explain>
        : <Explain><Rich text={t('The dashed blue line is the model’s seasonal heat assumption from past years, **not a weather forecast**. The shaded band covers the middle 80% of past values for these dates; it is not a forecast confidence interval. Dots after the forecast date show **what actually happened**, only where recorded weather is available.')} /></Explain>}
      {predicted && !chances && <Explain>{t('The purple line is predicted daily maximum THI. It learns the seasonal pattern and adds a recent-weather adjustment that fades over time. The shaded historical range is not uncertainty for this prediction.')}</Explain>}
      {!observed && <p className="pfie-mgr-note">{t('No later heat observations are included in this run yet.')}</p>}
      <DemoLine run={run} />
      </>}
    </ChartView>
  );
}
