/**
 * Future workspace (§7) — the Farm Future Brief.
 *
 * Deliberately not a KPI dashboard: one plain-language briefing, one dominant
 * forecast panel, then the findings. Everything else is a click away.
 */

import {
  DAILY,
  DATA_THROUGH,
  GENERATED_AT,
  HORIZONS,
  fmtInt,
  fmtLKR,
  financeMonth,
  longDate,
  productMonth,
  isoDate,
} from '../../../data/component2';
import { MasterTimeline } from '../panels/MasterTimeline';
import { FindingsList } from '../panels/Findings';
import { ForecastReplay, ReplayCompareStrip } from '../panels/ForecastReplay';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, Note } from '../ui';

export function FutureWorkspace() {
  const { horizon, openDrawer, go, setSelectedMonth, setSelectedDate } = useC2();
  const horizonOption = HORIZONS.find((option) => option.id === horizon) ?? HORIZONS[2];
  const points = DAILY.filter((point) => point.offset > 0 && point.offset <= horizonOption.days);
  const average = (items: typeof points, measure: (point: typeof points[number]) => number) =>
    items.reduce((sum, point) => sum + measure(point), 0) / Math.max(1, items.length);
  const early = points.slice(0, Math.min(7, points.length));
  const late = points.slice(-Math.min(7, points.length));
  const averageDailyMilk = average(points, (point) => point.expected ?? 0);
  const averagePerCow = average(points, (point) => (point.expected ?? 0) / Math.max(1, point.milkers));
  const earlyMilk = average(early, (point) => point.expected ?? 0);
  const lateMilk = average(late, (point) => point.expected ?? 0);
  const changePct = ((lateMilk - earlyMilk) / Math.max(1, earlyMilk)) * 100;
  const lowPoint = points.reduce((lowest, point) => (point.expected ?? Infinity) < (lowest.expected ?? Infinity) ? point : lowest, points[0]);
  const dryOffs = points.reduce((sum, point) => sum + point.dryOffs, 0);
  const entries = points.reduce((sum, point) => sum + point.calvings, 0);
  const confidence = points.some((point) => point.confidence === 'Limited') ? 'Limited'
    : points.some((point) => point.confidence === 'Moderate') ? 'Moderate' : 'High';
  const endMonth = points[points.length - 1]?.date.slice(0, 7) ?? '2026-09';
  const finance = financeMonth(endMonth);
  const product = productMonth(lowPoint?.date.slice(0, 7) ?? endMonth);
  const marginGap = finance ? (finance.marginForecast ?? finance.margin ?? 0) - finance.budgetMargin : 0;
  const direction = changePct >= 0 ? 'increase' : 'decline';

  return (
    <div className="pfie-stack" style={{ gap: 22 }}>
      {/* ---- plain-language briefing ---- */}
      <section className="pfie-brief">
        <div className="eyebrow">Farm future brief</div>
        <p className="lead">
          Across the selected {horizonOption.label.toLowerCase()} ({longDate(points[0].date)}–{longDate(points[points.length - 1].date)}),
          milk is expected to average {fmtInt(averageDailyMilk)} L/day ({averagePerCow.toFixed(1)} L per milking cow/day).
          The outlook is a {Math.abs(changePct).toFixed(1)}% {direction} from the opening week to the closing week,
          with {dryOffs} expected dry-offs and {entries} expected lactation entries shaping the path.
        </p>
        <div className="meta">
          <div>Selected range<b>{horizonOption.label}</b></div>
          <div>Forecast confidence<b>{confidence}</b></div>
          <div>Average daily milk<b>{fmtInt(averageDailyMilk)} L</b></div>
          <div>Average per milking cow<b>{averagePerCow.toFixed(1)} L/day</b></div>
          <div>Updated<b>{GENERATED_AT}</b></div>
          <div>Data through<b>{longDate(isoDate(DATA_THROUGH))}</b></div>
        </div>
      </section>

      <ReplayCompareStrip />

      {/* ---- the defining future movement ---- */}
      <Card
        className="pfie-movement"
        title="Selected forecast movement"
        sub={`Expected milk supply across ${longDate(points[0].date)}–${longDate(points[points.length - 1].date)}`}
        actions={
          <>
            <ConfidenceBadge level={confidence} />
            <button className="pfie-btn primary" onClick={() => openDrawer({ kind: 'structure', date: lowPoint.date, domain: 'herd' })}>
              Explore forecast structure
            </button>
          </>
        }
      >
        <div className="headline">
          <span className="delta" style={{ color: changePct < 0 ? 'var(--concern)' : 'var(--brand)' }}>{changePct >= 0 ? '+' : '−'}{Math.abs(changePct).toFixed(1)}%</span>
          <div>
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>
              from <b style={{ color: 'var(--ink)' }}>{fmtInt(earlyMilk)} L/day</b> in the opening week to about{' '}
              <b style={{ color: 'var(--predicted)' }}>{fmtInt(lateMilk)} L/day</b> in the closing week
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 3 }}>
              Lowest point around {longDate(lowPoint.date)}: {fmtInt(lowPoint.expected ?? 0)} L/day
              {lowPoint.lower !== null && lowPoint.upper !== null ? ` · likely range ${fmtInt(lowPoint.lower)}–${fmtInt(lowPoint.upper)} L/day` : ''}
            </div>
          </div>
        </div>

        <div className="pfie-consequence">
          <div>
            <div className="k">Herd movement</div>
            <div className="v">{dryOffs} out · {entries} in</div>
            <div className="d">Net {entries - dryOffs >= 0 ? '+' : ''}{entries - dryOffs} expected milking-animal movement across the selected range</div>
          </div>
          <div>
            <div className="k">Average milk production</div>
            <div className="v">{fmtInt(averageDailyMilk)} L/day</div>
            <div className="d">Average {averagePerCow.toFixed(1)} L per milking cow per day across the range</div>
          </div>
          <div>
            <div className="k">Product consequence</div>
            <div className="v">
              {product?.shortfall['Tetra pack'] ? `−${fmtInt(product.shortfall['Tetra pack'])} L` : 'Within plan'}
            </div>
            <div className="d">
              {product?.shortfall['Tetra pack']
                ? `Tetra pack at the low point in ${product.label}; the raw-milk contract is filled first.`
                : 'All product lines stay within the planned allocation at the low point.'}
            </div>
          </div>
          <div>
            <div className="k">Financial consequence</div>
            <div className="v" style={{ color: marginGap < 0 ? 'var(--concern)' : 'var(--brand)' }}>
              {fmtLKR(marginGap)}
            </div>
            <div className="d">
              Expected {finance?.label ?? 'period-end'} margin against budget{finance ? ` (${fmtLKR(finance.marginForecast ?? finance.margin ?? 0)} vs ${fmtLKR(finance.budgetMargin)})` : ''}
            </div>
          </div>
          <div>
            <div className="k">Lowest expected point</div>
            <div className="v">{longDate(lowPoint.date)}</div>
            <div className="d">{fmtInt(lowPoint.expected ?? 0)} L/day · {lowPoint.confidence} confidence at this point</div>
          </div>
        </div>

        <div className="pfie-row tight" style={{ marginTop: 16 }}>
          <button className="pfie-btn" onClick={() => { setSelectedDate(lowPoint.date); go('capacity', 'milk'); }}>
            See which cows drive it →
          </button>
          <button className="pfie-btn" onClick={() => { setSelectedMonth(endMonth); go('commerce'); }}>
            Follow it into products and margin →
          </button>
        </div>
      </Card>

      {/* ---- timeline + findings ---- */}
      <div className="pfie-stack">
        <MasterTimeline />
        <ForecastReplay />
        <Card title="Findings" sub="Grouped so one issue reads as one finding.">
          <FindingsList />
        </Card>
        <Note tone="info" title="How to read confidence.">
          Forecast confidence describes how much the system trusts the estimate. It is separate from an event
          probability such as a conception likelihood — the two are never combined.
        </Note>
      </div>
    </div>
  );
}
