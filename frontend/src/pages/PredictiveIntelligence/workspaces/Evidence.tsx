/**
 * Evidence workspace (§22, §26).
 *
 * Approachable by default; the technical metrics live behind "Advanced details".
 */

import { useState } from 'react';
import {
  CONFIDENCE_BY_HORIZON,
  DATA_COVERAGE,
  MODELS,
  RARE_EVENT_EVIDENCE,
  RECENT_CONFIDENCE_CHANGES,
  REVIEW_PRIORITIES,
  SENSITIVE_DISCLAIMER,
  longDate,
  type ModelStatus,
} from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, EmptyState, Meter, Note } from '../ui';

const STATUS_TONE: Record<ModelStatus, string> = {
  Active: 'conf-High',
  Reduced: 'conf-Moderate',
  Disabled: 'conf-Limited',
};

export function Evidence() {
  const [advanced, setAdvanced] = useState<Set<string>>(new Set());
  const { openDrawer } = useC2();

  const toggle = (id: string) =>
    setAdvanced((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });

  return (
    <div className="pfie-stack">
      <Note tone="info" title="What this workspace is for.">
        It shows what the system can and cannot currently estimate, and why. Nothing here changes a forecast —
        it explains the ground each forecast stands on.
      </Note>

      <div className="pfie-grid side">
        <Card title="Models" sub="Active, reduced in scope, or switched off — with the reason in plain language.">
          <div className="pfie-stack" style={{ gap: 10 }}>
            {MODELS.map((m) => (
              <div key={m.id} className="pfie-note" style={{ padding: '13px 15px' }}>
                <div className="pfie-row between">
                  <b style={{ fontSize: 13 }}>{m.name}</b>
                  <span className="pfie-row tight">
                    <span className={`pfie-badge ${STATUS_TONE[m.status]}`}>{m.status}</span>
                    <ConfidenceBadge level={m.confidence} hint={false} />
                  </span>
                </div>
                <div style={{ color: 'var(--muted)', marginTop: 4 }}>{m.purpose}</div>
                <div style={{ marginTop: 6, fontSize: 11.5 }}>
                  <b style={{ color: 'var(--ink-2)' }}>Output level:</b> {m.outputLevel} ·{' '}
                  <span style={{ color: 'var(--muted)' }}>{m.statusReason}</span>
                </div>
                <button className="pfie-btn ghost" style={{ marginTop: 6 }} onClick={() => toggle(m.id)}>
                  {advanced.has(m.id) ? 'Hide advanced details' : 'Advanced details'}
                </button>
                {advanced.has(m.id) && (
                  <table className="pfie-table" style={{ marginTop: 8 }}>
                    <tbody>
                      {Object.entries({
                        'Model family': m.advanced.family,
                        'Validation period': m.advanced.validationPeriod,
                        'Error': m.advanced.mae,
                        'Calibration': m.advanced.calibration,
                        'Training sample': m.advanced.trainingSample,
                        'Last validated': m.advanced.lastValidated,
                      }).map(([k, v]) => (
                        <tr key={k}>
                          <td style={{ color: 'var(--muted)', width: 130, whiteSpace: 'nowrap' }}>{k}</td>
                          <td style={{ whiteSpace: 'normal' }}>{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        </Card>

        <div className="pfie-stack">
          <Card title="Forecast confidence by horizon" sub="Confidence falls as the estimate depends more on transitions that have not happened.">
            {CONFIDENCE_BY_HORIZON.map((h) => (
              <div key={h.horizon} style={{ marginBottom: 14 }}>
                <div className="pfie-row between">
                  <b style={{ fontSize: 12.5 }}>{h.horizon}</b>
                  <ConfidenceBadge level={h.confidence} hint={false} />
                </div>
                <div className="pfie-row" style={{ gap: 10, marginTop: 5 }}>
                  <span style={{ flex: 1 }}>
                    <Meter pct={h.transitionShare} tone={h.transitionShare > 40 ? 'caution' : 'pred'} />
                  </span>
                  <span style={{ fontSize: 11.5, color: 'var(--muted)', width: 168 }}>
                    {h.transitionShare}% transition-dependent
                  </span>
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 3 }}>{h.note}</div>
              </div>
            ))}
          </Card>

          <Card title="Recent confidence changes">
            <div className="pfie-stack" style={{ gap: 10, fontSize: 12.5 }}>
              {RECENT_CONFIDENCE_CHANGES.map((c) => (
                <div key={c.what}>
                  <b>{c.what}</b>
                  <div style={{ color: 'var(--muted)' }}>{c.why}</div>
                  <div style={{ color: 'var(--faint)', fontSize: 11 }}>{longDate(c.when)}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <Card title="Data coverage" sub="How complete each source is, where the gaps are, and what they limit.">
        <div className="pfie-tablewrap">
          <table className="pfie-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Coverage</th>
                <th className="pfie-num">Through</th>
                <th>Known gaps</th>
                <th>What it limits</th>
              </tr>
            </thead>
            <tbody>
              {DATA_COVERAGE.map((d) => (
                <tr key={d.source}>
                  <td><b>{d.source}</b></td>
                  <td>
                    <span className="pfie-row tight">
                      <Meter pct={d.coverage} tone={d.coverage < 80 ? 'caution' : 'brand'} />
                      <span style={{ width: 34, textAlign: 'right' }}>{d.coverage}%</span>
                    </span>
                  </td>
                  <td className="pfie-num">{d.through}</td>
                  <td style={{ color: 'var(--muted)', whiteSpace: 'normal', minWidth: 200 }}>{d.gaps}</td>
                  <td style={{ color: 'var(--muted)', whiteSpace: 'normal', minWidth: 240 }}>{d.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="pfie-grid side">
        <Card title="Rare-event evidence" sub="Where the recorded event count decides what can honestly be published.">
          <div className="pfie-tablewrap">
            <table className="pfie-table">
              <thead>
                <tr>
                  <th>Outcome</th>
                  <th className="pfie-num">Recorded events</th>
                  <th>Verdict</th>
                  <th>Published at</th>
                </tr>
              </thead>
              <tbody>
                {RARE_EVENT_EVIDENCE.map((r) => (
                  <tr key={r.event}>
                    <td><b>{r.event}</b></td>
                    <td className="pfie-num">{r.events}</td>
                    <td style={{ color: 'var(--muted)', whiteSpace: 'normal', minWidth: 240 }}>{r.verdict}</td>
                    <td><span className="pfie-badge plain">{r.level}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 14 }}>
            <EmptyState title="Individual abortion prediction is unavailable">
              Only 17 comparable historical events are available. The system reports a herd-level rate instead of
              an animal-level estimate, and will publish one if the recorded event count grows.
            </EmptyState>
          </div>
        </Card>

        <Card title="Mortality review priority" sub="A ranking to help prioritise attention. Deliberately not a label.">
          <Note tone="concern" title="Read this carefully.">
            {SENSITIVE_DISCLAIMER}
          </Note>
          <div className="pfie-tablewrap pfie-scroll short" style={{ marginTop: 12 }}>
            <table className="pfie-table">
              <thead>
                <tr>
                  <th>Animal</th>
                  <th className="pfie-num">Estimated likelihood over 90 days</th>
                  <th className="pfie-num">Similar-cow baseline</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {REVIEW_PRIORITIES.map((r) => (
                  <tr key={r.animal.id} className="clickable" onClick={() => openDrawer({ kind: 'cow', animalId: r.animal.id })}>
                    <td><b>{r.animal.id}</b> <span style={{ color: 'var(--muted)' }}>· {r.drivers[0]}</span></td>
                    <td className="pfie-num">{r.range[0]}–{r.range[1]}%</td>
                    <td className="pfie-num" style={{ color: 'var(--muted)' }}>{r.baseline}%</td>
                    <td><ConfidenceBadge level={r.confidence} hint={false} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="sub" style={{ marginTop: 10 }}>
            Elevated mortality-related review priority. Use the ordering, not the absolute level — the model is
            poorly calibrated in absolute terms and trained on 31 events.
          </p>
        </Card>
      </div>
    </div>
  );
}
