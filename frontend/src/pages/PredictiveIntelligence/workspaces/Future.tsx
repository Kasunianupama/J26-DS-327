/**
 * Component 1 (PFOI): Farm Outlook.
 *
 * The timeline leads, then one plain-language brief for the selected grain
 * and horizon, the biggest drivers of the milk change, and the findings. The
 * brief reads the same headline helper as the metric deck, so they never
 * disagree.
 */

import {
  GRAIN_LABEL,
  confidenceOf,
  flowTotals,
  fmt1,
  fmtInt,
  headline,
  milkBreakdown,
  periodLabel,
  periodStart,
  type Confidence,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, Gauge, Note } from '../ui';
import { Icon } from '../icons';
import { MasterTimeline } from '../panels/MasterTimeline';
import { ContributionChart } from '../panels/ContributionChart';
import { FindingsList } from '../panels/Findings';

const CONFIDENCE_ARC: Record<Confidence, number> = { High: 86, Moderate: 58, Limited: 30 };

export function FutureWorkspace() {
  const { grain, horizon, go, openDrawer, setBreakdownMonth } = usePfoi();
  const run = useRun();
  const milk = headline(run, grain, horizon, 'milk_litres');
  const milking = headline(run, grain, horizon, 'milking');
  const mastitis = headline(run, grain, horizon, 'mastitis_episodes');
  const calvings = grain === 'day' ? null : flowTotals(run, grain, horizon, 'calvings');
  const reach = `${horizon} ${horizon === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many}`;
  const month = milk ? periodStart(milk.period, 'month') : null;
  const breakdown = month ? milkBreakdown(run, month) : null;
  const conf = confidenceOf(milk?.quality);

  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <MasterTimeline />

      {milk && (
        <section className="pfie-brief">
          <div className="pfie-brief-inner">
            <div>
              <span className="eyebrow"><i aria-hidden />Farm outlook · {reach} ahead</span>
              <p className="lead">
                In {periodLabel(milk.period, grain)}, milk is expected at about <b>{fmtInt(milk.value)} L/day</b>{' '}
                (likely {fmtInt(milk.lower)}–{fmtInt(milk.upper)})
                {milk.changePct !== null && milk.baselinePeriod && (
                  <>, <b>{Math.abs(milk.changePct).toFixed(1)}% {milk.changePct < 0 ? 'lower' : 'higher'}</b> than {periodLabel(milk.baselinePeriod, grain)}</>
                )}
                .
                {milking && <> About <b>{fmtInt(milking.value)} cows</b> are expected in milk.</>}
                {calvings && calvings.total > 0 && (
                  <> {fmtInt(calvings.total)} calvings are expected along the way, {Math.round((calvings.determined / calvings.total) * 100)}% of them already fixed by recorded conceptions.</>
                )}
              </p>
              <div className="meta">
                <div>Target period<b>{periodLabel(milk.period, grain)}</b></div>
                <div>Milk<b>{fmtInt(milk.value)} L/day</b></div>
                <div>Milking cows<b>{milking ? fmtInt(milking.value) : 'weekly / monthly'}</b></div>
                <div>Calvings to horizon<b>{calvings ? fmtInt(calvings.total) : 'weekly / monthly'}</b></div>
                <div>Mastitis expected<b>{mastitis ? fmt1(mastitis.pathTotal) : 'weekly / monthly'}</b></div>
              </div>
            </div>
            <div className="pfie-brief-gauge">
              <Gauge pct={CONFIDENCE_ARC[conf]} caption={conf} size={158} sub="Forecast quality" />
            </div>
          </div>
        </section>
      )}

      {breakdown && month && (
        <Card
          icon="trendDown"
          title={`What moves milk into ${periodLabel(month, 'month')}`}
          sub={breakdown.isPast ? 'Recorded month, explained by the model' : 'Change from the previous month, split exactly across the model factors'}
          actions={
            <button className="pfie-btn primary" onClick={() => { setBreakdownMonth(month); go('herd', 'milk'); }}>
              Open the full breakdown
            </button>
          }
        >
          <ContributionChart parts={breakdown.parts.filter((p) => breakdown.isPast || p.factor !== 'residual')} />
          <div className="pfie-row tight">
            <button className="pfie-btn" onClick={() => openDrawer({ kind: 'point', period: milk!.period, grain })}>
              Explain {periodLabel(milk!.period, grain)} <Icon name="arrowRight" size={13} />
            </button>
            <button className="pfie-btn" onClick={() => go('confidence')}>
              How accurate has this been? <Icon name="arrowRight" size={13} />
            </button>
          </div>
        </Card>
      )}

      <Card icon="flag" title="Findings" sub="Herd-level findings computed from this run.">
        <FindingsList />
      </Card>

      <Note tone="info" title="How to read this page.">
        Solid lines are records; dashed lines and shaded bands are forecasts with their 5–95% range. Factors are
        tagged <i>measured</i>, <i>derived</i> (computed by the model) or <i>assumed</i> (THI in forecasts comes
        from the climatology of the training years, not from a weather forecast).
      </Note>
    </div>
  );
}
