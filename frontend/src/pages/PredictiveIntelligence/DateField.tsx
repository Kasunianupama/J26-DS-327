/**
 * A typable date field with quick month / year steps.
 *
 * Accepts DD/MM/YYYY, YYYY-MM-DD, MM/YYYY (first of the month) or YYYY
 * (1 January). Commits on Enter or blur, clamped to [min, max]. ↑/↓ step a
 * month, Shift+↑/↓ a year; the ‹ › and « » buttons do the same.
 */

import { useEffect, useState, type KeyboardEvent } from 'react';

const pad = (n: number) => String(n).padStart(2, '0');
const toIso = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;
const daysIn = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();

/** ISO yyyy-mm-dd → DD/MM/YYYY */
export function displayDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-');
  return `${d}/${m}/${y}`;
}

/** Parse what was typed into an ISO date, or null when it isn't a real date. */
export function parseDate(text: string): string | null {
  const t = text.trim();
  let y: number, m = 1, d = 1;
  let match: RegExpMatchArray | null;
  if ((match = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) {
    [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  } else if ((match = t.match(/^(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{4})$/))) {
    [d, m, y] = [Number(match[1]), Number(match[2]), Number(match[3])];
  } else if ((match = t.match(/^(\d{1,2})[/.\- ](\d{4})$/))) {
    [m, y] = [Number(match[1]), Number(match[2])];
  } else if ((match = t.match(/^(\d{4})$/))) {
    y = Number(match[1]);
  } else {
    return null;
  }
  if (m < 1 || m > 12 || d < 1 || d > daysIn(y, m)) return null;
  return toIso(y, m, d);
}

/** Move an ISO date by whole months, keeping the day where the month allows. */
export function shiftMonths(iso: string, months: number): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const total = y * 12 + (m - 1) + months;
  const ny = Math.floor(total / 12);
  const nm = (total % 12) + 1;
  return toIso(ny, nm, Math.min(d, daysIn(ny, nm)));
}

const clamp = (iso: string, min: string, max: string) => (iso < min ? min : iso > max ? max : iso);

export function DateField({ value, min, max, onChange, label }: {
  value: string; min: string; max: string; onChange: (iso: string) => void; label: string;
}) {
  const [draft, setDraft] = useState(displayDate(value));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => { setDraft(displayDate(value)); setInvalid(false); }, [value]);

  const commit = () => {
    const iso = parseDate(draft);
    if (!iso) { setInvalid(true); return; }
    const next = clamp(iso, min, max);
    setInvalid(false);
    setDraft(displayDate(next));
    if (next !== value) onChange(next);
  };
  const step = (months: number) => onChange(clamp(shiftMonths(value, months), min, max));

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') { e.preventDefault(); commit(); }
    else if (e.key === 'Escape') { setDraft(displayDate(value)); setInvalid(false); }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      step((e.key === 'ArrowUp' ? 1 : -1) * (e.shiftKey ? 12 : 1));
    }
  };

  return (
    <span className="pfie-datefield" role="group" aria-label={label}>
      <button type="button" onClick={() => step(-12)} disabled={value <= min} title="Back one year" aria-label="Back one year">«</button>
      <button type="button" onClick={() => step(-1)} disabled={value <= min} title="Back one month" aria-label="Back one month">‹</button>
      <input
        type="text"
        inputMode="numeric"
        value={draft}
        aria-label={label}
        aria-invalid={invalid}
        className={invalid ? 'invalid' : undefined}
        placeholder="DD/MM/YYYY"
        title="Type DD/MM/YYYY, MM/YYYY or YYYY · ↑/↓ month · Shift+↑/↓ year"
        onChange={(e) => { setDraft(e.target.value); setInvalid(false); }}
        onBlur={commit}
        onKeyDown={onKey}
      />
      <button type="button" onClick={() => step(1)} disabled={value >= max} title="Forward one month" aria-label="Forward one month">›</button>
      <button type="button" onClick={() => step(12)} disabled={value >= max} title="Forward one year" aria-label="Forward one year">»</button>
    </span>
  );
}
