/**
 * Component 1 (PFOI): past → origin → future timeline.
 *
 * Four bands on one time axis, read top to bottom:
 *  1. milk — herd total or per milking cow, per day, week or month as the grain
 *     selector at the top says, with
 *     milking cows and total herd on a second (head) axis;
 *  2. cows — milking vs dry, the two groups that make up the cows;
 *  3. herd population — total herd and each non-overlapping group as its own
 *     line (not stacked areas, so no group reads as containing another);
 *  4. herd events per period.
 * Observed values are solid; forecasts are dashed or hatched, so the difference
 * survives without colour.
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
  HISTORY_ALL,
  SERIES_META,
  confidenceOf,
  fmt1,
  fmtInt,
  periodDays,
  periodLabel,
  periodsUntilOrigin,
  hasRealised,
  isForecast,
  sourceSwitch,
  timeline,
  type Grain,
  type SeriesId,
  type TimelinePoint,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, HATCH_DEFS, KindTag, Segmented, TipShell, type TipRow } from '../ui';
import { TimelinePlayer } from './TimelinePlayer';

type Band = 'milk' | 'cows' | 'herd' | 'events';
type MilkMode = 'total' | 'per_cow';
type Row = TimelinePoint & Record<string, unknown>;

/* Groups that do not overlap: total herd = cows + heifers + calves + bulls & other,
   and cows = milking + dry. */
const COWS_COLOR = '#6d4c8a';
const POPULATION: { key: string; label: string; color: string }[] = [
  { key: 'cows', label: 'Cows (milking + dry)', color: COWS_COLOR },
  { key: 'heifers', label: SERIES_META.heifers.label, color: SERIES_META.heifers.color },
  { key: 'calves', label: SERIES_META.calves.label, color: SERIES_META.calves.color },
  { key: 'other', label: SERIES_META.other.label, color: SERIES_META.other.color },
];
const MILK_COLOR = '#9a4f27';
const FORECAST_COLOR = '#5b7fa6';
const EVENT_CHOICES: SeriesId[] = [...EVENT_SERIES.filter((s) => s !== 'entries'), 'mastitis_episodes'];

/** The timeline at the selected grain, horizon and history start; shared by every panel that plays it. */
export function useTimelinePoints() {
  const { grain, horizon, historyFrom } = usePfoi();
  const run = useRun();
  return useMemo(
    () => timeline(run, grain, horizon, historyFrom ? Math.max(1, periodsUntilOrigin(run, grain, historyFrom)) : HISTORY_ALL),
    [run, grain, horizon, historyFrom],
  );
}

export function MasterTimeline({ bands = ['milk', 'cows', 'herd', 'events'], player = true }: { bands?: Band[]; player?: boolean }) {
  const { grain, horizon, selectedPeriod, setSelectedPeriod, openDrawer } = usePfoi();
  const points = useTimelinePoints();
  const run = useRun();
  const realised = hasRealised(run);
  /* pfoi-1.1.1 forecasts the herd daily; earlier runs only weekly and monthly */
  const herdDaily = isForecast(run, grain, 'milking');
  const origin = points.find((p) => p.future)?.period ?? null;
  const switchAt = sourceSwitch(points);
  const gaps = useMemo(() => gapRuns(points), [points]);
  /* F2: milk forecast withheld (no trusted milk level): hatch the forecast span, no line */
  const milkWithheld = (run.withheld ?? []).some((w) => w.series === 'milk_litres');
  const futureSpan = useMemo(() => {
    const f = points.filter((p) => p.future);
    return f.length ? [f[0].period, f[f.length - 1].period] as const : null;
  }, [points]);
  const [events, setEvents] = useState<SeriesId[]>(['calvings', 'dry_offs', 'abortions']);
  const [milkMode, setMilkMode] = useState<MilkMode>('total');
  const [overlay, setOverlay] = useState<{ milking: boolean; total_herd: boolean }>({ milking: true, total_herd: true });
  /* Lines shown in the cows and herd-population bands; each chip turns one on or off, like the event chips. */
  const [cowLines, setCowLines] = useState<SeriesId[]>(['milking', 'dry']);
  const [popLines, setPopLines] = useState<string[]>(['total_herd', ...POPULATION.map((g) => g.key)]);
  const flip = <T,>(set: (f: (cur: T[]) => T[]) => void, v: T) => set((cur) => (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]));
  const chip = (key: string, on: boolean, color: string, label: string, onClick: () => void) => (
    <button key={key} className={`pfie-serieschip${on ? ' on' : ''}`} onClick={onClick} aria-pressed={on}>
      <i style={{ background: color }} />{label}
    </button>
  );
  const milkUnit = milkMode === 'per_cow' ? `L/cow/${grain}` : `L/${grain}`;
  const rows = useMemo(() => withDerived(points, grain, milkMode), [points, grain, milkMode]);
  const tick = (iso: string) => periodLabel(iso, grain, true);
  const selected = selectedPeriod && points.some((p) => p.period === selectedPeriod) ? selectedPeriod : null;

  const onClick = (state: { activeLabel?: string | number } | null) => {
    if (state?.activeLabel) setSelectedPeriod(String(state.activeLabel));
  };

  const common = (height: number) => ({
    data: rows,
    height,
    margin: { top: 8, right: 12, bottom: 0, left: 0 },
    onClick,
  });

  const axes = (unit: string) => (
    <>
      <CartesianGrid stroke="#eef2f0" vertical={false} />
      <XAxis dataKey="period" tickFormatter={tick} tick={{ fontSize: 11, fill: '#70827a' }} minTickGap={24} />
      <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={unit.startsWith('L/') ? 70 : 52} tickFormatter={(v: number) => fmtInt(v)} label={{ value: unit, angle: -90, position: 'insideLeft', fontSize: 10, fill: '#70827a' }} />
      {origin && <ReferenceLine x={origin} stroke="#5b7fa6" strokeDasharray="4 3" label={{ value: realised ? 'Forecast date' : 'Origin', position: 'insideTopRight', fontSize: 10, fill: '#5b7fa6' }} />}
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
      {player && <TimelinePlayer points={points} />}

      {bands.includes('milk') && (
        <div className="pfie-band pfie-tlband">
          <div className="pfie-row between pfie-tlband-head">
            <h4 className="pfie-bandctl-label">Milk · {milkUnit}</h4>
            <span className="pfie-row tight">
              <Segmented<MilkMode>
                value={milkMode}
                onChange={setMilkMode}
                options={[
                  { id: 'total', label: 'Herd total' },
                  { id: 'per_cow', label: 'Per cow' },
                ]}
              />
              {(['milking', 'total_herd'] as const).map((s) => (
                <button
                  key={s}
                  className={`pfie-serieschip${overlay[s] ? ' on' : ''}`}
                  onClick={() => setOverlay((o) => ({ ...o, [s]: !o[s] }))}
                  aria-pressed={overlay[s]}
                >
                  <i style={{ background: SERIES_META[s].color }} />{SERIES_META[s].label}
                </button>
              ))}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart {...common(260)} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
              {HATCH_DEFS}
              {gaps.map(([a, b]) => (
                <ReferenceArea key={a} x1={a} x2={b} fill="url(#pfieDots)" fillOpacity={1} stroke="none" />
              ))}
              {milkWithheld && futureSpan && (
                <ReferenceArea
                  x1={futureSpan[0]} x2={futureSpan[1]} fill="url(#pfieHatchLight)" fillOpacity={1} stroke="none"
                  label={{ value: 'Milk forecast withheld: no trusted milk records', position: 'insideTop', fontSize: 11, fill: '#34483f' }}
                />
              )}
              {axes(milkUnit)}
              {(overlay.milking || overlay.total_herd) && (
                <YAxis yAxisId="head" orientation="right" tick={{ fontSize: 11, fill: '#70827a' }} width={44} tickFormatter={(v: number) => fmtInt(v)} label={{ value: 'head', angle: 90, position: 'insideRight', fontSize: 10, fill: '#70827a' }} />
              )}
              {switchAt && <ReferenceLine x={switchAt} stroke="#a8770a" strokeDasharray="2 3" label={{ value: 'Record source changes', position: 'insideTopLeft', fontSize: 10, fill: '#a8770a' }} />}
              {milkMode !== 'per_cow' && <Area dataKey="milk_v_band" stroke="none" fill={FORECAST_COLOR} fillOpacity={0.16} isAnimationActive={false} />}
              <Line dataKey="milk_v" stroke={MILK_COLOR} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
              <Line dataKey="milk_v_f" stroke={FORECAST_COLOR} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              {realised && <Line dataKey="milk_v_r" stroke={MILK_COLOR} strokeWidth={2} dot={outcomeDot(MILK_COLOR)} connectNulls={false} isAnimationActive={false} />}
              {(['milking', 'total_herd'] as const).filter((s) => overlay[s]).flatMap((s) => [
                <Line key={s} yAxisId="head" dataKey={s} stroke={SERIES_META[s].color} strokeWidth={1.2} strokeOpacity={0.85} dot={false} isAnimationActive={false} />,
                <Line key={`${s}_f`} yAxisId="head" dataKey={`${s}_f`} stroke={SERIES_META[s].color} strokeWidth={1.2} strokeDasharray="4 3" strokeOpacity={0.85} dot={false} isAnimationActive={false} />,
                ...(realised ? [<Line key={`${s}_r`} yAxisId="head" dataKey={`${s}_r`} stroke={SERIES_META[s].color} strokeWidth={1.2} strokeOpacity={0.85} dot={outcomeDot(SERIES_META[s].color, 2)} isAnimationActive={false} />] : []),
              ])}
              <Tooltip content={<MilkTip grain={grain} />} />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="pfie-legend">
            <span><i style={{ background: MILK_COLOR }} />Milk, recorded</span>
            <span><i className="dash" />Forecast</span>
            {realised && <OutcomeLegend color={MILK_COLOR} />}
            {milkMode !== 'per_cow' && <span><i style={{ background: 'rgba(91,127,166,.25)' }} />5–95% range</span>}
            {overlay.milking && <span><i style={{ background: SERIES_META.milking.color, height: 2 }} />Milking cows (right axis)</span>}
            {overlay.total_herd && <span><i style={{ background: SERIES_META.total_herd.color, height: 2 }} />Total herd (right axis)</span>}
            <span><i style={{ backgroundImage: 'radial-gradient(#93aec9 1.2px, #f2f5f8 1.3px)', backgroundSize: '6px 6px' }} />Data gap or flagged record</span>
            {milkWithheld && <span><i className="hatch" />Milk forecast withheld</span>}
          </div>
          {milkMode === 'per_cow' && (
            <p className="pfie-chart-note">
              Per cow = herd milk in the {grain} ÷ average milking cows in the {grain} <KindTag kind="derived" />.
              {!herdDaily ? ' Milking cows are not forecast daily, so there is no per-cow forecast at this grain.' : ' The forecast has no range here, because the herd and milk ranges are not joint.'}
            </p>
          )}
          {grain === 'month' && (
            <p className="pfie-chart-note">Monthly amounts also move with the number of days in the month (February is always lower); the tooltip gives the daily average too.</p>
          )}
          {grain !== 'month' && isForecast(run, 'day', 'milking') && (
            <p className="pfie-chart-note">
              Each day and week is the model&apos;s expected path, scaled so the days add up exactly to each month&apos;s forecast.
              It follows the herd and lactation stages, not day-to-day swings, so the 5–95% range is what to read far ahead.
            </p>
          )}
        </div>
      )}

      {bands.includes('cows') && (
        <div className="pfie-band pfie-tlband">
          <div className="pfie-row between pfie-tlband-head">
            <h4 className="pfie-bandctl-label">Cows · milking and dry · head (daily average)</h4>
            <span className="pfie-row tight">
              {(['milking', 'dry'] as SeriesId[]).map((s) => chip(s, cowLines.includes(s), SERIES_META[s].color, s === 'dry' ? 'Dry cows' : 'Milking cows', () => flip(setCowLines, s)))}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart {...common(200)}>
              {axes('head')}
              {(['milking', 'dry'] as SeriesId[]).filter((s) => cowLines.includes(s)).flatMap((s) => [
                <Area key={`${s}_band`} dataKey={`${s}_band`} stroke="none" fill={SERIES_META[s].color} fillOpacity={0.12} isAnimationActive={false} />,
                <Line key={s} dataKey={s} stroke={SERIES_META[s].color} strokeWidth={2} dot={false} isAnimationActive={false} />,
                <Line key={`${s}_f`} dataKey={`${s}_f`} stroke={SERIES_META[s].color} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />,
                ...(realised ? [<Line key={`${s}_r`} dataKey={`${s}_r`} stroke={SERIES_META[s].color} strokeWidth={2} dot={outcomeDot(SERIES_META[s].color)} isAnimationActive={false} />] : []),
              ])}
              <Tooltip content={<CowsTip />} />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="pfie-legend">
            <span><i className="dash" />Forecast, with 5–95% range</span>
            {realised && <OutcomeLegend color={SERIES_META.milking.color} />}
          </div>
          {!herdDaily && <p className="pfie-chart-note">Herd counts are forecast weekly and monthly; the daily view shows the record only.</p>}
        </div>
      )}

      {bands.includes('herd') && (
        <div className="pfie-band pfie-tlband">
          <div className="pfie-row between pfie-tlband-head">
            <h4 className="pfie-bandctl-label">Herd population · head (daily average)</h4>
            <span className="pfie-row tight">
              {chip('total_herd', popLines.includes('total_herd'), SERIES_META.total_herd.color, 'Total herd', () => flip(setPopLines, 'total_herd'))}
              {POPULATION.map((g) => chip(g.key, popLines.includes(g.key), g.color, g.label, () => flip(setPopLines, g.key)))}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart {...common(220)}>
              {axes('head')}
              {popLines.includes('total_herd') && <>
                <Area dataKey="total_herd_band" stroke="none" fill={SERIES_META.total_herd.color} fillOpacity={0.1} isAnimationActive={false} />
                <Line dataKey="total_herd" stroke={SERIES_META.total_herd.color} strokeWidth={2.6} dot={false} isAnimationActive={false} />
                <Line dataKey="total_herd_f" stroke={SERIES_META.total_herd.color} strokeWidth={2.6} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                {realised && <Line dataKey="total_herd_r" stroke={SERIES_META.total_herd.color} strokeWidth={2.6} dot={outcomeDot(SERIES_META.total_herd.color)} isAnimationActive={false} />}
              </>}
              {POPULATION.filter((g) => popLines.includes(g.key)).flatMap((g) => [
                <Line key={g.key} dataKey={g.key} stroke={g.color} strokeWidth={1.6} dot={false} isAnimationActive={false} />,
                <Line key={`${g.key}_f`} dataKey={`${g.key}_f`} stroke={g.color} strokeWidth={1.6} strokeDasharray="4 3" dot={false} isAnimationActive={false} />,
                ...(realised ? [<Line key={`${g.key}_r`} dataKey={`${g.key}_r`} stroke={g.color} strokeWidth={1.6} dot={outcomeDot(g.color, 2)} isAnimationActive={false} />] : []),
              ])}
              <Tooltip content={<PopulationTip />} />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="pfie-legend">
            <span><i className="dash" />Forecast</span>
            {realised && <OutcomeLegend color={SERIES_META.total_herd.color} />}
          </div>
          <p className="pfie-chart-note">
            The groups do not overlap: total herd = cows + heifers + calves + bulls &amp; other. Each is drawn as its own line so its movement is readable on its own.
            {!herdDaily ? ' Herd counts are forecast weekly and monthly; the daily view shows the record only.' : ''}
          </p>
        </div>
      )}

      {bands.includes('events') && (
        <div className="pfie-band pfie-tlband">
          <div className="pfie-row between pfie-tlband-head">
            <h4 className="pfie-bandctl-label">Herd events · per {grain}</h4>
            <span className="pfie-row tight">
              {EVENT_CHOICES.map((s) => chip(s, events.includes(s), SERIES_META[s].color, SERIES_META[s].label, () => flip(setEvents, s)))}
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
              {realised && events.map((s) => (
                <Line key={`${s}_r`} dataKey={`${s}_r`} stroke="none" dot={outcomeDot(SERIES_META[s].color, 4)} activeDot={false} isAnimationActive={false} />
              ))}
              <Tooltip content={<SeriesTip series={events} />} />
            </ComposedChart>
          </ResponsiveContainer>
          {realised && (
            <div className="pfie-legend">
              <span><i style={{ background: 'rgba(91,127,166,.35)' }} />Forecast (hatched, stacked)</span>
              <span><i style={{ background: '#34483f', borderRadius: '50%', width: 8, height: 8 }} />Recorded outcome of each event type (dots, not stacked; not seen by the model)</span>
            </div>
          )}
          {!isForecast(run, grain, 'calvings') && <p className="pfie-chart-note">Herd events are forecast weekly and monthly; the daily view shows the record only.</p>}
        </div>
      )}

    </Card>
  );
}

/** Recorded outcomes after the forecast date: the series colour, solid, with ringed dots. */
const outcomeDot = (color: string, r = 3) => ({ r, fill: '#fff', stroke: color, strokeWidth: 2 });

function OutcomeLegend({ color }: { color: string }) {
  return (
    <span title="What was recorded after the forecast date. The model never saw these values.">
      <i style={{ background: '#fff', border: `2px solid ${color}`, borderRadius: '50%', width: 8, height: 8 }} />
      Recorded outcome (not seen by the model)
    </span>
  );
}

/** Consecutive periods with a missing or flagged milk record, as [first, last]. */
function gapRuns(points: TimelinePoint[]) {
  const runs: [string, string][] = [];
  let start: string | null = null;
  let last: string | null = null;
  points.forEach((p) => {
    if (p.milkGap) {
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

/** Adds the milk value in the chosen unit, period totals, per-cow milk and cows (milking + dry). */
function withDerived(points: TimelinePoint[], grain: Grain, mode: MilkMode): Row[] {
  const num = (v: unknown) => (typeof v === 'number' ? v : null);
  const r1 = (n: number) => Math.round(n * 10) / 10;
  return points.map((p) => {
    const days = periodDays(p.period, grain);
    const milk = num(p.milk_litres);
    const milkF = num(p.milk_litres_f);
    const band = p.milk_litres_band as [number, number] | undefined;
    const milking = num(p.milking);
    const milkingF = num(p.milking_f);
    const milkR = num(p.milk_litres_r);
    const milkingR = num(p.milking_r);
    const perCow = milk !== null && milking ? milk / milking : null;
    const perCowF = milkF !== null && milkingF ? milkF / milkingF : null;
    const row: Row = {
      ...p,
      days,
      milk_total: milk !== null ? milk * days : null,
      milk_total_f: milkF !== null ? milkF * days : null,
      milk_pc: perCow !== null ? r1(perCow) : null,
      milk_pc_f: perCowF !== null ? r1(perCowF) : null,
      milk_v: mode === 'per_cow' ? (perCow !== null ? r1(perCow * days) : null) : milk !== null ? milk * days : null,
      milk_v_f: mode === 'per_cow' ? (perCowF !== null ? r1(perCowF * days) : null) : milkF !== null ? milkF * days : null,
      milk_v_band: mode !== 'per_cow' && band ? [band[0] * days, band[1] * days] : undefined,
      milk_v_r: mode === 'per_cow'
        ? (milkR !== null && milkingR ? r1((milkR / milkingR) * days) : null)
        : milkR !== null ? milkR * days : null,
    };
    const dry = num(p.dry);
    const dryF = num(p.dry_f);
    if (milking !== null && dry !== null) row.cows = milking + dry;
    if (milkingF !== null && dryF !== null) row.cows_f = milkingF + dryF;
    const dryR = num(p.dry_r);
    if (milkingR !== null && dryR !== null) row.cows_r = milkingR + dryR;
    return row;
  });
}

type TipProps = { active?: boolean; payload?: { payload: Row }[] };

const outcomePct = (outcome: number, forecast: number) =>
  forecast ? `${outcome - forecast >= 0 ? '+' : '−'}${Math.abs(((outcome - forecast) / forecast) * 100).toFixed(0)}% of forecast` : '—';

/** "Recorded" rows for a forecast point at a past forecast date: outcome and outcome − forecast. */
function outcomeRows(p: Row, series: string[], f: (n: number) => string = fmtInt): TipRow[] {
  const out: TipRow[] = [];
  series.forEach((s) => {
    const r = p[`${s}_r`];
    const fc = p[`${s}_f`];
    if (typeof r !== 'number' || typeof fc !== 'number') return;
    const label = s in SERIES_META ? SERIES_META[s as SeriesId].label : s;
    const color = s in SERIES_META ? SERIES_META[s as SeriesId].color : undefined;
    out.push([`${label}, recorded`, `${f(r)} (${r - fc >= 0 ? '+' : '−'}${f(Math.abs(r - fc))} vs forecast)`, color]);
  });
  return out;
}

const pick = (p: Row, key: string) => {
  const v = p.future ? p[`${key}_f`] : p[key];
  return typeof v === 'number' ? v : null;
};

function MilkTip({ active, payload, grain }: TipProps & { grain: Grain }) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  const band = p.milk_litres_band as [number, number] | undefined;
  const perDayV = pick(p, 'milk_litres');
  const total = pick(p, 'milk_total');
  const perCow = pick(p, 'milk_pc');
  const milking = pick(p, 'milking');
  const herd = pick(p, 'total_herd');
  const color = p.future ? FORECAST_COLOR : MILK_COLOR;
  const rows: TipRow[] = [];
  if (grain !== 'day' && total !== null) rows.push([`Total in the ${grain}`, `${fmtInt(total)} L`, color]);
  if (perDayV !== null) rows.push(['Average per day', `${fmtInt(perDayV)} L/day`, grain === 'day' ? color : undefined]);
  if (p.future && band) rows.push(['5–95% range', `${fmtInt(band[0])}–${fmtInt(band[1])} L/day`]);
  const outcome = typeof p.milk_litres_r === 'number' ? p.milk_litres_r : null;
  if (p.future && outcome !== null && perDayV !== null) {
    rows.push(['Recorded outcome', `${fmtInt(outcome)} L/day`, MILK_COLOR]);
    rows.push(['Outcome − forecast', `${outcome - perDayV >= 0 ? '+' : '−'}${fmtInt(Math.abs(outcome - perDayV))} L/day (${outcomePct(outcome, perDayV)})${band ? (outcome >= band[0] && outcome <= band[1] ? ' · inside range' : ' · outside range') : ''}`]);
  }
  if (perCow !== null) {
    if (grain !== 'day') rows.push([`Per cow in the ${grain}`, `${fmt1(perCow * Number(p.days))} L`]);
    rows.push(['Per cow per day', `${fmt1(perCow)} L`]);
  }
  if (milking !== null) rows.push(['Milking cows', fmtInt(milking), SERIES_META.milking.color]);
  if (herd !== null) rows.push(['Total herd', fmtInt(herd), SERIES_META.total_herd.color]);
  if (p.milkSource) rows.push(['Record', p.milkSource === 'shipment' ? 'Shipments' : 'DelPro']);
  const note = p.future
    ? `${p.horizon} ahead · ${confidenceOf(p.quality).toLowerCase()} confidence. Click, then "Explain" for the breakdown.`
    : p.milkGap ? 'Missing or flagged record: not scored.' : 'Click, then "Explain" for the breakdown.';
  const gapNote = p.future && p.milkGap ? ' The recorded outcome is missing or flagged: not scored.' : '';
  return <TipShell title={p.label} rows={rows} note={note + gapNote} />;
}

function CowsTip({ active, payload }: TipProps) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  const milking = pick(p, 'milking');
  const dry = pick(p, 'dry');
  const rows: TipRow[] = [
    ['Milking cows', milking !== null ? fmtInt(milking) : '—', SERIES_META.milking.color],
    ['Dry cows', dry !== null ? fmtInt(dry) : '—', SERIES_META.dry.color],
  ];
  if (milking !== null && dry !== null && milking + dry > 0) {
    rows.push(['Cows', fmtInt(milking + dry)]);
    rows.push(['Share of cows in milk', `${Math.round((milking / (milking + dry)) * 100)}%`]);
  }
  if (p.future) rows.push(...outcomeRows(p, ['milking', 'dry']));
  return <TipShell title={p.label} rows={rows} note={p.future ? 'Forecast.' : 'Recorded, daily average over the period.'} />;
}

function PopulationTip({ active, payload }: TipProps) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  const herd = pick(p, 'total_herd');
  const rows: TipRow[] = [['Total herd', herd !== null ? fmtInt(herd) : '—', SERIES_META.total_herd.color]];
  POPULATION.forEach((g) => {
    const v = pick(p, g.key);
    rows.push([g.label, v === null ? '—' : herd ? `${fmtInt(v)} · ${Math.round((v / herd) * 100)}%` : fmtInt(v), g.color]);
  });
  if (p.future) rows.push(...outcomeRows(p, ['total_herd']));
  return <TipShell title={p.label} rows={rows} note={p.future ? 'Forecast.' : 'Recorded, daily average over the period.'} />;
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
  if (p.future) rows.push(...outcomeRows(p, series, fmt1));
  return <TipShell title={p.label} rows={rows} note={p.future ? 'Forecast, with its 5–95% range.' : 'Recorded.'} />;
}
