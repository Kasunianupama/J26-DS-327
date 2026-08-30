/**
 * Capacity → Herd Profile & Genetics (§15, §16, §17).
 *
 * State matrix instead of a pie chart, genetic composition over time, a lineage
 * lens limited to two generations, and the 2D cow profile landscape.
 */

import { useMemo, useState, type CSSProperties } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import {
  COMPOSITION_SERIES,
  GENETICS_SUMMARY,
  GROUP_COLOR,
  HERD,
  HERD_STATE_SERIES,
  OVERLAY_OPTIONS,
  PROFILES,
  PROFILE_IDS,
  TODAY_ISO,
  buildProfileCurveSeries,
  byId,
  descendantsOf,
  fmtInt,
  profileSummary,
  stateMatrix,
  type Animal,
  type GeneticGroup,
  type ProfileId,
} from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, EmptyState, Note, Segmented, TipShell } from '../ui';
import { HerdFlow } from '../panels/HerdFlow';
import { ProfileHologram } from '../panels/ProfileHologram';

const PROD_STATES = ['Milking', 'Dry', 'Heifer', 'Calf', 'Male / bull'];
const REPRO_STATES = ['Voluntary wait', 'Eligible to breed', 'Bred — awaiting check', 'Pregnant', 'Repeat breeder', 'No service recorded', 'Not applicable'];

export function HerdGenetics() {
  return (
    <div className="pfie-stack">
      <HerdFlow />
      <StateMatrix />
      <div className="pfie-grid side">
        <GeneticComposition />
        <LineageLens />
      </div>
      <ProfileLandscape />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function StateMatrix() {
  const { openDrawer } = useC2();
  const [overlay, setOverlay] = useState<keyof typeof OVERLAY_OPTIONS>('None');
  const [overlayValue, setOverlayValue] = useState('All');
  const [cell, setCell] = useState<{ prod: string; repro: string } | null>({ prod: 'Milking', repro: 'Pregnant' });

  const cells = useMemo(
    () => stateMatrix(overlay as 'None', overlayValue),
    [overlay, overlayValue],
  );
  const find = (p: string, r: string) => cells.find((c) => c.prod === p && c.repro === r);
  const selected = cell ? find(cell.prod, cell.repro) : null;

  // Population band for the selected state, historical → forecast.
  const series = useMemo(
    () =>
      HERD_STATE_SERIES.map((h) => ({
        label: h.label,
        future: h.future,
        observed: h.future ? null : (h as unknown as Record<string, number>)[cell?.prod ?? 'Milking'],
        expected: h.future ? (h as unknown as Record<string, number>)[cell?.prod ?? 'Milking'] : null,
        band: h.future ? [h.lower, h.upper] : null,
        entries: h.entries,
        exits: -h.exits,
      })),
    [cell],
  );
  const todayLabel = HERD_STATE_SERIES.find((h) => h.future)?.label;

  return (
    <Card
      title="Herd state matrix"
      sub="Production state against reproductive state, with the expected 90-day change in each cell. Select a cell to drive the population band beneath."
      actions={
        <>
          <label className="pfie-field">
            Overlay
            <select
              value={overlay}
              onChange={(e) => { setOverlay(e.target.value as keyof typeof OVERLAY_OPTIONS); setOverlayValue('All'); }}
            >
              {Object.keys(OVERLAY_OPTIONS).map((k) => <option key={k}>{k}</option>)}
            </select>
          </label>
          {overlay !== 'None' && (
            <label className="pfie-field">
              Value
              <select value={overlayValue} onChange={(e) => setOverlayValue(e.target.value)}>
                {OVERLAY_OPTIONS[overlay].map((v) => <option key={v}>{v}</option>)}
              </select>
            </label>
          )}
        </>
      }
    >
      <div className="pfie-tablewrap">
        <table className="pfie-matrix">
          <thead>
            <tr>
              <th />
              {REPRO_STATES.map((r) => <th key={r} className="rot">{r}</th>)}
            </tr>
          </thead>
          <tbody>
            {PROD_STATES.map((p) => (
              <tr key={p}>
                <th>{p}</th>
                {REPRO_STATES.map((r) => {
                  const c = find(p, r);
                  if (!c) return <td key={r}><div className="void" /></td>;
                  const active = cell?.prod === p && cell?.repro === r;
                  return (
                    <td key={r}>
                      <button
                        aria-pressed={active}
                        onClick={() => setCell({ prod: p, repro: r })}
                        title={`${c.count} animals · expected 90-day change ${c.change > 0 ? '+' : ''}${c.change}`}
                      >
                        <span className="c">{c.count}</span>
                        <span className={`ch ${c.change > 0 ? 'up' : c.change < 0 ? 'down' : ''}`}>
                          {c.change === 0 ? '—' : `${c.change > 0 ? '▲ +' : '▼ '}${c.change}`}
                        </span>
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <>
          <div className="pfie-row between" style={{ marginTop: 20, marginBottom: 8 }}>
            <div>
              <div className="pfie-section-title" style={{ margin: 0 }}>
                Population band — {selected.prod} · {selected.repro}
              </div>
              <p className="sub">
                {selected.count} animals today, expected change {selected.change > 0 ? '+' : ''}{selected.change} over 90 days.
              </p>
            </div>
            <button
              className="pfie-btn"
              onClick={() => openDrawer({ kind: 'cohort', groupKey: 'State', value: `${selected.prod} · ${selected.repro}` })}
            >
              Open the {selected.count} animals →
            </button>
          </div>
          <ResponsiveContainer width="100%" height={190}>
            <ComposedChart data={series} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#eef2f0" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={{ stroke: '#e2e9e5' }} minTickGap={24} />
              <YAxis tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={false} width={40} />
              <Tooltip content={<StateTip state={selected.prod} />} />
              <Area dataKey="band" stroke="none" fill="#e4ecf3" isAnimationActive={false} name="Likely range" />
              <Line dataKey="observed" stroke="#1f6b4a" strokeWidth={2} dot={false} isAnimationActive={false} name="Recorded" />
              <Line dataKey="expected" stroke="#5b7fa6" strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} name="Expected" />
              {todayLabel && <ReferenceLine x={todayLabel} stroke="#1d2b26" strokeWidth={1.5} label={{ value: 'Today', position: 'insideTopLeft', fontSize: 10, fontWeight: 700 }} />}
            </ComposedChart>
          </ResponsiveContainer>
          <div className="pfie-legend">
            <span><i style={{ background: '#1f6b4a' }} />Recorded</span>
            <span><i className="dash" />Expected</span>
            <span><i style={{ background: '#e4ecf3' }} />Likely range</span>
          </div>
        </>
      )}
    </Card>
  );
}

function StateTip({ active, label, payload, state }: { active?: boolean; label?: string | number; payload?: { payload?: Record<string, number> }[]; state: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload ?? {};
  return (
    <TipShell
      title={`${state} — ${label}`}
      rows={[
        ['Head', String(p.observed ?? p.expected ?? '—')],
        ['Entry wave', `+${p.entries ?? 0}`],
        ['Exit wave', `${p.exits ?? 0}`],
      ]}
      note={p.expected != null ? 'Expected value with a likely range.' : 'Recorded head count.'}
    />
  );
}

/* ------------------------------------------------------------------ */

function GeneticComposition() {
  const todayLabel = COMPOSITION_SERIES.find((c) => c.future)?.label;
  const groups = Object.keys(GROUP_COLOR) as GeneticGroup[];

  return (
    <Card
      title="Genetic composition"
      sub="Recorded composition and the expected productive-herd mix as grading-up continues."
    >
      <ResponsiveContainer width="100%" height={210}>
        <ComposedChart data={COMPOSITION_SERIES} margin={{ top: 6, right: 8, left: 0, bottom: 0 }} stackOffset="expand">
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={{ stroke: '#e2e9e5' }} minTickGap={30} />
          <YAxis tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={false} width={38} tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`} />
          <Tooltip content={<CompTip />} />
          {groups.map((g) => (
            <Area key={g} dataKey={g} stackId="g" stroke={GROUP_COLOR[g]} fill={GROUP_COLOR[g]} fillOpacity={0.85} isAnimationActive={false} />
          ))}
          {todayLabel && <ReferenceLine x={todayLabel} stroke="#1d2b26" strokeWidth={1.5} />}
        </ComposedChart>
      </ResponsiveContainer>

      <div className="pfie-tablewrap" style={{ marginTop: 14 }}>
        <table className="pfie-table">
          <thead>
            <tr>
              <th>Group</th>
              <th className="pfie-num">Animals</th>
              <th className="pfie-num">Share</th>
              <th className="pfie-num">Avg peak</th>
              <th className="pfie-num">Persistence</th>
              <th className="pfie-num">Milk share</th>
              <th className="pfie-num">Services / conception</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {GENETICS_SUMMARY.map((g) => (
              <tr key={g.group}>
                <td>
                  <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: GROUP_COLOR[g.group as GeneticGroup], marginRight: 7 }} />
                  {g.group}
                </td>
                <td className="pfie-num">{g.animals}</td>
                <td className="pfie-num">{g.share}%</td>
                <td className="pfie-num">{g.avgPeak || '—'} L</td>
                <td className="pfie-num">{g.avgPersistence || '—'}%</td>
                <td className="pfie-num">{g.milkShare}%</td>
                <td className="pfie-num">{g.servicesPerConception ?? '—'}</td>
                <td><ConfidenceBadge level={g.confidence} hint={false} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {GENETICS_SUMMARY.some((g) => g.sampleNote) && (
        <div style={{ marginTop: 12 }}>
          <Note tone="caution">
            {GENETICS_SUMMARY.filter((g) => g.sampleNote).map((g) => `${g.group}: ${g.sampleNote}`).join(' ')}
          </Note>
        </div>
      )}
    </Card>
  );
}

function CompTip({ active, label, payload }: { active?: boolean; label?: string | number; payload?: { dataKey?: string | number; value?: number }[] }) {
  if (!active || !payload?.length) return null;
  return (
    <TipShell
      title={`Genetic mix — ${label}`}
      rows={payload.map((p) => [String(p.dataKey), `${p.value}%`] as [string, string])}
      note="Founder animals decline as their crossbred descendants enter the productive herd."
    />
  );
}

/* ------------------------------------------------------------------ */

function LineageLens() {
  const { openDrawer } = useC2();
  const [id, setId] = useState(HERD.find((a) => a.damId)?.id ?? HERD[0].id);
  const [expandGen2, setExpandGen2] = useState(false);
  const animal = byId(id);

  if (!animal) return null;
  const dam = animal.damId ? byId(animal.damId) : null;
  const granddam = dam?.damId ? byId(dam.damId) : null;
  const kids = descendantsOf(animal.id);

  const Node = ({ a, label, self }: { a: Animal | null | undefined; label: string; self?: boolean }) => (
    <span className={`node${self ? ' self' : ''}${!a ? ' unknown' : ''}`}>
      {a ? a.id : 'Unknown'}
      <span style={{ color: 'var(--faint)', fontWeight: 500 }}> · {label}</span>
    </span>
  );

  return (
    <Card
      title="Lineage lens"
      sub="Two ancestor generations and immediate descendants only. Dashed nodes are inferred or incomplete."
      actions={
        <label className="pfie-field">
          Animal
          <select value={id} onChange={(e) => { setId(e.target.value); setExpandGen2(false); }}>
            {HERD.filter((a) => a.damId).slice(0, 80).map((a) => <option key={a.id} value={a.id}>{a.id}</option>)}
          </select>
        </label>
      }
    >
      <div className="pfie-lineage">
        <div className="lbl">Generation 2</div>
        <div className="gen">
          {expandGen2 ? (
            <>
              <Node a={granddam} label="granddam" />
              <span className={`node${animal.sireCode ? ' inferred' : ' unknown'}`}>
                {dam?.sireCode ?? 'Unknown'} <span style={{ color: 'var(--faint)', fontWeight: 500 }}> · grandsire (inferred)</span>
              </span>
            </>
          ) : (
            <button className="pfie-btn ghost" onClick={() => setExpandGen2(true)}>Expand generation 2 →</button>
          )}
        </div>

        <div className="lbl">Generation 1</div>
        <div className="gen">
          <Node a={dam} label="dam" />
          <span className={`node${animal.sireCode ? '' : ' unknown'}`}>
            {animal.sireCode ?? 'Unknown'} <span style={{ color: 'var(--faint)', fontWeight: 500 }}> · sire</span>
          </span>
        </div>

        <div className="lbl">Selected</div>
        <div className="gen">
          <Node a={animal} label={animal.geneticGroup} self />
          <button className="pfie-btn ghost" onClick={() => openDrawer({ kind: 'cow', animalId: animal.id })}>
            Open predictive panel →
          </button>
        </div>

        <div className="lbl">Descendants ({kids.length})</div>
        <div className="gen">
          {kids.length === 0 ? (
            <span className="node unknown">None recorded</span>
          ) : (
            kids.slice(0, 6).map((k) => (
              <button
                key={k.id}
                className="node"
                style={{ cursor: 'pointer' }}
                onClick={() => setId(k.id)}
              >
                {k.id} <span style={{ color: 'var(--faint)', fontWeight: 500 }}>· {k.prodState}</span>
              </button>
            ))
          )}
          {kids.length > 6 && <span className="node unknown">+{kids.length - 6} more</span>}
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <Note>
          Breed composition propagates down the tree: {animal.breedComposition.jersey}% Jersey ·{' '}
          {animal.breedComposition.local}% local
          {animal.breedComposition.unknown > 0 ? ` · ${animal.breedComposition.unknown}% unknown` : ''}.
          {animal.geneticGroup === 'Unknown parentage' && ' Parentage is not recorded for this animal, so the composition is not derivable.'}
        </Note>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ */

const SHAPE_FOR: Record<string, 'circle' | 'square' | 'triangle' | 'diamond' | 'cross' | 'star' | 'wye'> = {
  Pregnant: 'circle',
  'Bred — awaiting check': 'square',
  'Repeat breeder': 'triangle',
  'No service recorded': 'cross',
  'Eligible to breed': 'diamond',
  'Voluntary wait': 'star',
  'Not applicable': 'wye',
};

function ProfileLandscape() {
  const { openDrawer } = useC2();
  const [overlay, setOverlay] = useState<'Profile' | 'Genetics'>('Profile');
  const [mode, setMode] = useState<'timelines' | 'similarity'>('timelines');
  const [hologramOpen, setHologramOpen] = useState(false);
  const [horizon, setHorizon] = useState<'90' | '180' | '305'>('305');
  const [selectedDay, setSelectedDay] = useState(120);
  const [focused, setFocused] = useState<ProfileId>('HP');
  const [visible, setVisible] = useState<Set<ProfileId>>(new Set(PROFILE_IDS));
  const horizonDays = Number(horizon);

  const curveSeries = useMemo(() => buildProfileCurveSeries(horizonDays), [horizonDays]);
  const summaries = useMemo(
    () => new Map(PROFILE_IDS.map((id) => [id, profileSummary(id, selectedDay)])),
    [selectedDay],
  );

  const points = useMemo(
    () =>
      HERD.filter((a) => visible.has(a.profile)).map((a) => ({
        x: a.landscape.x,
        y: a.landscape.y,
        z: Math.max(30, a.contribution90 / 6),
        a,
      })),
    [visible],
  );

  const grouped = useMemo(() => {
    const key = overlay === 'Profile' ? (p: typeof points[number]) => p.a.profile : (p: typeof points[number]) => p.a.geneticGroup;
    const map = new Map<string, typeof points>();
    for (const p of points) {
      const k = key(p);
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(p);
    }
    return [...map.entries()];
  }, [points, overlay]);

  const toggle = (profile: ProfileId) => {
    const next = new Set(visible);
    if (next.has(profile)) next.delete(profile); else next.add(profile);
    if (!next.size) return;
    setVisible(next);
    if (!next.has(focused)) setFocused([...next][0]);
  };

  return (
    <Card
      title="Profile performance through lactation"
      sub="Compare characteristic profiles using real farm quantities. The line is median milk per cow; the shaded range shows the middle 50% of adult cows in the selected profile."
      actions={
        <>
          <Segmented
            label="View"
            options={[
              { id: 'timelines' as const, label: 'Profile timelines' },
              { id: 'similarity' as const, label: 'Similarity model' },
            ]}
            value={mode}
            onChange={(value) => {
              setMode(value);
              if (value === 'similarity') setHologramOpen(false);
            }}
          />
          {mode === 'timelines' && (
            <>
              <Segmented
                label="Timeline"
                options={[{ id: '90' as const, label: '90 days' }, { id: '180' as const, label: '180 days' }, { id: '305' as const, label: 'Full lactation' }]}
                value={horizon}
                onChange={(value) => {
                  setHorizon(value);
                  setSelectedDay((day) => Math.min(day, Number(value)));
                }}
              />
              <button className="pfie-btn" aria-pressed={hologramOpen} onClick={() => setHologramOpen((open) => !open)}>
                {hologramOpen ? 'Hide profile hologram' : 'View profile hologram ↗'}
              </button>
            </>
          )}
          {mode === 'similarity' && (
            <Segmented
              label="Colour by"
              options={[{ id: 'Profile' as const, label: 'Profile' }, { id: 'Genetics' as const, label: 'Genetics' }]}
              value={overlay}
              onChange={setOverlay}
            />
          )}
        </>
      }
    >
      {mode === 'timelines' && (
        <>
          <label className="pfie-profile-day-control">
            <span>
              <b>Compare profiles at day {selectedDay} in milk</b>
              <small>The vertical guide and profile summaries move together</small>
            </span>
            <input type="range" min={1} max={horizonDays} value={selectedDay} onChange={(event) => setSelectedDay(Number(event.target.value))} />
          </label>

          <div className="pfie-profile-chart">
            <ResponsiveContainer width="100%" height={360}>
              <ComposedChart data={curveSeries} margin={{ top: 12, right: 18, left: 4, bottom: 10 }}>
                <CartesianGrid stroke="#eef2f0" vertical={false} />
                <XAxis
                  type="number"
                  dataKey="day"
                  domain={[1, horizonDays]}
                  tick={{ fontSize: 10, fill: '#70827a' }}
                  tickLine={false}
                  axisLine={{ stroke: '#d8e2dd' }}
                  label={{ value: 'Days in milk', position: 'insideBottom', offset: -5, fontSize: 10, fill: '#52665d' }}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#70827a' }}
                  tickLine={false}
                  axisLine={false}
                  width={52}
                  label={{ value: 'Milk (L/cow/day)', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#52665d' }}
                />
                <Tooltip content={<ProfileCurveTip visible={visible} />} />
                <Area
                  dataKey={`${focused}Band`}
                  stroke="none"
                  fill={PROFILES[focused].color}
                  fillOpacity={0.13}
                  isAnimationActive={false}
                  name={`${PROFILES[focused].short} typical range`}
                />
                {[...visible].map((profile) => (
                  <Line
                    key={profile}
                    dataKey={profile}
                    name={PROFILES[profile].name}
                    stroke={PROFILES[profile].color}
                    strokeWidth={focused === profile ? 3.2 : 2}
                    opacity={focused === profile ? 1 : 0.76}
                    dot={false}
                    isAnimationActive={false}
                  />
                ))}
                <ReferenceLine
                  x={selectedDay}
                  stroke="#1d2b26"
                  strokeDasharray="4 3"
                  label={{ value: `Day ${selectedDay}`, position: 'insideTopRight', fontSize: 10, fontWeight: 700 }}
                />
                {[...visible].map((profile) => (
                  <ReferenceDot
                    key={profile}
                    x={selectedDay}
                    y={summaries.get(profile)?.medianAtDay ?? 0}
                    r={focused === profile ? 5 : 3.5}
                    fill="#fff"
                    stroke={PROFILES[profile].color}
                    strokeWidth={2.5}
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {hologramOpen && (
            <ProfileHologram
              profile={focused}
              selectedDay={selectedDay}
              onSelectedDayChange={(day) => {
                setSelectedDay(day);
                if (day > horizonDays) setHorizon('305');
              }}
              onClose={() => setHologramOpen(false)}
            />
          )}
        </>
      )}

      {mode === 'similarity' && (
        <>
          <div className="pfie-landscape">
            <ResponsiveContainer width="100%" height={330}>
              <ScatterChart margin={{ top: 10, right: 14, left: 0, bottom: 8 }}>
                <CartesianGrid stroke="#eef2f0" />
                <XAxis type="number" dataKey="x" domain={[-4, 4]} tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={{ stroke: '#e2e9e5' }} label={{ value: 'Model production score (unitless) →', position: 'insideBottom', offset: -4, fontSize: 10, fill: '#70827a' }} />
                <YAxis type="number" dataKey="y" domain={[-3.5, 3.5]} tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={false} width={48} label={{ value: 'Model health / repro score (unitless) →', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#70827a' }} />
                <ZAxis type="number" dataKey="z" range={[24, 190]} />
                <Tooltip content={<CowTip />} cursor={{ strokeDasharray: '3 3' }} />
                {grouped.map(([key, groupPoints]) => (
                  <Scatter
                    key={key}
                    name={key}
                    data={groupPoints}
                    fill={overlay === 'Profile' ? PROFILES[key as ProfileId].color : GROUP_COLOR[key as GeneticGroup]}
                    fillOpacity={0.68}
                    shape={overlay === 'Profile' ? PROFILES[key as ProfileId].shape : 'circle'}
                    isAnimationActive={false}
                    onClick={(point: unknown) => {
                      const hit = point as { a?: Animal };
                      if (hit?.a) openDrawer({ kind: 'cow', animalId: hit.a.id });
                    }}
                    style={{ cursor: 'pointer' }}
                  />
                ))}
              </ScatterChart>
            </ResponsiveContainer>
            <span className="hint">{points.length} animals shown</span>
          </div>
          {overlay === 'Genetics' && (
            <div className="pfie-legend" style={{ marginTop: 10 }}>
              {(Object.keys(GROUP_COLOR) as GeneticGroup[]).map((group) => (
                <span key={group}><i style={{ background: GROUP_COLOR[group] }} />{group}</span>
              ))}
            </div>
          )}
          <div style={{ marginTop: 14 }}>
            <Note tone="caution">
              This advanced view shows model similarity, not litres or event counts. Zero is the herd centre;
              positive and negative positions are unitless model scores. Distance means overall similarity across
              production, reproduction, health and evidence variables. Marker size is expected 90-day milk contribution.
            </Note>
          </div>
        </>
      )}

      <div className="pfie-profile-filters" aria-label="Profiles shown">
        {PROFILE_IDS.map((profile) => (
          <div
            key={profile}
            className={focused === profile ? 'focused' : ''}
            style={{ '--profile-color': PROFILES[profile].color } as CSSProperties}
          >
            <button
              type="button"
              className="select"
              aria-pressed={focused === profile}
              onClick={() => {
                if (!visible.has(profile)) toggle(profile);
                setFocused(profile);
              }}
            >
              <i />
              <span>{PROFILES[profile].name}</span>
              <small>{HERD.filter((animal) => animal.profile === profile).length} animals</small>
            </button>
            <button
              type="button"
              className="toggle"
              aria-label={`${visible.has(profile) ? 'Hide' : 'Show'} ${PROFILES[profile].name}`}
              aria-pressed={visible.has(profile)}
              onClick={() => toggle(profile)}
            >{visible.has(profile) ? '−' : '+'}</button>
          </div>
        ))}
      </div>

      {mode !== 'similarity' && (
        <div className="pfie-profile-summaries">
          {[...visible].map((profile) => {
            const summary = summaries.get(profile)!;
            return (
              <article
                key={profile}
                className={focused === profile ? 'active' : ''}
                style={{ '--profile-color': PROFILES[profile].color } as CSSProperties}
                onClick={() => setFocused(profile)}
              >
                <span className="name">{PROFILES[profile].name}</span>
                <span className="milk">{summary.medianAtDay}<small> L/cow/day</small></span>
                <span className="range">Typical range {summary.lowerAtDay}–{summary.upperAtDay} L at day {selectedDay}</span>
                <span className="facts">
                  <span><b>{summary.medianPeak} L</b> median peak · day {summary.medianPeakDay}</span>
                  <span><b>{fmtInt(summary.median305)} L</b> median 305-day yield</span>
                  <span><b>{summary.meanHealthEvents}</b> health events · <b>{summary.meanAiAttempts}</b> AI attempts/cow</span>
                  <span>{summary.animals.length} adult cows support this curve</span>
                </span>
                <button
                  type="button"
                  className="open"
                  onClick={(event) => {
                    event.stopPropagation();
                    openDrawer({ kind: 'cohort', groupKey: 'Profile', value: PROFILES[profile].name });
                  }}
                >Open group →</button>
              </article>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function ProfileCurveTip({
  active,
  label,
  payload,
  visible,
}: {
  active?: boolean;
  label?: string | number;
  payload?: { payload?: Record<string, number | [number, number]> }[];
  visible: Set<ProfileId>;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const rows: [string, string][] = [...visible].map((profile) => [
    PROFILES[profile].short,
    `${row[profile]} L/day (${row[`${profile}Low`]}–${row[`${profile}High`]})`,
  ]);
  return <TipShell title={`Day ${label} in milk`} rows={rows} note="Median milk per cow; brackets show the middle 50%." />;
}

function CowTip({ active, payload }: { active?: boolean; payload?: { payload?: { a?: Animal } }[] }) {
  if (!active || !payload?.length) return null;
  const a = payload[0]?.payload?.a;
  if (!a) return null;
  return (
    <TipShell
      title={`${a.id} · ${PROFILES[a.profile].short}`}
      rows={[
        ['State', `${a.prodState} · ${a.reproState}`],
        ['Genetics', a.geneticGroup],
        ['Peak yield', `${a.peakYield} L/day`],
        ['Persistence', `${a.persistence}% of peak at 240 days`],
        ['90-day contribution', `${fmtInt(a.contribution90)} L`],
        ['Evidence', a.evidence],
      ]}
      note="Click for the predictive cow panel."
    />
  );
}

export { TODAY_ISO, EmptyState, SHAPE_FOR };
