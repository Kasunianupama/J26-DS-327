/**
 * Component 2 — reusable presentation primitives.
 *
 * Keeping confidence, evidence, ranges, drawers and empty states in one place
 * is what stops the vocabulary drifting between workspaces.
 */

import { useEffect, useState, type ReactNode } from 'react';
import {
  CONFIDENCE_META,
  EVIDENCE_META,
  fmtInt,
  fmtLKR,
  type Confidence,
  type EvidenceSource,
} from '../../data/component2';

/* ---------------- badges ---------------- */

export function ConfidenceBadge({ level, hint = true }: { level: Confidence; hint?: boolean }) {
  const m = CONFIDENCE_META[level];
  return (
    <span className={`pfie-badge conf-${level}`} title={hint ? m.blurb : undefined}>
      <span className="dots" aria-hidden>{m.mark}</span>
      {level} confidence
    </span>
  );
}

export function EvidenceBadge({ source }: { source: EvidenceSource }) {
  const m = EVIDENCE_META[source];
  return (
    <span className="pfie-badge ev" title={m.blurb}>
      <span aria-hidden>{m.mark}</span>
      {source}
    </span>
  );
}

export function Pill({ children, tone = 'plain', title }: { children: ReactNode; tone?: 'plain' | 'obs' | 'pred'; title?: string }) {
  return <span className={`pfie-badge ${tone}`} title={title}>{children}</span>;
}

/* ---------------- values ---------------- */

export function ForecastValue({
  label,
  value,
  unit,
  range,
  size = 'md',
  predicted = false,
}: {
  label?: string;
  value: number | string;
  unit?: string;
  range?: [number, number] | null;
  size?: 'sm' | 'md' | 'lg';
  predicted?: boolean;
}) {
  return (
    <div className={`pfie-fv${predicted ? ' pred' : ''}`}>
      {label && <div className="lbl">{label}</div>}
      <div className={`n${size === 'sm' ? ' sm' : size === 'lg' ? ' lg' : ''}`}>
        {typeof value === 'number' ? fmtInt(value) : value}
        {unit && <span style={{ fontSize: '0.5em', fontWeight: 600, marginLeft: 4 }}>{unit}</span>}
      </div>
      {range && <div className="rng">Likely range {fmtInt(range[0])}–{fmtInt(range[1])}{unit ? ` ${unit}` : ''}</div>}
    </div>
  );
}

export const LikelyRange = ({ range, unit = 'L' }: { range: [number, number]; unit?: string }) => (
  <span style={{ fontVariantNumeric: 'tabular-nums' }}>
    {fmtInt(range[0])}–{fmtInt(range[1])} {unit}
  </span>
);

export const Money = ({ k }: { k: number }) => <span>{fmtLKR(k)}</span>;

/* ---------------- layout ---------------- */

export function Card({
  title,
  sub,
  actions,
  children,
  flush,
  className = '',
}: {
  title?: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={`pfie-card${flush ? ' flush' : ''} ${className}`}>
      {(title || actions) && (
        <header className={flush ? '' : undefined} style={flush ? { padding: '18px 20px 0' } : undefined}>
          <div className="pfie-row between">
            <div>
              {title && <h3>{title}</h3>}
              {sub && <p className="sub">{sub}</p>}
            </div>
            {actions && <div className="pfie-row tight">{actions}</div>}
          </div>
        </header>
      )}
      {children}
    </section>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label?: string;
}) {
  return (
    <span className="pfie-row tight">
      {label && <span className="pfie-field" style={{ marginRight: 2 }}>{label}</span>}
      <span className="pfie-seg" role="group" aria-label={label}>
        {options.map((o) => (
          <button key={o.id} aria-pressed={value === o.id} onClick={() => onChange(o.id)}>
            {o.label}
          </button>
        ))}
      </span>
    </span>
  );
}

export function Note({
  tone = 'default',
  title,
  children,
}: {
  tone?: 'default' | 'info' | 'caution' | 'concern';
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`pfie-note${tone === 'default' ? '' : ` ${tone}`}`}>
      {title && <b>{title}</b>}
      {title && ' '}
      {children}
    </div>
  );
}

/** Designed empty / disabled-model state (§22, §32). */
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="pfie-empty">
      <b>{title}</b>
      {children}
    </div>
  );
}

/** Placeholder hand-off. Component 2 never reproduces a DelPro record page. */
export function DelProLink({ id }: { id: string }) {
  const [clicked, setClicked] = useState(false);
  useEffect(() => {
    if (!clicked) return;
    const t = setTimeout(() => setClicked(false), 2600);
    return () => clearTimeout(t);
  }, [clicked]);
  return (
    <button className="pfie-btn ghost" onClick={() => setClicked(true)}>
      {clicked ? `Would open ${id} in DelPro ↗` : 'Open full record in DelPro ↗'}
    </button>
  );
}

/* ---------------- drawer ---------------- */

export function Drawer({
  title,
  sub,
  onClose,
  wide,
  children,
}: {
  title: ReactNode;
  sub?: ReactNode;
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <div className="pfie-scrim" onClick={onClose} />
      <aside className={`pfie-drawer${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : 'Detail'}>
        <header>
          <div>
            <h3>{title}</h3>
            {sub && <p className="sub">{sub}</p>}
          </div>
          <button className="pfie-close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="content">{children}</div>
      </aside>
    </>
  );
}

/* ---------------- misc ---------------- */

export function Meter({ pct, tone = 'brand' }: { pct: number; tone?: 'brand' | 'pred' | 'caution' }) {
  return (
    <span className={`pfie-meter${tone === 'pred' ? ' pred' : tone === 'caution' ? ' caution' : ''}`}>
      <i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </span>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="pfie-subtabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Shared recharts tooltip shell so every chart explains itself the same way. */
export function TipShell({ title, rows, note }: { title: string; rows: [string, ReactNode][]; note?: ReactNode }) {
  return (
    <div className="pfie-tip">
      <div className="t">{title}</div>
      {rows.map(([k, v], i) => (
        <div className="r" key={i}><span>{k}</span><span>{v}</span></div>
      ))}
      {note && <div className="note">{note}</div>}
    </div>
  );
}

/** SVG pattern defs used to mark forecast-dependent areas without relying on colour. */
export const HATCH_DEFS = (
  <defs>
    <pattern id="pfieHatch" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
      <rect width="7" height="7" fill="#e4ecf3" />
      <line x1="0" y1="0" x2="0" y2="7" stroke="#5b7fa6" strokeWidth="2.4" opacity="0.55" />
    </pattern>
    <pattern id="pfieHatchLight" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
      <rect width="7" height="7" fill="#eef3f8" />
      <line x1="0" y1="0" x2="0" y2="7" stroke="#93aec9" strokeWidth="2.2" opacity="0.5" />
    </pattern>
    <pattern id="pfieDots" width="6" height="6" patternUnits="userSpaceOnUse">
      <rect width="6" height="6" fill="#f2f5f8" />
      <circle cx="3" cy="3" r="1.2" fill="#93aec9" />
    </pattern>
  </defs>
);
