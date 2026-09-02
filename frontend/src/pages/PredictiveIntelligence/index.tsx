/**
 * Component 2 — Predictive Farm Intelligence.
 *
 * Five workspaces over one shared selection state, presented as a command deck:
 * a frosted header, a metric deck scoped to the current workspace, the priority
 * signals that point into it, and a full-width canvas. This is a hard-coded
 * prototype: all data is fictional synthetic scaffold data, and no backend,
 * model or DelPro integration is involved.
 */

import { useMemo, useState } from 'react';
import {
  DATA_THROUGH,
  FARMS,
  GENERATED_AT,
  HERD,
  HORIZONS,
  PROFILES,
  SEVERITY_META,
  isoDate,
  longDate,
  type HorizonId,
} from '../../data/component2';
import { C2Provider, useC2, type CapacityTab, type Workspace } from './state';
import { PredictiveBackendProvider, usePredictiveBackend } from './backend';
import { CowPanel } from './panels/CowPanel';
import { TimelinePlayer } from './panels/TimelinePlayer';
import { HerdStrip } from './panels/HerdFlow';
import {
  CohortDrawer,
  FindingsDrawer,
  FlowStageDrawer,
  OutcomeReasoningDrawer,
  ProductDrawer,
  StructureDrawer,
} from './panels/Drawers';
import { findingsOpenCount } from './panels/Findings';
import { Evidence } from './workspaces/Evidence';
import { FutureWorkspace } from './workspaces/Future';
import { HerdGenetics } from './workspaces/HerdGenetics';
import { MilkSupply } from './workspaces/MilkSupply';
import { ProductsFinance } from './workspaces/ProductsFinance';
import { Reproduction } from './workspaces/Reproduction';
import { HerdOutcomes } from './workspaces/HerdOutcomes';
import { Operations } from './workspaces/Operations';
import { EmptyState, Tabs } from './ui';
import { Icon, type IconName } from './icons';
import { MetricDeck, signalsFor } from './deck';
import './pfie.css';

const WORKSPACES: { id: Workspace; label: string; icon: IconName }[] = [
  { id: 'future', label: 'Farm Outlook', icon: 'outlook' },
  { id: 'capacity', label: 'Herd & Production', icon: 'herd' },
  { id: 'commerce', label: 'Products & Income', icon: 'products' },
  { id: 'evidence', label: 'Forecast Confidence', icon: 'confidence' },
  { id: 'operations', label: 'Daily Operations', icon: 'operations' },
];

const CAPACITY_TABS: { id: CapacityTab; label: string }[] = [
  { id: 'milk', label: 'Milk supply' },
  { id: 'reproduction', label: 'Reproduction & capacity' },
  { id: 'outcomes', label: 'Herd outcomes & risk' },
  { id: 'genetics', label: 'Herd profile & genetics' },
];

export default function PredictiveIntelligencePage() {
  return (
    <C2Provider>
      <BackendBridge>
        <Shell />
      </BackendBridge>
    </C2Provider>
  );
}

function BackendBridge({ children }: { children: React.ReactNode }) {
  const { farm, horizon } = useC2();
  return <PredictiveBackendProvider farmId={farm} horizon={horizon}>{children}</PredictiveBackendProvider>;
}

function Shell() {
  const {
    farm, horizon, setHorizon, workspace, capacityTab, go,
    drawer, openDrawer, acknowledged, snoozed,
  } = useC2();
  const backend = usePredictiveBackend();

  const findings = backend.snapshot?.findings;
  const openFindings = findingsOpenCount(acknowledged, snoozed, findings);
  const detailOpen = drawer.kind !== 'none';
  const farms = backend.snapshot?.farms ?? FARMS;
  const activeFarm = farms.find((f) => f.id === farm) ?? FARMS[0];
  const generatedAt = backend.snapshot?.generated_at ?? GENERATED_AT;
  const dataThrough = backend.snapshot?.data_through ?? isoDate(DATA_THROUGH);
  const [overviewOpen, setOverviewOpen] = useState(false);

  return (
    <div className="pfie">
      {/* ================= command header ================= */}
      <header className="pfie-head">
        <div className="pfie-bar">
          <div className="pfie-ident">
            <span className="pfie-ident-mark" aria-hidden><Icon name="spark" size={19} /></span>
            <div>
              <h1>Predictive intelligence</h1>
              <p>{activeFarm.name} · prototype</p>
            </div>
          </div>

          <span className="spacer" />

          <CowSearch />

          <button
            className="pfie-btn pfie-findings-btn"
            onClick={() => openDrawer({ kind: 'findings' })}
          >
            <Icon name="flag" size={14} />
            Findings
            {openFindings > 0 && <span className="count">{openFindings}</span>}
          </button>

          <span
            className="pfie-live"
            title={backend.error ? `Backend unavailable; showing prototype fallback: ${backend.error}` : 'Loaded from the predictive backend'}
          >
            <i aria-hidden />{backend.error ? 'Fallback' : backend.loading ? 'Connecting' : 'Backend'} · {generatedAt.slice(11, 16)}
          </span>

          <div className="pfie-stamp">
            <span>Updated <b>{generatedAt.slice(0, 10)}</b></span>
            <span>Data through <b>{longDate(dataThrough)}</b></span>
          </div>
        </div>

        <nav className="pfie-nav" aria-label="Workspaces">
          <div className="pfie-nav-tabs">
            {WORKSPACES.map((w) => (
              <button
                key={w.id}
                aria-current={workspace === w.id ? 'page' : undefined}
                onClick={() => go(w.id)}
              >
                <Icon name={w.icon} size={15} />
                {w.label}
              </button>
            ))}
          </div>

          {/* Abbreviated so the workspace pills and the horizon share one row on
              a 14-inch screen; the full label stays available to assistive tech. */}
          <span className="pfie-seg compact" role="group" aria-label="Forecast horizon">
            {HORIZONS.map((h) => (
              <button
                key={h.id}
                aria-pressed={horizon === h.id}
                aria-label={h.label}
                title={h.label}
                onClick={() => setHorizon(h.id as HorizonId)}
              >
                {h.id.toUpperCase()}
              </button>
            ))}
          </span>
        </nav>
      </header>

      <div className="pfie-body">
        {detailOpen ? (
          <DetailPage />
        ) : !activeFarm.populated ? (
          <EmptyState title={`${activeFarm.name} has no data in this prototype`}>
            Only {FARMS[0].name} is populated. Switch back to it in the farm selector to explore the
            forecasts.
          </EmptyState>
        ) : (
          <>
            {/* ================= metric deck ================= */}
            <MetricDeck />

            {/* ================= priority signals ================= */}
            <SignalBand />

            {/* ================= working canvas ================= */}
            <div className="pfie-canvas">
              {/* Farm Outlook carries the full timeline inline, so the compact
                  overview would only repeat it. */}
              {workspace !== 'operations' && workspace !== 'future' && (
                <section className={`pfie-overview${overviewOpen ? ' open' : ''}`}>
                  <button
                    className="pfie-overview-toggle"
                    onClick={() => setOverviewOpen((open) => !open)}
                    aria-expanded={overviewOpen}
                    aria-controls="farm-overview-content"
                  >
                    <span className="pfie-overview-icon" aria-hidden>›</span>
                    <span>
                      <b>Farm timeline &amp; herd composition</b>
                      <small>Recorded history, today, and the expected path</small>
                    </span>
                    <span className="pfie-overview-action">{overviewOpen ? 'Collapse' : 'Expand'}</span>
                  </button>
                  {overviewOpen && (
                    <div id="farm-overview-content" className="pfie-overview-content">
                      <TimelinePlayer />
                      <HerdStrip />
                    </div>
                  )}
                </section>
              )}

              {workspace === 'future' && <FutureWorkspace />}
              {workspace === 'capacity' && (
                <>
                  <Tabs tabs={CAPACITY_TABS} value={capacityTab} onChange={(t) => go('capacity', t)} />
                  {capacityTab === 'milk' && <MilkSupply />}
                  {capacityTab === 'reproduction' && <Reproduction />}
                  {capacityTab === 'outcomes' && <HerdOutcomes />}
                  {capacityTab === 'genetics' && <HerdGenetics />}
                </>
              )}
              {workspace === 'commerce' && <ProductsFinance />}
              {workspace === 'evidence' && <Evidence />}
              {workspace === 'operations' && <Operations />}
            </div>
          </>
        )}

        {!detailOpen && <p className="pfie-disclaimer">
          All figures are fictional sample prototype data. They are not NLDB records, not DelPro data, and do
          not represent research findings. Component 2 is a predictive layer — animal records, event entry,
          treatments and operational reporting remain in DelPro. The Operations workspace demonstrates how
          acknowledgement, action and outcome evidence can be monitored without replacing those source systems.
        </p>}
      </div>

    </div>
  );
}

/** Routes the open detail state to the panel that knows how to render it. */
function DetailPage() {
  const { drawer } = useC2();
  switch (drawer.kind) {
    case 'cow': return <CowPanel animalId={drawer.animalId} />;
    case 'cohort': return <CohortDrawer groupKey={drawer.groupKey} value={drawer.value} />;
    case 'structure': return <StructureDrawer date={drawer.date} domain={drawer.domain} />;
    case 'outcome': return <OutcomeReasoningDrawer date={drawer.date} chart={drawer.chart} />;
    case 'flow-stage': return <FlowStageDrawer stageId={drawer.stageId} />;
    case 'product': return <ProductDrawer product={drawer.product} />;
    case 'findings': return <FindingsDrawer />;
    default: return null;
  }
}

/* ------------------------------------------------------------------ */
/* Priority signals — the findings that point into this workspace.     */

function SignalBand() {
  const {
    workspace, acknowledged, snoozed, openDrawer, go, setSelectedDate, setSelectedMonth,
  } = useC2();
  const { snapshot } = usePredictiveBackend();
  const signals = signalsFor(workspace, acknowledged, snoozed, snapshot?.findings);
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
          const link = f.links[0];
          return (
            <li key={f.id} className={`pfie-signal sev-${f.severity}`}>
              <span className="kind" style={{ color: sev.color }}>
                <span aria-hidden>{sev.mark}</span> {f.kind}
              </span>
              <b>{f.title}</b>
              <p>{f.summary}</p>
              {link && (
                <button
                  className="pfie-btn ghost"
                  onClick={() => {
                    if (link.date) setSelectedDate(link.date);
                    if (link.month) setSelectedMonth(link.month);
                    go(link.workspace, link.tab);
                  }}
                >
                  {link.label} <Icon name="arrowRight" size={13} />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ------------------------------------------------------------------ */

function CowSearch() {
  const { search, setSearch, openDrawer } = useC2();
  const [focused, setFocused] = useState(false);

  const results = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (q.length < 2) return [];
    return HERD.filter(
      (a) =>
        a.id.toLowerCase().includes(q) ||
        a.tag.includes(q) ||
        a.geneticGroup.toLowerCase().includes(q) ||
        a.opGroup.toLowerCase().includes(q) ||
        PROFILES[a.profile].name.toLowerCase().includes(q),
    ).slice(0, 8);
  }, [search]);

  return (
    <span className="pfie-search">
      <Icon name="search" size={14} />
      <input
        type="search"
        placeholder="Find a cow or cohort…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 160)}
        aria-label="Search animals and cohorts"
      />
      {focused && results.length > 0 && (
        <div className="pfie-search-results">
          {results.map((a) => (
            <button
              key={a.id}
              onClick={() => { openDrawer({ kind: 'cow', animalId: a.id }); setSearch(''); }}
            >
              <b>{a.id}</b>
              <span style={{ color: 'var(--muted)' }}>
                {' '}· {a.prodState} · {a.geneticGroup} · {PROFILES[a.profile].short}
              </span>
            </button>
          ))}
        </div>
      )}
      {focused && search.trim().length >= 2 && results.length === 0 && (
        <div className="pfie-search-results">
          <p className="none">No animal or cohort matches “{search}”.</p>
        </div>
      )}
    </span>
  );
}
