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
  actualRow,
  addPeriods,
  confidenceOf,
  flowTotals,
  isForecast,
  fmt1,
  fmtInt,
  forecastRow,
  headline,
  milkBreakdown,
  periodLabel,
  periodStart,
  type Confidence,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card, MonthlyOnly, Gauge, Note } from '../ui';
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
  const calvings = isForecast(run, grain, 'calvings') ? flowTotals(run, grain, horizon, 'calvings') : null;
  const reach = `${horizon} ${horizon === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many}`;
  const month = milk ? periodStart(milk.period, 'month') : null;
  const breakdown = month ? milkBreakdown(run, month) : null;
  const prevMonth = month ? addPeriods(month, 'month', -1) : null;
  /* Milking cows in the month vs the month before, to put the herd-size part in head. */
  const cowsAt = (m: string) => forecastRow(run, 'month', m, 'milking')?.forecast ?? actualRow(run, 'month', m, 'milking')?.value ?? null;
  const cowsNow = month ? cowsAt(month) : null;
  const cowsBefore = prevMonth ? cowsAt(prevMonth) : null;
  const cowDelta = cowsNow !== null && cowsBefore !== null ? Math.round(cowsNow - cowsBefore) : null;
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
          icon={breakdown.end >= breakdown.start ? 'trendUp' : 'trendDown'}
          title={<>Why milk changes into {periodLabel(month, 'month')} <MonthlyOnly /></>}
          sub={`Compared with ${periodLabel(prevMonth!, 'month')}, average litres per day`}
          actions={
            <button className="pfie-btn primary" onClick={() => { setBreakdownMonth(month); go('herd', 'milk'); }}>
              Open the full breakdown
            </button>
          }
        >
          <ContributionChart
            parts={breakdown.parts.filter((p) => breakdown.isPast || p.factor !== 'residual')}
            summary={{ fromLabel: periodLabel(prevMonth!, 'month'), toLabel: periodLabel(month, 'month'), start: breakdown.start, end: breakdown.end, isPast: breakdown.isPast }}
            facts={cowDelta ? { herd_size: `About ${Math.abs(cowDelta)} ${cowDelta > 0 ? 'more' : 'fewer'} cows in milk than in ${periodLabel(prevMonth!, 'month')}` } : undefined}
          />
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
