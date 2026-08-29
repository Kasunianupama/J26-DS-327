/**
 * Herd pictograms (§15).
 *
 * One glyph per animal, coloured by genetic group or by production state. The
 * counts come from re-classifying every animal against its own transition
 * dates, so the strip animates coherently as the timeline player runs.
 */

import { useMemo, useState } from 'react';
import {
  GROUP_COLOR,
  GROUP_ORDER,
  herdAt,
  longDate,
  type Animal,
  type GeneticGroup,
  type ProductionState,
} from '../../../data/component2';
import { useC2 } from '../state';
import { Card, Note, Segmented } from '../ui';

const PEN_CLASS: Record<ProductionState, string> = {
  Milking: 'milking',
  Dry: 'dry',
  Heifer: 'heifer',
  Calf: 'calf',
  'Male / bull': 'male',
};

const STATE_COLOR: Record<ProductionState, string> = {
  Milking: '#1f6b4a',
  Dry: '#8a9a94',
  Heifer: '#b8860b',
  Calf: '#6b5bd1',
  'Male / bull': '#5b7fa6',
};

/** One animal, drawn small. Kept as an inline SVG so it scales and prints. */
function Glyph({ color, title, i }: { color: string; title: string; i: number }) {
  return (
    <svg
      className="pfie-glyph"
      width="13"
      height="10"
      viewBox="0 0 20 15"
      aria-hidden
      style={{ animationDelay: `${Math.min(i, 60) * 5}ms` }}
    >
      <title>{title}</title>
      <path
        d="M3 4h11c1.6 0 3 1.2 3 2.8V9h-1.4v3.6h-1.6V9.6H6.8v3H5.2V9.4H3.6V12H2V6.6C2 5.2 2.6 4 3 4Z"
        fill={color}
      />
      <path d="M2.6 4.2 1 2.4l1.2-.9 1.6 2Z" fill={color} opacity=".75" />
    </svg>
  );
}

/** A single pen: header count plus one glyph per animal, capped for legibility. */
export function Pen({
  name,
  animals,
  state,
  colourBy,
  cap = 120,
  onPick,
}: {
  name: string;
  animals: Animal[];
  state: ProductionState;
  colourBy: 'group' | 'state';
  cap?: number;
  onPick?: (a: Animal) => void;
}) {
  const shown = animals.slice(0, cap);
  const rest = animals.length - shown.length;

  return (
    <div className={`pfie-pen ${PEN_CLASS[state]}`} style={{ flexGrow: Math.max(1, animals.length / 12) }}>
      <div className="hd">
        <span className="nm">{name}</span>
        <span className="ct">{animals.length}</span>
      </div>
      <div className="pfie-glyphs">
        {shown.map((a, i) => (
          <span
            key={a.id}
            onClick={onPick ? () => onPick(a) : undefined}
            style={{ cursor: onPick ? 'pointer' : 'default', lineHeight: 0 }}
          >
            <Glyph
              i={i}
              color={colourBy === 'group' ? GROUP_COLOR[a.geneticGroup] : STATE_COLOR[state]}
              title={`${a.id} · ${a.geneticGroup}`}
            />
          </span>
        ))}
        {rest > 0 && (
          <span style={{ fontSize: 10.5, color: 'var(--muted)', fontWeight: 700, marginLeft: 4 }}>+{rest}</span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

/** Compact strip that sits under the timeline player. */
export function HerdStrip() {
  const { selectedDate, openDrawer } = useC2();
  const snap = useMemo(() => herdAt(selectedDate), [selectedDate]);

  return (
    <div className="pfie-strip">
      {GROUP_ORDER.map((g) => (
        <Pen
          key={g}
          name={g}
          state={g}
          animals={snap.members[g]}
          colourBy="state"
          cap={g === 'Milking' ? 90 : 40}
          onPick={(a) => openDrawer({ kind: 'cow', animalId: a.id })}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */

export function HerdFlow() {
  const { selectedDate, openDrawer } = useC2();
  const [colourBy, setColourBy] = useState<'group' | 'state'>('group');
  const snap = useMemo(() => herdAt(selectedDate), [selectedDate]);

  const exitRows = [
    { label: 'Deaths', sub: 'mortality, all causes', n: snap.exits.deaths },
    { label: 'Sales', sub: 'cull and surplus stock', n: snap.exits.sales },
    { label: 'Transfers out', sub: 'to other NLDB farms', n: snap.exits.transfers },
  ];
  const maxExit = Math.max(...exitRows.map((r) => r.n), 1);

  return (
    <Card
      title="Group flow"
      sub={`Every animal in the herd on ${longDate(selectedDate)}, placed in its pen. Play the timeline to watch the composition move.`}
      actions={
        <Segmented
          label="Colour by"
          options={[{ id: 'group' as const, label: 'Genetic group' }, { id: 'state' as const, label: 'Production state' }]}
          value={colourBy}
          onChange={setColourBy}
        />
      }
    >
      {colourBy === 'group' && (
        <div className="pfie-legend" style={{ marginBottom: 14, marginTop: -4 }}>
          {snap.composition.map((c) => (
            <span key={c.group}>
              <i style={{ background: GROUP_COLOR[c.group as GeneticGroup], borderRadius: '50%' }} />
              {c.group} <b style={{ color: 'var(--ink-2)' }}>{c.share}%</b>
            </span>
          ))}
        </div>
      )}

      <div className="pfie-flowgrid">
        <div className="col">
          <Pen name="Calves" state="Calf" animals={snap.members.Calf} colourBy={colourBy} cap={48}
            onPick={(a) => openDrawer({ kind: 'cow', animalId: a.id })} />
          <Pen name="Heifers" state="Heifer" animals={snap.members.Heifer} colourBy={colourBy} cap={48}
            onPick={(a) => openDrawer({ kind: 'cow', animalId: a.id })} />
          <Pen name="Males & bulls" state="Male / bull" animals={snap.members['Male / bull']} colourBy={colourBy} cap={24}
            onPick={(a) => openDrawer({ kind: 'cow', animalId: a.id })} />
        </div>

        <div className="col">
          <Pen name="Milking" state="Milking" animals={snap.members.Milking} colourBy={colourBy} cap={200}
            onPick={(a) => openDrawer({ kind: 'cow', animalId: a.id })} />
          <Pen name="Dry" state="Dry" animals={snap.members.Dry} colourBy={colourBy} cap={80}
            onPick={(a) => openDrawer({ kind: 'cow', animalId: a.id })} />
        </div>

        <div className="col">
          <div className="pfie-pen exit" style={{ flexGrow: 1 }}>
            <div className="hd">
              <span className="nm" style={{ color: 'var(--concern)' }}>Left the herd</span>
              <span className="ct">{snap.exits.total}</span>
            </div>
            <div style={{ marginTop: 14 }}>
              {exitRows.map((r) => (
                <div className="pfie-exitrow" key={r.label}>
                  <div className="t">
                    <span className="lbl">{r.label}</span>
                    <span className="n">{r.n}</span>
                  </div>
                  <div className="sub">{r.sub}</div>
                  <div className="track"><i style={{ width: `${(r.n / maxExit) * 100}%` }} /></div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.5, marginTop: 10 }}>
              Cumulative since 1 January 2024. Every exit is reconciled against the herd count before it is
              displayed.
            </div>
          </div>

          <div className="pfie-pen pregnant">
            <div className="hd">
              <span className="nm">Pregnant (any pen)</span>
              <span className="ct">{snap.pregnant}</span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 6, lineHeight: 1.5 }}>
              Counted across the milking, dry and heifer pens — pregnancy is a reproductive state, not a pen.
            </div>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <Note>
          Each glyph is one animal. Pens resize as the herd moves, and a glyph opens that animal's predictive
          panel. Counts past today are modelled from each animal's own transition dates.
        </Note>
      </div>
    </Card>
  );
}
