/**
 * Component 1 — Predictive Farm Outlook Intelligence (PFOI).
 *
 * Herd-level forecasts of milk, herd counts, herd events and mastitis for
 * Farm X, each with its range and its explanation. Three workspaces share one
 * weekly or monthly grain / horizon / period selection. The page reads one `PfoiRun`; until the
 * model writes `c1_output` that run is synthetic demo data and is labelled so.
 */

import { useEffect, useState } from 'react';
import {
  GRAIN_LABEL, SEVERITY_META,
  earliestActual, findings, firstTarget, horizonOptions, periodLabel, type Grain,
} from '../../data/pfoi';
import { PfoiProvider, usePfoi, type HerdTab, type Workspace } from './state';
import { RunProvider, useRun } from './source';
import { RunStatus } from './RunStatus';
import { FindingsDrawer, PointDrawer } from './panels/Drawers';
import { FutureWorkspace, OutlookBrief } from './workspaces/Future';
import { MilkSupply } from './workspaces/MilkSupply';
import { Reproduction } from './workspaces/Reproduction';
import { HerdOutcomes } from './workspaces/HerdOutcomes';
import { HerdGenetics } from './workspaces/HerdGenetics';
import { Tabs } from './ui';
import { DateField } from './DateField';
import { Icon, type IconName } from './icons';
import { MetricDeck } from './deck';
import { OutcomeBar } from './panels/OutcomeBar';
import { ManagerView } from './ManagerView';
import { useUser } from '../../context/UserContext';
import './pfie.css';

const WORKSPACES: { id: Workspace; label: string; icon: IconName }[] = [
  { id: 'outlook', label: 'Farm Outlook', icon: 'outlook' },
  { id: 'herd', label: 'Herd & Production', icon: 'herd' },
];

const HERD_TABS: { id: HerdTab; label: string }[] = [
  { id: 'flow', label: 'Herd count & movement' },
  { id: 'milk', label: 'Milk supply' },
  { id: 'events', label: 'Herd events' },
  { id: 'generations', label: 'Generations' },
];

/* Farm staff open the simple view; vets and board members open the full page. */
type View = 'simple' | 'detailed';
const defaultView = (role: string): View => (role === 'farm_manager' || role === 'farm_worker' ? 'simple' : 'detailed');

const GRAINS: { id: Grain; label: string }[] = [
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
  const { role } = useUser();
  const [view, setView] = useState<View>(() => defaultView(role));
  useEffect(() => { setView(defaultView(role)); }, [role]);
  const simple = view === 'simple';
  const { grain, setGrain, horizon, setHorizon, historyFrom, setHistoryFrom, workspace, herdTab, go, drawer, openDrawer, acknowledged } = usePfoi();
  const run = useRun();
  const openFindings = findings(run).filter((f) => !acknowledged.has(f.id)).length;
  const detailOpen = drawer.kind !== 'none';
  /* Older runs publish 14 days and 13 weeks, pfoi-1.1.1 a full year: stay on a step this run has. */
  const availableHorizons = horizonOptions(run, grain);
  const lastStep = availableHorizons[availableHorizons.length - 1] ?? 1;
  useEffect(() => {
    if (horizon > lastStep) setHorizon(lastStep);
  }, [horizon, lastStep, setHorizon]);

  return (
    <div className="pfie">
      <header className="pfie-head">
        <div className="pfie-bar">
          <div className="pfie-ident">
            <span className="pfie-ident-mark" aria-hidden><Icon name="spark" size={19} /></span>
            <div>
              <h1>Predictive Farm Outlook</h1>
              <p>{simple ? 'Farm X · what to expect for the whole herd' : 'Farm X · herd level · Component 1'}</p>
            </div>
          </div>

          <span className="spacer" />

          <span className="pfie-seg pfie-viewswitch" role="group" aria-label="Page view">
            <button aria-pressed={simple} onClick={() => setView('simple')} title="The main numbers in plain words">Simple view</button>
            <button aria-pressed={!simple} onClick={() => setView('detailed')} title="All charts, controls and model checks">Detailed view</button>
          </span>

          {!simple && <button className="pfie-btn pfie-findings-btn" onClick={() => openDrawer({ kind: 'findings' })}>
            <Icon name="flag" size={14} />
            Findings
            {openFindings > 0 && <span className="count">{openFindings}</span>}
          </button>}

          {!simple && <RunStatus />}
        </div>

        {!simple && <nav className="pfie-nav" aria-label="Workspaces">
          <div className="pfie-nav-tabs">
            {WORKSPACES.map((w) => (
              <button key={w.id} aria-current={workspace === w.id ? 'page' : undefined} onClick={() => go(w.id)}>
                <Icon name={w.icon} size={15} />
                {w.label}
              </button>
            ))}
          </div>

          <span className="pfie-row tight pfie-horizon">
            <span className="pfie-seg compact" role="group" aria-label="Forecast grain">
              {GRAINS.map((g) => (
                <button key={g.id} aria-pressed={grain === g.id} onClick={() => setGrain(g.id)}>{g.label}</button>
              ))}
            </span>
            <span className="pfie-seg compact" role="group" aria-label="Forecast horizon">
              {horizonOptions(run, grain).map((h) => (
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
          </span>
        </nav>}
      </header>

      <div className={`pfie-body${simple && !detailOpen ? ' pfie-body-simple' : ''}`}>
        {simple && !detailOpen && <ManagerView onDetailed={() => setView('detailed')} />}
        {simple && !detailOpen ? null : detailOpen ? (
          <DetailPage />
        ) : (
          <>
            {run.source === 'demo' && (
              <div className="pfie-demo-banner" role="note">
                <b>Demo data.</b> Every number on this page is synthetic. It has the shape of the planned
                model outputs but is not Farm X data, not a forecast and not a backtest result.
              </div>
            )}

            {workspace === 'outlook' && <>
              <OutcomeBar />
              <MetricDeck />
              <SignalBand />
              <OutlookBrief />
              <div className="pfie-canvas"><FutureWorkspace /></div>
            </>}

            {workspace === 'herd' && (
              <div className="pfie-canvas">
                <Tabs tabs={HERD_TABS} value={herdTab} onChange={(t) => go('herd', t)} />
                {herdTab === 'milk' && <MilkSupply />}
                {herdTab === 'flow' && <Reproduction />}
                {herdTab === 'events' && <HerdOutcomes />}
                {herdTab === 'generations' && <HerdGenetics />}
              </div>
            )}
          </>
        )}

        {!detailOpen && !simple && (
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
  const availableHorizons = horizonOptions(run, grain);
  const last = availableHorizons[availableHorizons.length - 1] ?? 1;
  return (
    <span className="pfie-row tight pfie-pickers">
      <label className="pfie-pick" title={`Any step the model publishes (1–${last} ${unit.many}); the buttons are the scored ones`}>
        Ahead
        <input
          type="number"
          min={1}
          max={last}
          value={horizon}
          aria-label={`Forecast steps ahead, 1 to ${last} ${unit.many}`}
          onChange={(e) => {
            const h = Math.round(Number(e.target.value));
            if (Number.isFinite(h)) setHorizon(Math.min(last, Math.max(1, h)));
          }}
        />
        {horizon === 1 ? unit.one : unit.many}
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
