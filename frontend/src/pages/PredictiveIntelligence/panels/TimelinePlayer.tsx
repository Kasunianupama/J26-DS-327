/**
 * Component 1 (PFOI): step or play through the timeline's periods.
 *
 * Moving the selected period moves the marker on every band and the period
 * the "Explain" button opens, so the herd's path can be walked one period at
 * a time across the origin.
 */

import { useEffect, useState } from 'react';
import { confidenceOf, fmtInt, type TimelinePoint } from '../../../data/pfoi';
import { usePfoi } from '../state';

export function TimelinePlayer({ points }: { points: TimelinePoint[] }) {
  const { selectedPeriod, setSelectedPeriod } = usePfoi();
  const [playing, setPlaying] = useState(false);
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
    }, 450);
    return () => window.clearInterval(timer);
  }, [playing, points, selectedPeriod, setSelectedPeriod]);

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
          Jump to origin
        </button>
        {current && (
          <span className="at">
            <b>{current.label}</b>
            {' · '}{current.future ? `forecast, ${confidenceOf(current.quality).toLowerCase()} confidence` : 'recorded'}
            {typeof milk === 'number' && <> · <b>{fmtInt(milk)} L/day</b></>}
          </span>
        )}
        {!current && <span className="at">Click a chart or press play to pick a period</span>}
      </div>
    </div>
  );
}
