/**
 * Simple view, "How far to trust this" tab: how close the forecast came, the
 * forecast against simple rules of thumb, accuracy by record quality, the
 * record checks, what the records cover, and a look back at an earlier
 * forecast. Same rows as the detailed Forecast Confidence workspace.
 */

import { useMemo, useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  confidenceOf, fmtInt, hasRealised, headline, isForecast, outcomeScore, replayOrigins, replayPath,
  type BacktestRow, type BenchmarkModel, type SeriesId,
} from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { TipShell } from '../ui';
import { Rich, aheadText, dateLabel, perGrain, periodText, useLang, useT } from './i18n';
import { Reasons } from './Reasons';
import {
  Box, CHART_TICK, DemoLine, Explain, FORECAST_COLOR, Legend, MILK_COLOR, PLAIN_CONFIDENCE, PLAIN_SERIES, SimpleTable, litres, pct,
} from './common';

export function TrustTab() {
  return (
    <>
      <HowClose />
      <VersusRules />
      <ByRecordQuality />
      <RecordChecks />
      <Coverage />
      <LookBack />
    </>
  );
}

const SCORED: SeriesId[] = ['milk_litres', 'milking', 'total_herd', 'calvings', 'dry_offs'];

function HowClose() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();

  if (hasRealised(run)) {
    const rows = SCORED.filter((s) => isForecast(run, grain, s))
      .map((s) => ({ s, x: outcomeScore(run, grain, horizon, s) }))
      .filter((r) => r.x && r.x.scored && r.x.mae !== null);
    return (
      <Box title={`${t('How close was this forecast?')}`} sub={t('Forecast made on {d}, checked against what was recorded later.', { d: dateLabel(run.origin_date, lang) })}>
        <SimpleTable
          head={['', t('Off by, on average'), t('Mostly too'), t('Inside the likely range')]}
          textCols={[2]}
          rows={rows.map(({ s, x }) => {
            const dir = Math.abs(x!.bias!) < 0.05 * (x!.mae || 1) ? t('about right') : x!.bias! > 0 ? t('low') : t('high');
            return [
              <b>{t(PLAIN_SERIES[s])}</b>,
              `${fmtInt(x!.mae!)}${x!.maeShare !== null ? ` (${Math.max(1, Math.round(x!.maeShare * 100))}%)` : ''}`,
              dir,
              t('{a} of {b}', { a: x!.inside, b: x!.scored }),
            ];
          })}
        />
        <p className="pfie-mgr-note">{aheadText(t, grain, horizon)} · {t('The model never saw these later records.')}</p>
        <DemoLine run={run} />
      </Box>
    );
  }

  const row = run.backtest.find((r) => r.block === 'development' && r.model === 'pfoi' && r.grain === grain && r.horizon === horizon && r.series === 'milk_litres');
  const level = headline(run, grain, horizon, 'milk_litres')?.value;
  if (!row || !level) return null;
  return (
    <Box title={`${t('How close have past forecasts been?')}`}>
      <div className="pfie-mgr-facts">
        <div className="pfie-mgr-fact"><span className="lbl">{t('Milk off by, on average')}</span><b>{litres(row.mae)} L ({Math.max(1, Math.round((row.mae / level) * 100))}%)</b></div>
        {row.coverage !== null && <div className="pfie-mgr-fact"><span className="lbl">{t('Inside the likely range')}</span><b>{pct(row.coverage)}</b></div>}
      </div>
      <DemoLine run={run} />
    </Box>
  );
}

const METHOD: Record<BenchmarkModel, string> = {
  pfoi: 'This forecast',
  persistence: 'Rule: same as last time',
  seasonal_naive: 'Rule: same as a year ago',
  sarima: 'Standard statistics method',
};
const METHODS: BenchmarkModel[] = ['pfoi', 'persistence', 'seasonal_naive', 'sarima'];

function VersusRules() {
  const run = useRun();
  const t = useT();
  const { grain, horizon } = usePfoi();
  const [block, setBlock] = useState<BacktestRow['block']>('development');
  const blocks = [...new Set(run.backtest.map((r) => r.block))];
  const series = [...new Set(run.backtest.filter((r) => r.grain === grain).map((r) => r.series))];
  const [pickS, setPickS] = useState<SeriesId>('milk_litres');
  const s = series.includes(pickS) ? pickS : series[0];
  const horizons = [...new Set(run.backtest.filter((r) => r.grain === grain && r.series === s).map((r) => r.horizon))].sort((a, b) => a - b);
  const h = horizons.includes(horizon) ? horizon : horizons.filter((x) => x <= horizon).pop() ?? horizons[0];
  const rows = run.backtest.filter((r) => r.block === block && r.grain === grain && r.series === s && r.horizon === h);
  if (!series.length || !rows.length) return null;
  const best = Math.min(...rows.map((r) => r.mae));
  const ours = rows.find((r) => r.model === 'pfoi');
  const simple = rows.find((r) => r.model === 'persistence');

  return (
    <Box
      title={`${t('Better than a simple rule of thumb?')}`}
      sub={`${aheadText(t, grain, h)} · ${t('lower error is better')}`}
      actions={
        <>
          <label className="pfie-mgr-select">
            <select value={s} onChange={(e) => setPickS(e.target.value as SeriesId)} aria-label={t('Number')}>
              {series.map((x) => <option key={x} value={x}>{t(PLAIN_SERIES[x] ?? x)}</option>)}
            </select>
          </label>
          {blocks.length > 1 && (
            <label className="pfie-mgr-select">
              <select value={block} onChange={(e) => setBlock(e.target.value as BacktestRow['block'])} aria-label={t('Years')}>
                <option value="development">{t('Years used to build the model')}</option>
                <option value="test">{t('Later test years')}</option>
              </select>
            </label>
          )}
        </>
      }
    >
      {ours && simple && (
        <p className="pfie-mgr-lead">
          {ours.mae < simple.mae
            ? <> <Rich text={t('Error is **{n}% smaller** than "same as last time".', { n: Math.round((1 - ours.mae / simple.mae) * 100) })} /></>
            : <> <Rich text={t('**Not better** than "same as last time" here.')} /></>}
        </p>
      )}
      <SimpleTable
        head={[t('Method'), `${t('Average error')} (${s === 'milk_litres' ? t('L a day') : perGrain(t, grain)})`, t('Inside the likely range')]}
        rows={METHODS.map((m) => rows.find((r) => r.model === m)).filter((r): r is BacktestRow => !!r).map((r) => [
          r.model === 'pfoi' ? <b>{t(METHOD[r.model])}</b> : t(METHOD[r.model as BenchmarkModel]),
          <span className={r.mae === best ? 'best' : ''}>{s === 'milk_litres' ? fmtInt(r.mae) : r.mae.toFixed(1)}{r.mae === best ? `${t('best')}` : ''}</span>,
          r.coverage !== null ? `${pct(r.coverage)} (${t('aim')} 90%)` : '—',
        ])}
      />
      <DemoLine run={run} />
    </Box>
  );
}

function ByRecordQuality() {
  const run = useRun();
  const t = useT();
  if (!run.qualityBands.length) return null;
  return (
    <Box title={`${t('Accuracy depends on the records')}`} sub={`${t('By month')}`}>
      <SimpleTable
        head={[t('Records were'), t('Off by, on average'), t('Inside the likely range'), t('Months checked')]}
        rows={run.qualityBands.map((q) => {
          const c = PLAIN_CONFIDENCE[confidenceOf(q.band)];
          return [<>{c.dots} {t(q.band === 'high' ? 'Complete' : q.band === 'moderate' ? 'Some gaps' : 'Poor')}</>, `${(q.mae_pct * 100).toFixed(0)}%`, pct(q.coverage), fmtInt(q.n_periods)];
        })}
      />
    </Box>
  );
}

const CHECK: Record<string, string> = {
  freshness: 'Up to date',
  completeness: 'Complete',
  plausibility: 'Believable',
  source_agreement: 'Shipped and recorded milk agree',
};

function RecordChecks() {
  const run = useRun();
  const t = useT();
  const rs = run.record_status;
  if (!rs) return null;
  return (
    <Box
      title={`${t('Are the milk records good enough?')}`}
      sub={rs.status === 'current' ? `${t('Yes')}` : rs.status === 'stale' ? `${t('Partly: the milk range is wider')}` : `${t('No: no milk number is given')}`}
    >
      <ul className="pfie-mgr-checks">
        {rs.checks.map((c) => (
          <li key={c.check} className={c.ok === null ? 'na' : c.ok ? 'ok' : 'fail'}>
            <span className="mark" aria-hidden>{c.ok === null ? '–' : c.ok ? '✓' : '✗'}</span>
            <b>{t(CHECK[c.check] ?? c.check)}</b>
            <span>{c.ok === null ? t('not checked') : c.ok ? t('passed') : t('failed')}</span>
          </li>
        ))}
      </ul>
      <p className="pfie-mgr-note">{t('{a} of the last {b} days had trusted milk records.', { a: rs.fresh_days, b: rs.lookback_days })}</p>
    </Box>
  );
}

function Coverage() {
  const run = useRun();
  const t = useT();
  if (!run.coverage.length) return null;
  return (
    <Box title={`${t('What the records cover each year')}`}>
      <SimpleTable
        head={[t('Year'), t('Cow-days with good milk records'), t('Milk days that could be checked'), t('Days with weather'), t('Health records')]}
        rows={run.coverage.map((c) => [c.year, fmtInt(c.reliable_cow_days), pct(c.milk_days_scoreable_pct), pct(c.weather_complete_pct), fmtInt(c.health_records)])}
      />
      <Explain>{t('A "cow-day" is one cow on one day. More good records make a more reliable forecast.')}</Explain>
    </Box>
  );
}

function LookBack() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const origins = replayOrigins(run);
  const [origin, setOrigin] = useState(() => [...origins].reverse()
    .find((o) => replayPath(run, o).filter((p) => p.actual !== null && p.scoreable).length >= 6)
    ?? origins[Math.max(0, origins.length - 7)] ?? '');
  const path = useMemo(() => replayPath(run, origin).map((p) => ({ ...p, label: periodText(p.period, 'month', lang, true) })), [run, origin, lang]);
  const prev = origins[origins.indexOf(origin) - 1];
  const targets = path.filter((p) => prev && p.horizon <= 11).map((p) => p.period);
  const [target, setTarget] = useState<string | null>(null);
  const shown = target && targets.includes(target) ? target : targets[0] ?? null;
  const scored = path.filter((p) => p.actual !== null && p.scoreable);
  const inside = scored.filter((p) => p.actual! >= p.band[0] && p.actual! <= p.band[1]).length;
  if (!origins.length) return null;

  return (
    <Box
      title={`${t('Look back: an earlier forecast')}`}
      sub={`${t('By month')}`}
      actions={
        <label className="pfie-mgr-select">{t('Made in')}
          <select value={origin} onChange={(e) => { setOrigin(e.target.value); setTarget(null); }}>
            {origins.map((o) => <option key={o} value={o}>{periodText(o, 'month', lang)}</option>)}
          </select>
        </label>
      }
    >
      <p className="pfie-mgr-lead">
        {scored.length > 0
          ? <Rich text={t('The real milk was inside the likely range in **{a} of {b}** months.', { a: inside, b: scored.length })} />
          : t('What happened is not recorded yet for these months.')}
      </p>
      <div style={{ height: 240 }}>
        <ResponsiveContainer>
          <ComposedChart data={path} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#eef2f0" vertical={false} />
            <XAxis dataKey="label" tick={CHART_TICK} />
            <YAxis tick={CHART_TICK} width={58} tickFormatter={(v: number) => fmtInt(v)} domain={['auto', 'auto']} />
            <Area dataKey="band" stroke="none" fill={FORECAST_COLOR} fillOpacity={0.14} isAnimationActive={false} />
            <Line dataKey="forecast" stroke={FORECAST_COLOR} strokeDasharray="7 5" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            <Line dataKey="actual" stroke={MILK_COLOR} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
            <Tooltip content={({ active, payload }) => {
              const p = payload?.[0]?.payload as (typeof path)[number] | undefined;
              if (!active || !p) return null;
              return <TipShell title={periodText(p.period, 'month', lang)} rows={[
                [t('Forecast then'), `${litres(p.forecast)} L`, FORECAST_COLOR],
                [t('Likely range'), `${litres(p.band[0])} – ${litres(p.band[1])}`],
                [t('What happened'), p.actual !== null ? `${litres(p.actual)} L` : '—', MILK_COLOR],
              ]} />;
            }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[{ label: t('Forecast then'), color: FORECAST_COLOR, kind: 'dash' }, { label: t('Likely range'), kind: 'band' }, { label: t('What happened'), color: MILK_COLOR }]} />

      {prev && shown && (() => {
        const rev = run.revisions.filter((r) => r.origin_date === origin && r.target_period === shown);
        const parts = rev.map((r) => ({ factor: r.factor, value: r.contribution }));
        const now = path.find((p) => p.period === shown)?.forecast ?? 0;
        const delta = parts.reduce((s, p) => s + p.value, 0);
        return (
          <>
            <div className="pfie-mgr-card-head">
              <h4 className="pfie-mgr-h4">{t('Why did this forecast change from the month before?')}</h4>
              <label className="pfie-mgr-select pfie-noprint">
                <select value={shown} onChange={(e) => setTarget(e.target.value)} aria-label={t('Month')}>
                  {targets.map((x) => <option key={x} value={x}>{periodText(x, 'month', lang)}</option>)}
                </select>
              </label>
            </div>
            <Reasons parts={parts} start={now - delta} end={now} isPast={false}
              fromLabel={t('the {m} forecast', { m: periodText(prev, 'month', lang) })} toLabel={t('the {m} forecast', { m: periodText(origin, 'month', lang) })} />
          </>
        );
      })()}
      <DemoLine run={run} />
    </Box>
  );
}
