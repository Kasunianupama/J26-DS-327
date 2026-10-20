/**
 * Component 1 (PFOI): step or play through the timeline's periods.
 *
 * Moving the selected period moves the marker on every band and the period
 * the "Explain" button opens, so the herd's path can be walked one period at
 * a time across the origin. A milk carton fills to the period's milk, relative
 * to the highest period on the timeline, so the level is easy to follow while
 * playing.
 */

import { useEffect, useMemo, useState } from 'react';
import { confidenceOf, fmtInt, type TimelinePoint } from '../../../data/pfoi';
import { usePfoi } from '../state';

export function TimelinePlayer({ points }: { points: TimelinePoint[] }) {
  const { selectedPeriod, setSelectedPeriod } = usePfoi();
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<'slow' | 'normal' | 'fast'>('normal');
  const stepMs = { slow: 1200, normal: 700, fast: 260 }[speed];
  const milkMax = useMemo(
    () => Math.max(1, ...points.map((p) => Math.max(Number(p.milk_litres ?? 0), Number(p.milk_litres_f ?? 0)))),
    [points],
  );
  const originIdx = Math.max(0, points.findIndex((p) => p.future));
  const idx = Math.max(0, points.findIndex((p) => p.period === selectedPeriod));
  const current = selectedPeriod ? points[idx] : null;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      const at = points.findIndex((p) => p.period === selectedPeriod);
      const next = at < 0 || at >= points.length - 1 ? null : points[at + 1];
      if (!next) { setPlaying(false); return; }
      setSelectedPeriod(next.period);
    }, stepMs);
    return () => window.clearInterval(timer);
  }, [playing, points, selectedPeriod, setSelectedPeriod, stepMs]);

  const step = (d: number) => {
    setPlaying(false);
    const base = selectedPeriod ? idx : originIdx;
    setSelectedPeriod(points[Math.min(points.length - 1, Math.max(0, base + d))].period);
  };

  const milk = current ? (current.future ? current.milk_litres_f : current.milk_litres) : null;

  return (
    <div className="pfie-player">
      <div className="head">
        <button className="pfie-btn ghost" onClick={() => step(-1)} aria-label="Previous period">‹</button>
        <button
          className="pfie-play"
          aria-pressed={playing}
          onClick={() => {
            if (!playing && (!selectedPeriod || idx >= points.length - 1)) setSelectedPeriod(points[0].period);
            setPlaying(!playing);
          }}
        >
          <span className="glyph" aria-hidden>{playing ? '❚❚' : '▶'}</span>
          {playing ? 'Pause' : 'Play'}
        </button>
        <button className="pfie-btn ghost" onClick={() => step(1)} aria-label="Next period">›</button>
        <button className="pfie-btn ghost" onClick={() => { setPlaying(false); setSelectedPeriod(points[originIdx]?.period ?? null); }}>
          Jump to forecast start
        </button>
        <label className="pfie-pick" title="Jump to the period that contains this date">
          Date
          <input
            type="date"
            value={current?.period ?? ''}
            min={points[0]?.period}
            max={points[points.length - 1]?.period}
            onChange={(e) => {
              const d = e.target.value;
              if (!d) return;
              setPlaying(false);
              /* the period that contains the date: the last one starting on or before it */
              const hit = [...points].reverse().find((p) => p.period <= d) ?? points[0];
              setSelectedPeriod(hit.period);
            }}
          />
        </label>
        <label className="pfie-pick" title="How fast play moves through the periods">
          Speed
          <select value={speed} onChange={(e) => setSpeed(e.target.value as typeof speed)}>
            <option value="slow">Slow</option>
            <option value="normal">Normal</option>
            <option value="fast">Fast</option>
          </select>
        </label>
        {current && typeof milk === 'number' && (
          <MilkCarton level={milk / milkMax} litres={milk} forecast={current.future} playing={playing} />
        )}
        {current && (
          <span className="at">
            <b>{current.label}</b>
            {' · '}{current.future ? `forecast, ${confidenceOf(current.quality).toLowerCase()} confidence` : 'recorded'}
          </span>
        )}
        {!current && <span className="at">Click a chart or press play to pick a period</span>}
      </div>
    </div>
  );
}

/** A carton that fills to the period's milk, relative to the highest period shown. */
function MilkCarton({ level, litres, forecast, playing }: { level: number; litres: number; forecast: boolean; playing: boolean }) {
  const fill = Math.max(0.04, Math.min(1, level));
  return (
    <span className={`pfie-carton${playing ? ' playing' : ''}${forecast ? ' forecast' : ''}`} title={`${fmtInt(litres)} L/day · ${Math.round(fill * 100)}% of the highest period shown`}>
      <svg viewBox="0 0 40 56" aria-hidden>
        <defs>
          <clipPath id="pfieCartonBody"><path d="M5 18 L20 8 L35 18 V53 H5 Z" /></clipPath>
        </defs>
        <g clipPath="url(#pfieCartonBody)">
          <rect x="0" y="0" width="40" height="56" className="bg" />
          <g className="milk" style={{ transform: `translateY(${(1 - fill) * 45}px)` }}>
            <path className="wave" d="M-40 13 q5 -3 10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 V60 H-40 Z" />
          </g>
        </g>
        <path d="M5 18 L20 8 L35 18 V53 H5 Z" className="edge" />
        <path d="M14 4 H26 L28 8 H12 Z" className="cap" />
      </svg>
      <span className="lbl"><b>{fmtInt(litres)}</b>L/day{forecast ? ' · forecast' : ''}</span>
    </span>
  );
}
