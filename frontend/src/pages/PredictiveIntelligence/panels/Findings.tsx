/**
 * Findings inbox (§25).
 *
 * The milk decline, the tetra-pack shortfall and the margin effect are one
 * finding with a consequence chain, not three competing alerts.
 */

import { useState } from 'react';
import { FINDINGS, SEVERITY_META, type Finding } from '../../../data/component2';
import { useC2 } from '../state';
import { ConfidenceBadge, Tabs } from '../ui';

type FindingFilter = 'All' | Finding['kind'];

const FINDING_FILTERS: FindingFilter[] = [
  'All',
  'Forecast change',
  'Action needed',
  'Upcoming',
  'Confidence change',
  'Data limitation',
  'Opportunity',
];

export function FindingCard({ f, compact = false }: { f: Finding; compact?: boolean }) {
  const { acknowledge, snooze, acknowledged, snoozed, go, setSelectedDate, setSelectedMonth } = useC2();
  const [open, setOpen] = useState(false);
  const sev = SEVERITY_META[f.severity];
  const done = acknowledged.has(f.id) || snoozed.has(f.id);

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

      {f.chain && open && (
        <ul className="pfie-chain">
          {f.chain.map((c) => (
            <li key={c.step}>
              <span className="s">{c.step}</span>
              <span>{c.detail}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="pfie-row tight" style={{ marginTop: 11 }}>
        {f.chain && (
          <button className="pfie-btn ghost" onClick={() => setOpen(!open)}>
            {open ? 'Hide the consequence chain' : `Show the consequence chain (${f.chain.length} steps)`}
          </button>
        )}
        {!compact &&
          f.links.map((l) => (
            <button
              key={l.label}
              className="pfie-btn"
              onClick={() => {
                if (l.date) setSelectedDate(l.date);
                if (l.month) setSelectedMonth(l.month);
                go(l.workspace, l.tab);
              }}
            >
              {l.label} →
            </button>
          ))}
        {!done ? (
          <>
            <button className="pfie-btn ghost" onClick={() => acknowledge(f.id)}>Acknowledge</button>
            <button className="pfie-btn ghost" onClick={() => snooze(f.id)}>Snooze</button>
          </>
        ) : (
          <span className="pfie-badge plain">{acknowledged.has(f.id) ? 'Acknowledged' : 'Snoozed'}</span>
        )}
      </div>
    </article>
  );
}

export function FindingsList({ compact = false }: { compact?: boolean }) {
  const { acknowledged, snoozed, restoreFindings } = useC2();
  const [showDone, setShowDone] = useState(false);
  const [filter, setFilter] = useState<FindingFilter>('All');

  const rank: Record<string, number> = { critical: 0, attention: 1, routine: 2 };
  const all = [...FINDINGS].sort((a, b) => rank[a.severity] - rank[b.severity]);
  const open = all.filter((f) => !acknowledged.has(f.id) && !snoozed.has(f.id));
  const done = all.filter((f) => acknowledged.has(f.id) || snoozed.has(f.id));
  const source = showDone ? all : open;
  const list = filter === 'All' ? source : source.filter((f) => f.kind === filter);
  const countFor = (kind: FindingFilter) =>
    kind === 'All' ? source.length : source.filter((f) => f.kind === kind).length;

  return (
    <div className="pfie-stack" style={{ gap: 10 }}>
      <Tabs
        value={filter}
        onChange={setFilter}
        tabs={FINDING_FILTERS.map((kind) => ({
          id: kind,
          label: `${kind}${countFor(kind) ? ` (${countFor(kind)})` : ''}`,
        }))}
      />
      {list.length === 0 && (
        <div className="pfie-empty">
          <b>No {filter === 'All' ? 'outstanding findings' : `${filter.toLowerCase()} findings`}</b>
          {showDone ? 'No findings match this category.' : 'Try All or show handled findings.'}
        </div>
      )}
      {list.map((f) => <FindingCard key={f.id} f={f} compact={compact} />)}
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

export function findingsOpenCount(acknowledged: Set<string>, snoozed: Set<string>) {
  return FINDINGS.filter((f) => !acknowledged.has(f.id) && !snoozed.has(f.id)).length;
}
