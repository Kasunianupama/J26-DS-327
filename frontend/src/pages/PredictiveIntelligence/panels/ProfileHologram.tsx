import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  PROFILES,
  profileHologramState,
  profileSummary,
  type ProfileId,
} from '../../../data/component2';
import { useC2 } from '../state';

const HOTSPOT_POSITIONS = [
  { x: -72, y: -25 },
  { x: 20, y: -38 },
  { x: 84, y: -10 },
  { x: -18, y: 25 },
];

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
      style={{ '--holo-profile': PROFILES[profile].color, '--milk-energy': productionRatio } as CSSProperties}
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
              <stop offset="0" stopColor="var(--holo-profile)" stopOpacity="0.08" />
              <stop offset="1" stopColor="var(--holo-profile)" stopOpacity="0.32" />
            </linearGradient>
            <radialGradient id="pfieMilkCore">
              <stop offset="0" stopColor="#eaffff" stopOpacity="0.96" />
              <stop offset="0.38" stopColor="#6be6ff" stopOpacity="0.72" />
              <stop offset="1" stopColor="var(--holo-profile)" stopOpacity="0" />
            </radialGradient>
          </defs>

          <g className="holo-grid" aria-hidden>
            {[90, 145, 200, 255, 310, 365, 420, 475, 530, 585, 640, 695, 750, 805].map((x) => <line key={`x${x}`} x1={x} y1="300" x2="460" y2="420" />)}
            {[312, 336, 360, 384, 408].map((y) => <ellipse key={`y${y}`} cx="460" cy={y} rx={(y - 286) * 3.2} ry={(y - 286) * 0.45} />)}
          </g>

          <ellipse className="holo-platform outer" cx="460" cy="346" rx="202" ry="38" />
          <ellipse className="holo-platform inner" cx="460" cy="346" rx="146" ry="24" />
          <path className="holo-beam" d="M320 345 L365 83 L555 83 L600 345 Z" />

          <g className="holo-day-ring">
            <circle cx="460" cy="212" r="176" />
            <circle cx="460" cy="212" r="164" strokeDasharray="3 12" />
            <text x="460" y="48" textAnchor="middle">DAY {selectedDay} IN MILK</text>
          </g>

          <g
            className="holo-cow"
            transform={`translate(460 204) scale(${facing * depthScale * 1.08} 1.08)`}
          >
            <ellipse className="body-energy" cx="-5" cy="0" rx="132" ry="64" />
            <ellipse className="cow-outline" cx="-5" cy="0" rx="132" ry="64" />
            <path className="cow-outline" d="M100 -38 C128 -50 138 -73 145 -88 C163 -100 197 -94 211 -72 C220 -56 212 -34 190 -27 L148 -28 C132 -13 123 4 114 20" />
            <path className="cow-outline" d="M205 -73 L234 -69 L230 -51 L207 -49" />
            <path className="cow-outline thin" d="M161 -92 L151 -112 M184 -93 L196 -112 M148 -87 L126 -101 M198 -84 L222 -96" />
            <path className="cow-outline" d="M-116 -34 C-151 -48 -166 -72 -154 -92 M-154 -92 L-170 -104" />
            <path className="cow-outline" d="M-90 48 L-94 130 L-75 130 L-62 54 M-32 58 L-28 132 L-8 132 L3 59 M52 56 L60 132 L80 132 L84 48" />
            <ellipse className="udder" cx="38" cy="53" rx={27 + productionRatio * 8} ry={17 + productionRatio * 5} />
            <path className="cow-outline thin" d="M25 63 L23 79 M42 67 L43 83 M57 63 L60 78" />
            {[-42, -14, 14, 42].map((y) => <path key={y} className="mesh" d={`M-125 ${y} C-55 ${y + 18} 55 ${y - 18} 123 ${y}`} />)}
            {[-78, -38, 2, 42, 82].map((x) => <path key={x} className="mesh" d={`M${x} -58 C${x - 17} -20 ${x - 17} 20 ${x} 58`} />)}
            <ellipse className="milk-core" cx="38" cy="53" rx={42 + productionRatio * 23} ry={31 + productionRatio * 14} />
            {HOTSPOT_POSITIONS.slice(0, hotspotCount).map((point, index) => (
              <g className="health-hotspot" key={index} transform={`translate(${point.x} ${point.y})`}>
                <circle r="12" /><circle r="4" />
              </g>
            ))}
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
        <span className="drag-hint">Drag to rotate · milk glow follows the selected day</span>
      </div>

      <label className="pfie-holo-timeline">
        <span><b>Day {selectedDay}</b><small>{state.supportingAnimals} adult cows support this profile avatar</small></span>
        <input type="range" min={1} max={305} value={selectedDay} onChange={(event) => onSelectedDayChange(Number(event.target.value))} />
      </label>
    </section>
  );
}
