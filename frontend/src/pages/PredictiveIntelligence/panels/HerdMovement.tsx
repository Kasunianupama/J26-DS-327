/**
 * Component 1 (PFOI): animated herd movement for one period, as circles.
 *
 * Each herd group is a circle sized by its head count, with the animals that
 * came in (+) and went out (−) during the period. Every route between groups
 * is always drawn with its arrow; it turns active (coloured, flowing) when
 * animals took it:
 *
 *   born → calves → heifers ──first calving──▶ milking ⇄ dry
 *             └─▶ bulls & other                (dry-off / calving again)
 *
 * Arrivals enter a circle through a short stub at its top-left; deaths and
 * culls / sales leave through a stub at its bottom-right. Pregnancies lost do
 * not move an animal: they show as a red badge on the group. When the period
 * changes (step, play or a picked date) dots walk each active route once.
 *
 * Three layouts, picked from the panel's own width so the diagram fills it:
 * wide (one row), medium (two rows) and tall (phones). Moves come from `run.moves`; where a move's group is not recorded
 * (group "herd") it is shown at the herd's edge, and no total is split here.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  SERIES_META,
  fmt1,
  fmtInt,
  fmtSigned,
  type MoveGroup,
  type MoveRow,
  type SeriesId,
  type TimelinePoint,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun } from '../source';
import { Card } from '../ui';
import { TimelinePlayer } from './TimelinePlayer';
import { useTimelinePoints } from './MasterTimeline';

type Pt = [number, number];
type Pen = 'calves' | 'heifers' | 'milking' | 'dry' | 'other';
type Move = { from: MoveGroup; to: MoveGroup; value: number };
type Layout = {
  w: number;
  h: number;
  herd: { x: number; y: number; w: number; h: number };
  at: Record<Pen, Pt>;
  born: Pt;
  /** perpendicular bend of the two milking ⇄ dry routes */
  loop: number;
  /** groups whose name sits beside the circle because a route runs below it */
  sideLabel?: Partial<Record<Pen, 'left' | 'right'>>;
  /** names above the circles, leaving the space below for the flows out */
  labelAbove?: boolean;
  /** where animals end up: died and culled / sold outside the herd, pregnancies lost inside */
  sinks: Record<Sink, Pt>;
  /** a lane the exit flows of these groups run down, clear of the circles below them */
  lane?: { x: number; pens: Pen[] };
};
type Sink = 'died' | 'culled_sold' | 'lost';

/* One row, for wide panels: the life cycle reads left to right. */
const WIDE: Layout = {
  w: 1000,
  h: 410,
  herd: { x: 76, y: 12, w: 912, h: 290 },
  at: { calves: [210, 130], heifers: [420, 130], milking: [635, 130], dry: [885, 130], other: [125, 245] },
  born: [36, 130],
  loop: 36,
  labelAbove: true,
  sideLabel: { other: 'right' },
  sinks: { died: [520, 362], culled_sold: [730, 362], lost: [770, 262] },
};
/* Two rows, for medium panels (tablets, narrow desktop columns). */
const MEDIUM: Layout = {
  w: 640,
  h: 470,
  herd: { x: 62, y: 14, w: 566, h: 340 },
  at: { calves: [150, 110], heifers: [320, 110], milking: [470, 110], dry: [470, 272], other: [150, 272] },
  born: [28, 110],
  loop: 32,
  labelAbove: true,
  sideLabel: { milking: 'right', dry: 'right', other: 'left' },
  sinks: { died: [250, 420], culled_sold: [430, 420], lost: [330, 255] },
};
const TALL: Layout = {
  w: 360,
  h: 640,
  herd: { x: 12, y: 54, w: 336, h: 476 },
  at: { calves: [132, 140], heifers: [132, 290], milking: [132, 440], dry: [268, 372], other: [282, 140] },
  born: [132, 22],
  loop: 26,
  sideLabel: { calves: 'left', heifers: 'left', milking: 'left' },
  sinks: { died: [120, 590], culled_sold: [250, 590], lost: [282, 262] },
  lane: { x: 214, pens: ['calves', 'heifers'] },
};

const GROUP: Record<Pen, { series: SeriesId; label: string }> = {
  calves: { series: 'calves', label: 'Calves' },
  heifers: { series: 'heifers', label: 'Heifers' },
  milking: { series: 'milking', label: 'Milking cows' },
  dry: { series: 'dry', label: 'Dry cows' },
  other: { series: 'other', label: 'Bulls & other' },
};
const PENS: Pen[] = ['calves', 'heifers', 'milking', 'dry', 'other'];

type Link = { key: string; from: Pen | 'born'; to: Pen; label?: string; color: string; bend?: number; match: (m: Move) => boolean };
const LINKS: Link[] = [
  { key: 'born', from: 'born', to: 'calves', color: '#93aec9', match: (m) => m.from === 'born' },
  { key: 'grow', from: 'calves', to: 'heifers', label: 'grow into heifers', color: SERIES_META.heifers.color, match: (m) => m.from === 'calves' && m.to === 'heifers' },
  { key: 'first', from: 'heifers', to: 'milking', label: 'first calving', color: SERIES_META.calvings.color, match: (m) => m.from === 'heifers' && m.to === 'milking' },
  { key: 'dryoff', from: 'milking', to: 'dry', label: 'dry-off', color: SERIES_META.dry_offs.color, bend: 1, match: (m) => m.from === 'milking' && m.to === 'dry' },
  { key: 'again', from: 'dry', to: 'milking', label: 'calving again', color: SERIES_META.calvings.color, bend: 1, match: (m) => m.from === 'dry' && m.to === 'milking' },
  { key: 'bull', from: 'calves', to: 'other', label: 'become bulls', color: SERIES_META.other.color, match: (m) => m.from === 'calves' && m.to === 'other' },
];
const IN_COLOR = SERIES_META.entries.color;
const DIED_COLOR = SERIES_META.deaths.color;
const CULL_COLOR = SERIES_META.culls_sales.color;
const LOST_COLOR = SERIES_META.abortions.color;
const SINK_R = 18;
const SINK: Record<Sink, { label: string; icon: string; color: string; from: Pen[] }> = {
  died: { label: 'Died', icon: '✝', color: DIED_COLOR, from: ['calves', 'heifers', 'milking', 'dry', 'other'] },
  culled_sold: { label: 'Culled / sold', icon: '⇥', color: CULL_COLOR, from: ['calves', 'heifers', 'milking', 'dry', 'other'] },
  /* only pregnant animals lose a pregnancy: heifers in calf, milking cows and dry cows */
  lost: { label: 'Pregnancies lost', icon: '●', color: LOST_COLOR, from: ['heifers', 'milking', 'dry'] },
};

const DURATION = 1500;
const MAX_DOTS = 14;
const NICE = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500];

const valueAt = (p: TimelinePoint | undefined, s: string) => {
  if (!p) return null;
  const v = p.future ? p[`${s}_f`] : p[s];
  return typeof v === 'number' ? v : null;
};
const quad = (a: Pt, c: Pt, b: Pt, u: number): Pt => [
  (1 - u) ** 2 * a[0] + 2 * (1 - u) * u * c[0] + u ** 2 * b[0],
  (1 - u) ** 2 * a[1] + 2 * (1 - u) * u * c[1] + u ** 2 * b[1],
];
const toward = (c: Pt, r: number, to: Pt, pad = 3): Pt => {
  const dx = to[0] - c[0];
  const dy = to[1] - c[1];
  const len = Math.hypot(dx, dy) || 1;
  return [c[0] + (dx / len) * (r + pad), c[1] + (dy / len) * (r + pad)];
};
const quantile = (xs: number[], k: number) => {
  const s = xs.filter((x) => x > 0).sort((a, b) => a - b);
  return s.length ? s[Math.min(s.length - 1, Math.floor(k * (s.length - 1)))] : 1;
};

/** A route: quadratic (a, c, b) or, with c2, cubic (a, c, c2, b). */
type Path = { key: string; a: Pt; c: Pt; c2?: Pt; b: Pt; color: string; v: number; label?: string; labelAt?: Pt; anchor?: 'start' | 'middle' | 'end'; fade?: 'in' | 'out'; title?: string };
const cubic = (a: Pt, c1: Pt, c2: Pt, b: Pt, u: number): Pt => {
  const v = 1 - u;
  return [
    v * v * v * a[0] + 3 * v * v * u * c1[0] + 3 * v * u * u * c2[0] + u * u * u * b[0],
    v * v * v * a[1] + 3 * v * v * u * c1[1] + 3 * v * u * u * c2[1] + u * u * u * b[1],
  ];
};
const pointOn = (x: Path, u: number): Pt => (x.c2 ? cubic(x.a, x.c, x.c2, x.b, u) : quad(x.a, x.c, x.b, u));

export function HerdMovement() {
  const { grain, selectedPeriod } = usePfoi();
  const run = useRun();
  const points = useTimelinePoints();
  const lastRecorded = [...points].reverse().find((p) => !p.future && typeof p.milking === 'number');
  const idx = Math.max(0, points.findIndex((p) => p.period === (selectedPeriod ?? lastRecorded?.period)));
  const p = points[idx];
  const prev = idx > 0 ? points[idx - 1] : undefined;

  /* Layout from the panel's own width, so it also works inside narrow columns. */
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<'wide' | 'medium' | 'tall'>('wide');
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([e]) => {
      const w = e.contentRect.width;
      setSize(w >= 860 ? 'wide' : w >= 520 ? 'medium' : 'tall');
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const L = size === 'wide' ? WIDE : size === 'medium' ? MEDIUM : TALL;

  const movesIndex = useMemo(() => {
    const m = new Map<string, MoveRow[]>();
    (run.moves ?? []).forEach((r) => {
      const k = `${r.grain}|${r.period}|${r.forecast ? 'f' : 'a'}`;
      const list = m.get(k);
      if (list) list.push(r); else m.set(k, [r]);
    });
    return m;
  }, [run.moves]);
  const byGroup = p ? movesIndex.get(`${grain}|${p.period}|${p.future ? 'f' : 'a'}`) : undefined;
  const split = Boolean(byGroup?.length);
  const moves: Move[] = useMemo(() => {
    if (byGroup?.length) return byGroup.map((r) => ({ from: r.from, to: r.to, value: r.value }));
    /* Totals only: no split is invented. */
    const v = (s: SeriesId) => valueAt(p, s) ?? 0;
    return [
      { from: 'milking', to: 'dry', value: v('dry_offs') },
      { from: 'herd', to: 'died', value: v('deaths') },
      { from: 'herd', to: 'culled_sold', value: v('culls_sales') },
      { from: 'arrived', to: 'herd', value: v('entries') },
      { from: 'herd', to: 'lost_pregnancy', value: v('abortions') },
    ];
  }, [byGroup, p]);
  const total = (pred: (m: Move) => boolean) => moves.filter(pred).reduce((s, m) => s + m.value, 0);

  const hasOther = useMemo(() => points.some((x) => (valueAt(x, 'other') ?? 0) > 0), [points]);
  const pens = PENS.filter((g) => hasOther || g !== 'other');
  const links = LINKS.filter((l) => hasOther || l.to !== 'other');

  const stockRef = useMemo(
    () => quantile(points.flatMap((x) => (['calves', 'heifers', 'milking', 'dry'] as SeriesId[]).map((s) => valueAt(x, s) ?? 0)), 0.98),
    [points],
  );
  const flowRef = useMemo(
    () => quantile((run.moves ?? []).filter((r) => r.grain === grain && r.to !== 'lost_pregnancy').map((r) => r.value)
      .concat(points.flatMap((x) => (['calvings', 'dry_offs'] as SeriesId[]).map((s) => valueAt(x, s) ?? 0))), 0.95),
    [run.moves, points, grain],
  );
  const radius = (g: Pen) => 16 + 22 * Math.sqrt(Math.min(1.3, (valueAt(p, GROUP[g].series) ?? 0) / stockRef));
  const width = (v: number) => 2 + 7 * Math.sqrt(Math.min(1.5, v / flowRef));

  /* Geometry of every path for this layout and these circle sizes. */
  const paths: Path[] = [];
  links.forEach((l) => {
    const A = l.from === 'born' ? L.born : L.at[l.from];
    const B = L.at[l.to];
    const mid: Pt = [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2];
    const dx = B[0] - A[0];
    const dy = B[1] - A[1];
    const len = Math.hypot(dx, dy) || 1;
    const n: Pt = [-dy / len, dx / len];
    const k = (l.bend ?? 0) * L.loop;
    const c: Pt = [mid[0] + n[0] * k, mid[1] + n[1] * k];
    const a = l.from === 'born' ? toward(A, 16, c, 0) : toward(A, radius(l.from), c);
    const b = toward(B, radius(l.to), c, 6);
    const vertical = Math.abs(dy) > Math.abs(dx);
    const lp: Pt = l.bend ? [mid[0] + n[0] * k * 1.3, mid[1] + n[1] * k * 1.3 + 3] : vertical ? [mid[0] + (dx < 0 ? -8 : 8), mid[1] + 3] : [mid[0], mid[1] + 13];
    const anchor: 'start' | 'middle' | 'end' = l.bend
      ? (n[0] * k > 0.1 ? 'start' : n[0] * k < -0.1 ? 'end' : 'middle')
      : vertical ? (dx < 0 ? 'end' : 'start') : 'middle';
    /* in the tall layout the "calving again" label would sit under "first calving": put it above the dry cows */
    const tallAgain = L === TALL && l.key === 'again';
    paths.push({
      key: l.key, a, c, b, color: l.color, v: total(l.match), label: l.label,
      labelAt: tallAgain ? [L.at.dry[0] - 12, L.at.dry[1] - radius('dry') - 10] : lp,
      anchor: tallAgain ? 'start' : anchor,
    });
  });
  pens.forEach((g) => {
    const C = L.at[g];
    const r = radius(g);
    const inDir: Pt = [C[0] - 1, C[1] - 1];
    const inEnd = toward(C, r, inDir, 4);
    const inStart = toward(C, r + 24, inDir, 0);
    const midOf = (a: Pt, b: Pt): Pt => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    paths.push({ key: `in-${g}`, a: inStart, c: midOf(inStart, inEnd), b: inEnd, color: IN_COLOR, v: total((m) => m.from === 'arrived' && m.to === g), fade: 'in' });
    (Object.keys(SINK) as Sink[]).filter((k) => SINK[k].from.includes(g)).forEach((k) => {
      const S = L.sinks[k];
      const to = k === 'lost' ? 'lost_pregnancy' : k;
      const v = total((m) => m.from === g && m.to === to);
      const inLane = L.lane?.pens.includes(g);
      /* leave the circle on the side facing the sink (or the lane), then curve into the sink */
      const a = inLane ? toward(C, r, [L.lane!.x, C[1] + r], 2) : toward(C, r, S, 2);
      const dy = S[1] - a[1];
      const c1: Pt = inLane ? [L.lane!.x, a[1] + 40] : [a[0], a[1] + dy * 0.45];
      const c2: Pt = inLane ? [L.lane!.x, S[1] - 60] : [S[0], S[1] - dy * 0.45];
      const b = toward(S, SINK_R, c2, 5);
      paths.push({ key: `${k}-${g}`, a, c: c1, c2, b, color: SINK[k].color, v, title: `${GROUP[g].label} → ${SINK[k].label.toLowerCase()}: ${fmt1(v)}` });
    });
  });
  const herdIn = total((m) => m.from === 'arrived' && m.to === 'herd');
  const herdDied = total((m) => m.from === 'herd' && m.to === 'died');
  const herdCulled = total((m) => m.from === 'herd' && m.to === 'culled_sold');
  const hx = L.herd.x + L.herd.w / 2;
  const hb = L.herd.y + L.herd.h;
  if (herdIn >= 0.05) paths.push({ key: 'in-herd', a: [hx, L.herd.y - 18], c: [hx, L.herd.y - 8], b: [hx, L.herd.y + 4], color: IN_COLOR, v: herdIn, fade: 'in' });
  (['died', 'culled_sold'] as const).forEach((k) => {
    const v = k === 'died' ? herdDied : herdCulled;
    if (v < 0.05) return;
    const S = L.sinks[k];
    const a: Pt = [S[0], hb];
    const b = toward(S, SINK_R, a, 5);
    paths.push({ key: `${k}-herd`, a, c: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], b, color: SINK[k].color, v, title: `Group not recorded → ${SINK[k].label.toLowerCase()}: ${fmt1(v)}` });
  });

  const active = paths.filter((x) => x.v >= 0.05);
  const biggest = Math.max(0, ...active.map((x) => x.v));
  const perDot = NICE.find((n) => biggest / n <= MAX_DOTS) ?? NICE[NICE.length - 1];

  /* Dots walk once each time the period changes, then stop. */
  const [t, setT] = useState(1);
  const raf = useRef<number>();
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setT(1); return; }
    const start = performance.now();
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / DURATION);
      setT(k);
      if (k < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    const settle = window.setTimeout(() => setT(1), DURATION + 80);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); window.clearTimeout(settle); };
  }, [p?.period, grain]);

  const arrow = (x: Path, on: boolean) => {
    const back = pointOn(x, 0.9);
    const ang = (Math.atan2(x.b[1] - back[1], x.b[0] - back[0]) * 180) / Math.PI;
    return <path key={`h-${x.key}`} d="M0 0 L-7 -3.5 L-7 3.5 Z" transform={`translate(${x.b[0]} ${x.b[1]}) rotate(${ang})`} className={`arrow${on ? ' on' : ''}`} style={on ? { fill: x.color } : undefined} />;
  };
  const d = (x: Path) => x.c2
    ? `M${x.a[0]} ${x.a[1]} C${x.c[0]} ${x.c[1]} ${x.c2[0]} ${x.c2[1]} ${x.b[0]} ${x.b[1]}`
    : `M${x.a[0]} ${x.a[1]} Q${x.c[0]} ${x.c[1]} ${x.b[0]} ${x.b[1]}`;

  const calvingsTotal = valueAt(p, 'calvings');
  const notForecast = p?.future && valueAt(p, 'milking') === null;
  const totals: [string, number, string, string][] = [
    ['born', total((m) => m.from === 'born'), '●', '#93aec9'],
    ['arrived', total((m) => m.from === 'arrived'), '↘', IN_COLOR],
    ['died', total((m) => m.to === 'died'), '✝', DIED_COLOR],
    ['culled / sold', total((m) => m.to === 'culled_sold'), '⇥', CULL_COLOR],
    ['pregnancies lost', total((m) => m.to === 'lost_pregnancy'), '●', LOST_COLOR],
  ];

  return (
    <Card
      icon="herd"
      title="Herd movement"
      sub={`Head in each group and how many came in (+) and went out (−) during the ${grain}. Play, step or pick a date.`}
    >
      <TimelinePlayer points={points} />
      <div className={`pfie-move ${size}`} ref={box}>
        <svg viewBox={`0 0 ${L.w} ${L.h}`} role="img" aria-label={`Herd movement in ${p?.label ?? 'the selected period'}`}>
          <rect x={L.herd.x} y={L.herd.y} width={L.herd.w} height={L.herd.h} rx="20" className="boundary" />
          <text x={L.herd.x + L.herd.w - 12} y={L.herd.y + 17} className="period-label" textAnchor="end">
            {p?.label ?? ''}{p?.future ? ' · forecast' : ''}
          </text>
          {!split && calvingsTotal !== null && calvingsTotal > 0.05 && (
            <text x={L.herd.x + 12} y={L.herd.y + 17} className="calv-note">+{fmt1(calvingsTotal)} calvings (not split by group)</text>
          )}

          <g className="born">
            <circle cx={L.born[0]} cy={L.born[1]} r="16" />
            <text x={L.born[0]} y={L.born[1] + 1} className="v">{fmtInt(total((m) => m.from === 'born'))}</text>
            <text x={L.born[0]} y={L.born[1] + 9} className="l">born</text>
          </g>

          {paths.map((x) => <path key={`t-${x.key}`} d={d(x)} className={`track${x.title ? ' exit' : ''}`} />)}
          {active.map((x) => (
            <g key={`a-${x.key}`}>
              <path d={d(x)} className="ribbon" style={{ stroke: x.color, strokeWidth: width(x.v) }}>{x.title && <title>{x.title}</title>}</path>
              <path d={d(x)} className="current" style={{ strokeWidth: Math.max(1, width(x.v) / 3.5) }} />
            </g>
          ))}
          {paths.map((x) => arrow(x, x.v >= 0.05))}

          {pens.map((g) => {
            const [cx, cy] = L.at[g];
            const r = radius(g);
            const v = valueAt(p, GROUP[g].series);
            const before = valueAt(prev, GROUP[g].series);
            const delta = v !== null && before !== null ? Math.round(v - before) : null;
            const into = total((m) => m.to === g);
            const out = total((m) => m.from === g && m.to !== 'lost_pregnancy');
            const arrived = total((m) => m.from === 'arrived' && m.to === g);
            const side = L.sideLabel?.[g];
            const above = !side && L.labelAbove;
            const sx = side === 'right' ? cx + r + 8 : side === 'left' ? cx - r - 8 : cx;
            const anchor = side === 'right' ? 'start' : side === 'left' ? 'end' : 'middle';
            return (
              <g key={g} className={`node${into + out >= 0.05 ? ' busy' : ''}`} style={{ ['--c' as string]: SERIES_META[GROUP[g].series].color }}>
                {delta !== null && delta !== 0 && <circle key={`halo-${p?.period}`} cx={cx} cy={cy} r={r} className={`halo ${delta > 0 ? 'up' : 'down'}`} />}
                <circle cx={cx} cy={cy} r={r} className="disc" />
                <text x={cx} y={cy + 5} className="count">{v !== null ? fmtInt(v) : '—'}</text>
                <text x={sx} y={side ? cy - 2 : above ? cy - r - 20 : cy + r + 13} className="name" textAnchor={anchor}>{GROUP[g].label}</text>
                <text x={sx} y={side ? cy + 11 : above ? cy - r - 8 : cy + r + 25} className="io" textAnchor={anchor}>
                  <tspan className={into >= 0.05 ? 'in' : 'none'}>{into >= 0.05 ? `+${fmt1(into)}` : '+0'}</tspan>
                  <tspan className="sep"> · </tspan>
                  <tspan className={out >= 0.05 ? 'out' : 'none'}>{out >= 0.05 ? `−${fmt1(out)}` : '−0'}</tspan>
                </text>
                {delta !== null && delta !== 0 && (
                  <text x={cx + r * 0.75} y={cy - r * 0.75} className={`delta ${delta > 0 ? 'up' : 'down'}`}>
                    <title>{`Head count ${delta > 0 ? 'up' : 'down'} ${Math.abs(delta)} on the previous ${grain}`}</title>
                    {fmtSigned(delta)}
                  </text>
                )}
                {arrived >= 0.05 && (
                  <text x={cx - r * 0.7 - 20} y={cy - r * 0.7 - 20} className="stub in" textAnchor="end">+{fmt1(arrived)}</text>
                )}
              </g>
            );
          })}

          {paths.filter((x) => x.label).map((x) => (
            <text key={`l-${x.key}`} x={x.labelAt![0]} y={x.labelAt![1]} textAnchor={x.anchor} className={`flow-label${x.v >= 0.05 ? ' on' : ''}`}>
              {x.label} <tspan className="v">{x.v >= 0.05 ? fmt1(x.v) : '0'}</tspan>
            </text>
          ))}

          {herdIn >= 0.05 && <text x={hx + 8} y={L.herd.y - 8} className="stub in">+{fmt1(herdIn)} arrived · group not recorded</text>}
          {(Object.keys(SINK) as Sink[]).map((k) => {
            const [sx, sy] = L.sinks[k];
            const to = k === 'lost' ? 'lost_pregnancy' : k;
            const v = total((m) => m.to === to);
            const herdOnly = total((m) => m.from === 'herd' && m.to === to);
            return (
              <g key={k} className={`sink ${k}${v >= 0.05 ? ' on' : ''}`} style={{ ['--c' as string]: SINK[k].color }}>
                <title>{`${SINK[k].label}: ${fmt1(v)}${k === 'lost' ? ' (the animals stay in their group)' : ''}${herdOnly >= 0.05 ? `; ${fmt1(herdOnly)} with the group not recorded` : ''}`}</title>
                {v >= 0.05 && <circle key={`ring-${k}-${p?.period}`} cx={sx} cy={sy} r={SINK_R} className="halo" />}
                <circle cx={sx} cy={sy} r={SINK_R} className="disc" />
                <text x={sx} y={sy - 3} className="icon">{SINK[k].icon}</text>
                <text x={sx} y={sy + 9} className="v">{fmt1(v)}</text>
                <text x={sx} y={sy + SINK_R + 12} className="name">{SINK[k].label}</text>
                {k === 'lost' && <text x={sx} y={sy + SINK_R + 23} className="hint">animal stays in its group</text>}
                {herdOnly >= 0.05 && <text x={sx} y={sy + SINK_R + (k === 'lost' ? 34 : 23)} className="hint">{fmt1(herdOnly)} group not recorded</text>}
              </g>
            );
          })}

          {t < 1 && active.flatMap((x) => {
            const n = Math.min(MAX_DOTS, Math.max(x.v >= perDot / 2 ? 1 : 0, Math.round(x.v / perDot)));
            return Array.from({ length: n }, (_, i) => {
              const delay = n > 1 ? (i / (n - 1)) * 0.4 : 0;
              const u = (t - delay) / 0.6;
              if (u <= 0 || u >= 1) return null;
              const [px, py] = pointOn(x, u);
              const fade = x.fade === 'in' ? Math.min(1, u * 3) : x.fade === 'out' ? Math.min(1, (1 - u) * 3) : Math.min(1, u * 8, (1 - u) * 8);
              return <circle key={`${x.key}-${i}`} cx={px} cy={py} r="3.4" className="mover" style={{ fill: x.color, opacity: fade }} />;
            });
          })}
        </svg>
      </div>
      <div className="pfie-move-totals">
        <span className="lbl">This {grain}</span>
        {totals.map(([label, v, icon, color]) => (
          <span key={label} className={v >= 0.05 ? 'on' : ''}><i style={{ color }}>{icon}</i><b>{fmt1(v)}</b> {label}</span>
        ))}
      </div>
      <p className="pfie-chart-note">
        Under each circle: <b>+</b> joined the group, <b>−</b> left it (to another group or out of the herd). Arrivals come in on the small stub at each circle's top-left. Deaths, culls / sales and pregnancies lost (abortions) flow from the group they happened in to their own circle; a lost pregnancy does not move the animal, which stays in its group.
        Grey routes had no animals this {grain}. {perDot === 1 ? 'One dot = one animal.' : `One dot = ${perDot} animals.`}
        {split
          ? `${run.source === 'demo' ? ' Demo split.' : ''}${!p?.future && grain !== 'month' ? ' Arrivals and pregnancies lost are herd totals here: their group is not dated.' : ''}`
          : ` ${!run.moves?.length ? 'This run has no moves by group' : grain === 'month' || p?.future ? 'No moves by group for this period' : `This run has no moves by group per ${grain}; rebuild it to add them`}, so totals are shown at the herd's edge.`}
        {notForecast ? ' Herd counts are forecast weekly and monthly, not daily.' : ''}
      </p>
    </Card>
  );
}
