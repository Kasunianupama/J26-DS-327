/**
 * Component 1 (PFOI): findings inbox.
 *
 * Findings are computed from the run (lowest forecast month, upcoming
 * calvings, the abortion-rate shift, record gaps), so they move with it. All
 * are herd level; none name an animal.
 */

import { useState } from 'react';
import { SEVERITY_META, findings, type Finding } from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { ConfidenceBadge, Tabs } from '../ui';

type FindingFilter = 'All' | Finding['kind'];
const FILTERS: FindingFilter[] = ['All', 'Forecast change', 'Upcoming', 'Pattern', 'Data limitation'];

export function FindingCard({ f }: { f: Finding }) {
  const { acknowledge, acknowledged, go, closeDrawer, drawer, setGrain, setSelectedPeriod, setBreakdownMonth } = usePfoi();
  const sev = SEVERITY_META[f.severity];
  const done = acknowledged.has(f.id);

  const follow = () => {
    if (f.link.period) {
      setGrain('month');
      setSelectedPeriod(f.link.period);
      setBreakdownMonth(f.link.period);
    }
    go(f.link.workspace, f.link.tab);
    if (drawer.kind !== 'none') closeDrawer();
  };

  return (
    <article className={`pfie-finding sev-${f.severity}${done ? ' acked' : ''}`}>
      <div className="pfie-row between" style={{ gap: 8 }}>
        <span className="kind" style={{ color: sev.color }}>
          <span aria-hidden>{sev.mark}</span> {f.kind}
        </span>
        <ConfidenceBadge level={f.confidence} />
      </div>
      <h4 style={{ marginTop: 6 }}>{f.title}</h4>
      <p>{f.summary}</p>
      <div className="pfie-row tight" style={{ marginTop: 11 }}>
        <button className="pfie-btn" onClick={follow}>{f.link.label} →</button>
        {!done
          ? <button className="pfie-btn ghost" onClick={() => acknowledge(f.id)}>Acknowledge</button>
          : <span className="pfie-badge plain">Acknowledged</span>}
      </div>
    </article>
  );
}

export function FindingsList() {
  const { acknowledged, restoreFindings } = usePfoi();
  const run = useRun();
  const [showDone, setShowDone] = useState(false);
  const [filter, setFilter] = useState<FindingFilter>('All');

  const all = [...findings(run)].sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'attention' ? -1 : 1));
  const open = all.filter((f) => !acknowledged.has(f.id));
  const done = all.filter((f) => acknowledged.has(f.id));
  const source = showDone ? all : open;
  const list = filter === 'All' ? source : source.filter((f) => f.kind === filter);
  const countFor = (kind: FindingFilter) => (kind === 'All' ? source.length : source.filter((f) => f.kind === kind).length);

  return (
    <div className="pfie-stack" style={{ gap: 10 }}>
      <Tabs
        value={filter}
        onChange={setFilter}
        tabs={FILTERS.map((kind) => ({ id: kind, label: `${kind}${countFor(kind) ? ` (${countFor(kind)})` : ''}` }))}
      />
      {list.length === 0 && (
        <div className="pfie-empty">
          <b>No {filter === 'All' ? 'outstanding findings' : `${filter.toLowerCase()} findings`}</b>
          {showDone ? 'No findings match this category.' : 'Try All or show handled findings.'}
        </div>
      )}
      {list.length > 0 && <div className="pfie-findings-grid">{list.map((f) => <FindingCard key={f.id} f={f} />)}</div>}
      {done.length > 0 && (
        <div className="pfie-row tight">
          <button className="pfie-btn ghost" onClick={() => setShowDone(!showDone)}>
            {showDone ? 'Hide' : 'Show'} {done.length} handled
          </button>
          <button className="pfie-btn ghost" onClick={restoreFindings}>Restore all</button>
        </div>
      )}
    </div>
  );
}
