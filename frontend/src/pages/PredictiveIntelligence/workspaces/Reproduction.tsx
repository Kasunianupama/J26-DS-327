/**
 * Capacity → Reproduction & Capacity (§12, §13, §14).
 *
 * Reproduction is presented as the pipeline that feeds future milking capacity,
 * not as an attention list — DelPro already does attention lists.
 */

import { Fragment, useMemo, useState } from 'react';
import {
  AI_INSIGHTS,
  AI_SUMMARY,
  ATTEMPTS_DISTRIBUTION,
  CAPACITY_FLOW,
  DRY_PLAN,
  EXPECTED_EXITS,
  EXPECTED_MILKERS,
  HARD_MINIMUM_DAYS,
  THI_RESPONSE,
  fmtInt,
  longDate,
} from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, DelProLink, EmptyState, Meter, Note } from '../ui';

export function Reproduction() {
  const { openDrawer } = useC2();
  const [stage, setStage] = useState<string | null>(null);

  const maxCount = Math.max(...CAPACITY_FLOW.map((s) => Math.max(s.current, s.expected)));

  return (
    <div className="pfie-stack">
      {/* ---- capacity flow ---- */}
      <Card
        title="Capacity flow"
        sub="How today's reproductive position becomes tomorrow's milking herd. Width reflects expected animal count; time runs left to right."
      >
        <div className="pfie-flow">
          {CAPACITY_FLOW.map((s, i) => (
            <Fragment key={s.id}>
              <button
                className={`pfie-flow-stage ${s.state}`}
                aria-pressed={stage === s.id}
                style={{ flexGrow: Math.max(0.55, (Math.max(s.current, s.expected) / maxCount) * 1.6) }}
                onClick={() => { setStage(s.id); openDrawer({ kind: 'flow-stage', stageId: s.id }); }}
              >
                <span className="bar" style={{ display: 'block' }}>
                  <span className="nm">{s.name}</span>
                  <span className="ct" style={{ display: 'block' }}>{s.expected || s.current}</span>
                  <span className="rg">
                    {s.range[0]}–{s.range[1]} expected
                  </span>
                  <span className="rg" style={{ display: 'block', marginTop: 4 }}>
                    {s.confirmed} confirmed · {s.uncertain} uncertain
                  </span>
                </span>
              </button>
              {i < CAPACITY_FLOW.length - 1 && <span className="pfie-flow-arrow" aria-hidden>→</span>}
            </Fragment>
          ))}
        </div>

        <div className="pfie-legend">
          <span><i style={{ background: '#e5f0ea', border: '1.5px solid #1f6b4a' }} />Confirmed record</span>
          <span><i style={{ background: 'repeating-linear-gradient(45deg,#5b7fa6 0 2px,#e4ecf3 2px 5px)', border: '1.5px dashed #5b7fa6' }} />Predicted</span>
          <span><i style={{ background: '#fbf2dc', border: '1.5px solid #a8770a' }} />Delayed</span>
          <span><i style={{ background: '#fbeae7', border: '1.5px dotted #a44b3c' }} />Missing evidence</span>
        </div>

        <div className="pfie-consequence" style={{ marginTop: 18 }}>
          {EXPECTED_MILKERS.map((m) => (
            <div key={m.horizon}>
              <div className="k">Expected active milkers · {m.horizon}</div>
              <div className="v">{m.value}</div>
              <div className="d">Likely range {m.range[0]}–{m.range[1]} · {m.confidence} confidence</div>
            </div>
          ))}
          <div>
            <div className="k">Expected exits · 90 days</div>
            <div className="v">{EXPECTED_EXITS.dryOffs90 + EXPECTED_EXITS.culls90 + EXPECTED_EXITS.mortality90}</div>
            <div className="d">
              {EXPECTED_EXITS.dryOffs90} dry-offs · {EXPECTED_EXITS.culls90} expected sales · {EXPECTED_EXITS.mortality90} mortality allowance
            </div>
          </div>
        </div>
      </Card>

      {/* ---- AI intelligence (secondary to capacity) ---- */}
      <div className="pfie-grid side">
        <Card
          title="Conception likelihood"
          sub="Live breeding decisions only, ranked by likelihood. Event probability — not the same thing as forecast confidence."
        >
          <div className="pfie-tablewrap pfie-scroll short">
            <table className="pfie-table">
              <thead>
                <tr>
                  <th>Animal</th>
                  <th className="pfie-num">Estimated likelihood</th>
                  <th className="pfie-num">Similar-cow baseline</th>
                  <th>Forecast confidence</th>
                  <th>Capacity effect</th>
                </tr>
              </thead>
              <tbody>
                {AI_INSIGHTS.slice(0, 24).map((a) => (
                  <tr
                    key={a.animal.id}
                    className="clickable"
                    onClick={() => openDrawer({ kind: 'cow', animalId: a.animal.id })}
                  >
                    <td><b>{a.animal.id}</b> <span style={{ color: 'var(--muted)' }}>· {a.animal.reproState}</span></td>
                    <td className="pfie-num">
                      <span className="pfie-row tight" style={{ justifyContent: 'flex-end' }}>
                        <Meter pct={a.likelihood} tone={a.likelihood >= a.peerBaseline ? 'brand' : 'caution'} />
                        <b>{a.likelihood}%</b>
                      </span>
                    </td>
                    <td className="pfie-num" style={{ color: 'var(--muted)' }}>{a.peerBaseline}%</td>
                    <td><ConfidenceBadge level={a.confidence} hint={false} /></td>
                    <td style={{ color: 'var(--muted)' }}>Entry around {longDate(a.expectedEntry).slice(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {AI_INSIGHTS[0] && (
            <div style={{ marginTop: 14 }}>
              <Note tone="info" title={`Why ${AI_INSIGHTS[0].animal.id} sits above the baseline.`}>
                {AI_INSIGHTS[0].reasons[0]}
              </Note>
            </div>
          )}
        </Card>

        <div className="pfie-stack">
          <Card title="Herd reproductive performance" sub="Descriptive, from the recorded service history.">
            <dl className="pfie-dl" style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '8px 16px', fontSize: 13 }}>
              <dt style={{ color: 'var(--muted)' }}>Animals served</dt><dd style={{ textAlign: 'right', fontWeight: 600 }}>{AI_SUMMARY.servedAnimals}</dd>
              <dt style={{ color: 'var(--muted)' }}>Recorded services</dt><dd style={{ textAlign: 'right', fontWeight: 600 }}>{AI_SUMMARY.services}</dd>
              <dt style={{ color: 'var(--muted)' }}>Conception rate</dt><dd style={{ textAlign: 'right', fontWeight: 600 }}>{AI_SUMMARY.successRate}%</dd>
              <dt style={{ color: 'var(--muted)' }}>Services per conception</dt><dd style={{ textAlign: 'right', fontWeight: 600 }}>{AI_SUMMARY.servicesPerConception}</dd>
            </dl>
            <div className="pfie-section-title" style={{ marginTop: 18 }}>Services before conception</div>
            {ATTEMPTS_DISTRIBUTION.map((d) => (
              <div className="pfie-row" key={d.attempts} style={{ gap: 10, marginBottom: 5 }}>
                <span style={{ width: 26, fontSize: 12, color: 'var(--muted)' }}>{d.attempts}</span>
                <span style={{ flex: 1 }}><Meter pct={d.pct * 2.4} /></span>
                <span style={{ fontSize: 12, width: 62, textAlign: 'right' }}>{d.animals} · {d.pct}%</span>
              </div>
            ))}
          </Card>

          <Card title="Conception against the heat index" sub="The clearest external signal in the recorded services.">
            {THI_RESPONSE.map((t) => (
              <div className="pfie-row" key={t.band} style={{ gap: 10, marginBottom: 6 }}>
                <span style={{ width: 76, fontSize: 12, color: 'var(--muted)' }}>{t.band}</span>
                <span style={{ flex: 1 }}><Meter pct={t.rate * 1.7} tone={t.rate < 35 ? 'caution' : 'brand'} /></span>
                <span style={{ fontSize: 12, width: 78, textAlign: 'right' }}>{t.rate}% · n={t.services}</span>
              </div>
            ))}
            <div style={{ marginTop: 12 }}>
              <Note>
                Recorded together, not proven to cause one another. The current window sits in the moderate-to-severe
                bands.
              </Note>
            </div>
          </Card>
        </div>
      </div>

      {/* ---- dry planning ---- */}
      <DryPlanning />
    </div>
  );
}

function DryPlanning() {
  const { openDrawer } = useC2();
  const [filter, setFilter] = useState<'All' | 'Recommendation available' | 'Provisional' | 'Schedule only' | 'No reliable recommendation'>('All');

  const rows = useMemo(
    () => (filter === 'All' ? DRY_PLAN : DRY_PLAN.filter((r) => r.status === filter)).slice(0, 60),
    [filter],
  );

  return (
    <Card
      title="Dry planning"
      sub={`Rest windows for animals approaching dry-off. The hard minimum of ${HARD_MINIMUM_DAYS} days is never crossed.`}
      actions={
        <label className="pfie-field">
          Status
          <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option>All</option>
            <option>Recommendation available</option>
            <option>Provisional</option>
            <option>Schedule only</option>
            <option>No reliable recommendation</option>
          </select>
        </label>
      }
    >
      {rows.length === 0 ? (
        <EmptyState title="No animals in this state">
          Change the status filter to see the rest of the dry-off schedule.
        </EmptyState>
      ) : (
        <div className="pfie-tablewrap pfie-scroll">
          <table className="pfie-table">
            <thead>
              <tr>
                <th>Cow</th>
                <th>Current stage</th>
                <th>Recommended window</th>
                <th className="pfie-num">Hard minimum</th>
                <th>Confidence</th>
                <th className="pfie-num">Comparable cases</th>
                <th>Capacity consequence</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.animal.id} className="clickable" onClick={() => openDrawer({ kind: 'cow', animalId: r.animal.id })}>
                  <td><b>{r.animal.id}</b></td>
                  <td>{r.stage}</td>
                  <td>
                    {r.window ? (
                      <b>{r.window[0]}–{r.window[1]} days</b>
                    ) : (
                      <span style={{ color: 'var(--muted)' }}>Not published</span>
                    )}
                  </td>
                  <td className="pfie-num">{r.hardMinimum} days</td>
                  <td><ConfidenceBadge level={r.confidence} hint={false} /></td>
                  <td className="pfie-num">{r.comparableCases}</td>
                  <td style={{ color: 'var(--muted)', whiteSpace: 'normal', minWidth: 260 }}>{r.capacityConsequence}</td>
                  <td>
                    <span className="pfie-badge plain">{r.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ marginTop: 14 }} className="pfie-row between">
        <Note tone="caution">
          A recommendation is only published where enough comparable completed dry periods exist. “Schedule only”
          shows the planned date without a recommendation.
        </Note>
        <DelProLink id="the dry-off schedule" />
      </div>
      <p className="sub" style={{ marginTop: 8 }}>Showing {rows.length} of {DRY_PLAN.length} animals · {fmtInt(DRY_PLAN.length)} within 150 days of dry-off.</p>
    </Card>
  );
}
