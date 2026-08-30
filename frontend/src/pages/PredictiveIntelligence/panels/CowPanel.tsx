/**
 * Individual predictive cow panel (§18).
 *
 * Not a cow record — DelPro owns that. This is the forward view: trajectory,
 * contribution, capacity effect, profile and the evidence behind the estimate.
 */

import { useMemo, useState } from 'react';
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  EVIDENCE_META,
  PROFILES,
  SENSITIVE_DISCLAIMER,
  byId,
  descendantsOf,
  fmtInt,
  longDate,
  woodsYield,
  type Animal,
} from '../../../data/component2';
import { useC2 } from '../state';
import { ConfidenceBadge, DelProLink, Drawer, EvidenceBadge, Meter, Note, Tabs, TipShell } from '../ui';

type Tab = 'outlook' | 'milk' | 'capacity' | 'profile' | 'evidence';

export function CowPanel({ animalId }: { animalId: string }) {
  const { closeDrawer, openDrawer } = useC2();
  const [tab, setTab] = useState<Tab>('outlook');
  const a = byId(animalId);

  if (!a) {
    return (
      <Drawer title="Animal not found" onClose={closeDrawer}>
        <div className="pfie-empty">
          <b>No record for {animalId}</b>
          This animal is not in the current herd snapshot.
        </div>
      </Drawer>
    );
  }

  const nextTransition =
    a.prodState === 'Milking' && a.dryOffDate
      ? `Dry-off around ${longDate(a.dryOffDate)}`
      : a.expectedCalving
        ? `Calving around ${longDate(a.expectedCalving)}`
        : a.predictedCalving
          ? `Possible calving around ${longDate(a.predictedCalving)}`
          : 'No transition expected in the horizon';

  return (
    <Drawer
      wide
      title={<>{a.id} <span style={{ color: 'var(--muted)', fontWeight: 500 }}>· {a.opGroup}</span></>}
      sub={
        <>
          {a.prodState} · {a.reproState} · {a.stage} · parity {a.parity || '—'} · {a.geneticGroup}
        </>
      }
      onClose={closeDrawer}
    >
      <div className="pfie-consequence" style={{ marginTop: 0, marginBottom: 18 }}>
        <div>
          <div className="k">Next expected transition</div>
          <div className="v" style={{ fontSize: 14 }}>{nextTransition}</div>
          <div className="d">{a.transitionConfirmed ? 'From a confirmed record' : 'Modelled, not yet confirmed'}</div>
        </div>
        <div>
          <div className="k">90-day milk contribution</div>
          <div className="v">{fmtInt(a.contribution90)} L</div>
          <div className="d">{a.currentYield > 0 ? `${a.currentYield} L/day today` : 'Not milking today'}</div>
        </div>
        <div>
          <div className="k">Evidence</div>
          <div className="v" style={{ fontSize: 14 }}><EvidenceBadge source={a.evidence} /></div>
          <div className="d"><ConfidenceBadge level={a.confidence} hint={false} /></div>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'outlook', label: 'Outlook' },
          { id: 'milk', label: 'Milk contribution' },
          { id: 'capacity', label: 'Capacity & reproduction' },
          { id: 'profile', label: 'Genetics / profile' },
          { id: 'evidence', label: 'Evidence' },
        ]}
      />

      {tab === 'outlook' && <Outlook a={a} />}
      {tab === 'milk' && <MilkTab a={a} />}
      {tab === 'capacity' && <CapacityTab a={a} />}
      {tab === 'profile' && <ProfileTab a={a} onOpen={(id) => openDrawer({ kind: 'cow', animalId: id })} />}
      {tab === 'evidence' && <EvidenceTab a={a} />}

      <div className="pfie-row between" style={{ marginTop: 22, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
        <span className="sub">Component 2 does not reproduce the DelPro record.</span>
        <DelProLink id={a.id} />
      </div>
    </Drawer>
  );
}

/* ------------------------------------------------------------------ */

function Outlook({ a }: { a: Animal }) {
  const data = useMemo(() => {
    const out: {
      dim: number;
      actual: number | null;
      forecast: number | null;
      lower: number | null;
      upper: number | null;
      peer: number;
      previous: number | null;
    }[] = [];
    const peerPeak = a.peakYield * 0.93;
    for (let d = 1; d <= 320; d += 4) {
      const y = woodsYield(a.woods, d);
      const past = d <= a.dim;
      const spread = y * (0.05 + Math.max(0, d - a.dim) / 900);
      out.push({
        dim: d,
        actual: past ? Number((y * (0.95 + ((d * 7919) % 100) / 1000)).toFixed(1)) : null,
        forecast: past ? null : Number(y.toFixed(1)),
        lower: past ? null : Number((y - spread).toFixed(1)),
        upper: past ? null : Number((y + spread).toFixed(1)),
        peer: Number((peerPeak * Math.pow(d, a.woods.b) * Math.exp(-a.woods.c * d) / Math.pow(a.peakDay, a.woods.b) / Math.exp(-a.woods.b) * 1).toFixed(1)),
        previous: a.previous305 ? Number((y * 0.9).toFixed(1)) : null,
      });
    }
    return out;
  }, [a]);

  const evidenceNote =
    a.evidence === 'Peer' || a.evidence === 'Herd'
      ? `Mainly based on similar cows. This cow has ${a.validLactationDays} valid current-lactation days${a.previous305 ? '' : ' and no completed previous lactation'}, so the estimate relies mainly on ${a.peerCount} comparable animals.`
      : a.evidence === 'Individual + peer'
        ? `Blends ${a.validLactationDays} valid current-lactation days with ${a.peerCount} comparable animals.`
        : `Built from this animal's own record: ${a.validLactationDays} valid current-lactation days${a.previous305 ? ` and a completed previous lactation of ${fmtInt(a.previous305)} L` : ''}.`;

  if (a.prodState !== 'Milking') {
    return (
      <>
        <div className="pfie-empty">
          <b>Not currently in lactation</b>
          {a.prodState === 'Dry'
            ? `In the dry period. The next curve begins at calving, expected around ${a.expectedCalving ? longDate(a.expectedCalving) : 'a date not yet set'}.`
            : `${a.prodState}. No lactation trajectory is published for this animal yet.`}
        </div>
        <div style={{ marginTop: 14 }}><Note tone="info">{evidenceNote}</Note></div>
      </>
    );
  }

  return (
    <>
      <div className="pfie-row between" style={{ marginBottom: 10 }}>
        <div className="pfie-section-title" style={{ margin: 0 }}>Lactation trajectory</div>
        <span className="pfie-row tight">
          <EvidenceBadge source={a.evidence} />
          <ConfidenceBadge level={a.confidence} />
        </span>
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 8, right: 10, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="dim" tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={{ stroke: '#e2e9e5' }}
            label={{ value: 'Days in milk', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#93a29b' }} />
          <YAxis tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={false} width={38} unit="L" />
          <Tooltip content={<CurveTip dim={a.dim} />} />
          <ReferenceArea x1={305} x2={320} fill="#9aa8a2" fillOpacity={0.14} label={{ value: 'Dry window', fontSize: 9, fill: '#6b7c75' }} />
          <Line dataKey="previous" stroke="#c4cfca" strokeWidth={1.2} dot={false} isAnimationActive={false} name="Previous lactation" />
          <Line dataKey="peer" stroke="#b8860b" strokeWidth={1.2} strokeDasharray="2 3" dot={false} isAnimationActive={false} name="Peer reference" />
          <Line dataKey="upper" stroke="#cfdde9" strokeWidth={1} dot={false} isAnimationActive={false} name="Upper" />
          <Line dataKey="lower" stroke="#cfdde9" strokeWidth={1} dot={false} isAnimationActive={false} name="Lower" />
          <Line dataKey="actual" stroke="#1f6b4a" strokeWidth={2.2} dot={false} isAnimationActive={false} name="Recorded" />
          <Line dataKey="forecast" stroke="#5b7fa6" strokeWidth={2.2} strokeDasharray="5 3" dot={false} isAnimationActive={false} name="Expected" />
          <ReferenceLine x={a.dim} stroke="#1d2b26" strokeWidth={1.5} label={{ value: 'Today', position: 'insideTopLeft', fontSize: 10, fontWeight: 700 }} />
          <ReferenceLine x={a.peakDay} stroke="#4d9070" strokeWidth={1} strokeDasharray="3 3" label={{ value: 'Peak', position: 'insideTopRight', fontSize: 9, fill: '#4d9070' }} />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="pfie-legend">
        <span><i style={{ background: '#1f6b4a' }} />Recorded</span>
        <span><i className="dash" />Expected</span>
        <span><i style={{ background: 'none', borderTop: '2px dashed #b8860b', height: 0 }} />Peer reference</span>
        <span><i style={{ background: '#c4cfca' }} />Previous lactation</span>
        <span><i style={{ background: 'rgba(154,168,162,.3)' }} />Dry window</span>
      </div>

      <div className="pfie-consequence" style={{ marginTop: 16 }}>
        <div><div className="k">Peak</div><div className="v">{a.peakYield} L</div><div className="d">around day {a.peakDay}{a.dim < a.peakDay ? ` · ${a.peakDay - a.dim} days away` : ' · already passed'}</div></div>
        <div><div className="k">Persistence</div><div className="v">{a.persistence}%</div><div className="d">of peak still held at 240 days</div></div>
        <div><div className="k">Projected 305-day</div><div className="v">{fmtInt(a.projected305)} L</div><div className="d">{a.previous305 ? `previous lactation ${fmtInt(a.previous305)} L` : 'no completed previous lactation'}</div></div>
      </div>

      <div style={{ marginTop: 14 }}><Note tone="info">{evidenceNote}</Note></div>
    </>
  );
}

function CurveTip({ active, label, payload, dim }: { active?: boolean; label?: string | number; payload?: { payload?: Record<string, number | null> }[]; dim: number }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload ?? {};
  const future = Number(label) > dim;
  return (
    <TipShell
      title={`Day ${label} in milk`}
      rows={[
        [future ? 'Expected' : 'Recorded', `${p.forecast ?? p.actual ?? '—'} L/day`],
        ...(future && p.lower != null ? ([['Likely range', `${p.lower}–${p.upper} L/day`]] as [string, string][]) : []),
        ['Peer reference', `${p.peer} L/day`],
      ]}
      note={future ? 'Forward estimate from this animal’s fitted curve.' : 'Recorded observation.'}
    />
  );
}

/* ------------------------------------------------------------------ */

function MilkTab({ a }: { a: Animal }) {
  const herdShare = 0.7; // indicative share of the herd's 90-day pool
  return (
    <>
      <div className="pfie-consequence" style={{ marginTop: 0 }}>
        <div><div className="k">Next 30 days</div><div className="v">{fmtInt(Math.round(a.contribution90 / 3))} L</div><div className="d">High confidence — already milking</div></div>
        <div><div className="k">Next 90 days</div><div className="v">{fmtInt(a.contribution90)} L</div><div className="d">Contribution type: {a.contributionType}</div></div>
        <div><div className="k">Remaining lactation</div><div className="v">{a.dim > 0 ? fmtInt(Math.max(0, a.projected305 - Math.round(a.projected305 * (a.dim / 305)))) : '—'} L</div><div className="d">To the 305-day mark</div></div>
      </div>
      <div style={{ marginTop: 18 }}>
        <div className="pfie-section-title" style={{ marginTop: 0 }}>Where this animal sits</div>
        <div className="pfie-row" style={{ gap: 10, marginBottom: 8 }}>
          <span style={{ width: 130, fontSize: 12, color: 'var(--muted)' }}>Peak vs herd</span>
          <span style={{ flex: 1 }}><Meter pct={(a.peakYield / 26) * 100} /></span>
          <span style={{ fontSize: 12, width: 60, textAlign: 'right' }}>{a.peakYield} L</span>
        </div>
        <div className="pfie-row" style={{ gap: 10, marginBottom: 8 }}>
          <span style={{ width: 130, fontSize: 12, color: 'var(--muted)' }}>Persistence</span>
          <span style={{ flex: 1 }}><Meter pct={a.persistence} /></span>
          <span style={{ fontSize: 12, width: 60, textAlign: 'right' }}>{a.persistence}%</span>
        </div>
        <div className="pfie-row" style={{ gap: 10 }}>
          <span style={{ width: 130, fontSize: 12, color: 'var(--muted)' }}>90-day contribution</span>
          <span style={{ flex: 1 }}><Meter pct={Math.min(100, (a.contribution90 / 1800) * 100)} tone="pred" /></span>
          <span style={{ fontSize: 12, width: 60, textAlign: 'right' }}>{fmtInt(a.contribution90)} L</span>
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <Note>
          This animal sits in the <b>{a.contributionType}</b> layer of the milk river. Removing it from the
          forecast would change the 90-day herd total by about {fmtInt(Math.round(a.contribution90 * herdShare))} L.
        </Note>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */

function CapacityTab({ a }: { a: Animal }) {
  return (
    <>
      <div className="pfie-consequence" style={{ marginTop: 0 }}>
        <div><div className="k">Reproductive state</div><div className="v" style={{ fontSize: 15 }}>{a.reproState}</div><div className="d">{a.aiAttempts} recorded services{a.daysSinceLastAI !== null ? ` · last ${a.daysSinceLastAI} days ago` : ''}</div></div>
        <div>
          <div className="k">Conception likelihood</div>
          <div className="v">{a.conceptionProb !== null ? `${Math.round(a.conceptionProb * 100)}%` : '—'}</div>
          <div className="d">
            {a.conceptionProb !== null
              ? `Similar-cow baseline ${Math.round(a.peerConceptionBaseline * 100)}% · event probability, not forecast confidence`
              : 'No live breeding decision for this animal'}
          </div>
        </div>
        <div>
          <div className="k">Effect on milking capacity</div>
          <div className="v" style={{ fontSize: 15 }}>
            {a.prodState === 'Milking' ? 'Leaves the herd' : 'Joins the herd'}
          </div>
          <div className="d">
            {a.prodState === 'Milking' && a.dryOffDate
              ? `Dry-off around ${longDate(a.dryOffDate)}, removing about ${Math.round(a.currentYield)} L/day`
              : a.expectedCalving
                ? `Calving around ${longDate(a.expectedCalving)}, adding a new curve peaking near ${a.peakYield} L/day`
                : 'No transition within the horizon'}
          </div>
        </div>
      </div>

      <div className="pfie-section-title">Service history</div>
      {a.aiEvents.length === 0 ? (
        <div className="pfie-empty"><b>No services recorded</b>Nothing has been entered for this animal in the current cycle.</div>
      ) : (
        <table className="pfie-table">
          <thead><tr><th>Date</th><th>Sire</th><th>Outcome</th></tr></thead>
          <tbody>
            {a.aiEvents.map((e, i) => (
              <tr key={i}><td>{longDate(e.date)}</td><td>{e.sire}</td><td>{e.outcome}</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {a.mortalityRisk90 && (
        <div style={{ marginTop: 18 }}>
          <Note tone="concern" title="Elevated mortality-related review priority.">
            Estimated likelihood over 90 days: {a.mortalityRisk90[0]}–{a.mortalityRisk90[1]}%. Similar-cow
            baseline: {a.mortalityBaseline}%. Confidence: Limited. {SENSITIVE_DISCLAIMER}
          </Note>
        </div>
      )}

      {a.flags.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="pfie-section-title" style={{ marginTop: 0 }}>Flags</div>
          <div className="pfie-stack" style={{ gap: 6 }}>
            {a.flags.map((f) => <div key={f} className="pfie-note caution">{f}</div>)}
          </div>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */

function ProfileTab({ a, onOpen }: { a: Animal; onOpen: (id: string) => void }) {
  const p = PROFILES[a.profile];
  const kids = descendantsOf(a.id);
  return (
    <>
      <div className="pfie-note" style={{ borderLeft: `3px solid ${p.color}` }}>
        <b>{p.name}</b>
        <div style={{ color: 'var(--muted)', marginTop: 4 }}>{p.blurb}</div>
      </div>

      <div className="pfie-section-title">Genetics</div>
      <table className="pfie-table">
        <tbody>
          <tr><td style={{ color: 'var(--muted)' }}>Group</td><td><b>{a.geneticGroup}</b></td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Breed composition</td><td>{a.breedComposition.jersey}% Jersey · {a.breedComposition.local}% local{a.breedComposition.unknown ? ` · ${a.breedComposition.unknown}% unknown` : ''}</td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Dam</td><td>{a.damId ?? <span style={{ color: 'var(--faint)' }}>Not recorded</span>}</td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Sire</td><td>{a.sireCode ?? <span style={{ color: 'var(--faint)' }}>Not recorded</span>}</td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Descendants</td><td>
            {kids.length === 0 ? <span style={{ color: 'var(--faint)' }}>None recorded</span> :
              kids.map((k) => (
                <button key={k.id} className="pfie-btn ghost" onClick={() => onOpen(k.id)}>{k.id}</button>
              ))}
          </td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Age</td><td>{Math.floor(a.ageMonths / 12)}y {a.ageMonths % 12}m</td></tr>
        </tbody>
      </table>

      {a.geneticGroup === 'Unknown parentage' && (
        <div style={{ marginTop: 14 }}>
          <Note tone="caution">
            Parentage is not recorded, so breed composition cannot be derived. This animal is excluded from
            genetic-group comparisons.
          </Note>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */

function EvidenceTab({ a }: { a: Animal }) {
  const indShare = a.evidence === 'Individual' ? 86 : a.evidence === 'Individual + peer' ? 58 : a.evidence === 'Peer' ? 22 : 6;
  return (
    <>
      <div className="pfie-row tight" style={{ marginBottom: 14 }}>
        <EvidenceBadge source={a.evidence} />
        <ConfidenceBadge level={a.confidence} />
      </div>
      <p className="sub">{EVIDENCE_META[a.evidence].blurb}</p>

      <div className="pfie-section-title">Where the estimate comes from</div>
      <div className="pfie-row" style={{ gap: 10, marginBottom: 8 }}>
        <span style={{ width: 150, fontSize: 12, color: 'var(--muted)' }}>Individual history</span>
        <span style={{ flex: 1 }}><Meter pct={indShare} /></span>
        <span style={{ fontSize: 12, width: 42, textAlign: 'right' }}>{indShare}%</span>
      </div>
      <div className="pfie-row" style={{ gap: 10, marginBottom: 8 }}>
        <span style={{ width: 150, fontSize: 12, color: 'var(--muted)' }}>Comparable animals</span>
        <span style={{ flex: 1 }}><Meter pct={100 - indShare} tone="pred" /></span>
        <span style={{ fontSize: 12, width: 42, textAlign: 'right' }}>{100 - indShare}%</span>
      </div>

      <table className="pfie-table" style={{ marginTop: 14 }}>
        <tbody>
          <tr><td style={{ color: 'var(--muted)' }}>Valid current-lactation days</td><td><b>{a.validLactationDays}</b></td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Completed previous lactation</td><td>{a.previous305 ? `${fmtInt(a.previous305)} L` : 'None on record'}</td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Comparable animals used</td><td>{a.peerCount}</td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Health events this lactation</td><td>{a.healthEvents.length}</td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Somatic cell count</td><td>{a.scc}k</td></tr>
          <tr><td style={{ color: 'var(--muted)' }}>Transition dependency</td><td>{a.transitionConfirmed ? 'Confirmed record' : 'Depends on an unconfirmed transition'}</td></tr>
        </tbody>
      </table>

      <div style={{ marginTop: 14 }}>
        <Note>
          Individual feed intake is not recorded anywhere on this farm — rations are group-level only — so no
          nutrition response is modelled for this animal.
        </Note>
      </div>
    </>
  );
}
