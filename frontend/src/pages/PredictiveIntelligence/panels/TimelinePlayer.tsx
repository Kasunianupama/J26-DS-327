/**
 * The period bar: a scrubbable overview of the whole window with a play head.
 *
 * Playing advances the shared selected date, so the herd pictograms, the
 * forecast panels and every other workspace move together — the farm's
 * predicted structure changing over time rather than a set of static charts.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  DAILY,
  DEFINING_MOVEMENT,
  TODAY_ISO,
  WINDOW_END,
  WINDOW_START,
  dateAtProgress,
  fmtInt,
  herdAt,
  longDate,
  progressOfDate,
  windowDays,
} from '../../../data/component2';
import { useC2, type Grain } from '../state';

const GRAINS: { id: Grain; label: string; step: number }[] = [
  { id: 'day', label: 'Day', step: 1 },
  { id: 'week', label: 'Week', step: 7 },
  { id: 'month', label: 'Month', step: 30 },
];

const SPEEDS = [
  { id: 1, label: '1×' },
  { id: 2, label: '2×' },
  { id: 4, label: '4×' },
];

export function TimelinePlayer() {
  const {
    selectedDate, setSelectedDate, grain, setGrain, playing, setPlaying, speed, setSpeed,
  } = useC2();
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const progress = progressOfDate(selectedDate);
  const snap = herdAt(selectedDate);
  const step = GRAINS.find((g) => g.id === grain)!.step;

  /* -- playback ---------------------------------------------------- */
  useEffect(() => {
    if (!playing) return;
    const tick = window.setInterval(() => {
      setSelectedDate(advance(selectedDate, step));
    }, 420 / speed);
    return () => window.clearInterval(tick);
  }, [playing, speed, step, selectedDate, setSelectedDate]);

  // Stop at the end of the window rather than looping past it.
  useEffect(() => {
    if (playing && selectedDate >= WINDOW_END) setPlaying(false);
  }, [playing, selectedDate, setPlaying]);

  /* -- scrubbing --------------------------------------------------- */
  const seek = useCallback(
    (clientX: number) => {
      const el = trackRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setSelectedDate(dateAtProgress(Math.min(1, Math.max(0, (clientX - r.left) / r.width))));
    },
    [setSelectedDate],
  );

  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => seek(e.clientX);
    const up = () => setDragging(false);
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
  }, [dragging, seek]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight') { setSelectedDate(advance(selectedDate, step)); e.preventDefault(); }
    if (e.key === 'ArrowLeft') { setSelectedDate(advance(selectedDate, -step)); e.preventDefault(); }
    if (e.key === ' ') { setPlaying(!playing); e.preventDefault(); }
  };

  const todayPct = progressOfDate(TODAY_ISO) * 100;
  const evStart = progressOfDate(DEFINING_MOVEMENT.windowStart) * 100;
  const evEnd = progressOfDate(DEFINING_MOVEMENT.windowEnd) * 100;

  return (
    <div className="pfie-player pfie-rise">
      <div className="head">
        <span className="period">
          Period <b>{longDate(WINDOW_START)} — {longDate(WINDOW_END)}</b>
        </span>

        <span className="pfie-seg" role="group" aria-label="Timeline granularity">
          {GRAINS.map((g) => (
            <button key={g.id} aria-pressed={grain === g.id} onClick={() => setGrain(g.id)}>{g.label}</button>
          ))}
        </span>

        <button className="pfie-play" aria-pressed={playing} onClick={() => setPlaying(!playing)}>
          <span className="glyph" aria-hidden>{playing ? '❚❚' : '▶'}</span>
          {playing ? 'Pause' : `Play ${Math.round(windowDays / 365 * 10) / 10} years`}
        </button>

        {playing && (
          <span className="pfie-seg" role="group" aria-label="Playback speed">
            {SPEEDS.map((s) => (
              <button key={s.id} aria-pressed={speed === s.id} onClick={() => setSpeed(s.id)}>{s.label}</button>
            ))}
          </span>
        )}

        <button className="pfie-btn ghost" onClick={() => setSelectedDate(TODAY_ISO)}>Jump to today</button>

        <span className="at">
          Herd on <b>{longDate(selectedDate)}</b> · <b>{snap.total} head</b>
        </span>
      </div>

      <div
        className="pfie-scrub"
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label="Scrub the timeline"
        aria-valuemin={0}
        aria-valuemax={windowDays}
        aria-valuenow={Math.round(progress * windowDays)}
        aria-valuetext={longDate(selectedDate)}
        onKeyDown={onKey}
        onPointerDown={(e) => { setDragging(true); setPlaying(false); seek(e.clientX); }}
      >
        <div className="forecastzone" style={{ left: `${todayPct}%`, right: 0 }} />
        <div className="eventzone" style={{ left: `${evStart}%`, width: `${evEnd - evStart}%` }} />
        <Sparkline />
        <div className="today" style={{ left: `${todayPct}%` }} />
        <div className="cursor" style={{ left: `${progress * 100}%` }} />
        {yearTicks().map((t) => (
          <span key={t.label} className="tick" style={{ left: `${t.pct}%` }}>{t.label}</span>
        ))}
      </div>
    </div>
  );
}

/** Milk volume across the whole window, drawn once as a static backdrop. */
function Sparkline() {
  const pts = DAILY.filter((d) => d.date >= WINDOW_START && d.date <= WINDOW_END);
  if (!pts.length) return null;
  const vals = pts.map((d) => d.observed ?? d.expected ?? 0);
  const lo = Math.min(...vals) * 0.94;
  const hi = Math.max(...vals) * 1.02;
  const w = 1000;
  const h = 44;
  const path = vals
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${((i / (vals.length - 1)) * w).toFixed(1)},${(h - ((v - lo) / (hi - lo)) * h).toFixed(1)}`)
    .join(' ');
  const splitAt = pts.findIndex((d) => d.offset > 0) / (vals.length - 1);

  return (
    <svg viewBox={`0 0 ${w} ${h + 12}`} preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id="pfieSparkFade" x1="0" x2="1">
          <stop offset="0" stopColor="#1f6b4a" />
          <stop offset={String(Math.max(0, splitAt - 0.002))} stopColor="#1f6b4a" />
          <stop offset={String(splitAt)} stopColor="#5b7fa6" />
          <stop offset="1" stopColor="#5b7fa6" />
        </linearGradient>
      </defs>
      <path d={`${path} L${w},${h + 12} L0,${h + 12} Z`} fill="url(#pfieSparkFade)" opacity="0.1" />
      <path d={path} fill="none" stroke="url(#pfieSparkFade)" strokeWidth="1.1" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function yearTicks() {
  const out: { label: string; pct: number }[] = [];
  const firstYear = Number(WINDOW_START.slice(0, 4));
  const lastYear = Number(WINDOW_END.slice(0, 4));
  for (let y = firstYear; y <= lastYear; y++) {
    const iso = `${y}-01-01`;
    if (iso < WINDOW_START || iso > WINDOW_END) continue;
    out.push({ label: String(y), pct: progressOfDate(iso) * 100 });
  }
  return out;
}

function advance(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  const next = d.toISOString().slice(0, 10);
  if (next > WINDOW_END) return WINDOW_END;
  if (next < WINDOW_START) return WINDOW_START;
  return next;
}

export { fmtInt };
