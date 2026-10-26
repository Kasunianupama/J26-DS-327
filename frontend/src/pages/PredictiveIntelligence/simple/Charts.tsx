/**
 * Simple view: the landing-page charts for milk, herd population and herd events.
 * All follow the Weekly / Monthly switch and the look ahead, can be
 * shown as a table, and explain any point that is clicked.
 */

import { useMemo, useState } from 'react';
import {
  Area, Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from 'recharts';
import { SERIES_META, actualRow, fmtInt, hasRealised, isForecast, perDay, timeline, type Grain, type PfoiRun, type SeriesId } from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { TipShell } from '../ui';
import { useLang, useT, periodText } from './i18n';
import { PickHint, PointExplanation, usePointPick, type PointSelection } from './PointExplain';
import {
  CHART_TICK, FORECAST_COLOR, HISTORY, Legend, MILK_COLOR, PLAIN_SERIES, SimpleTable, about, litres, useChartOrTable, whole, yearBefore,
} from './common';

import { ChartView, useChartStart } from './ChartView';

/** One selection and one explanation across the overview, using the full row. */
export function OverviewCharts() {
  const run = useRun();
  const { grain, horizon } = usePfoi();
  // A new forecast or time window clears a selection that may no longer be visible.
  return <OverviewSelection key={`${run.origin_date}-${grain}-${horizon}`} />;
}

function OverviewSelection() {
  const [selected, setSelected] = useState<{ kind: 'milk' | 'herd'; at: string } | null>(null);
  const selection = (kind: 'milk' | 'herd'): PointSelection => ({
    picked: selected?.kind === kind ? selected.at : null,
    pick: (at) => setSelected(at ? { kind, at } : null),
  });
  return <div className="pfie-mgr-charts">
    <MilkChart selection={selection('milk')} />
    <HerdChart selection={selection('herd')} />
    {selected && <div className="pfie-overview-explanation">
      <PointExplanation kind={selected.kind} at={selected.at} onClose={() => setSelected(null)} />
    </div>}
  </div>;
}

/* ------------------------------------------------------------------ herd events */

const EVENT_CHART_SERIES: SeriesId[] = ['calvings', 'dry_offs', 'abortions', 'deaths', 'culls_sales'];

export function HerdEventsChart({ selection }: { selection?: PointSelection }) {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();
  const { asTable, toggle } = useChartOrTable();
  const { history, controls } = useChartStart(run, grain);
  const available = EVENT_CHART_SERIES.filter((s) => isForecast(run, grain, s) || run.actuals.some((a) => a.grain === grain && a.series === s));
  const [enabled, setEnabled] = useState<SeriesId[]>(available);
  const shown = available.filter((s) => enabled.includes(s));
  const rows = useMemo(() => timeline(run, grain, horizon, history).map((p) => {
    const row: Record<string, string | boolean | number | [number, number] | null> = {
      period: p.period, label: periodText(p.period, grain, lang, true), future: p.future,
    };
    let low = 0; let high = 0; let hasBand = false;
    EVENT_CHART_SERIES.forEach((s) => {
      row[s] = p.future ? null : typeof p[s] === 'number' ? p[s] as number : null;
      row[`${s}_f`] = p.future && typeof p[`${s}_f`] === 'number' ? p[`${s}_f`] as number : null;
      row[`${s}_r`] = p.future && typeof p[`${s}_r`] === 'number' ? p[`${s}_r`] as number : null;
      if (shown.includes(s) && Array.isArray(p[`${s}_band`])) {
        const band = p[`${s}_band`] as [number, number];
        low += band[0]; high += band[1]; hasBand = true;
      }
    });
    row.band = p.future && hasBand ? [low, high] : null;
    return row;
  }), [run, grain, horizon, history, lang, shown.join()]);
  const start = rows.find((r) => r.future)?.label as string | undefined;
  const realised = shown.some((s) => rows.some((r) => r[`${s}_r`] !== null));
  const { picked, pick, clear, onChartClick } = usePointPick(selection);
  const pickedLabel = rows.find((r) => r.period === picked)?.label as string | undefined;
  const switchSeries = (s: SeriesId) => setEnabled((current) => current.includes(s) ? current.filter((x) => x !== s) : [...current, s]);

  if (!available.length) return null;
  return (
    <ChartView title={t('Herd events')} actions={toggle} controls={controls}>
      {(expanded) => <>
        <div className="pfie-event-switches pfie-noprint" role="group" aria-label={t('Show event types')}>
          {available.map((s) => <button key={s} type="button" aria-pressed={enabled.includes(s)} onClick={() => switchSeries(s)}>
            <i style={{ background: SERIES_META[s].color }} />{t(PLAIN_SERIES[s])}
          </button>)}
        </div>
        {!asTable ? (
          <>
            <div style={{ height: expanded ? (picked ? 300 : 'max(320px, calc(100dvh - 300px))') : 280 }}>
              <ResponsiveContainer>
                <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
                  <CartesianGrid stroke="#eef2f0" vertical={false} />
                  <XAxis dataKey="label" tick={CHART_TICK} interval="preserveStartEnd" minTickGap={18} />
                  <YAxis tick={CHART_TICK} width={42} allowDecimals={false} domain={[0, 'auto']} />
                  <Tooltip content={({ active, payload }) => {
                    const r = payload?.[0]?.payload as Record<string, string | boolean | number | [number, number] | null> | undefined;
                    if (picked || !active || !r) return null;
                    const tipRows = shown.flatMap((s): [string, string, string?][] => {
                      const value = (r[s] ?? r[`${s}_f`]) as number | null;
                      const actual = r[`${s}_r`] as number | null;
                      return [
                        [`${t(PLAIN_SERIES[s])} · ${t(r.future ? 'Expected' : 'Recorded')}`, value !== null ? about(value) : '—', SERIES_META[s].color],
                        ...(actual !== null ? [[`${t(PLAIN_SERIES[s])} · ${t('What actually happened')}`, about(actual), SERIES_META[s].color] as [string, string, string]] : []),
                      ];
                    });
                    const band = r.band as [number, number] | null;
                    if (band) tipRows.push([t('Combined likely range'), `${about(band[0])} – ${about(band[1])}`]);
                    return <TipShell title={periodText(String(r.period), grain, lang)} rows={tipRows} note={t('Click to explain')} />;
                  }} />
                  <Area dataKey="band" stroke="none" fill={FORECAST_COLOR} fillOpacity={0.14} isAnimationActive={false} />
                  {shown.map((s) => <Bar key={s} dataKey={s} stackId="recorded-events" fill={SERIES_META[s].color} isAnimationActive={false} />)}
                  {shown.map((s) => <Bar key={`${s}_f`} dataKey={`${s}_f`} stackId="forecast-events" fill={SERIES_META[s].color} fillOpacity={0.55} stroke={SERIES_META[s].color} strokeDasharray="3 2" isAnimationActive={false} />)}
                  {realised && shown.map((s) => <Scatter key={`${s}_r`} dataKey={`${s}_r`} fill="#fff" stroke={SERIES_META[s].color} strokeWidth={2} isAnimationActive={false} />)}
                  {start && <ReferenceLine x={start} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12, fill: '#34483f' }} />}
                  {pickedLabel && <ReferenceLine x={pickedLabel} stroke={MILK_COLOR} strokeWidth={8} strokeOpacity={0.18} />}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <Legend items={[
              ...shown.map((s) => ({ label: t(PLAIN_SERIES[s]), color: SERIES_META[s].color, kind: 'bar' as const })),
              { label: t('Forecast (lighter, outlined)'), color: FORECAST_COLOR, kind: 'bar' },
              { label: t('Combined likely range'), kind: 'band' },
              ...(realised ? [{ label: t('What actually happened'), kind: 'dot' as const }] : []),
            ]} />
          </>
        ) : (
          <SimpleTable
            head={[t('Date'), ...shown.map((s) => t(PLAIN_SERIES[s])), t('Likely low'), t('Likely high')]}
            onRow={(i) => pick(rows[i].period === picked ? null : String(rows[i].period))}
            selected={rows.findIndex((r) => r.period === picked)}
            rows={rows.map((r) => [
              <>{periodText(String(r.period), grain, lang)}{r.future && <span className="pfie-mgr-tag">{t('expected')}</span>}</>,
              ...shown.map((s) => { const value = r[s] ?? r[`${s}_f`]; return typeof value === 'number' ? about(value) : '—'; }),
              Array.isArray(r.band) ? about(r.band[0]) : '—',
              Array.isArray(r.band) ? about(r.band[1]) : '—',
            ])}
          />
        )}
        <PickHint picked={picked} />
        {picked && (expanded || !selection) && <PointExplanation kind="events" at={picked} onClose={clear} series={shown} />}
      </>}
    </ChartView>
  );
}

export interface MilkRow {
  period: string;
  label: string;
  future: boolean;
  recorded: number | null;
  expected: number | null;
  band: [number, number] | null;
  actual: number | null;
  lastYear: number | null;
  /** Recorded value estimated from part of the period (shown, not scored). */
  partial?: boolean;
  /** A recorded value with no recorded neighbour (drawn as a dot so it is not lost). */
  isolated?: boolean;
  /** Dotted join across a short stretch without records (never across long gaps). */
  bridge?: number | null;
}

/** Longest stretch without records that is still joined by a dotted line, per grain. */
const MAX_BRIDGE: Record<Grain, number> = { day: 7, week: 3, month: 2 };

export function milkRows(run: PfoiRun, grain: Grain, steps: number, label: (p: string) => string, history = HISTORY[grain]): MilkRow[] {
  const rows: MilkRow[] = timeline(run, grain, steps, history).map((p) => {
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
      partial: !p.future && p.milkGap && typeof p.milk_litres === 'number',
      bridge: null,
    };
  });
  /* Join short stretches without records with a dotted line (interpolated), and mark lone values. */
  const has = (i: number) => i >= 0 && i < rows.length && !rows[i].future && rows[i].recorded !== null;
  rows.forEach((r, i) => { if (has(i)) r.isolated = !has(i - 1) && !has(i + 1); });
  let last = -1;
  rows.forEach((r, i) => {
    if (!has(i)) return;
    const gap = i - last - 1;
    if (last >= 0 && gap > 0 && gap <= MAX_BRIDGE[grain]) {
      const a = rows[last].recorded as number, b = r.recorded as number;
      for (let k = last; k <= i; k++) rows[k].bridge = a + ((b - a) * (k - last)) / (i - last);
      rows[last].isolated = false; r.isolated = false;
    }
    last = i;
  });
  return rows;
}

/** Recorded milk: a ring where the period is only partly recorded, a dot for monthly/weekly values and lone days. */
const recordedDot = (grain: Grain) => function Dot(props: { cx?: number; cy?: number; index?: number; payload?: MilkRow }) {
  const { cx, cy, index, payload } = props;
  if (cx == null || cy == null || !payload || payload.recorded === null) return <g key={`rd-${index}`} />;
  if (payload.partial) return <circle key={`rd-${index}`} cx={cx} cy={cy} r={3.5} fill="#fff" stroke={MILK_COLOR} strokeWidth={2} />;
  if (grain !== 'day' || payload.isolated) return <circle key={`rd-${index}`} cx={cx} cy={cy} r={grain === 'day' ? 2.5 : 3} fill={MILK_COLOR} />;
  return <g key={`rd-${index}`} />;
};
const ACTUAL_COLOR = '#17231f';


export function MilkChart({ selection }: { selection?: PointSelection }) {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();
  const { asTable, toggle } = useChartOrTable();
  const { history, controls } = useChartStart(run, grain);
  const rows = useMemo(() => milkRows(run, grain, horizon, (p) => periodText(p, grain, lang, true), history), [run, grain, horizon, lang, history]);
  const start = rows.find((r) => r.future)?.label;
  const realised = hasRealised(run);
  const future = rows.filter((r) => r.future);
  const { picked, pick, clear, onChartClick } = usePointPick(selection);
  const pickedLabel = rows.find((r) => r.period === picked)?.label;

  return (
    <ChartView title={t('Total Milk Yield')} actions={toggle} controls={controls}>
      {(expanded) => <>
      {!asTable ? (
        <>
          <div style={{ height: expanded ? (picked ? 300 : 'max(320px, calc(100dvh - 300px))') : 280 }}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
                <CartesianGrid stroke="#eef2f0" vertical={false} />
                <XAxis dataKey="label" tick={CHART_TICK} interval="preserveStartEnd" minTickGap={18} />
                <YAxis tick={CHART_TICK} width={58} tickFormatter={(v: number) => fmtInt(v)} domain={['auto', 'auto']} />
                <Tooltip content={picked ? () => null : <MilkTip grain={grain} />} />
                <Area dataKey="band" stroke="none" fill={FORECAST_COLOR} fillOpacity={0.14} isAnimationActive={false} />
                <Line dataKey="bridge" stroke={MILK_COLOR} strokeWidth={1.6} strokeDasharray="2 4" dot={false} connectNulls={false} isAnimationActive={false} />
                <Line dataKey="recorded" stroke={MILK_COLOR} strokeWidth={3} dot={recordedDot(grain)} connectNulls={false} isAnimationActive={false} />
                <Line dataKey="expected" stroke={FORECAST_COLOR} strokeWidth={3} strokeDasharray="7 5" dot={false} connectNulls isAnimationActive={false} />
                {realised && <Line dataKey="actual" stroke={ACTUAL_COLOR} strokeWidth={2} dot={grain === 'day' ? false : { r: 3.5, fill: '#fff', stroke: ACTUAL_COLOR, strokeWidth: 2 }} connectNulls isAnimationActive={false} />}
                {start && <ReferenceLine x={start} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12, fill: '#34483f' }} />}
                {pickedLabel && <ReferenceLine x={pickedLabel} stroke={MILK_COLOR} strokeWidth={8} strokeOpacity={0.18} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <Legend items={[
            { label: t('Recorded'), color: MILK_COLOR },
            ...(rows.some((r) => r.partial) ? [{ label: t('Partly recorded (estimate)'), kind: 'dot' as const }] : []),
            ...(rows.some((r) => r.bridge !== null && r.recorded === null) ? [{ label: t('No record (joined)'), color: MILK_COLOR, kind: 'dash' as const }] : []),
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
      {picked && (expanded || !selection) && <PointExplanation kind="milk" at={picked} onClose={clear} />}
    </>}
    </ChartView>
  );
}

function MilkTip({ active, payload, grain }: { active?: boolean; payload?: { payload: MilkRow }[]; grain: Grain }) {
  const t = useT();
  const { lang } = useLang();
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  const rows: [string, string][] = [];
  if (r.recorded !== null) rows.push([r.partial ? t('Partly recorded (estimate)') : t('Recorded'), `${litres(r.recorded)} L`]);
  else if (r.expected !== null) rows.push([t('Expected'), `${litres(r.expected)} L`]);
  if (r.future && r.band) rows.push([t('Likely range'), `${litres(r.band[0])} – ${litres(r.band[1])}`]);
  if (r.actual !== null) rows.push([t('What actually happened'), `${litres(r.actual)} L`]);
  if (r.lastYear !== null) rows.push([t('A year before'), `${litres(r.lastYear)} L`]);
  return <TipShell title={periodText(r.period, grain, lang)} rows={rows} note={t('Click to explain')} />;
}

/* ------------------------------------------------------------------ herd population */

const GROUPS: SeriesId[] = ['total_herd', 'dry', 'heifers', 'calves', 'other'];
const COLOR: Record<string, string> = { total_herd: '#17231f', milking: '#2f7f86', dry: '#c99a77', heifers: '#5b7fa6', calves: '#93aec9', other: '#8a8f87' };

export function HerdChart({ selection }: { selection?: PointSelection }) {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();
  const { asTable, toggle } = useChartOrTable();
  const { history, controls } = useChartStart(run, grain);
  const shown = GROUPS.filter((s) => isForecast(run, grain, s) || run.actuals.some((a) => a.grain === grain && a.series === s));
  const rows = useMemo(() => timeline(run, grain, horizon, history).map((p) => {
    const r: Record<string, number | string | boolean | null> = { period: p.period, label: periodText(p.period, grain, lang, true), future: p.future };
    shown.forEach((s) => {
      r[s] = p.future ? null : (p[s] as number | undefined) ?? null;
      r[`${s}_f`] = (p[`${s}_f`] as number | undefined) ?? null;
      r[`${s}_r`] = p.future ? (p[`${s}_r`] as number | undefined) ?? null : null;
    });
    return r;
  }), [run, grain, horizon, lang, history, shown.join()]);
  const start = rows.find((r) => r.future)?.label as string | undefined;
  const realised = shown.some((s) => rows.some((r) => r[`${s}_r`] != null));
  const { picked, pick, clear, onChartClick } = usePointPick(selection);
  const pickedLabel = rows.find((r) => r.period === picked)?.label as string | undefined;
  const val = (r: Record<string, unknown>, s: string) => (r[s] ?? r[`${s}_f`]) as number | null;

  if (!shown.length) return null;
  return (
    <ChartView title={t('Herd population')} actions={toggle} controls={controls}>
      {(expanded) => <>
      {!asTable ? (
        <>
          <div style={{ height: expanded ? (picked ? 300 : 'max(320px, calc(100dvh - 300px))') : 280 }}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }} onClick={onChartClick} className="pfie-mgr-clickchart">
                <CartesianGrid stroke="#eef2f0" vertical={false} />
                <XAxis dataKey="label" tick={CHART_TICK} interval="preserveStartEnd" minTickGap={18} />
                <YAxis tick={CHART_TICK} width={50} tickFormatter={(v: number) => fmtInt(v)} />
                {start && <ReferenceLine x={start} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12, fill: '#34483f' }} />}
                {pickedLabel && <ReferenceLine x={pickedLabel} stroke={MILK_COLOR} strokeWidth={8} strokeOpacity={0.18} />}
                {shown.map((s) => <Line key={s} dataKey={s} stroke={COLOR[s]} strokeWidth={s === 'total_herd' ? 3 : 2.2} dot={false} isAnimationActive={false} />)}
                {shown.map((s) => <Line key={`${s}_f`} dataKey={`${s}_f`} stroke={COLOR[s]} strokeWidth={s === 'total_herd' ? 3 : 2.2} strokeDasharray="7 5" dot={false} isAnimationActive={false} />)}
                {realised && shown.map((s) => <Line key={`${s}_r`} dataKey={`${s}_r`} stroke={COLOR[s]} strokeWidth={1.6} strokeDasharray={grain === 'day' ? '1 2' : undefined} dot={grain === 'day' ? false : { r: 3, fill: '#fff', stroke: COLOR[s], strokeWidth: 2 }} connectNulls isAnimationActive={false} />)}
                <Tooltip content={({ active, payload }) => {
                  const r = payload?.[0]?.payload as Record<string, number | string | null> | undefined;
                  if (picked || !active || !r) return null;
                  return <TipShell title={periodText(String(r.period), grain, lang)} rows={shown.flatMap((s): [string, string, string][] => {
                    const v = val(r, s);
                    const actual = r[`${s}_r`];
                    const label = t(PLAIN_SERIES[s]);
                    const color = COLOR[s] ?? SERIES_META[s].color;
                    return [
                      [`${label} · ${t(r.future ? 'Expected' : 'Recorded')}`, v != null ? whole(v) : '—', color],
                      ...(typeof actual === 'number' ? [[`${label} · ${t('What actually happened')}`, whole(actual), color] as [string, string, string]] : []),
                    ];
                  })} note={t('Click to explain')} />;
                }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <Legend items={[
            ...shown.map((s) => ({ label: t(PLAIN_SERIES[s]), color: COLOR[s] })),
            { label: t('Expected'), color: FORECAST_COLOR, kind: 'dash' },
            ...(realised ? [{ label: t('What actually happened'), kind: 'dot' as const }] : []),
          ]} />
        </>
      ) : (
        <SimpleTable
          head={[t('Date'), ...shown.flatMap((s) => [t(PLAIN_SERIES[s]), ...(realised ? [`${t(PLAIN_SERIES[s])} · ${t('What actually happened')}`] : [])])]}
          onRow={(i) => { const p = String(rows[i].period); pick(p === picked ? null : p); }}
          selected={rows.findIndex((r) => r.period === picked)}
          rows={rows.map((r) => [
            <>{periodText(String(r.period), grain, lang)}{r.future && <span className="pfie-mgr-tag">{t('expected')}</span>}</>,
            ...shown.flatMap((s) => {
              const v = val(r, s);
              const actual = r[`${s}_r`];
              return [v != null ? whole(v) : '—', ...(realised ? [typeof actual === 'number' ? whole(actual) : '—'] : [])];
            }),
          ])}
        />
      )}
      <PickHint picked={picked} />
      {picked && (expanded || !selection) && <PointExplanation kind="herd" at={picked} onClose={clear} />}
    </>}
    </ChartView>
  );
}
