/**
 * Simple view, "Heat" tab: recent daily heat against this herd's usual peak,
 * and the usual heat for the coming weeks from past years (not a weather
 * forecast). Same data as the detailed heat outlook.
 */

import { useMemo } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useRun } from '../source';
import { TipShell } from '../ui';
import { Rich, dateLabel, periodText, useLang, useT } from './i18n';
import { PickHint, PointExplanation, usePointPick } from './PointExplain';
import { Box, CHART_TICK, DemoLine, Explain, FORECAST_COLOR, Legend, NotInRun } from './common';

const RECORDED = '#a44b3c';
const LIMIT = '#a8770a';

export function HeatTab() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const h = run.heat;
  const rows = useMemo(() => {
    if (!h) return [];
    const r: { date: string; recorded?: number | null; usual?: number; band?: [number, number] }[] = h.recent.map((d) => ({ date: d.date, recorded: d.thi_max }));
    h.climatology.forEach((c) => r.push({ date: c.date, usual: c.p50, band: [c.p10, c.p90] }));
    return r;
  }, [h]);
  const { picked, clear, onChartClick } = usePointPick();
  if (!h) return <Box title={t('Heat stress')}><NotInRun /></Box>;
  const limit = h.knot_p75;
  const hotDays = limit !== null ? h.climatology.slice(0, 30).filter((c) => c.p50 > limit).length : 0;

  return (
    <Box title={`${t('Heat stress')}`} sub={t('Weather up to {d}', { d: dateLabel(h.last_weather_day, lang) })}>
      <div className="pfie-mgr-facts">
        <div className={`pfie-mgr-fact ${h.hot_run_days ? 'warn' : ''}`}>
          
          <span className="lbl">{t('Recent days')}</span>
          <b>{h.hot_run_days ? t('{n} hot days', { n: h.hot_run_days }) : t('Normal')}</b>
        </div>
        <div className="pfie-mgr-fact">
          
          <span className="lbl">{t('Next 30 days (usual)')}</span>
          <b>{t('{n} hot days', { n: hotDays })}</b>
        </div>
      </div>
      <div style={{ height: 240 }}>
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
            <CartesianGrid stroke="#eef2f0" vertical={false} />
            <XAxis dataKey="date" tick={CHART_TICK} minTickGap={40} tickFormatter={(d: string) => periodText(d, 'day', lang, true)} />
            <YAxis tick={CHART_TICK} width={36} domain={['auto', 'auto']} />
            <Area dataKey="band" stroke="none" fill={FORECAST_COLOR} fillOpacity={0.14} isAnimationActive={false} />
            <Line dataKey="usual" stroke={FORECAST_COLOR} strokeDasharray="6 4" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="recorded" stroke={RECORDED} strokeWidth={2.5} dot={false} isAnimationActive={false} />
            {picked && <ReferenceLine x={picked} stroke="#9a4f27" strokeWidth={6} strokeOpacity={0.2} />}
            {limit !== null && <ReferenceLine y={limit} stroke={LIMIT} strokeDasharray="4 3" label={{ value: t('Usual peak for this herd'), position: 'insideTopLeft', fontSize: 12, fill: LIMIT }} />}
            <Tooltip content={({ active, payload }) => {
              const r = payload?.[0]?.payload as (typeof rows)[number] | undefined;
              if (!active || !r) return null;
              return <TipShell title={dateLabel(r.date, lang)} rows={[
                ...(r.recorded != null ? [[t('Recorded heat'), String(Math.round(r.recorded)), RECORDED] as [string, string, string]] : []),
                ...(r.usual != null ? [[t('Usual in past years'), String(Math.round(r.usual)), FORECAST_COLOR] as [string, string, string]] : []),
              ]} note={t('Click to explain')} />;
            }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[
        { label: t('Recorded heat'), color: RECORDED },
        { label: t('Usual in past years'), color: FORECAST_COLOR, kind: 'dash' },
        { label: t('Usual peak for this herd'), color: LIMIT, kind: 'dash' },
      ]} />
      <PickHint picked={picked} />
      {picked && <PointExplanation kind="heat" at={picked} onClose={clear} />}
      <Explain><Rich text={t('Heat is the **THI** (heat and humidity). Above the yellow line, cows eat and milk less. The blue line is the usual weather for the time of year, **not a weather forecast**.')} /></Explain>
      <DemoLine run={run} />
    </Box>
  );
}
