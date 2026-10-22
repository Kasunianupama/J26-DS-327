/**
 * Simple view, "Milk Yield per Cow": litres per milking cow per day from every model
 * version published for the shown forecast date, on one chart (recorded and what
 * actually happened drawn once). Per cow = that run's herd milk / its milking cows for
 * the same period (recorded: recorded milk / recorded milking cows).
 *
 * The main charts keep showing the page's own run; development versions such as
 * pfoi-1.8.0-dev appear only here (`GET /pfoi/run/versions`, `GET /pfoi/run?model_version=`).
 * A forecast with no calibrated range is drawn as a hollow point and labelled so; a
 * period a version does not forecast is left empty, never filled from another model.
 */

import { useEffect, useMemo, useState } from 'react';
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../../../services/api';
import { forecastRow, hasRealised, perDay, timeline, type Grain, type PfoiRun } from '../../../data/pfoi';
import { useRun } from '../source';
import { TipShell } from '../ui';
import { useLang, useT, periodText } from './i18n';
import { CHART_TICK, Legend, MILK_COLOR, SimpleTable, useChartOrTable } from './common';
import { ChartView, useChartStart } from './ChartView';

const VERSION_COLORS = ['#5b7fa6', '#2a9d5c', '#b5651d', '#8a4fb5'];

interface Version { label: string; run: PfoiRun }

/** Practice comparison for the demo: the demo run's milk for its first month only, no range. */
function demoComparison(run: PfoiRun): Version[] {
  const first = run.outlook.filter((r) => r.series === 'milk_litres')
    .map((r) => r.target_period).sort()[0];
  const end = first ? new Date(new Date(first).getFullYear(), new Date(first).getMonth() + 1, 1) : null;
  const inMonth = (p: string) => end !== null && new Date(p) < end;
  const second: PfoiRun = {
    ...run,
    model_version: 'demo-one-month-model',
    milk_model: end ? { model_version: 'demo-one-month-model', supported_to: new Date(end.getTime() - 864e5).toISOString().slice(0, 10), intervals: 'uncalibrated (practice data)' } : undefined,
    // like pfoi-1.8.0-dev: herd rows kept, milk only for the first month
    outlook: run.outlook.filter((r) => r.series !== 'milk_litres').concat(run.outlook.filter((r) => r.series === 'milk_litres' && inMonth(r.target_period)
      && (r.grain !== 'week' || new Date(new Date(r.target_period).getTime() + 6 * 864e5) < (end as Date)))
      .map((r) => ({ ...r, forecast: r.forecast * 0.97, lower: r.forecast * 0.97, upper: r.forecast * 0.97 }))),
  };
  return [{ label: run.model_version, run }, { label: 'demo-one-month-model', run: second }];
}

function useVersions(run: PfoiRun): { versions: Version[]; loading: boolean } {
  const [fetched, setFetched] = useState<{ origin: string; versions: Version[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const origin = run.origin_date;
  useEffect(() => {
    if (run.source !== 'model') return;
    let alive = true;
    setLoading(true);
    api.get<{ versions: { model_version: string }[] }>('/predictive/pfoi/run/versions', { params: { origin } })
      .then(async (r) => {
        const names = (r.data?.versions ?? []).map((v) => v.model_version).filter((v) => v !== run.model_version);
        const others = await Promise.all(names.map((v) =>
          api.get<PfoiRun>('/predictive/pfoi/run', { params: { origin, model_version: v } })
            .then((d) => (d.data?.source === 'model' ? { label: v, run: d.data } : null))
            .catch(() => null)));
        if (alive) setFetched({ origin, versions: others.filter((x): x is Version => x !== null) });
      })
      .catch(() => { if (alive) setFetched({ origin, versions: [] }); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [run, origin]);
  if (run.source !== 'model') return { versions: demoComparison(run), loading: false };
  const others = fetched?.origin === origin ? fetched.versions : [];
  return { versions: [{ label: run.model_version, run }, ...others], loading };
}

type Row = Record<string, number | string | boolean | [number, number] | null>;

/** Days shown after the origin: through the end of the longest milk forecast of any
 *  version that has a milk model (the predictor's month), else 31 days. */
function forecastDays(run: PfoiRun, versions: Version[]): number {
  const origin = new Date(run.origin_date);
  const ends = versions.map((v) => v.run.milk_model?.supported_to).filter((x): x is string => !!x)
    .map((x) => Math.round((new Date(x).getTime() - origin.getTime()) / 864e5) + 1);
  return ends.length ? Math.max(...ends) : 31;
}

const perCow = (milk: unknown, cows: unknown): number | null =>
  typeof milk === 'number' && typeof cows === 'number' && cows > 0 ? Math.round((milk / cows) * 100) / 100 : null;
const oneDecimal = (v: number) => v.toFixed(1);
const perCowText = (v: number) => `${v.toFixed(1)}`;

export function MilkCompareChart() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  // Always daily: the Notebook 6 predictor forecasts one month, day by day. The page's
  // Weekly / Monthly switch does not apply to this chart.
  const grain: Grain = 'day';
  const { asTable, toggle } = useChartOrTable();
  const { history, controls } = useChartStart(run, grain);
  const { versions, loading } = useVersions(run);
  const horizon = forecastDays(run, versions);
  const realised = hasRealised(run);

  const rows = useMemo<Row[]>(() => timeline(run, grain, horizon, history).map((p) => {
    const r: Row = { period: p.period, label: periodText(p.period, grain, lang, true), future: p.future,
      recorded: p.future ? null : perCow(p.milk_litres, p.milking),
      actual: p.future ? perCow(p.milk_litres_r, p.milking_r) : null };
    versions.forEach((v, i) => {
      const f = p.future ? forecastRow(v.run, grain, p.period, 'milk_litres') : undefined;
      const cows = p.future ? forecastRow(v.run, grain, p.period, 'milking') : undefined;
      const n = cows ? perDay('milking', cows.forecast, grain, p.period) : null;
      const val = f ? perCow(perDay('milk_litres', f.forecast, grain, p.period), n) : null;
      const ranged = !!f && f.upper > f.lower && val !== null;
      r[`f${i}`] = val;
      // milk range divided by the expected cows (the herd-count range is not included)
      r[`b${i}`] = f && ranged ? [perCow(perDay('milk_litres', f.lower, grain, p.period), n) as number,
        perCow(perDay('milk_litres', f.upper, grain, p.period), n) as number] : null;
      r[`n${i}`] = f && !ranged ? val : null; // a forecast without a calibrated range
    });
    return r;
  }), [run, grain, horizon, history, lang, versions]);
  const start = rows.find((r) => r.future)?.label as string | undefined;
  const future = rows.filter((r) => r.future);
  const noRange = versions.map((_, i) => rows.some((r) => r[`n${i}`] !== null));
  const missing = versions.map((_, i) => future.length > 0 && future.every((r) => r[`f${i}`] === null));

  return (
    <ChartView title={t('Milk Yield per Cow')} actions={toggle} controls={controls}>
      {() => <>
        <p className="pfie-mgr-note">{t('Litres per milking cow, by day, for the month the milk model forecasts.')}</p>
        {run.source !== 'model' && <p className="pfie-mgr-demo" role="note">{t('Practice data: made-up numbers, not real Farm X numbers.')}</p>}
        {!asTable ? (
          <>
            <div style={{ height: 280 }}>
              <ResponsiveContainer>
                <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#eef2f0" vertical={false} />
                  <XAxis dataKey="label" tick={CHART_TICK} interval="preserveStartEnd" minTickGap={18} />
                  <YAxis tick={CHART_TICK} width={58} tickFormatter={oneDecimal} domain={['auto', 'auto']} />
                  <Tooltip content={<CompareTip grain={grain} versions={versions} />} />
                  {versions.map((v, i) => (
                    <Area key={`b${i}`} dataKey={`b${i}`} stroke={VERSION_COLORS[i % 4]} strokeOpacity={0.5} strokeDasharray="2 3"
                      fill={VERSION_COLORS[i % 4]} fillOpacity={0.1} isAnimationActive={false} connectNulls={false} />
                  ))}
                  <Line dataKey="recorded" stroke={MILK_COLOR} strokeWidth={3} dot={grain === 'day' ? false : { r: 3 }} connectNulls={false} isAnimationActive={false} />
                  {versions.map((v, i) => (
                    <Line key={`f${i}`} dataKey={`f${i}`} stroke={VERSION_COLORS[i % 4]} strokeWidth={2.5} strokeDasharray="7 5"
                      dot={{ r: 2.5 }} connectNulls={false} isAnimationActive={false} />
                  ))}
                  {versions.map((v, i) => (
                    <Scatter key={`n${i}`} dataKey={`n${i}`} fill="#fff" stroke={VERSION_COLORS[i % 4]} strokeWidth={2} isAnimationActive={false} />
                  ))}
                  {realised && <Scatter dataKey="actual" fill="#17231f" isAnimationActive={false} />}
                  {start && <ReferenceLine x={start} stroke="#17231f" strokeDasharray="3 3" label={{ value: t('Forecast starts'), position: 'top', fontSize: 12, fill: '#34483f' }} />}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <Legend items={[
              { label: t('Recorded'), color: MILK_COLOR },
              ...versions.map((v, i) => ({ label: `${v.label}${noRange[i] ? ` (${t('no calibrated range')})` : ''}${missing[i] ? ` (${t('no milk forecast')})` : ''}`, color: VERSION_COLORS[i % 4], kind: 'dash' as const })),
              { label: t('Likely range (5–95% of milk ÷ expected cows)'), kind: 'band' },
              ...(realised ? [{ label: t('What actually happened'), kind: 'dot' as const }] : []),
            ]} />
          </>
        ) : (
          <SimpleTable
            head={[t('Date'), ...versions.flatMap((v) => [v.label, t('Likely range')]), ...(realised ? [t('What actually happened')] : [])]}
            rows={future.map((r) => [
              periodText(r.period as string, grain, lang),
              ...versions.flatMap((_, i) => {
                const f = r[`f${i}`] as number | null;
                const b = r[`b${i}`] as [number, number] | null;
                return [f !== null ? perCowText(f) : '—', b ? `${perCowText(b[0])} – ${perCowText(b[1])}` : (f !== null ? t('not calibrated') : '—')];
              }),
              ...(realised ? [r.actual !== null ? perCowText(r.actual as number) : '—'] : []),
            ])}
          />
        )}
        <VersionNotes versions={versions} loading={loading} />
      </>}
    </ChartView>
  );
}

function VersionNotes({ versions, loading }: { versions: Version[]; loading: boolean }) {
  const t = useT();
  if (loading) return <p className="pfie-mgr-note">{t('Loading other model versions…')}</p>;
  if (versions.length < 2) return <p className="pfie-mgr-note">{t('Only one model version is published for this date.')}</p>;
  return (
    <ul className="pfie-mgr-note">
      {versions.map((v) => {
        const mm = v.run.milk_model;
        const reasons = [...new Set((v.run.withheld ?? []).filter((w) => w.series === 'milk_litres').map((w) => w.reason))];
        return <li key={v.label}>
          <b>{v.label}</b>
          {mm ? `: ${t('milk from')} ${mm.selected_model ?? '?'}${mm.is_neural_network === false ? ` (${t('not a neural network')})` : ''}; ${mm.intervals ?? ''}${mm.supported_to ? `; ${t('forecast up to')} ${mm.supported_to}` : ''}` : ''}
          {reasons.length > 0 && `; ${t('no milk for some periods')}: ${reasons.join(', ')}`}
        </li>;
      })}
      <li>{t('Litres per milking cow per day: each version’s milk divided by its expected milking cows. Herd counts come from the same model in every version shown.')}</li>
    </ul>
  );
}

function CompareTip({ active, payload, grain, versions }: { active?: boolean; payload?: { payload: Row }[]; grain: Grain; versions: Version[] }) {
  const t = useT();
  const { lang } = useLang();
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  const rows: [string, string][] = [];
  if (r.recorded !== null) rows.push([t('Recorded'), `${perCowText(r.recorded as number)} L/cow`]);
  versions.forEach((v, i) => {
    const f = r[`f${i}`] as number | null;
    if (f === null) return;
    const b = r[`b${i}`] as [number, number] | null;
    rows.push([v.label, `${perCowText(f)} L/cow${b ? ` (${perCowText(b[0])} – ${perCowText(b[1])})` : ` (${t('no calibrated range')})`}`]);
  });
  if (r.actual !== null) rows.push([t('What actually happened'), `${perCowText(r.actual as number)} L/cow`]);
  return <TipShell title={periodText(r.period as string, grain, lang)} rows={rows} />;
}
