/**
 * Component 1 — Predictive Farm Outlook Intelligence (PFOI).
 *
 * Herd-level forecasts of milk, herd counts, herd events and mastitis for
 * Farm X, each with its range and its explanation. Three workspaces share one
 * grain / horizon / period selection. The page reads one `PfoiRun`; until the
 * model writes `c1_output` that run is synthetic demo data and is labelled so.
 */

import { useState } from 'react';
import {
  GRAIN_LABEL, HORIZONS, MAX_HORIZON, SEVERITY_META,
  earliestActual, findings, firstTarget, periodLabel, type Grain,
} from '../../data/pfoi';
import { PfoiProvider, usePfoi, type HerdTab, type Workspace } from './state';
import { RunProvider, useRun } from './source';
import { ForecastInfo, RunStatus } from './RunStatus';
import { FindingsDrawer, PointDrawer } from './panels/Drawers';
import { FutureWorkspace } from './workspaces/Future';
import { MilkSupply } from './workspaces/MilkSupply';
import { Reproduction } from './workspaces/Reproduction';
import { HerdOutcomes } from './workspaces/HerdOutcomes';
import { HerdGenetics } from './workspaces/HerdGenetics';
import { Evidence } from './workspaces/Evidence';
import { ModelEvaluation } from './workspaces/ModelEvaluation';
import { Tabs } from './ui';
import { DateField } from './DateField';
import { Icon, type IconName } from './icons';
import { MetricDeck } from './deck';
import { OutcomeBar } from './panels/OutcomeBar';
import './pfie.css';

const WORKSPACES: { id: Workspace; label: string; icon: IconName }[] = [
  { id: 'outlook', label: 'Farm Outlook', icon: 'outlook' },
  { id: 'herd', label: 'Herd & Production', icon: 'herd' },
  { id: 'confidence', label: 'Forecast Confidence', icon: 'confidence' },
];

const HERD_TABS: { id: HerdTab; label: string }[] = [
  { id: 'milk', label: 'Milk supply' },
  { id: 'flow', label: 'Herd count & movement' },
  { id: 'events', label: 'Herd events' },
  { id: 'generations', label: 'Generations' },
];

const GRAINS: { id: Grain; label: string }[] = [
  { id: 'day', label: 'Day' },
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' },
];

export default function PredictiveIntelligencePage() {
  return (
    <RunProvider>
      <PfoiProvider>
        <Shell />
      </PfoiProvider>
    </RunProvider>
  );
}

function Shell() {
  const [evaluation, setEvaluation] = useState(false);
  const { grain, setGrain, horizon, setHorizon, historyFrom, setHistoryFrom, workspace, herdTab, go, drawer, openDrawer, acknowledged } = usePfoi();
  const run = useRun();
  const openFindings = findings(run).filter((f) => !acknowledged.has(f.id)).length;
  const detailOpen = drawer.kind !== 'none';

  return (
    <div className="pfie">
      <header className="pfie-head">
        <div className="pfie-bar">
          <div className="pfie-ident">
            <span className="pfie-ident-mark" aria-hidden><Icon name="spark" size={19} /></span>
            <div>
              <h1>Predictive Farm Outlook</h1>
              <p>Farm X · herd level · Component 1</p>
            </div>
          </div>

          <span className="spacer" />

          <button className="pfie-btn pfie-findings-btn" onClick={() => openDrawer({ kind: 'findings' })}>
            <Icon name="flag" size={14} />
            Findings
            {openFindings > 0 && <span className="count">{openFindings}</span>}
          </button>

          <RunStatus />
        </div>

        <nav className="pfie-nav" aria-label="Workspaces">
          <div className="pfie-nav-tabs">
            {WORKSPACES.map((w) => (
              <button key={w.id} aria-current={!evaluation && workspace === w.id ? 'page' : undefined} onClick={() => { setEvaluation(false); go(w.id); }}>
                <Icon name={w.icon} size={15} />
                {w.label}
              </button>
            ))}
            <button aria-current={evaluation ? 'page' : undefined} onClick={() => setEvaluation(true)}>
              <Icon name="confidence" size={15} />Model evaluation
            </button>
          </div>

          {!evaluation && <span className="pfie-row tight pfie-horizon">
            <span className="pfie-seg compact" role="group" aria-label="Forecast grain">
              {GRAINS.map((g) => (
                <button key={g.id} aria-pressed={grain === g.id} onClick={() => setGrain(g.id)}>{g.label}</button>
              ))}
            </span>
            <span className="pfie-seg compact" role="group" aria-label="Forecast horizon">
              {HORIZONS[grain].map((h) => (
                <button
                  key={h}
                  aria-pressed={horizon === h}
                  aria-label={`${h} ${h === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many} ahead`}
                  title={`${h} ${h === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many} ahead`}
                  onClick={() => setHorizon(h)}
                >
                  {h}{GRAIN_LABEL[grain].short}
                </button>
              ))}
            </span>
            <RangePickers
              grain={grain}
              horizon={horizon}
              setHorizon={setHorizon}
              historyFrom={historyFrom}
              setHistoryFrom={setHistoryFrom}
            />
          </span>}
        </nav>
      </header>

      <div className="pfie-body">
        <ForecastInfo />
        {detailOpen ? (
          <DetailPage />
        ) : (
          <>
            {run.source === 'demo' && (
              <div className="pfie-demo-banner" role="note">
                <b>Demo data.</b> Every number on this page is synthetic. It has the shape of the planned
                model outputs but is not Farm X data, not a forecast and not a backtest result.
              </div>
            )}

            {evaluation ? <ModelEvaluation /> : <>
            <OutcomeBar />
            <MetricDeck />
            <SignalBand />

            <div className="pfie-canvas">
              {workspace === 'outlook' && <FutureWorkspace />}
              {workspace === 'herd' && (
                <>
                  <Tabs tabs={HERD_TABS} value={herdTab} onChange={(t) => go('herd', t)} />
                  {herdTab === 'milk' && <MilkSupply />}
                  {herdTab === 'flow' && <Reproduction />}
                  {herdTab === 'events' && <HerdOutcomes />}
                  {herdTab === 'generations' && <HerdGenetics />}
                </>
              )}
              {workspace === 'confidence' && <Evidence />}
            </div>
            </>}
          </>
        )}

        {!detailOpen && (
          <p className="pfie-disclaimer">
            Component 1 forecasts the herd as a whole: milk, herd counts, herd events and expected mastitis
            episodes. It shows no individual animals. Animal records stay in DelPro; individual health detection
            belongs to Component 3. Measured, derived and assumed values are tagged where they appear.
          </p>
        )}
      </div>
    </div>
  );
}

function DetailPage() {
  const { drawer } = usePfoi();
  switch (drawer.kind) {
    case 'point': return <PointDrawer period={drawer.period} grain={drawer.grain} />;
    case 'findings': return <FindingsDrawer />;
    default: return null;
  }
}

/* ------------------------------------------------------------------ */
/* Priority signals: the findings that point into this workspace.      */

function SignalBand() {
  const { workspace, acknowledged, openDrawer, go, setSelectedPeriod, setBreakdownMonth, setGrain } = usePfoi();
  const run = useRun();
  const signals = findings(run)
    .filter((f) => !acknowledged.has(f.id))
    .filter((f) => workspace === 'outlook' || f.link.workspace === workspace)
    .slice(0, 3);
  if (signals.length === 0) return null;

  return (
    <section className="pfie-band-signals">
      <div className="pfie-band-signals-head">
        <h2>Priority signals</h2>
        <button className="pfie-btn ghost" onClick={() => openDrawer({ kind: 'findings' })}>
          View all findings <Icon name="arrowRight" size={13} />
        </button>
      </div>
      <ul className="pfie-signals">
        {signals.map((f) => {
          const sev = SEVERITY_META[f.severity];
          return (
            <li key={f.id} className={`pfie-signal sev-${f.severity}`}>
              <span className="kind" style={{ color: sev.color }}>
                <span aria-hidden>{sev.mark}</span> {f.kind}
              </span>
              <b>{f.title}</b>
              <p>{f.summary}</p>
              <button
                className="pfie-btn ghost"
                onClick={() => {
                  if (f.link.period) {
                    setGrain('month');
                    setSelectedPeriod(f.link.period);
                    setBreakdownMonth(f.link.period);
                  }
                  go(f.link.workspace, f.link.tab);
                }}
              >
                {f.link.label} <Icon name="arrowRight" size={13} />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}


/** Any published horizon, and recorded history from a chosen date (all history by default). */
function RangePickers({ grain, horizon, setHorizon, historyFrom, setHistoryFrom }: {
  grain: Grain; horizon: number; setHorizon: (h: number) => void;
  historyFrom: string | null; setHistoryFrom: (d: string | null) => void;
}) {
  const run = useRun();
  const unit = GRAIN_LABEL[grain];
  const earliest = earliestActual(run, grain);
  const first = firstTarget(run, grain);
  return (
    <span className="pfie-row tight pfie-pickers">
      <label className="pfie-pick" title="Any step the model publishes; the buttons are the backtested ones">
        Ahead
        <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
          {Array.from({ length: MAX_HORIZON[grain] }, (_, i) => i + 1).map((h) => (
            <option key={h} value={h}>{h} {h === 1 ? unit.one : unit.many}</option>
          ))}
        </select>
      </label>
      <span className="pfie-pick" title={`Show recorded history from this date (records start ${periodLabel(earliest, grain)})`}>
        From
        <DateField
          label="Show history from"
          value={historyFrom ?? earliest}
          min={earliest}
          max={first}
          onChange={(d) => setHistoryFrom(d > earliest ? d : null)}
        />
      </span>
      {historyFrom && (
        <button className="pfie-btn pfie-pick-reset" onClick={() => setHistoryFrom(null)} title="Show all recorded history">
          All history
        </button>
      )}
    </span>
  );
}
