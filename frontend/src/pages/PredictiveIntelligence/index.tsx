/**
 * Component 2 — Predictive Farm Intelligence.
 *
 * Four workspaces over one shared selection state. This is a hard-coded
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
  isoDate,
  longDate,
  type HorizonId,
} from '../../data/component2';
import { C2Provider, useC2, type CapacityTab, type Workspace } from './state';
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
import './pfie.css';

const WORKSPACES: { id: Workspace; label: string }[] = [
  { id: 'future', label: 'Farm Outlook' },
  { id: 'capacity', label: 'Herd & Production' },
  { id: 'commerce', label: 'Products & Income' },
  { id: 'evidence', label: 'Forecast Confidence' },
  { id: 'operations', label: 'Daily Operations' },
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
      <Shell />
    </C2Provider>
  );
}

function Shell() {
  const {
    farm, horizon, setHorizon, workspace, capacityTab, go,
    drawer, openDrawer, acknowledged, snoozed,
  } = useC2();

  const openFindings = findingsOpenCount(acknowledged, snoozed);
  const activeFarm = FARMS.find((f) => f.id === farm)!;
  const [overviewOpen, setOverviewOpen] = useState(false);

  return (
    <div className="pfie">
      {/* ---- persistent control bar ---- */}
      <div className="pfie-bar">
        <span className="pfie-seg" role="group" aria-label="Forecast horizon">
          {HORIZONS.map((h) => (
            <button key={h.id} aria-pressed={horizon === h.id} onClick={() => setHorizon(h.id as HorizonId)}>
              {h.label}
            </button>
          ))}
        </span>

        <CowSearch />

        <span className="spacer" />

        <button className="pfie-btn" onClick={() => openDrawer({ kind: 'findings' })}>
          Findings {openFindings > 0 && <span className="pfie-badge conf-Limited" style={{ marginLeft: 4 }}>{openFindings}</span>}
        </button>

        <div className="pfie-stamp">
          Updated <b>{GENERATED_AT}</b>
          <br />
          Data through <b>{longDate(isoDate(DATA_THROUGH))}</b>
        </div>
      </div>

      {/* ---- workspace navigation ---- */}
      <nav className="pfie-nav">
        {WORKSPACES.map((w) => (
          <button
            key={w.id}
            aria-current={workspace === w.id ? 'page' : undefined}
            onClick={() => go(w.id)}
          >
            {w.label}
          </button>
        ))}
      </nav>

      <main className="pfie-body">
        {activeFarm.populated && workspace !== 'operations' && (
          <section className={`pfie-overview${overviewOpen ? ' open' : ''}`}>
            <button
              className="pfie-overview-toggle"
              onClick={() => setOverviewOpen((open) => !open)}
              aria-expanded={overviewOpen}
              aria-controls="farm-overview-content"
            >
              <span className="pfie-overview-icon" aria-hidden>{overviewOpen ? '⌄' : '›'}</span>
              <span>
                <b>Farm overview</b>
                <small>Timeline and current herd composition</small>
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
        {!activeFarm.populated ? (
          <EmptyState title={`${activeFarm.name} has no data in this prototype`}>
            Only {FARMS[0].name} is populated. Switch back to it in the farm selector to explore the
            forecasts.
          </EmptyState>
        ) : (
          <>
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
          </>
        )}

        <p style={{ fontSize: 11.5, color: 'var(--faint)', marginTop: 40, paddingTop: 16, borderTop: '1px solid var(--line)', lineHeight: 1.6 }}>
          All figures are fictional synthetic prototype data. They are not NLDB records, not DelPro data, and do
          not represent research findings. Component 2 is a predictive layer — animal records, event entry,
          treatments and operational reporting remain in DelPro. The Operations workspace demonstrates how
          acknowledgement, action and outcome evidence can be monitored without replacing those source systems.
        </p>
      </main>

      {/* ---- drawers ---- */}
      {drawer.kind === 'cow' && <CowPanel animalId={drawer.animalId} />}
      {drawer.kind === 'cohort' && <CohortDrawer groupKey={drawer.groupKey} value={drawer.value} />}
      {drawer.kind === 'structure' && <StructureDrawer date={drawer.date} domain={drawer.domain} />}
      {drawer.kind === 'outcome' && <OutcomeReasoningDrawer date={drawer.date} chart={drawer.chart} />}
      {drawer.kind === 'flow-stage' && <FlowStageDrawer stageId={drawer.stageId} />}
      {drawer.kind === 'product' && <ProductDrawer product={drawer.product} />}
      {drawer.kind === 'findings' && <FindingsDrawer />}
    </div>
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
    <span style={{ position: 'relative' }}>
      <label className="pfie-field">
        <input
          type="search"
          placeholder="Find a cow or cohort…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 160)}
          style={{ width: 190 }}
          aria-label="Search animals and cohorts"
        />
      </label>
      {focused && results.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 6,
            width: 330,
            background: 'var(--paper)',
            border: '1px solid var(--line)',
            borderRadius: 10,
            boxShadow: 'var(--shadow-lg)',
            zIndex: 50,
            overflow: 'hidden',
          }}
        >
          {results.map((a) => (
            <button
              key={a.id}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                border: 0,
                background: 'none',
                padding: '9px 12px',
                fontSize: 12.5,
                borderBottom: '1px solid var(--line-2)',
              }}
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
        <div
          style={{
            position: 'absolute', top: '100%', left: 0, marginTop: 6, width: 330,
            background: 'var(--paper)', border: '1px solid var(--line)', borderRadius: 10,
            boxShadow: 'var(--shadow-lg)', zIndex: 50, padding: '12px 14px',
            fontSize: 12.5, color: 'var(--muted)',
          }}
        >
          No animal or cohort matches “{search}”.
        </div>
      )}
    </span>
  );
}
