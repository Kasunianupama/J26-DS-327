import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  PROFILES,
  profileHologramState,
  profileIndicators,
  profileLactationCurve,
  profileSummary,
  type ProfileId,
} from '../../../data/component2';
import { fmtInt } from '../../../data/component2';
import { useC2 } from '../state';

const HOTSPOT_POSITIONS = [
  { x: -72, y: -25 },
  { x: 20, y: -38 },
  { x: 84, y: -10 },
  { x: -18, y: 25 },
];

/* ------------------------------------------------------------------ */
/* Wireframe geometry                                                  */
/*                                                                     */
/* A thin outline reads as a diagram; a dense mesh with bright nodes    */
/* reads as a volume being scanned. The mesh is generated from a seeded */
/* RNG so it is stable across renders and never flickers — and it is    */
/* seeded per profile, so the five avatars are visibly different        */
/* animals rather than one drawing in five colours.                     */
/* ------------------------------------------------------------------ */

function seeded(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * How each profile is built. These are drawing parameters, not measurements:
 * the shape carries the group's character so the five avatars can be told
 * apart at a glance, and the numbers beside them carry the actual data.
 */
interface ProfileForm {
  seed: number;
  /**
   * The animal itself is the same animal in every profile — deforming its body
   * would imply anatomy the data does not support. The differences live in the
   * chamber around it: field strength, scan cadence, and the readouts.
   */
  depth: number;
  bias: number;
  udder: number;
  /** Mesh density — how much recorded evidence the group actually carries. */
  density: number;
  /** A dashed, faded outline: too thin a record to draw a solid one. */
  sparse: boolean;
  pelvisGlow: number;

}

/**
 * A full holographic palette per profile, derived from that group's colour so
 * the whole chamber — ground, glass, mesh, callouts, readouts — shifts with the
 * selection rather than only an accent detail. Each is a deep tinted ground
 * with a bright edge, so the panel stays legible whichever group is selected.
 */
const HOLO_PALETTE: Record<ProfileId, {
  bg1: string; bg2: string; bg3: string;
  border: string; line: string; accent: string; hot: string;
  text: string; dim: string; panel: string;
}> = {
  HP: {
    bg1: '#0d2b21', bg2: '#071a14', bg3: '#03100c', border: '#1d5540',
    line: '#2f9068', accent: '#86e3b6', hot: '#eefff7',
    text: '#e8fff4', dim: '#8fc4ac', panel: 'rgba(4, 22, 16, 0.7)',
  },
  PT: {
    bg1: '#2e1f05', bg2: '#1d1303', bg3: '#110b01', border: '#5f4409',
    line: '#b8860b', accent: '#ffd98a', hot: '#fff9ea',
    text: '#fff4dd', dim: '#c9aa72', panel: 'rgba(22, 14, 2, 0.7)',
  },
  SR: {
    bg1: '#132635', bg2: '#0b1823', bg3: '#060f16', border: '#2c4a63',
    line: '#5b8cb8', accent: '#a9cfec', hot: '#f0f8ff',
    text: '#e6f2fb', dim: '#93b1c8', panel: 'rgba(7, 18, 27, 0.7)',
  },
  HA: {
    bg1: '#331410', bg2: '#200c09', bg3: '#140705', border: '#67302a',
    line: '#b8574a', accent: '#f2a495', hot: '#fff0ec',
    text: '#ffeae5', dim: '#c99287', panel: 'rgba(26, 9, 7, 0.7)',
  },
  LH: {
    bg1: '#1e2523', bg2: '#141918', bg3: '#0c100f', border: '#3b4744',
    line: '#7d8c86', accent: '#c9d6d0', hot: '#f4f8f6',
    text: '#eaf0ed', dim: '#9aa8a2', panel: 'rgba(15, 19, 18, 0.72)',
  },
};

const PROFILE_FORM: Record<ProfileId, ProfileForm> = {
  HP: { seed: 1071, depth: 1, bias: 0, udder: 1, density: 1, sparse: false, pelvisGlow: 0.3, },
  PT: { seed: 2143, depth: 1, bias: 0, udder: 1, density: 0.9, sparse: false, pelvisGlow: 0.3, },
  SR: { seed: 3319, depth: 1, bias: 0, udder: 1, density: 0.92, sparse: false, pelvisGlow: 1, },
  HA: { seed: 4457, depth: 1, bias: 0, udder: 1, density: 0.62, sparse: false, pelvisGlow: 0.3, },
  LH: { seed: 5623, depth: 1, bias: 0, udder: 1, density: 0.3, sparse: true, pelvisGlow: 0.3, },
};

/** Half-height of the barrel at a position along the body axis, -1..1. */
const bodyProfile = (t: number, form: ProfileForm) => {
  const base = Math.sqrt(Math.max(0, 1 - t * t * 0.94));
  /* `bias` slides the deepest point along the animal. */
  const swell = 1 + Math.cos((t - form.bias) * 1.9) * 0.1;
  return base * swell * form.depth;
};

const BODY_X0 = -132;
const BODY_X1 = 126;
const BODY_RY = 64;

interface Ring { cx: number; ry: number; rx: number; t: number }

interface Wireframe {
  rings: Ring[];
  filaments: string[];
  nodes: { x: number; y: number; r: number; o: number }[];
}

/** Built once per profile and cached — the geometry never changes after that. */
const wireframeCache = new Map<ProfileId, Wireframe>();

function wireframeFor(profile: ProfileId): Wireframe {
  const hit = wireframeCache.get(profile);
  if (hit) return hit;
  const form = PROFILE_FORM[profile];
  const rnd = seeded(form.seed);

  const rings: Ring[] = Array.from({ length: 17 }, (_, i) => {
    const t = (i / 16) * 2 - 1;
    const cx = BODY_X0 + (BODY_X1 - BODY_X0) * (i / 16);
    const ry = BODY_RY * bodyProfile(t, form);
    return { cx, t, ry, rx: 15 * bodyProfile(t, form) };
  }).filter((r) => r.ry > 5);

  const filamentCount = form.sparse ? 6 : 11;
  const filaments = Array.from({ length: filamentCount }, (_, i) => {
    const k = (i / (filamentCount - 1)) * 2 - 1;
    return `M${rings.map((r) => `${r.cx.toFixed(1)},${(k * r.ry).toFixed(1)}`).join(' L')}`;
  });

  const nodes: Wireframe['nodes'] = [];
  for (const ring of rings) {
    const count = Math.round((5 + rnd() * 4) * form.density);
    for (let i = 0; i < count; i += 1) {
      const a = rnd() * Math.PI * 2;
      nodes.push({
        x: ring.cx + Math.cos(a) * ring.rx * 0.9 + (rnd() - 0.5) * 8,
        y: Math.sin(a) * ring.ry * (0.55 + rnd() * 0.45),
        r: 0.7 + rnd() * 1.7,
        o: (0.25 + rnd() * 0.7) * (0.55 + form.density * 0.45),
      });
    }
  }
  /* Denser bands where each profile's story actually sits. */
  const clusters: [number, number, number][] = [
    [-58, -14, 0.9],
    [46, 30, 0.7 + form.pelvisGlow * 0.6],
  ];
  for (const [cx, cy, weight] of clusters) {
    const count = Math.round(20 * weight * form.density);
    for (let i = 0; i < count; i += 1) {
      nodes.push({
        x: cx + (rnd() - 0.5) * 66,
        y: cy + (rnd() - 0.5) * 52,
        r: 0.8 + rnd() * 2.1,
        o: (0.4 + rnd() * 0.6) * (0.55 + form.density * 0.45),
      });
    }
  }

  const frame = { rings, filaments, nodes };
  wireframeCache.set(profile, frame);
  return frame;
}

export function ProfileHologram({
  profile,
  selectedDay,
  onSelectedDayChange,
  onClose,
}: {
  profile: ProfileId;
  selectedDay: number;
  onSelectedDayChange: (day: number) => void;
  onClose: () => void;
}) {
  const { openDrawer } = useC2();
  const [angle, setAngle] = useState(18);
  const [rotating, setRotating] = useState(true);
  const drag = useRef<{ x: number; angle: number } | null>(null);
  const state = useMemo(() => profileHologramState(profile, selectedDay), [profile, selectedDay]);
  const form = PROFILE_FORM[profile];
  const palette = HOLO_PALETTE[profile];
  const indicators = useMemo(() => profileIndicators(profile, selectedDay), [profile, selectedDay]);
  const curve = useMemo(() => profileLactationCurve(profile), [profile]);

  /* The chamber restates the numbers rather than decorating them: field
     strength is how much of the group stands on its own record, and the ring
     cadence is its persistence — a fast-tapering group pulses visibly faster.
     Both are normalised across the range the herd actually produces, so the
     difference is legible instead of technically-correct-but-invisible. */
  const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
  const field = clamp01(1 - indicators.peerDerived / 100) * 0.75 + 0.25;
  const emitters = Math.max(2, Math.round(field * 6));
  const persistenceNorm = clamp01((indicators.persistence - 45) / 30);
  const pulse = 1.4 + persistenceNorm * 4;
  const frame = useMemo(() => wireframeFor(profile), [profile]);
  const summary = useMemo(() => profileSummary(profile, selectedDay), [profile, selectedDay]);
  const productionRatio = Math.max(0.16, Math.min(1, state.median / Math.max(1, summary.medianPeak)));
  const radians = (angle * Math.PI) / 180;
  const facing = Math.cos(radians) < 0 ? -1 : 1;
  const depthScale = 0.42 + Math.abs(Math.cos(radians)) * 0.58;
  const hotspotCount = Math.min(HOTSPOT_POSITIONS.length, Math.round(state.healthEvents));

  useEffect(() => {
    if (!rotating || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let frame = 0;
    let previous = performance.now();
    const rotate = (now: number) => {
      const elapsed = Math.min(40, now - previous);
      previous = now;
      setAngle((value) => (value + elapsed * 0.018) % 360);
      frame = requestAnimationFrame(rotate);
    };
    frame = requestAnimationFrame(rotate);
    return () => cancelAnimationFrame(frame);
  }, [rotating]);

  useEffect(() => {
    const move = (event: PointerEvent) => {
      if (!drag.current) return;
      setAngle(drag.current.angle + (event.clientX - drag.current.x) * 0.55);
    };
    const up = () => { drag.current = null; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
  }, []);

  return (
    <section
      className="pfie-hologram"
      style={{
        '--holo-profile': PROFILES[profile].color,
        '--holo-bg-1': palette.bg1,
        '--holo-bg-2': palette.bg2,
        '--holo-bg-3': palette.bg3,
        '--holo-border': palette.border,
        '--holo-line': palette.line,
        '--holo-accent': palette.accent,
        '--holo-hot': palette.hot,
        '--holo-text': palette.text,
        '--holo-dim': palette.dim,
        '--holo-panel': palette.panel,
        '--milk-energy': productionRatio,
        '--holo-field': field,
        '--holo-pulse': `${pulse}s`,
      } as CSSProperties}
      aria-label={`${PROFILES[profile].name} profile hologram`}
    >
      <header>
        <div>
          <span className="eyebrow">Profile avatar · not an individual cow</span>
          <h4>{PROFILES[profile].name}</h4>
          <p>{PROFILES[profile].blurb}</p>
        </div>
        <div className="pfie-row tight">
          <button className="pfie-holo-btn" aria-pressed={rotating} onClick={() => setRotating(!rotating)}>
            {rotating ? 'Pause rotation' : 'Rotate'}
          </button>
          <button
            className="pfie-holo-btn"
            onClick={() => openDrawer({ kind: 'cohort', groupKey: 'Profile', value: PROFILES[profile].name })}
          >Open group</button>
          <button className="pfie-holo-btn close" onClick={onClose} aria-label="Close profile hologram">×</button>
        </div>
      </header>

      <div
        className="pfie-holo-stage"
        onPointerDown={(event) => {
          drag.current = { x: event.clientX, angle };
          setRotating(false);
        }}
      >
        <svg viewBox="0 0 920 440" role="img" aria-label={`Holographic profile avatar at day ${selectedDay} in milk`}>
          <defs>
            <filter id="pfieHoloGlow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <linearGradient id="pfieHoloBody" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--holo-accent)" stopOpacity="0.05" />
              <stop offset="0.55" stopColor="var(--holo-line)" stopOpacity="0.2" />
              <stop offset="1" stopColor="var(--holo-profile)" stopOpacity="0.32" />
            </linearGradient>
            {/* The udder glow is the one genuinely hot part of the figure. */}
            <radialGradient id="pfieMilkCore">
              <stop offset="0" stopColor="var(--holo-hot)" stopOpacity="0.97" />
              <stop offset="0.34" stopColor="var(--holo-accent)" stopOpacity="0.75" />
              <stop offset="0.68" stopColor="var(--holo-line)" stopOpacity="0.34" />
              <stop offset="1" stopColor="var(--holo-bg-1)" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="pfieHoloAura">
              <stop offset="0" stopColor="var(--holo-line)" stopOpacity="0.3" />
              <stop offset="1" stopColor="var(--holo-line)" stopOpacity="0" />
            </radialGradient>
          </defs>

          <ellipse className="holo-aura" cx="460" cy="212" rx="330" ry="210" aria-hidden />

          <g className="holo-grid" aria-hidden>
            {[90, 145, 200, 255, 310, 365, 420, 475, 530, 585, 640, 695, 750, 805].map((x) => <line key={`x${x}`} x1={x} y1="300" x2="460" y2="420" />)}
            {[312, 336, 360, 384, 408].map((y) => <ellipse key={`y${y}`} cx="460" cy={y} rx={(y - 286) * 3.2} ry={(y - 286) * 0.45} />)}
          </g>

          {/* Containment chamber. Its glass, its emitters and the cadence of its
              base rings are what change between profiles — the animal does not. */}
          <g className="holo-chamber" key={profile}>
            <path className="glass" d="M255 96 A205 30 0 0 1 665 96 L665 344 A205 32 0 0 1 255 344 Z" />
            <ellipse className="cap" cx="460" cy="96" rx="205" ry="30" />
            <ellipse className="cap rim" cx="460" cy="96" rx="205" ry="30" />
            <line className="edge" x1="255" y1="96" x2="255" y2="344" />
            <line className="edge" x1="665" y1="96" x2="665" y2="344" />
            {Array.from({ length: emitters }, (_, i) => {
              const a = (i / emitters) * Math.PI * 2;
              const x = 460 + Math.cos(a) * 176;
              const y = 346 + Math.sin(a) * 30;
              return <line className="emitter" key={i} x1={x} y1={y} x2={x} y2={y - 26} style={{ animationDelay: `${i * 0.16}s` }} />;
            })}
          </g>

          <ellipse className="holo-platform outer" cx="460" cy="346" rx="202" ry="38" />
          <ellipse className="holo-platform inner" cx="460" cy="346" rx="146" ry="24" />
          {/* Pulse rings: fast for a decaying group, slow for a thin record. */}
          {[0, 1, 2].map((i) => (
            <ellipse
              className="holo-pulse-ring"
              key={`${profile}-${i}`}
              cx="460"
              cy="346"
              rx="120"
              ry="20"
              style={{ animationDelay: `${(pulse / 3) * i}s` }}
            />
          ))}
          <path className="holo-beam" d="M320 345 L365 96 L555 96 L600 345 Z" />

          <g className="holo-day-ring">
            <circle cx="460" cy="212" r="176" />
            <circle cx="460" cy="212" r="164" strokeDasharray="3 12" />
            <text x="460" y="48" textAnchor="middle">DAY {selectedDay} IN MILK</text>
          </g>

          <g
            className="holo-cow"
            transform={`translate(460 204) scale(${facing * depthScale * 1.08} 1.08)`}
          >
            <ellipse className="body-energy" cx="-5" cy="0" rx={132} ry={64 * form.depth} />

            {/* Cross-sections along the body axis, then filaments over them:
                together they read as a surface rather than a silhouette. */}
            <g className="holo-mesh-rings" aria-hidden>
              {frame.rings.map((ring) => (
                <ellipse key={ring.cx} cx={ring.cx} cy={0} rx={ring.rx} ry={ring.ry} />
              ))}
            </g>
            <g className="holo-mesh-filaments" aria-hidden>
              {frame.filaments.map((d, i) => <path key={i} d={d} />)}
            </g>
            <g className="holo-nodes" aria-hidden>
              {frame.nodes.map((n, i) => (
                <circle key={i} cx={n.x} cy={n.y} r={n.r} style={{ opacity: n.o }} />
              ))}
            </g>

            <ellipse
              className={`cow-outline${form.sparse ? ' sparse' : ''}`}
              cx="-5"
              cy="0"
              rx={132}
              ry={64 * form.depth}
            />
            <path className={`cow-outline${form.sparse ? ' sparse' : ''}`} d="M100 -38 C128 -50 138 -73 145 -88 C163 -100 197 -94 211 -72 C220 -56 212 -34 190 -27 L148 -28 C132 -13 123 4 114 20" />
            <path className="cow-outline" d="M205 -73 L234 -69 L230 -51 L207 -49" />
            <path className="cow-outline thin" d="M161 -92 L151 -112 M184 -93 L196 -112 M148 -87 L126 -101 M198 -84 L222 -96" />
            <path className="cow-outline" d="M-116 -34 C-151 -48 -166 -72 -154 -92 M-154 -92 L-170 -104" />
            <path className={`cow-outline${form.sparse ? ' sparse' : ''}`} d="M-90 48 L-94 130 L-75 130 L-62 54 M-32 58 L-28 132 L-8 132 L3 59 M52 56 L60 132 L80 132 L84 48" />

            {/* Leg cross-hatching keeps the limbs part of the same mesh. */}
            <g className="holo-mesh-filaments" aria-hidden>
              {[70, 88, 106, 122].map((y) => (
                <path key={y} d={`M-93 ${y} L-68 ${y} M-30 ${y + 2} L1 ${y + 2} M58 ${y} L82 ${y}`} />
              ))}
            </g>
            <g className="holo-mesh-rings" aria-hidden>
              {[-104, -92, -80, -68].map((x, i) => (
                <ellipse key={x} cx={x} cy={-24 - i * 3} rx={6 - i * 0.8} ry={(30 - i * 4) * form.depth} />
              ))}
            </g>

            {/* The udder sits between the hind legs and tucks up under the belly
                line, rather than hanging off the middle of the barrel. */}
            <g className="holo-udder" transform={`translate(52 ${40 * form.depth})`}>
              <ellipse
                className="udder"
                cx="0"
                cy="0"
                rx={(19 + productionRatio * 6) * form.udder}
                ry={(12 + productionRatio * 4) * form.udder}
              />
              <ellipse
                className="milk-core"
                cx="0"
                cy="-2"
                rx={(27 + productionRatio * 15) * form.udder}
                ry={(19 + productionRatio * 10) * form.udder}
              />
            </g>

            <line className="scan-line" x1="-145" y1="-70" x2="232" y2="-70" />
          </g>

          <g className="holo-callout milk-callout">
            <path d="M585 154 L690 112 L815 112" />
            <circle cx="585" cy="154" r="4" />
            <text className="label" x="704" y="94">MILK PRODUCTION</text>
            <text className="value" x="704" y="119">{state.median} L/cow/day</text>
            <text className="detail" x="704" y="139">Typical range {state.lower}–{state.upper} L</text>
          </g>
          <g className="holo-callout health-callout">
            <path d="M365 170 L242 130 L100 130" />
            <circle cx="365" cy="170" r="4" />
            <text className="label" x="100" y="105">HEALTH HISTORY</text>
            <text className="value" x="100" y="130">{state.healthEvents} events/cow</text>
            <text className="detail" x="100" y="150">Recorded by day {selectedDay}</text>
          </g>
          <g className="holo-callout repro-callout">
            <path d="M555 263 L678 294 L814 294" />
            <circle cx="555" cy="263" r="4" />
            <text className="label" x="704" y="278">REPRODUCTION</text>
            <text className="value" x="704" y="303">{state.meanAiAttempts} AI attempts/cow</text>
            <text className="detail" x="704" y="323">Across supporting adult cows</text>
          </g>
        </svg>
        {/* Re-keyed on the profile so switching replays the sweep. */}
        <span className="pfie-holo-sweep" key={`sweep-${profile}`} aria-hidden />

        <span className="drag-hint">Drag to rotate · milk glow follows the selected day</span>
      </div>

      {/* The aggregate lactation curve for this group, past and expected. This
          is the panel that actually distinguishes a persistent group from a
          fast-tapering one, and it shares its x axis with the slider below. */}
      <figure className="pfie-holo-curve">
        <figcaption>
          <span>
            <b>Aggregate lactation curve</b>
            <small>
              Median litres per cow per day across {indicators.animals} cows in this group, over a
              305-day lactation. Solid to day {selectedDay}; dashed beyond it is the expected remainder.
            </small>
          </span>
          <span className="pfie-holo-curve-stats">
            <span><i>Now</i><b>{state.median} L/day</b></span>
            <span><i>Peak</i><b>{summary.medianPeak} L · day {summary.medianPeakDay}</b></span>
            <span><i>Persistence</i><b>{indicators.persistence}% of peak</b></span>
            <span><i>305-day</i><b>{fmtInt(summary.median305)} L</b></span>
          </span>
        </figcaption>
        <LactationCurve curve={curve} selectedDay={selectedDay} peakDay={summary.medianPeakDay} />
      </figure>

      <label className="pfie-holo-timeline">
        <span className="pfie-holo-timeline-head">
          <b>Day in milk · {selectedDay} of 305</b>
          <small>
            Drag to move through the lactation. Every figure above — the curve, the callouts and the
            milk glow — reports this group at that day.
          </small>
        </span>
        <span className="pfie-holo-slider">
          <input
            type="range"
            min={1}
            max={305}
            value={selectedDay}
            aria-label={`Day in milk, ${selectedDay} of 305`}
            onChange={(event) => onSelectedDayChange(Number(event.target.value))}
          />
          <span className="pfie-holo-ticks" aria-hidden>
            {[1, 60, 120, 180, 240, 305].map((day) => (
              <span key={day} style={{ left: `${((day - 1) / 304) * 100}%` }}>{day}</span>
            ))}
            <i className="peak" style={{ left: `${((summary.medianPeakDay - 1) / 304) * 100}%` }} title="Median peak">
              Peak
            </i>
          </span>
        </span>
      </label>
    </section>
  );
}

/**
 * The group's median curve with its interquartile band. Days up to the selected
 * day are drawn solid — that part of the lactation is established by recorded
 * curves — and the remainder is dashed, because it has not happened yet.
 */
function LactationCurve({
  curve,
  selectedDay,
  peakDay,
}: {
  curve: { day: number; median: number; lower: number; upper: number }[];
  selectedDay: number;
  peakDay: number;
}) {
  const W = 920;
  const H = 150;
  const padL = 44;
  const padR = 14;
  const padT = 12;
  const padB = 22;
  const max = Math.max(...curve.map((p) => p.upper)) * 1.08;

  const x = (day: number) => padL + ((day - 1) / 304) * (W - padL - padR);
  const y = (v: number) => H - padB - (v / Math.max(1, max)) * (H - padT - padB);

  const past = curve.filter((p) => p.day <= selectedDay);
  const future = curve.filter((p) => p.day >= selectedDay);
  const line = (pts: typeof curve) =>
    pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.day).toFixed(1)},${y(p.median).toFixed(1)}`).join(' ');
  const band = `${curve.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.day).toFixed(1)},${y(p.upper).toFixed(1)}`).join(' ')} ${[...curve].reverse().map((p) => `L${x(p.day).toFixed(1)},${y(p.lower).toFixed(1)}`).join(' ')} Z`;

  const atDay = curve.reduce((best, p) => (Math.abs(p.day - selectedDay) < Math.abs(best.day - selectedDay) ? p : best), curve[0]);

  return (
    <svg className="pfie-holo-curve-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Aggregate lactation curve for this profile">
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line className="grid" x1={padL} y1={y(max * f)} x2={W - padR} y2={y(max * f)} />
          <text className="tick" x={padL - 7} y={y(max * f) + 3}>{Math.round(max * f)}</text>
        </g>
      ))}
      <path className="band" d={band} />
      <path className="future" d={line(future)} />
      <path className="past" d={line(past)} />
      <line className="peak" x1={x(peakDay)} y1={padT} x2={x(peakDay)} y2={H - padB} />
      <line className="cursor" x1={x(selectedDay)} y1={padT} x2={x(selectedDay)} y2={H - padB} />
      <circle className="dot" cx={x(selectedDay)} cy={y(atDay.median)} r="4" />
      <text className="unit" x={padL - 7} y={padT + 2}>L/day</text>
    </svg>
  );
}
