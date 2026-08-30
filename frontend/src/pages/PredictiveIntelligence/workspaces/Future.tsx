/**
 * Future workspace (§7) — the Farm Future Brief.
 *
 * Deliberately not a KPI dashboard: one plain-language briefing, one dominant
 * forecast panel, then the findings. Everything else is a click away. The
 * headline numbers come from the shared horizon summary so the metric deck in
 * the header and this brief can never disagree.
 */

import { fmtInt, fmtLKR, longDate } from '../../../data/component2';
import { MasterTimeline } from '../panels/MasterTimeline';
import { FindingsList } from '../panels/Findings';
import { ForecastReplay, ReplayCompareStrip } from '../panels/ForecastReplay';
import { horizonSummary } from '../summary';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, Gauge, Note, Sparkline } from '../ui';
import { Icon } from '../icons';

/** How full the confidence arc reads for each level of the standard vocabulary. */
const CONFIDENCE_ARC = { High: 88, Moderate: 58, Limited: 28 } as const;

export function FutureWorkspace() {
  const { horizon, openDrawer, go, setSelectedMonth, setSelectedDate } = useC2();
  const s = horizonSummary(horizon);
  const direction = s.changePct >= 0 ? 'increase' : 'decline';

  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      {/* ---- the charts lead: this workspace is about the shape of the future ---- */}
      <MasterTimeline />

      {/* ---- plain-language briefing ---- */}
      <section className="pfie-brief">
        <div className="pfie-brief-inner">
          <div>
            <span className="eyebrow"><i aria-hidden />Farm future brief</span>
            <p className="lead">
              Across the selected {s.label.toLowerCase()} ({longDate(s.first.date)}–{longDate(s.last.date)}),
              milk is expected to average <b>{fmtInt(s.averageDailyMilk)} L/day</b> ({s.averagePerCow.toFixed(1)} L
              per milking cow/day). The outlook is a <b>{Math.abs(s.changePct).toFixed(1)}% {direction}</b> from the
              opening week to the closing week, with {s.dryOffs} expected dry-offs and {s.entries} expected
              lactation entries shaping the path.
            </p>
            <div className="meta">
              <div>Selected range<b>{s.label}</b></div>
              <div>Average daily milk<b>{fmtInt(s.averageDailyMilk)} L</b></div>
              <div>Per milking cow<b>{s.averagePerCow.toFixed(1)} L/day</b></div>
              <div>Expected dry-offs<b>{s.dryOffs}</b></div>
              <div>Lactation entries<b>{s.entries}</b></div>
            </div>
          </div>

          <div className="pfie-brief-gauge">
            <Gauge
              pct={CONFIDENCE_ARC[s.confidence]}
              caption={s.confidence}
              size={158}
              sub="Forecast confidence"
            />
          </div>
        </div>
      </section>

      <ReplayCompareStrip />

      {/* ---- the defining future movement ---- */}
      <Card
        className="pfie-movement"
        icon="trendDown"
        title="Selected forecast movement"
        sub={`Expected milk supply across ${longDate(s.first.date)}–${longDate(s.last.date)}`}
        actions={
          <>
            <ConfidenceBadge level={s.confidence} />
            <button
              className="pfie-btn primary"
              onClick={() => openDrawer({ kind: 'structure', date: s.lowPoint.date, domain: 'herd' })}
            >
              Explore forecast structure
            </button>
          </>
        }
      >
        <div className="headline">
          <span className="delta" style={{ color: s.changePct < 0 ? 'var(--concern)' : 'var(--brand)' }}>
            {s.changePct >= 0 ? '+' : '−'}{Math.abs(s.changePct).toFixed(1)}%
          </span>
          <div>
            <div style={{ fontSize: 13.5, color: 'var(--muted)' }}>
              from <b style={{ color: 'var(--ink)' }}>{fmtInt(s.earlyMilk)} L/day</b> in the opening week to about{' '}
              <b style={{ color: 'var(--predicted)' }}>{fmtInt(s.lateMilk)} L/day</b> in the closing week
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 4 }}>
              Lowest point around {longDate(s.lowPoint.date)}: {fmtInt(s.lowPoint.expected ?? 0)} L/day
              {s.lowPoint.lower !== null && s.lowPoint.upper !== null
                ? ` · likely range ${fmtInt(s.lowPoint.lower)}–${fmtInt(s.lowPoint.upper)} L/day`
                : ''}
            </div>
          </div>
          <span className="headline-spark">
            <Sparkline data={s.spark} tone={s.changePct < 0 ? 'concern' : 'brand'} width={190} height={54} />
          </span>
        </div>

        <div className="pfie-consequence">
          <div>
            <div className="k">Herd movement</div>
            <div className="v">{s.dryOffs} out · {s.entries} in</div>
            <div className="d">Net {s.netMovement >= 0 ? '+' : ''}{s.netMovement} expected milking-animal movement across the selected range</div>
          </div>
          <div>
            <div className="k">Average milk production</div>
            <div className="v">{fmtInt(s.averageDailyMilk)} L/day</div>
            <div className="d">Average {s.averagePerCow.toFixed(1)} L per milking cow per day across the range</div>
          </div>
          <div>
            <div className="k">Product consequence</div>
            <div className="v">
              {s.product?.shortfall['Tetra pack'] ? `−${fmtInt(s.product.shortfall['Tetra pack'])} L` : 'Within plan'}
            </div>
            <div className="d">
              {s.product?.shortfall['Tetra pack']
                ? `Tetra pack at the low point in ${s.product.label}; the raw-milk contract is filled first.`
                : 'All product lines stay within the planned allocation at the low point.'}
            </div>
          </div>
          <div>
            <div className="k">Financial consequence</div>
            <div className="v" style={{ color: s.marginGap < 0 ? 'var(--concern)' : 'var(--brand)' }}>
              {fmtLKR(s.marginGap)}
            </div>
            <div className="d">
              Expected {s.finance?.label ?? 'period-end'} margin against budget
              {s.finance ? ` (${fmtLKR(s.finance.marginForecast ?? s.finance.margin ?? 0)} vs ${fmtLKR(s.finance.budgetMargin)})` : ''}
            </div>
          </div>
          <div>
            <div className="k">Lowest expected point</div>
            <div className="v">{longDate(s.lowPoint.date)}</div>
            <div className="d">{fmtInt(s.lowPoint.expected ?? 0)} L/day · {s.lowPoint.confidence} confidence at this point</div>
          </div>
        </div>

        <div className="pfie-row tight" style={{ marginTop: 16 }}>
          <button className="pfie-btn" onClick={() => { setSelectedDate(s.lowPoint.date); go('capacity', 'milk'); }}>
            See which cows drive it <Icon name="arrowRight" size={13} />
          </button>
          <button className="pfie-btn" onClick={() => { setSelectedMonth(s.endMonth); go('commerce'); }}>
            Follow it into products and margin <Icon name="arrowRight" size={13} />
          </button>
        </div>
      </Card>

      {/* ---- replay + findings ---- */}
      <ForecastReplay />
      <Card icon="flag" title="Findings" sub="Grouped so one issue reads as one finding.">
        <FindingsList />
      </Card>
      <Note tone="info" title="How to read confidence.">
        Forecast confidence describes how much the system trusts the estimate. It is separate from an event
        probability such as a conception likelihood — the two are never combined.
      </Note>
    </div>
  );
}
