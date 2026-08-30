/**
 * Component 2 — reusable presentation primitives.
 *
 * Keeping confidence, evidence, ranges, drawers and empty states in one place
 * is what stops the vocabulary drifting between workspaces.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  CONFIDENCE_META,
  EVIDENCE_META,
  fmtInt,
  fmtLKR,
  type Confidence,
  type EvidenceSource,
} from '../../data/component2';
import { Icon, type IconName } from './icons';
import { useC2 } from './state';

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
  icon,
  actions,
  onExpand,
  expandLabel = 'Open detail',
  children,
  flush,
  className = '',
}: {
  title?: ReactNode;
  sub?: ReactNode;
  icon?: IconName;
  actions?: ReactNode;
  onExpand?: () => void;
  expandLabel?: string;
  children: ReactNode;
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={`pfie-card${flush ? ' flush' : ''} ${className}`.trim()}>
      {(title || actions || onExpand) && (
        <header style={flush ? { padding: '20px 22px 0' } : undefined}>
          <div className="pfie-card-head">
            {icon && <span className="pfie-card-icon" aria-hidden><Icon name={icon} size={17} /></span>}
            <div className="pfie-card-headings">
              {title && <h3>{title}</h3>}
              {sub && <p className="sub">{sub}</p>}
            </div>
            {actions && <div className="pfie-row tight pfie-card-actions">{actions}</div>}
            {onExpand && (
              <button className="pfie-corner" onClick={onExpand} aria-label={expandLabel} title={expandLabel}>
                <Icon name="expand" size={14} />
              </button>
            )}
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

/* ---------------- detail view ---------------- */

const WORKSPACE_LABEL: Record<string, string> = {
  future: 'Farm Outlook',
  capacity: 'Herd & Production',
  commerce: 'Products & Income',
  evidence: 'Forecast Confidence',
  operations: 'Daily Operations',
};

/**
 * A detail view is a page, not a side panel: it takes the whole viewport, has
 * its own breadcrumb and Back control, and is backed by a history entry so the
 * browser's Back button does exactly what the in-page Back control does.
 *
 * The name stays `Drawer` because every panel already speaks it.
 */
export function Drawer({
  title,
  sub,
  eyebrow,
  actions,
  summary,
  onClose,
  wide,
  children,
}: {
  title: ReactNode;
  sub?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  /** Optional at-a-glance strip rendered directly under the title. */
  summary?: ReactNode;
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  const { workspace, detailDepth, popDrawer } = useC2();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  /* Arriving on a page means arriving at its top, not wherever the previous
     page happened to be scrolled to. */
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'auto' }); }, [title]);

  const stacked = detailDepth > 1;

  return (
    <article className={`pfie-detail${wide ? ' wide' : ''}`}>
      <nav className="pfie-detail-bar" aria-label="Detail navigation">
        <button className="pfie-btn pfie-detail-back" onClick={stacked ? popDrawer : onClose}>
          <Icon name="arrowLeft" size={14} />
          {stacked ? 'Back' : `Back to ${WORKSPACE_LABEL[workspace] ?? 'workspace'}`}
        </button>
        <span className="pfie-detail-crumbs">
          <span>{WORKSPACE_LABEL[workspace] ?? 'Workspace'}</span>
          <i aria-hidden>/</i>
          <b>{typeof title === 'string' ? title : 'Explanation'}</b>
        </span>
      </nav>

      <div className={`pfie-detail-page${wide ? ' wide' : ''}`}>
        <header className="pfie-detail-head">
          {eyebrow && <span className="pfie-detail-eyebrow">{eyebrow}</span>}
          <h2>{title}</h2>
          {sub && <p>{sub}</p>}
          {actions && <div className="pfie-row tight pfie-detail-actions">{actions}</div>}
        </header>
        {summary && <div className="pfie-detail-summary">{summary}</div>}
        <div className="pfie-detail-body">{children}</div>
      </div>
    </article>
  );
}

/**
 * A small explanation attached to a single number. Opens a compact popover;
 * when the point has a fuller story, the popover escalates into a detail view
 * rather than trying to tell it in 200px.
 */
export function InfoPoint({
  label,
  children,
  expandLabel = 'Open full detail',
  onExpand,
}: {
  label: string;
  children: ReactNode;
  expandLabel?: string;
  onExpand?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const host = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!host.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <span className="pfie-infopoint" ref={host}>
      <button
        className="pfie-infopoint-btn"
        aria-expanded={open}
        aria-label={`About ${label}`}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
      >
        i
      </button>
      {open && (
        <span className="pfie-infopop" role="note">
          <b>{label}</b>
          <span className="pfie-infopop-body">{children}</span>
          {onExpand && (
            <button
              className="pfie-btn ghost"
              onClick={(e) => { e.stopPropagation(); setOpen(false); onExpand(); }}
            >
              {expandLabel} <Icon name="arrowRight" size={12} />
            </button>
          )}
        </span>
      )}
    </span>
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

/**
 * Shared recharts tooltip shell so every chart explains itself the same way.
 *
 * A row may carry the colour of the series it came from; the swatch is what
 * lets a reader match a number in a six-series tooltip to its line.
 */
export type TipRow = [label: string, value: ReactNode, color?: string];

export function TipShell({ title, rows, note }: { title: string; rows: TipRow[]; note?: ReactNode }) {
  return (
    <div className="pfie-tip">
      <div className="t">{title}</div>
      {rows.map(([k, v, color], i) => (
        <div className="r" key={i}>
          <span>
            {color && <i className="sw" style={{ background: color }} aria-hidden />}
            {k}
          </span>
          <span>{v}</span>
        </div>
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

/* ---------------- headline presentation ---------------- */

/**
 * Compact trend line. Purely decorative support for a number that is already
 * stated in text, so it carries no axis and is hidden from assistive tech.
 */
export function Sparkline({
  data,
  tone = 'brand',
  width = 104,
  height = 30,
}: {
  data: number[];
  tone?: 'brand' | 'pred' | 'concern';
  width?: number;
  height?: number;
}) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = Math.max(1e-6, max - min);
  const pad = 2.5;
  const x = (i: number) => (i / (data.length - 1)) * (width - pad * 2) + pad;
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2);
  const line = data.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(data.length - 1).toFixed(1)},${height} L${x(0).toFixed(1)},${height} Z`;
  const id = `pfieSpark-${tone}`;

  return (
    <svg className={`pfie-spark tone-${tone}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden focusable="false">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.24" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={x(data.length - 1)} cy={y(data[data.length - 1])} r="2.4" fill="currentColor" />
    </svg>
  );
}

/** Signed change chip. `goodWhenUp` flips the tone for costs and shortfalls. */
export function DeltaChip({
  value,
  unit = '%',
  goodWhenUp = true,
  dp = 1,
}: {
  value: number;
  unit?: string;
  goodWhenUp?: boolean;
  dp?: number;
}) {
  const up = value >= 0;
  const good = up === goodWhenUp;
  return (
    <span className={`pfie-delta ${good ? 'good' : 'bad'}`}>
      <Icon name={up ? 'trendUp' : 'trendDown'} size={12} />
      {up ? '+' : '−'}{Math.abs(value).toFixed(dp)}{unit}
    </span>
  );
}

/**
 * Radial confidence arc. The three-level confidence vocabulary stays the
 * source of truth — the arc only makes the level readable at a glance.
 */
export function Gauge({
  pct,
  caption,
  sub,
  size = 132,
  tone = 'brand',
}: {
  pct: number;
  caption: ReactNode;
  sub?: ReactNode;
  size?: number;
  tone?: 'brand' | 'pred' | 'caution' | 'concern';
}) {
  const stroke = 9;
  const r = (size - stroke) / 2 - 1;
  const c = size / 2;
  /* 270° sweep starting bottom-left, the same reading direction as a dial. */
  const sweep = 0.75;
  const circumference = 2 * Math.PI * r;
  const value = Math.max(0, Math.min(100, pct)) / 100;

  return (
    <div className={`pfie-gauge tone-${tone}`} style={{ width: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden focusable="false">
        <g transform={`rotate(135 ${c} ${c})`}>
          <circle
            cx={c} cy={c} r={r} fill="none" strokeWidth={stroke} strokeLinecap="round"
            className="track"
            strokeDasharray={`${circumference * sweep} ${circumference}`}
          />
          <circle
            cx={c} cy={c} r={r} fill="none" strokeWidth={stroke} strokeLinecap="round"
            className="value"
            strokeDasharray={`${circumference * sweep * value} ${circumference}`}
          />
        </g>
      </svg>
      <div className="pfie-gauge-face">
        <b>{Math.round(pct)}<i>%</i></b>
        <span>{caption}</span>
      </div>
      {sub && <p className="pfie-gauge-sub">{sub}</p>}
    </div>
  );
}

/** One metric in the command strip or a consequence grid. */
export function KpiTile({
  icon,
  label,
  value,
  unit,
  delta,
  foot,
  tone = 'plain',
  spark,
  sparkTone,
  onClick,
}: {
  icon?: IconName;
  label: ReactNode;
  value: ReactNode;
  unit?: string;
  delta?: ReactNode;
  foot?: ReactNode;
  tone?: 'plain' | 'brand' | 'pred' | 'caution' | 'concern';
  spark?: number[];
  sparkTone?: 'brand' | 'pred' | 'concern';
  onClick?: () => void;
}) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag className={`pfie-kpi tone-${tone}${onClick ? ' clickable' : ''}`} onClick={onClick} type={onClick ? 'button' : undefined}>
      <span className="pfie-kpi-top">
        {icon && <span className="pfie-kpi-icon" aria-hidden><Icon name={icon} size={15} /></span>}
        <span className="pfie-kpi-label">{label}</span>
      </span>
      <span className="pfie-kpi-main">
        <span className="pfie-kpi-value">
          {value}
          {unit && <i>{unit}</i>}
        </span>
        {delta}
      </span>
      {spark && <Sparkline data={spark} tone={sparkTone ?? 'brand'} width={132} height={26} />}
      {foot && <span className="pfie-kpi-foot">{foot}</span>}
    </Tag>
  );
}

/** Row of KPI tiles. Wraps into a grid rather than scrolling sideways. */
export function KpiStrip({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`pfie-kpistrip ${className}`.trim()}>{children}</div>;
}
