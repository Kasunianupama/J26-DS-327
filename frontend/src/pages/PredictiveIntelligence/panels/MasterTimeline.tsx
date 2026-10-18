/**
 * Component 1 (PFOI): past → origin → future timeline.
 *
 * Three bands on one time axis: milk (actual, forecast, 5–95% range, data
 * gap and record-source switch), herd events (actual vs forecast counts) and
 * herd counts by state. Observed values are solid; forecasts are dashed or
 * hatched, so the difference survives without colour.
 */

import { useMemo, useState } from 'react';
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  EVENT_SERIES,
  SERIES_META,
  confidenceOf,
  fmt1,
  fmtInt,
  periodLabel,
  sourceSwitch,
  timeline,
  type SeriesId,
  type TimelinePoint,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, HATCH_DEFS, TipShell, type TipRow } from '../ui';
import { TimelinePlayer } from './TimelinePlayer';

type Band = 'milk' | 'events' | 'herd';
const HERD_STATES: SeriesId[] = ['milking', 'dry', 'heifers', 'calves'];
const EVENT_CHOICES: SeriesId[] = [...EVENT_SERIES.filter((s) => s !== 'entries'), 'mastitis_episodes'];

export function MasterTimeline({ bands = ['milk', 'events', 'herd'] }: { bands?: Band[] }) {
  const { grain, horizon, selectedPeriod, setSelectedPeriod, openDrawer } = usePfoi();
  const run = useRun();
  const points = useMemo(() => timeline(run, grain, horizon), [run, grain, horizon]);
  const origin = points.find((p) => p.future)?.period ?? null;
  const switchAt = sourceSwitch(points);
  const gaps = useMemo(() => gapRuns(points), [points]);
  const [events, setEvents] = useState<SeriesId[]>(['calvings', 'dry_offs', 'abortions']);
  const tick = (iso: string) => periodLabel(iso, grain, true);
  const selected = selectedPeriod && points.some((p) => p.period === selectedPeriod) ? selectedPeriod : null;

  const onClick = (state: { activeLabel?: string | number } | null) => {
    if (state?.activeLabel) setSelectedPeriod(String(state.activeLabel));
  };

  const common = (height: number) => ({
    data: points,
    height,
    margin: { top: 8, right: 12, bottom: 0, left: 0 },
    onClick,
  });

  const axes = (unit: string) => (
    <>
      <CartesianGrid stroke="#eef2f0" vertical={false} />
      <XAxis dataKey="period" tickFormatter={tick} tick={{ fontSize: 11, fill: '#70827a' }} minTickGap={24} />
      <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={52} tickFormatter={(v: number) => fmtInt(v)} label={{ value: unit, angle: -90, position: 'insideLeft', fontSize: 10, fill: '#70827a' }} />
      {origin && <ReferenceLine x={origin} stroke="#5b7fa6" strokeDasharray="4 3" label={{ value: 'Origin', position: 'insideTopRight', fontSize: 10, fill: '#5b7fa6' }} />}
      {selected && <ReferenceLine x={selected} stroke="#9a4f27" strokeWidth={1.5} />}
    </>
  );

  return (
    <Card
      icon="outlook"
      title="Farm timeline"
      sub={`Recorded history, the forecast origin, and the expected path ${horizon} ${grain === 'day' ? 'days' : grain === 'week' ? 'weeks' : 'months'} ahead`}
      actions={selected ? (
        <button className="pfie-btn primary" onClick={() => openDrawer({ kind: 'point', period: selected, grain })}>
          Explain {periodLabel(selected, grain)}
        </button>
      ) : undefined}
    >
      <TimelinePlayer points={points} />

      {bands.includes('milk') && (
        <div className="pfie-band">
          <h4 className="pfie-bandctl-label">Milk · L/day</h4>
          <ResponsiveContainer width="100%" height={230}>
            <ComposedChart {...common(230)}>
              {HATCH_DEFS}
              {gaps.map(([a, b]) => (
                <ReferenceArea key={a} x1={a} x2={b} fill="url(#pfieDots)" fillOpacity={1} stroke="none" />
              ))}
              {axes('L/day')}
              {switchAt && <ReferenceLine x={switchAt} stroke="#a8770a" strokeDasharray="2 3" label={{ value: 'Record source changes', position: 'insideTopLeft', fontSize: 10, fill: '#a8770a' }} />}
              <Area dataKey="milk_litres_band" stroke="none" fill="#5b7fa6" fillOpacity={0.16} isAnimationActive={false} />
              <Line dataKey="milk_litres" stroke="#9a4f27" strokeWidth={1.8} dot={false} connectNulls={false} isAnimationActive={false} />
              <Line dataKey="milk_litres_f" stroke="#5b7fa6" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              <Tooltip content={<MilkTip />} />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="pfie-legend">
            <span><i style={{ background: '#9a4f27' }} />Actual</span>
            <span><i className="dash" />Forecast</span>
            <span><i style={{ background: 'rgba(91,127,166,.25)' }} />5–95% range</span>
            <span><i style={{ backgroundImage: 'radial-gradient(#93aec9 1.2px, #f2f5f8 1.3px)', backgroundSize: '6px 6px' }} />Data gap or flagged record</span>
          </div>
        </div>
      )}

      {bands.includes('events') && (
        <div className="pfie-band">
          <div className="pfie-row between">
            <h4 className="pfie-bandctl-label">Herd events · per {grain}</h4>
            <span className="pfie-row tight">
              {EVENT_CHOICES.map((s) => (
                <button
                  key={s}
                  className={`pfie-serieschip${events.includes(s) ? ' on' : ''}`}
                  onClick={() => setEvents((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))}
                  aria-pressed={events.includes(s)}
                >
                  <i style={{ background: SERIES_META[s].color }} />{SERIES_META[s].label}
                </button>
              ))}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={190}>
            <ComposedChart {...common(190)}>
              {HATCH_DEFS}
              {axes('events')}
              {events.map((s) => (
                <Bar key={s} dataKey={s} stackId="a" fill={SERIES_META[s].color} isAnimationActive={false} />
              ))}
              {events.map((s) => (
                <Bar key={`${s}_f`} dataKey={`${s}_f`} stackId="f" fill={SERIES_META[s].color} fillOpacity={0.4} stroke={SERIES_META[s].color} strokeDasharray="3 2" isAnimationActive={false} />
              ))}
              <Tooltip content={<SeriesTip series={events} />} />
            </ComposedChart>
          </ResponsiveContainer>
          {grain === 'day' && <p className="pfie-chart-note">Herd events are forecast weekly and monthly; the daily view shows the record only.</p>}
        </div>
      )}

      {bands.includes('herd') && (
        <div className="pfie-band">
          <h4 className="pfie-bandctl-label">Herd by state · head (daily average)</h4>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart {...common(200)}>
              {axes('head')}
              {HERD_STATES.map((s) => (
                <Area key={s} dataKey={s} stackId="a" stroke={SERIES_META[s].color} fill={SERIES_META[s].color} fillOpacity={0.55} isAnimationActive={false} />
              ))}
              {HERD_STATES.map((s) => (
                <Area key={`${s}_f`} dataKey={`${s}_f`} stackId="f" stroke={SERIES_META[s].color} strokeDasharray="4 3" fill={SERIES_META[s].color} fillOpacity={0.18} isAnimationActive={false} />
              ))}
              <Tooltip content={<SeriesTip series={HERD_STATES} />} />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="pfie-legend">
            {HERD_STATES.map((s) => <span key={s}><i style={{ background: SERIES_META[s].color }} />{SERIES_META[s].label}</span>)}
            <span><i className="dash" />Forecast (lighter)</span>
          </div>
          {grain === 'day' && <p className="pfie-chart-note">Herd counts are forecast weekly and monthly; the daily view shows the record only.</p>}
        </div>
      )}
    </Card>
  );
}

/** Consecutive periods with a missing or flagged milk record, as [first, last]. */
function gapRuns(points: TimelinePoint[]) {
  const runs: [string, string][] = [];
  let start: string | null = null;
  let last: string | null = null;
  points.forEach((p) => {
    if (p.milkGap && !p.future) {
      if (!start) start = p.period;
      last = p.period;
    } else if (start && last) {
      runs.push([start, last]);
      start = null;
      last = null;
    }
  });
  if (start && last) runs.push([start, last]);
  return runs;
}

type TipProps = { active?: boolean; payload?: { payload: TimelinePoint }[] };

function MilkTip({ active, payload }: TipProps) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  const band = p.milk_litres_band as [number, number] | undefined;
  const rows: TipRow[] = [];
  if (typeof p.milk_litres === 'number') rows.push(['Actual', `${fmtInt(p.milk_litres)} L/day`, '#9a4f27']);
  if (p.future && typeof p.milk_litres_f === 'number') rows.push(['Forecast', `${fmtInt(p.milk_litres_f)} L/day`, '#5b7fa6']);
  if (p.future && band) rows.push(['5–95% range', `${fmtInt(band[0])}–${fmtInt(band[1])}`]);
  if (p.milkSource) rows.push(['Record', p.milkSource === 'shipment' ? 'Shipments' : 'DelPro']);
  const note = p.future
    ? `${p.horizon} ahead · ${confidenceOf(p.quality).toLowerCase()} confidence. Click, then "Explain" for the breakdown.`
    : p.milkGap ? 'Missing or flagged record: not scored.' : 'Click, then "Explain" for the breakdown.';
  return <TipShell title={p.label} rows={rows} note={note} />;
}

function SeriesTip({ active, payload, series }: TipProps & { series: SeriesId[] }) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  const rows: TipRow[] = series.map((s) => {
    const a = p[s];
    const f = p[`${s}_f`];
    const band = p[`${s}_band`] as [number, number] | undefined;
    const value = p.future
      ? typeof f === 'number' ? `${fmt1(f)}${band ? ` (${fmt1(band[0])}–${fmt1(band[1])})` : ''}` : '—'
      : typeof a === 'number' ? fmt1(a) : '—';
    return [SERIES_META[s].label, value, SERIES_META[s].color];
  });
  return <TipShell title={p.label} rows={rows} note={p.future ? 'Forecast, with its 5–95% range.' : 'Recorded.'} />;
}
