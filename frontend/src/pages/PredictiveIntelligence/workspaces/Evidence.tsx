/**
 * Component 1 (PFOI): Forecast Confidence.
 *
 * The rolling-origin backtest against the benchmarks (persistence, seasonal
 * naive, SARIMA) by grain and horizon, accuracy by record-quality band, the
 * forecast replay, and data coverage. The development and test blocks are
 * kept apart; the test block is run once, on the frozen model.
 */

import { useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  GRAIN_LABEL,
  MODEL_LABEL,
  SERIES_META,
  confidenceOf,
  fmt1,
  fmtInt,
  fmtPct,
  type BacktestRow,
  type BenchmarkModel,
  type SeriesId,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, MonthlyOnly, ConfidenceBadge, Note, Segmented, TipShell } from '../ui';
import { ForecastReplay } from '../panels/ForecastReplay';

const MODELS: BenchmarkModel[] = ['pfoi', 'persistence', 'seasonal_naive', 'sarima'];
const MODEL_COLORS: Record<BenchmarkModel, string> = { pfoi: '#9a4f27', persistence: '#93a29b', seasonal_naive: '#a8770a', sarima: '#5b7fa6' };

export function Evidence() {
  const { grain } = usePfoi();
  const run = useRun();
  const [block, setBlock] = useState<BacktestRow['block']>('development');
  const seriesOptions = [...new Set(run.backtest.filter((r) => r.grain === grain).map((r) => r.series))];
  const [seriesPick, setSeriesPick] = useState<SeriesId>('milk_litres');
  const series = seriesOptions.includes(seriesPick) ? seriesPick : seriesOptions[0];
  const rows = run.backtest.filter((r) => r.block === block && r.grain === grain && r.series === series);
  const horizons = [...new Set(rows.map((r) => r.horizon))].sort((a, b) => a - b);
  const unit = series === 'milk_litres' ? 'L/day' : SERIES_META[series]?.unit ?? '';

  const chart = horizons.map((h) => {
    const row: Record<string, number | string> = { h: `${h}${GRAIN_LABEL[grain].short}` };
    MODELS.forEach((m) => { const r = rows.find((x) => x.horizon === h && x.model === m); if (r) row[m] = r.mae; });
    return row;
  });

  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <Note tone="info" title={`Evidence for ${run.model_version}`}>
        These metrics belong to the displayed {run.source === 'demo' ? 'synthetic demo' : 'published'} run.
        Candidate configuration results for 2019–2023 are discussed separately in Model evaluation.
        A test-period label alone does not establish that a configuration was frozen before those outcomes were inspected.
      </Note>
      {run.source === 'demo' && (
        <Note tone="concern" title="These are demo numbers, not results.">
          The tables and charts below show how the backtest will be reported. Every value is synthetic and says
          nothing about how well PFOI forecasts. The real values come from the rolling-origin backtest run by the
          model owner.
        </Note>
      )}

      <Card
        title="Backtest against the benchmarks"
        sub={`${run.model_version} · rolling origin · ${GRAIN_LABEL[grain].one}ly grain · error in ${unit}`}
        actions={
          <>
            <Segmented
              label="Block"
              value={block}
              onChange={setBlock}
              options={[{ id: 'development', label: 'Development' }, { id: 'test', label: 'Test period' }]}
            />
            <select value={series} onChange={(e) => setSeriesPick(e.target.value as SeriesId)}>
              {seriesOptions.map((s) => <option key={s} value={s}>{SERIES_META[s].label}</option>)}
            </select>
          </>
        }
      >
        {rows.length === 0 ? (
          <p className="pfie-chart-note">No backtest rows for this grain and series.</p>
        ) : (
          <div className="pfie-grid side">
            <div className="pfie-tablewrap">
              <table className="pfie-table">
                <thead>
                  <tr>
                    <th>Horizon</th><th>Model</th>
                    <th className="num">MAE</th><th className="num">RMSE</th><th className="num">Bias</th><th className="num">Coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {horizons.flatMap((h) => {
                    const atH = rows.filter((r) => r.horizon === h);
                    const best = Math.min(...atH.map((r) => r.mae));
                    return MODELS.map((m, i) => {
                      const r = atH.find((x) => x.model === m);
                      if (!r) return null;
                      return (
                        <tr key={`${h}-${m}`}>
                          <td>{i === 0 ? `${h} ${h === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many}` : ''}</td>
                          <td>{MODEL_LABEL[m]}</td>
                          <td className={`num${r.mae === best ? ' best' : ''}`}>{fmt1(r.mae)}</td>
                          <td className="num">{fmt1(r.rmse)}</td>
                          <td className="num">{r.bias >= 0 ? '+' : '−'}{fmt1(Math.abs(r.bias))}</td>
                          <td className="num">{r.coverage !== null ? fmtPct(r.coverage, 0) : '—'}</td>
                        </tr>
                      );
                    });
                  })}
                </tbody>
              </table>
            </div>
            <div>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={chart} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#eef2f0" vertical={false} />
                  <XAxis dataKey="h" tick={{ fontSize: 11, fill: '#70827a' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={44} />
                  {MODELS.map((m) => (
                    <Line key={m} dataKey={m} stroke={MODEL_COLORS[m]} strokeWidth={m === 'pfoi' ? 2.4 : 1.5} dot={{ r: 2.5 }} isAnimationActive={false} />
                  ))}
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null;
                      return <TipShell title={`MAE · ${label} ahead`} rows={payload.map((p) => [MODEL_LABEL[p.dataKey as BenchmarkModel], `${fmt1(Number(p.value))} ${unit}`, MODEL_COLORS[p.dataKey as BenchmarkModel]])} />;
                    }}
                  />
                </LineChart>
              </ResponsiveContainer>
              <div className="pfie-legend">
                {MODELS.map((m) => <span key={m}><i style={{ background: MODEL_COLORS[m] }} />{MODEL_LABEL[m]}</span>)}
              </div>
              <p className="pfie-chart-note">
                Bold = lowest MAE at that horizon. Coverage is the share of actuals inside the 5–95% range (target
                90%); persistence and seasonal naive have no interval. {rows[0] && `${fmtInt(rows[0].n_origins)} origins.`}
              </p>
            </div>
          </div>
        )}
      </Card>

      <div className="pfie-grid c2">
        <Card title={<>Accuracy by record quality <MonthlyOnly /></>} sub="Monthly milk, PFOI: the range should widen when the records are thinner">
          <div className="pfie-tablewrap">
            <table className="pfie-table">
              <thead><tr><th>Quality band</th><th className="num">MAE</th><th className="num">Coverage</th><th className="num">Periods</th></tr></thead>
              <tbody>
                {run.qualityBands.map((q) => (
                  <tr key={q.band}>
                    <td><ConfidenceBadge level={confidenceOf(q.band)} /></td>
                    <td className="num">{fmtPct(q.mae_pct)}</td>
                    <td className="num">{fmtPct(q.coverage, 0)}</td>
                    <td className="num">{q.n_periods}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Data coverage" sub="What the records allow, by year">
          <div className="pfie-tablewrap">
            <table className="pfie-table">
              <thead>
                <tr><th>Year</th><th className="num">Reliable cow-days</th><th className="num">Milk days scored</th><th className="num">Weather complete</th><th className="num">Health records</th></tr>
              </thead>
              <tbody>
                {run.coverage.map((c) => (
                  <tr key={c.year}>
                    <td>{c.year}</td>
                    <td className="num">{fmtInt(c.reliable_cow_days)}</td>
                    <td className="num">{fmtPct(c.milk_days_scoreable_pct, 0)}</td>
                    <td className="num">{fmtPct(c.weather_complete_pct, 0)}</td>
                    <td className="num">{fmtInt(c.health_records)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="pfie-chart-note">
            Reliable cow-days decide how well the lactation curves can be checked. Before per-cow records exist,
            the curve shape comes from a published reference and is labelled as such.
          </p>
        </Card>
      </div>

      <ForecastReplay />
    </div>
  );
}
