/**
 * Simple view: the two charts on the landing page, milk and herd population.
 * Both follow the Daily / Weekly / Monthly switch and the look ahead, can be
 * shown as a table, and explain any point that is clicked.
 */

import { useMemo } from 'react';
import {
  Area, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from 'recharts';
import { SERIES_META, actualRow, fmtInt, hasRealised, isForecast, perDay, timeline, type Grain, type PfoiRun, type SeriesId } from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { TipShell } from '../ui';
import { useLang, useT, periodText } from './i18n';
import { PickHint, PointExplanation, usePointPick } from './PointExplain';
import {
  Box, CHART_TICK, FORECAST_COLOR, HISTORY, Legend, MILK_COLOR, PLAIN_SERIES, SimpleTable, litres, useChartOrTable, whole, yearBefore,
} from './common';

export interface MilkRow {
  period: string;
  label: string;
  future: boolean;
  recorded: number | null;
  expected: number | null;
  band: [number, number] | null;
  actual: number | null;
  lastYear: number | null;
}

export function milkRows(run: PfoiRun, grain: Grain, steps: number, label: (p: string) => string): MilkRow[] {
  return timeline(run, grain, steps, HISTORY[grain]).map((p) => {
    const lyP = yearBefore(p.period, grain);
    const ly = actualRow(run, grain, lyP, 'milk_litres');
    return {
      period: p.period,
      label: label(p.period),
      future: p.future,
      recorded: p.future ? null : (p.milk_litres as number | undefined) ?? null,
      expected: (p.milk_litres_f as number | undefined) ?? null,
      band: (p.milk_litres_band as [number, number] | undefined) ?? null,
      actual: p.future ? (p.milk_litres_r as number | undefined) ?? null : null,
      lastYear: ly && ly.value !== null ? perDay('milk_litres', ly.value, grain, lyP) : null,
    };
  });
}

export function MilkChart() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();
  const { asTable, toggle } = useChartOrTable();
  const rows = useMemo(() => milkRows(run, grain, horizon, (p) => periodText(p, grain, lang, true)), [run, grain, horizon, lang]);
  const start = rows.find((r) => r.future)?.label;
  const realised = hasRealised(run);
  const future = rows.filter((r) => r.future);
  const { picked, pick, clear, onChartClick } = usePointPick();
  const pickedLabel = rows.find((r) => r.period === picked)?.label;

  return (
    <Box title={`${t('Milk per day')}`} actions={toggle}>
      {!asTable ? (
        <>
          <div style={{ height: 280 }}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
                <CartesianGrid stroke="#eef2f0" vertical={false} />
                <XAxis dataKey="label" tick={CHART_TICK} interval="preserveStartEnd" minTickGap={18} />
                <YAxis tick={CHART_TICK} width={58} tickFormatter={(v: number) => fmtInt(v)} domain={['auto', 'auto']} />
                <Tooltip content={<MilkTip grain={grain} />} />
                <Area dataKey="band" stroke="none" fill={FORECAST_COLOR} fillOpacity={0.14} isAnimationActive={false} />
                <Line dataKey="recorded" stroke={MILK_COLOR} strokeWidth={3} dot={grain === 'day' ? false : { r: 3 }} connectNulls={false} isAnimationActive={false} />
                <Line dataKey="expected" stroke={FORECAST_COLOR} strokeWidth={3} strokeDasharray="7 5" dot={false} connectNulls isAnimationActive={false} />
                {realised && <Scatter dataKey="actual" fill="#fff" stroke="#17231f" strokeWidth={2} isAnimationActive={false} />}
                {start && <ReferenceLine x={start} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12, fill: '#34483f' }} />}
                {pickedLabel && <ReferenceLine x={pickedLabel} stroke={MILK_COLOR} strokeWidth={8} strokeOpacity={0.18} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <Legend items={[
            { label: t('Recorded'), color: MILK_COLOR },
            { label: t('Expected'), color: FORECAST_COLOR, kind: 'dash' },
            { label: t('Likely range'), kind: 'band' },
            ...(realised ? [{ label: t('What actually happened'), kind: 'dot' as const }] : []),
          ]} />
        </>
      ) : (
        <SimpleTable
          head={[t('Date'), t('Expected'), t('Likely low'), t('Likely high'), t('A year before'), ...(realised ? [t('What actually happened')] : [])]}
          onRow={(i) => pick(future[i].period === picked ? null : future[i].period)}
          selected={future.findIndex((r) => r.period === picked)}
          rows={future.map((r) => [
            periodText(r.period, grain, lang),
            <b>{r.expected !== null ? litres(r.expected) : '—'}</b>,
            r.band ? litres(r.band[0]) : '—',
            r.band ? litres(r.band[1]) : '—',
            r.lastYear !== null ? litres(r.lastYear) : '—',
            ...(realised ? [r.actual !== null ? litres(r.actual) : '—'] : []),
          ])}
        />
      )}
      <PickHint picked={picked} />
      {picked && <PointExplanation kind="milk" at={picked} onClose={clear} />}
    </Box>
  );
}

function MilkTip({ active, payload, grain }: { active?: boolean; payload?: { payload: MilkRow }[]; grain: Grain }) {
  const t = useT();
  const { lang } = useLang();
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  const rows: [string, string][] = [];
  if (r.recorded !== null) rows.push([t('Recorded'), `${litres(r.recorded)} L`]);
  else if (r.expected !== null) rows.push([t('Expected'), `${litres(r.expected)} L`]);
  if (r.future && r.band) rows.push([t('Likely range'), `${litres(r.band[0])} – ${litres(r.band[1])}`]);
  if (r.actual !== null) rows.push([t('What actually happened'), `${litres(r.actual)} L`]);
  if (r.lastYear !== null) rows.push([t('A year before'), `${litres(r.lastYear)} L`]);
  return <TipShell title={periodText(r.period, grain, lang)} rows={rows} note={t('Click to explain')} />;
}

/* ------------------------------------------------------------------ herd population */

const GROUPS: SeriesId[] = ['total_herd', 'milking', 'dry', 'heifers', 'calves', 'other'];
const COLOR: Record<string, string> = { total_herd: '#17231f', milking: '#2f7f86', dry: '#c99a77', heifers: '#5b7fa6', calves: '#93aec9', other: '#8a8f87' };

export function HerdChart() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();
  const { asTable, toggle } = useChartOrTable();
  const shown = GROUPS.filter((s) => isForecast(run, grain, s) || run.actuals.some((a) => a.grain === grain && a.series === s));
  const rows = useMemo(() => timeline(run, grain, horizon, HISTORY[grain]).map((p) => {
    const r: Record<string, number | string | boolean | null> = { period: p.period, label: periodText(p.period, grain, lang, true), future: p.future };
    shown.forEach((s) => {
      r[s] = p.future ? null : (p[s] as number | undefined) ?? null;
      r[`${s}_f`] = (p[`${s}_f`] as number | undefined) ?? null;
    });
    return r;
  }), [run, grain, horizon, lang, shown.join()]);
  const start = rows.find((r) => r.future)?.label as string | undefined;
  const { picked, pick, clear, onChartClick } = usePointPick();
  const pickedLabel = rows.find((r) => r.period === picked)?.label as string | undefined;
  const val = (r: Record<string, unknown>, s: string) => (r[s] ?? r[`${s}_f`]) as number | null;

  if (!shown.length) return null;
  return (
    <Box title={`${t('Herd population')}`} actions={toggle}>
      {!asTable ? (
        <>
          <div style={{ height: 280 }}>
            <ResponsiveContainer>
              <LineChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
                <CartesianGrid stroke="#eef2f0" vertical={false} />
                <XAxis dataKey="label" tick={CHART_TICK} interval="preserveStartEnd" minTickGap={18} />
                <YAxis tick={CHART_TICK} width={44} />
                {start && <ReferenceLine x={start} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12, fill: '#34483f' }} />}
                {pickedLabel && <ReferenceLine x={pickedLabel} stroke={MILK_COLOR} strokeWidth={8} strokeOpacity={0.18} />}
                {shown.map((s) => <Line key={s} dataKey={s} stroke={COLOR[s]} strokeWidth={s === 'total_herd' ? 3 : 2.2} dot={false} isAnimationActive={false} />)}
                {shown.map((s) => <Line key={`${s}_f`} dataKey={`${s}_f`} stroke={COLOR[s]} strokeWidth={s === 'total_herd' ? 3 : 2.2} strokeDasharray="7 5" dot={false} isAnimationActive={false} />)}
                <Tooltip content={({ active, payload }) => {
                  const r = payload?.[0]?.payload as Record<string, number | string | null> | undefined;
                  if (!active || !r) return null;
                  return <TipShell title={periodText(String(r.period), grain, lang)} rows={shown.map((s) => { const v = val(r, s); return [t(PLAIN_SERIES[s]), v != null ? whole(v) : '—', COLOR[s] ?? SERIES_META[s].color]; })} note={t('Click to explain')} />;
                }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <Legend items={shown.map((s) => ({ label: t(PLAIN_SERIES[s]), color: COLOR[s] }))} />
        </>
      ) : (
        <SimpleTable
          head={[t('Date'), ...shown.map((s) => t(PLAIN_SERIES[s]))]}
          onRow={(i) => { const p = String(rows[i].period); pick(p === picked ? null : p); }}
          selected={rows.findIndex((r) => r.period === picked)}
          rows={rows.map((r) => [
            <>{periodText(String(r.period), grain, lang)}{r.future && <span className="pfie-mgr-tag">{t('expected')}</span>}</>,
            ...shown.map((s) => { const v = val(r, s); return v != null ? whole(v) : '—'; }),
          ])}
        />
      )}
      <PickHint picked={picked} />
      {picked && <PointExplanation kind="herd" at={picked} onClose={clear} />}
    </Box>
  );
}
