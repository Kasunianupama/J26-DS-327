/**
 * Component 1 (PFOI): full-page detail views.
 *
 * `PointDrawer` explains one period: every series with its range, milk per
 * milking cow, the milk breakdown for that month and the determined /
 * rate-driven split of each herd flow. `FindingsDrawer` is the inbox.
 */

import {
  EVENT_SERIES,
  SERIES_META,
  STOCK_SERIES,
  actualRow,
  confidenceOf,
  firstTarget,
  flowSplit,
  fmt1,
  fmtInt,
  forecastRow,
  isForecast,
  milkBreakdown,
  periodLabel,
  periodStart,
  perDay,
  type Grain,
  type SeriesId,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, ConfidenceBadge, Drawer, KindTag, Note } from '../ui';
import { FindingsList } from './Findings';
import { Waterfall } from './Waterfall';

export function PointDrawer({ period, grain }: { period: string; grain: Grain }) {
  const { closeDrawer } = usePfoi();
  const run = useRun();
  const future = period >= firstTarget(run, grain);
  const milkF = forecastRow(run, grain, period, 'milk_litres');
  const milkA = actualRow(run, grain, period, 'milk_litres');
  const milkingF = forecastRow(run, grain, period, 'milking');
  const milkingA = actualRow(run, grain, period, 'milking');
  const milk = future ? (milkF ? perDay('milk_litres', milkF.forecast, grain, period) : null) : milkA?.value != null ? perDay('milk_litres', milkA.value, grain, period) : null;
  const milking = future ? milkingF?.forecast ?? null : milkingA?.value ?? null;
  const month = periodStart(period, 'month');
  const breakdown = milkBreakdown(run, month);

  const valueOf = (s: SeriesId) => {
    if (future) {
      const f = forecastRow(run, grain, period, s);
      return f ? { v: perDay(s, f.forecast, grain, period), lo: perDay(s, f.lower, grain, period), hi: perDay(s, f.upper, grain, period) } : null;
    }
    const a = actualRow(run, grain, period, s);
    return a?.value != null ? { v: perDay(s, a.value, grain, period), lo: null, hi: null } : null;
  };

  return (
    <Drawer
      title={periodLabel(period, grain)}
      eyebrow={future ? `Forecast · ${milkF ? `${milkF.horizon} ${grain}${milkF.horizon === 1 ? '' : 's'} ahead` : ''}` : 'Recorded'}
      sub={future
        ? 'Every value with its 5–95% range, and where the milk change comes from.'
        : 'What was recorded, and how the model explains the milk change into this month.'}
      actions={milkF ? <ConfidenceBadge level={confidenceOf(milkF.quality_flag)} /> : undefined}
      onClose={closeDrawer}
      wide
    >
      <div className="pfie-stack">
        <div className="pfie-consequence">
          <div>
            <div className="k">Milk</div>
            <div className="v">{milk !== null ? `${fmtInt(milk)} L/day` : '—'}</div>
            <div className="d">
              {future && milkF
                ? `Range ${fmtInt(perDay('milk_litres', milkF.lower, grain, period))}–${fmtInt(perDay('milk_litres', milkF.upper, grain, period))}`
                : milkA ? `${milkA.source === 'shipment' ? 'Shipment' : 'DelPro'} record${milkA.scoreable ? '' : ' · not scored (gap or flagged)'}` : 'No record'}
            </div>
          </div>
          <div>
            <div className="k">Milking cows</div>
            <div className="v">{milking !== null ? fmtInt(milking) : '—'}</div>
            <div className="d">{milking === null && future && !isForecast(run, grain, 'milking') ? 'Herd counts are forecast weekly and monthly' : 'Daily average'}</div>
          </div>
          <div>
            <div className="k">Milk per milking cow <KindTag kind="derived" /></div>
            <div className="v">{milk !== null && milking ? `${fmt1(milk / milking)} L/day` : '—'}</div>
            <div className="d">Milk ÷ milking cows; the model builds it from cells × lactation curve × k</div>
          </div>
        </div>

        <Card title="All series in this period" sub={future ? 'Forecast with 5–95% range' : 'Recorded values'}>
          <div className="pfie-tablewrap">
            <table className="pfie-table">
              <thead>
                <tr><th>Series</th><th className="num">{future ? 'Forecast' : 'Recorded'}</th>{future && <th className="num">Range</th>}<th>Unit</th></tr>
              </thead>
              <tbody>
                {(['milk_litres', ...STOCK_SERIES, ...EVENT_SERIES, 'mastitis_episodes'] as SeriesId[]).map((s) => {
                  const x = valueOf(s);
                  return (
                    <tr key={s}>
                      <td>{SERIES_META[s].label}</td>
                      <td className="num">{x ? fmt1(x.v) : '—'}</td>
                      {future && <td className="num">{x && x.lo !== null && x.hi !== null ? `${fmt1(x.lo)}–${fmt1(x.hi)}` : '—'}</td>}
                      <td>{SERIES_META[s].unit}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {future && !isForecast(run, grain, 'milking') && <p className="pfie-chart-note">Only milk is forecast at this grain in this run.</p>}
        </Card>

        {breakdown ? (
          <Card title={`Why milk changes into ${periodLabel(month, 'month')}`} sub="Each reason's share of the change from the month before; the reasons add up exactly to the change">
            <Waterfall breakdown={breakdown} />
          </Card>
        ) : (
          <Note tone="info" title="No milk breakdown for this month.">
            Breakdowns are published monthly, from the last 24 months to the end of the forecast.
          </Note>
        )}

        {future && isForecast(run, grain, 'calvings') && (
          <Card title="Herd events expected this period" sub="How much of each count is already known from records, and how much is an estimate from recent rates">
            <div className="pfie-flowlinks">
              {EVENT_SERIES.map((s) => {
                const split = flowSplit(run, grain, period, s);
                if (!split) return null;
                const total = split.determined + split.rate_driven;
                const detShare = total ? split.determined / total : 0;
                const summary = !total
                  ? 'None expected.'
                  : detShare >= 0.995
                    ? `All ${fmt1(total)} are already known from records, so this count is firm.`
                    : detShare <= 0.005
                      ? `All ${fmt1(total)} are estimated from recent rates, so this count is less certain.`
                      : `${fmt1(split.determined)} already known from records (${Math.round(detShare * 100)}%), ${fmt1(split.rate_driven)} estimated from recent rates.`;
                return (
                  <div className="pfie-flowlink" key={s}>
                    <span className="nm">
                      <b>{SERIES_META[s].label}</b>
                      <small>{summary}</small>
                    </span>
                    <span className="bar" aria-label={`${SERIES_META[s].label}: ${Math.round(detShare * 100)}% already known`}>
                      <i className="det" style={{ width: `${detShare * 100}%` }} />
                      <i className="rate" style={{ width: `${total ? (1 - detShare) * 100 : 0}%` }} />
                    </span>
                    <span className="v">{fmt1(total)}<small> expected</small></span>
                  </div>
                );
              })}
            </div>
            <div className="pfie-legend">
              <span><i style={{ background: 'var(--brand)' }} />Already known from records (e.g. calvings from confirmed pregnancies)</span>
              <span><i className="hatch" />Estimated from recent rates (the uncertain part)</span>
            </div>
          </Card>
        )}
      </div>
    </Drawer>
  );
}

export function FindingsDrawer() {
  const { closeDrawer } = usePfoi();
  return (
    <Drawer title="Findings" sub="Herd-level findings computed from this run." onClose={closeDrawer}>
      <FindingsList />
    </Drawer>
  );
}
