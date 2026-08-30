/**
 * Capacity → Milk Supply (§10, §11).
 *
 * The contribution river decomposes expected milk into where it comes from, and
 * the waterfall reconciles any two dates on that river.
 */

import { useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  CONTRIBUTION_META,
  DEFINING_MOVEMENT,
  HORIZONS,
  fmtInt,
  layerSeries,
  longDate,
  milkWaterfall,
  type GroupingKey,
} from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, Note, Segmented, TipShell } from '../ui';

const GROUPINGS: { id: GroupingKey; label: string }[] = [
  { id: 'Contribution type', label: 'Contribution' },
  { id: 'Parity', label: 'Parity' },
  { id: 'Genetic group', label: 'Genetics' },
  { id: 'Operational group', label: 'Shed' },
  { id: 'Lactation stage', label: 'Stage' },
  { id: 'Prediction source', label: 'Evidence' },
];

const PALETTE = ['#1f6b4a', '#4d9070', '#87b8a0', '#5b7fa6', '#93aec9', '#b8860b', '#a44b3c', '#9aa8a2'];

export function MilkSupply() {
  const { horizon, selectedDate, setSelectedDate, compareDate, setCompareDate, openDrawer } = useC2();
  const [grouping, setGrouping] = useState<GroupingKey>('Contribution type');

  const days = HORIZONS.find((option) => option.id === horizon)?.days ?? 365;
  const { rows, keys } = useMemo(() => layerSeries(grouping, days), [grouping, days]);

  const rowAt = (iso: string) =>
    rows.find((r, i) => String(r.start) <= iso && (!rows[i + 1] || String(rows[i + 1].start) > iso));
  const selectedRow = rowAt(selectedDate);
  const compareRow = compareDate ? rowAt(compareDate) : null;

  const waterfall = useMemo(
    () => (compareDate ? milkWaterfall(selectedDate, compareDate) : []),
    [selectedDate, compareDate],
  );
  const maxAbs = Math.max(1, ...waterfall.filter((s) => s.kind !== 'anchor' && s.kind !== 'total').map((s) => Math.abs(s.value)));
  const maxTotal = Math.max(1, ...waterfall.filter((s) => s.kind === 'anchor' || s.kind === 'total').map((s) => Math.abs(s.value)));

  return (
    <div className="pfie-stack">
      <Card
        title="Milk contribution river"
        sub="Expected milk through time, decomposed by where it comes from. Click a layer to open the animals behind it."
        actions={
          <>
            <Segmented label="Group by" options={GROUPINGS} value={grouping} onChange={setGrouping} />
            <button className="pfie-btn" onClick={() => setCompareDate(compareDate ? null : DEFINING_MOVEMENT.windowEnd)}>
              {compareDate ? 'Clear second date' : 'Compare two dates'}
            </button>
          </>
        }
      >
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart
            data={rows}
            margin={{ top: 12, right: 8, left: 0, bottom: 0 }}
            onClick={(e) => {
              const r = rows.find((x) => x.label === String(e?.activeLabel));
              if (r) setSelectedDate(String(r.start));
            }}
          >
            <defs>
              <pattern id="pfieRiverA" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
                <rect width="6" height="6" fill="#5b7fa6" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="#ffffff" strokeWidth="2.2" opacity="0.8" />
              </pattern>
              <pattern id="pfieRiverB" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
                <rect width="6" height="6" fill="#93aec9" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="#ffffff" strokeWidth="2.6" opacity="0.9" />
              </pattern>
            </defs>
            <CartesianGrid stroke="#eef2f0" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={{ stroke: '#e2e9e5' }} minTickGap={24} />
            <YAxis tick={{ fontSize: 10, fill: '#93a29b' }} tickLine={false} axisLine={false} width={54} tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`} />
            <Tooltip content={<RiverTip grouping={grouping} groupCount={keys.length} />} />
            {keys.map((k, i) => {
              const meta = CONTRIBUTION_META[k as keyof typeof CONTRIBUTION_META];
              const colour = meta?.color ?? PALETTE[i % PALETTE.length];
              const fill = meta?.pattern
                ? k.includes('predicted') ? 'url(#pfieRiverB)' : 'url(#pfieRiverA)'
                : colour;
              return (
                <Area
                  key={k}
                  dataKey={k}
                  stackId="river"
                  name={k}
                  stroke={colour}
                  strokeWidth={1}
                  fill={fill}
                  fillOpacity={meta?.pattern ? 1 : 0.82}
                  isAnimationActive={false}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openDrawer({ kind: 'cohort', groupKey: grouping, value: k })}
                />
              );
            })}
            {selectedRow && (
              <ReferenceLine x={String(selectedRow.label)} stroke="#1d2b26" strokeWidth={2} strokeDasharray="4 3"
                label={{ value: 'A', position: 'top', fontSize: 11, fontWeight: 700, fill: '#1d2b26' }} />
            )}
            {compareRow && (
              <ReferenceLine x={String(compareRow.label)} stroke="#b8860b" strokeWidth={2} strokeDasharray="2 3"
                label={{ value: 'B', position: 'top', fontSize: 11, fontWeight: 700, fill: '#a8770a' }} />
            )}
          </AreaChart>
        </ResponsiveContainer>

        <div className="pfie-legend">
          {keys.map((k, i) => {
            const meta = CONTRIBUTION_META[k as keyof typeof CONTRIBUTION_META];
            const colour = meta?.color ?? PALETTE[i % PALETTE.length];
            return (
              <span key={k}>
                <i style={{ background: meta?.pattern ? `repeating-linear-gradient(45deg, ${colour} 0 2px, #fff 2px 4.5px)` : colour }} />
                {k}
              </span>
            );
          })}
        </div>
        <div style={{ marginTop: 12 }}>
          <Note>
            Solid fills come from animals already milking. Hatched fills depend on a calving that has not happened
            yet, so they carry the widest range.
          </Note>
        </div>
      </Card>

      <Card
        title="What changed between these dates?"
        sub={
          compareDate
            ? `${longDate(selectedDate)} → ${longDate(compareDate)}. The steps reconcile to the river.`
            : 'Pick a second date to reconcile the change between two points on the river.'
        }
        actions={compareDate ? <ConfidenceBadge level="Moderate" /> : undefined}
      >
        {!compareDate ? (
          <div className="pfie-empty">
            <b>No comparison selected</b>
            Use “Compare two dates”, then click the river to move point A. Point B defaults to the end of the
            October transition window.
          </div>
        ) : (
          <div className="pfie-wf">
            {waterfall.map((s) => {
              const isEdge = s.kind === 'anchor' || s.kind === 'total';
              const w = isEdge
                ? (Math.abs(s.value) / maxTotal) * 100
                : (Math.abs(s.value) / maxAbs) * 46;
              return (
                <div className={`step ${s.kind}`} key={s.label} title={s.detail}>
                  <span className="nm">{s.label}</span>
                  <span className="track">
                    <span
                      className={`fill ${s.kind}`}
                      style={
                        isEdge
                          ? { left: 0, width: `${w}%` }
                          : s.value >= 0
                            ? { left: '50%', width: `${w}%` }
                            : { right: '50%', width: `${w}%` }
                      }
                    />
                  </span>
                  <span className="v">
                    {isEdge ? '' : s.value > 0 ? '+' : ''}
                    {fmtInt(s.value)} L
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

function RiverTip({
  active, label, payload, grouping, groupCount,
}: {
  active?: boolean;
  label?: string | number;
  payload?: { dataKey?: string | number; value?: number }[];
  grouping: GroupingKey;
  groupCount: number;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + (p.value ?? 0), 0);
  const sorted = [...payload].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).filter((p) => (p.value ?? 0) > 0);
  const transition = payload
    .filter((p) => String(p.dataKey).includes('New entrants'))
    .reduce((s, p) => s + (p.value ?? 0), 0);

  return (
    <TipShell
      title={`Expected milk — ${label}`}
      rows={[
        ['Total', `${fmtInt(total)} L`],
        ...sorted.slice(0, 5).map(
          (p) => [String(p.dataKey), `${fmtInt(p.value ?? 0)} L · ${Math.round(((p.value ?? 0) / Math.max(1, total)) * 100)}%`] as [string, string],
        ),
      ]}
      note={
        grouping === 'Contribution type' && transition > 0
          ? `${Math.round((transition / Math.max(1, total)) * 100)}% of this estimate depends on cows that have not calved yet. Click a layer for the animals behind it.`
          : `Grouped by ${grouping.toLowerCase()} · ${groupCount} groups. Click a layer for the animals behind it.`
      }
    />
  );
}
