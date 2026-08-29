/**
 * Master historical → current → future timeline (§8).
 *
 * Four synchronized bands over one shared time axis. Observed data is solid
 * green, predicted is muted blue with a likely-range envelope, and anything
 * that depends on a transition which has not happened yet is hatched as well as
 * coloured, so the distinction survives without colour.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  DEFINING_MOVEMENT,
  FINANCE_MONTHS,
  HISTORY_DAYS,
  HORIZONS,
  PRODUCTS,
  PRODUCT_META,
  PRODUCT_WEEKS,
  TODAY_ISO,
  WINDOW_END,
  WINDOW_START,
  fmtInt,
  fmtLKR,
  monthly,
  shortDate,
  weekly,
  type Bucket,
} from '../../../data/component2';
import { useC2, type ForecastDomain } from '../state';
import { ConfidenceBadge, HATCH_DEFS, TipShell } from '../ui';

type BandId = ForecastDomain;
type HistoryRange = '6m' | '1y' | '2y' | 'all';
type Expansion = BandId | 'all' | 'compact';

const BANDS: { id: BandId; label: string; hint: string }[] = [
  { id: 'herd', label: 'Herd & milk', hint: 'Expected litres and milking head' },
  { id: 'repro', label: 'Reproduction & health', hint: 'Calvings, dry-offs and health events' },
  { id: 'products', label: 'Products', hint: 'Allocation across the four product lines' },
  { id: 'finance', label: 'Finance & context', hint: 'Revenue, cost, margin and heat index' },
];

interface Row {
  label: string;
  start: string;
  future: boolean;
  observed: number | null;
  expected: number | null;
  band: [number, number] | null;
  bandWidth: number;
  milkers: number;
  calvings: number;
  dryOffs: number;
  health: number;
  thi: number;
  confidence: string;
  revenue: number | null;
  revenueForecast: number | null;
  cost: number | null;
  margin: number | null;
  marginForecast: number | null;
  raw: number;
  tetra: number;
  yoghurt: number;
  other: number;
  tetraShort: number;
}

function buildRows(buckets: Bucket[], granularity: 'week' | 'month'): Row[] {
  return buckets.map((b) => {
    const pw = granularity === 'week'
      ? PRODUCT_WEEKS.find((w) => w.key === b.key)
      : undefined;
    const fm = FINANCE_MONTHS.find((f) => f.key === b.key);

    // Product split at week resolution comes from the weekly allocation;
    // at month resolution it is scaled from the monthly finance record.
    const alloc = pw?.allocation;
    const scale = alloc ? 1 : b.total;

    return {
      label: b.label,
      start: b.start,
      future: b.future,
      observed: b.observed,
      expected: b.future ? b.expected : null,
      band: b.future && b.lower !== null && b.upper !== null ? [b.lower, b.upper] : null,
      bandWidth: b.future && b.lower !== null && b.upper !== null ? b.upper - b.lower : 0,
      milkers: b.milkers,
      calvings: b.calvings,
      dryOffs: -b.dryOffs,
      health: Math.round(b.milkers * 0.04),
      thi: b.thi,
      confidence: b.confidence,
      revenue: fm?.revenue ?? null,
      revenueForecast: fm?.revenueForecast ?? null,
      cost: fm?.cost ?? fm?.costForecast ?? null,
      margin: fm?.margin ?? null,
      marginForecast: fm?.marginForecast ?? null,
      raw: alloc ? alloc['Raw milk'] : Math.round(scale * 0.64),
      tetra: alloc ? alloc['Tetra pack'] : Math.round(scale * 0.28),
      yoghurt: alloc ? alloc['Yoghurt'] : Math.round(scale * 0.06),
      other: alloc ? alloc['Other by-products'] : Math.round(scale * 0.02),
      tetraShort: pw?.shortfall['Tetra pack'] ?? 0,
    };
  });
}

export function MasterTimeline() {
  const { horizon, selectedDate, setSelectedDate, compareDate, setCompareDate, openDrawer } = useC2();
  const [expanded, setExpanded] = useState<Expansion>('all');
  const [collapsed, setCollapsed] = useState<Set<BandId>>(new Set());
  const [historyRange, setHistoryRange] = useState<HistoryRange>('all');
  const [fullScreenBand, setFullScreenBand] = useState<BandId | null>(null);
  const [selectedBand, setSelectedBand] = useState<BandId>('herd');
  const bandRefs = useRef<Partial<Record<BandId, HTMLDivElement>>>({});

  useEffect(() => {
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) setFullScreenBand(null);
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, []);

  const ahead = HORIZONS.find((option) => option.id === horizon)?.days ?? 365;
  const granularity: 'week' | 'month' = ahead > 90 || historyRange === 'all' ? 'month' : 'week';
  const back = historyRange === '6m' ? 182 : historyRange === '1y' ? 365 : historyRange === '2y' ? 730 : HISTORY_DAYS;
  const rangeConfidence = ahead <= 30 ? 'High' : ahead <= 150 ? 'Moderate' : 'Limited';

  const rows = useMemo(() => {
    const buckets = granularity === 'week' ? weekly(-back, ahead) : monthly(-back, ahead);
    return buildRows(buckets, granularity);
  }, [granularity, back, ahead]);

  const todayRow = rows.find((r) => r.start > TODAY_ISO) ?? rows[rows.length - 1];
  const selectedRow =
    rows.find((r, i) => r.start <= selectedDate && (!rows[i + 1] || rows[i + 1].start > selectedDate)) ?? null;

  const eventStart = rows.find((r) => r.start >= DEFINING_MOVEMENT.windowStart);
  const eventEnd = rows.find((r) => r.start >= DEFINING_MOVEMENT.windowEnd);

  const onChartClick = (domain: BandId, e: { activeLabel?: string | number } | null) => {
    if (!e?.activeLabel) return;
    const row = rows.find((r) => r.label === String(e.activeLabel));
    if (!row) return;
    setSelectedBand(domain);
    setSelectedDate(row.start);
    openDrawer({ kind: 'structure', date: row.start, domain });
  };

  const isCollapsed = (id: BandId) => collapsed.has(id);
  const toggle = (id: BandId) =>
    setCollapsed((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });

  /** Expanded band gets full height; the others compress to context strips. */
  const heightFor = (id: BandId) => {
    if (isCollapsed(id)) return 0;
    if (fullScreenBand === id) return 700;
    if (expanded === 'all') return 240;
    if (expanded === id) return 340;
    return 82;
  };
  const isExpandedView = (id: BandId) =>
    expanded === 'all' || expanded === id || fullScreenBand === id;

  const showFullScreen = async (id: BandId) => {
    const node = bandRefs.current[id];
    if (!node?.requestFullscreen) return;
    setFullScreenBand(id);
    await node.requestFullscreen();
  };

  const moveSelectedDate = (days: number) => {
    const d = new Date(`${selectedDate}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + days);
    const next = d.toISOString().slice(0, 10);
    setSelectedDate(next < WINDOW_START ? WINDOW_START : next > WINDOW_END ? WINDOW_END : next);
  };
  const periodStep = granularity === 'week' ? 7 : 30;

  const shared = {
    data: rows,
    margin: { top: 6, right: 10, left: 0, bottom: 0 },
  };

  const axis = (compact: boolean) => (
    <>
      <CartesianGrid stroke="#eef2f0" vertical={false} />
      <XAxis
        dataKey="label"
        tick={compact ? false : { fontSize: 10, fill: '#93a29b' }}
        axisLine={{ stroke: '#e2e9e5' }}
        tickLine={false}
        height={compact ? 4 : 22}
        interval="preserveStartEnd"
        minTickGap={26}
      />
    </>
  );

  const markers = (
    <>
      {todayRow && (
        <ReferenceLine
          x={todayRow.label}
          stroke="#1d2b26"
          strokeWidth={1.5}
          label={{ value: 'Today', position: 'insideTopLeft', fill: '#1d2b26', fontSize: 10, fontWeight: 700 }}
        />
      )}
      {eventStart && eventEnd && (
        <ReferenceArea x1={eventStart.label} x2={eventEnd.label} fill="#a44b3c" fillOpacity={0.07} />
      )}
      {selectedRow && <ReferenceLine x={selectedRow.label} stroke="#5b7fa6" strokeWidth={2} strokeDasharray="4 3" />}
      {compareDate && (() => {
        const r = rows.find((x, i) => x.start <= compareDate && (!rows[i + 1] || rows[i + 1].start > compareDate));
        return r ? <ReferenceLine x={r.label} stroke="#b8860b" strokeWidth={2} strokeDasharray="2 3" /> : null;
      })()}
    </>
  );

  return (
    <section className="pfie-card flush">
      <header style={{ padding: '18px 20px 12px', borderBottom: '1px solid var(--line)' }}>
        <div className="pfie-row between">
          <div>
            <h3>Farm timeline</h3>
            <p className="sub">
              Recorded history, today, and the expected path. Hover for details from that chart only; click to
              lock the point and open its full reasoning pathway.
            </p>
          </div>
          <div className="pfie-timeline-controls">
            <button className="pfie-btn" onClick={() => setExpanded(expanded === 'all' ? 'compact' : 'all')}>
              {expanded === 'all' ? 'Compact all charts' : 'Expand all charts'}
            </button>
            <span className="pfie-seg" role="group" aria-label="History shown">
              {([
                ['6m', '6 months'],
                ['1y', '1 year'],
                ['2y', '2 years'],
                ['all', 'Since 2024'],
              ] as [HistoryRange, string][]).map(([id, label]) => (
                <button key={id} aria-pressed={historyRange === id} onClick={() => setHistoryRange(id)}>
                  {label}
                </button>
              ))}
            </span>
            <span className="pfie-date-nav" aria-label="Selected timeline date">
              <button className="pfie-btn" onClick={() => moveSelectedDate(-periodStep)} aria-label="Previous period">‹</button>
              <label>
                <span>Selected date</span>
                <input
                  type="date"
                  min={WINDOW_START}
                  max={WINDOW_END}
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                />
              </label>
              <button className="pfie-btn" onClick={() => moveSelectedDate(periodStep)} aria-label="Next period">›</button>
              <button className="pfie-btn ghost" onClick={() => setSelectedDate(TODAY_ISO)}>Today</button>
            </span>
            {selectedRow && (
              <button
                className="pfie-btn"
                onClick={() =>
                  setCompareDate(compareDate ? null : selectedRow.start === TODAY_ISO ? DEFINING_MOVEMENT.windowEnd : TODAY_ISO)
                }
              >
                {compareDate ? 'Clear comparison' : 'Compare two dates'}
              </button>
            )}
            {compareDate && (
              <label className="pfie-date-compare">
                <span>Compare with</span>
                <input
                  type="date"
                  min={WINDOW_START}
                  max={WINDOW_END}
                  value={compareDate}
                  onChange={(e) => setCompareDate(e.target.value)}
                />
              </label>
            )}
            <span className="pfie-range-confidence" title="Confidence falls as more of the selected range relies on transitions that have not happened yet.">
              <span>Range confidence</span>
              <ConfidenceBadge level={rangeConfidence} hint={false} />
            </span>
            <button className="pfie-btn primary" onClick={() => openDrawer({ kind: 'structure', date: selectedDate, domain: selectedBand })}>
              Explain selected {BANDS.find((band) => band.id === selectedBand)?.label.toLowerCase()}
            </button>
          </div>
        </div>
      </header>

      {BANDS.map((b) => {
        const h = heightFor(b.id);
        return (
          <div
            className={`pfie-band${fullScreenBand === b.id ? ' fullscreen' : ''}`}
            key={b.id}
            ref={(node) => { bandRefs.current[b.id] = node ?? undefined; }}
          >
            <div className="bandheadrow">
              <button
                className="bandhead"
                onClick={() => toggle(b.id)}
                aria-expanded={!isCollapsed(b.id)}
              >
                <span className="chev" aria-hidden>{isCollapsed(b.id) ? '▶' : '▼'}</span>
                <span>{b.label}</span>
                <span className="bandmeta">{b.hint}</span>
              </button>
              {!isCollapsed(b.id) && (
                <>
                  <button
                    className="pfie-band-expand"
                    onClick={() => setExpanded(expanded === b.id ? 'all' : b.id)}
                    aria-pressed={expanded === b.id}
                  >
                    {expanded === b.id ? 'Show all' : 'Focus'}
                  </button>
                  <button className="pfie-band-fullscreen" onClick={() => void showFullScreen(b.id)} aria-label={`View ${b.label} full screen`} title="Full screen">
                    ⛶
                  </button>
                </>
              )}
            </div>

            {!isCollapsed(b.id) && (
              <div className="bandbody">
                <ResponsiveContainer width="100%" height={h}>
                  {b.id === 'herd' ? (
                    <ComposedChart {...shared} onClick={(event) => onChartClick('herd', event)}>
                      {HATCH_DEFS}
                      {axis(!isExpandedView('herd'))}
                      <YAxis
                        tick={expanded === 'herd' ? { fontSize: 10, fill: '#93a29b' } : false}
                        axisLine={false}
                        tickLine={false}
                        width={expanded === 'herd' ? 52 : 4}
                        tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`}
                      />
                      <Tooltip content={<BandTip band="herd" rows={rows} />} cursor={{ stroke: '#93a29b', strokeDasharray: '3 3' }} />
                      <Area
                        dataKey="band"
                        stroke="none"
                        fill="url(#pfieHatchLight)"
                        fillOpacity={0.85}
                        isAnimationActive={false}
                        name="Likely range"
                      />
                      <Line dataKey="observed" stroke="#1f6b4a" strokeWidth={2} dot={false} isAnimationActive={false} name="Recorded" />
                      <Line dataKey="expected" stroke="#5b7fa6" strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} name="Expected" />
                      {markers}
                    </ComposedChart>
                  ) : b.id === 'repro' ? (
                    <ComposedChart {...shared} stackOffset="sign" onClick={(event) => onChartClick('repro', event)}>
                      {axis(!isExpandedView('repro'))}
                      <YAxis tick={expanded === 'repro' ? { fontSize: 10, fill: '#93a29b' } : false} axisLine={false} tickLine={false} width={expanded === 'repro' ? 52 : 4} />
                      <Tooltip content={<BandTip band="repro" rows={rows} />} cursor={{ fill: 'rgba(147,162,155,.12)' }} />
                      <ReferenceLine y={0} stroke="#dfe6e2" />
                      <Bar dataKey="calvings" stackId="r" fill="#5b7fa6" name="Expected calvings" isAnimationActive={false} />
                      <Bar dataKey="dryOffs" stackId="r" fill="#b8860b" name="Dry-offs" isAnimationActive={false} />
                      {markers}
                    </ComposedChart>
                  ) : b.id === 'products' ? (
                    <ComposedChart {...shared} onClick={(event) => onChartClick('products', event)}>
                      {axis(!isExpandedView('products'))}
                      <YAxis tick={expanded === 'products' ? { fontSize: 10, fill: '#93a29b' } : false} axisLine={false} tickLine={false} width={expanded === 'products' ? 52 : 4} tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`} />
                      <Tooltip content={<BandTip band="products" rows={rows} />} cursor={{ fill: 'rgba(147,162,155,.12)' }} />
                      <Area dataKey="raw" stackId="p" stroke={PRODUCT_META['Raw milk'].color} fill={PRODUCT_META['Raw milk'].color} fillOpacity={0.75} isAnimationActive={false} name="Raw milk" />
                      <Area dataKey="tetra" stackId="p" stroke={PRODUCT_META['Tetra pack'].color} fill={PRODUCT_META['Tetra pack'].color} fillOpacity={0.75} isAnimationActive={false} name="Tetra pack" />
                      <Area dataKey="yoghurt" stackId="p" stroke={PRODUCT_META.Yoghurt.color} fill={PRODUCT_META.Yoghurt.color} fillOpacity={0.75} isAnimationActive={false} name="Yoghurt" />
                      <Area dataKey="other" stackId="p" stroke={PRODUCT_META['Other by-products'].color} fill={PRODUCT_META['Other by-products'].color} fillOpacity={0.75} isAnimationActive={false} name="Other" />
                      {markers}
                    </ComposedChart>
                  ) : (
                    <ComposedChart {...shared} onClick={(event) => onChartClick('finance', event)}>
                      {axis(!isExpandedView('finance'))}
                      <YAxis tick={expanded === 'finance' ? { fontSize: 10, fill: '#93a29b' } : false} axisLine={false} tickLine={false} width={expanded === 'finance' ? 52 : 4} />
                      <Tooltip content={<BandTip band="finance" rows={rows} />} cursor={{ stroke: '#93a29b', strokeDasharray: '3 3' }} />
                      <Bar dataKey="margin" fill="#1f6b4a" name="Recorded margin" isAnimationActive={false} />
                      <Bar dataKey="marginForecast" fill="url(#pfieHatch)" stroke="#5b7fa6" name="Expected margin" isAnimationActive={false} />
                      <Line dataKey="thi" stroke="#a8770a" strokeWidth={1.4} dot={false} yAxisId="thi" isAnimationActive={false} name="Heat index" />
                      <YAxis yAxisId="thi" orientation="right" hide domain={[60, 92]} />
                      {markers}
                    </ComposedChart>
                  )}
                </ResponsiveContainer>
              </div>
            )}
          </div>
        );
      })}

      <div style={{ padding: '12px 20px 18px' }}>
        <div className="pfie-legend">
          <span><i style={{ background: '#1f6b4a' }} />Recorded — solid</span>
          <span><i className="dash" />Expected — dashed blue</span>
          <span><i className="hatch" />Likely range / transition-dependent — hatched</span>
          <span><i style={{ background: '#1d2b26', width: 2 }} />Today</span>
          <span><i style={{ background: 'rgba(164,75,60,.25)' }} />October transition window</span>
        </div>
        <p className="sub" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--muted)' }}>
          Each band can be collapsed. Expand one band for detailed inspection while the other timelines remain as
          compact context strips.
        </p>
      </div>
    </section>
  );
}

/** A tooltip stays within the domain the user is hovering. */
function BandTip({ band, active, label, rows }: { band: BandId; active?: boolean; label?: string | number; rows?: Row[] }) {
  if (!active || !label || !rows) return null;
  const index = rows.findIndex((x) => x.label === String(label));
  const r = rows[index];
  if (!r) return null;
  const previous = rows[Math.max(0, index - 1)];
  const constraint = r.tetraShort > 0 ? (r.tetraShort > 2500 ? 'High' : r.tetraShort > 800 ? 'Moderate' : 'Mild') : 'None';
  const title = `${r.future ? 'Expected' : 'Recorded'} — ${r.label}`;
  const standardNote = r.future
    ? `${r.confidence} confidence. Click to select this point and open the full explanation.`
    : 'Recorded point. Click to select it and open the full explanation.';

  if (band === 'herd') {
    const milk = r.expected ?? r.observed ?? 0;
    const priorMilk = previous?.expected ?? previous?.observed ?? milk;
    const milkDelta = milk - priorMilk;
    const herdDelta = r.milkers - (previous?.milkers ?? r.milkers);
    const movement = milkDelta >= 0
      ? `${herdDelta >= 0 ? `${herdDelta > 0 ? '+' : ''}${herdDelta} milking head; ` : ''}more production is coming from cows approaching peak than from tapering cows.`
      : `${Math.abs(r.dryOffs)} dry-offs in this period and tapering cows are outweighing new production.`;
    return <TipShell title={title} rows={[
      [r.future ? 'Expected milk' : 'Recorded milk', `${fmtInt(milk)} L`],
      ...(r.band ? ([['Likely range', `${fmtInt(r.band[0])}–${fmtInt(r.band[1])} L`]] as [string, string][]) : []),
      ['Milking herd', `${r.milkers} head`],
      ['Change vs previous', `${milkDelta >= 0 ? '+' : '−'}${fmtInt(Math.abs(milkDelta))} L`],
    ]} note={`Why it moved: ${movement} ${standardNote}`} />;
  }

  if (band === 'repro') {
    const calvingDelta = r.calvings - (previous?.calvings ?? r.calvings);
    const dryOffDelta = Math.abs(r.dryOffs) - Math.abs(previous?.dryOffs ?? r.dryOffs);
    const movement = calvingDelta - dryOffDelta >= 0
      ? 'The transition balance is stronger than the previous period, supporting future milk capacity.'
      : 'Dry-offs are running ahead of new entries relative to the previous period, increasing capacity pressure.';
    return <TipShell title={title} rows={[
      ['Calvings', `${r.calvings}`],
      ['Dry-offs', `${Math.abs(r.dryOffs)}`],
      ['Health events flagged', `${r.health}`],
      ['Change vs previous', `${calvingDelta >= 0 ? '+' : '−'}${Math.abs(calvingDelta)} calvings · ${dryOffDelta >= 0 ? '+' : '−'}${Math.abs(dryOffDelta)} dry-offs`],
    ]} note={`Why it moved: ${movement} ${standardNote}`} />;
  }

  if (band === 'products') {
    const rawDelta = r.raw - (previous?.raw ?? r.raw);
    const tetraDelta = r.tetra - (previous?.tetra ?? r.tetra);
    const movement = constraint === 'None'
      ? 'All product lines remain within plan; output changes follow the available milk supply.'
      : `The raw-milk contract is allocated first, so tetra pack absorbs the ${constraint.toLowerCase()} supply constraint.`;
    return <TipShell title={title} rows={[
      ['Raw milk', `${fmtInt(r.raw)} L`],
      ['Tetra pack', `${fmtInt(r.tetra)} L`],
      ['Yoghurt', `${fmtInt(r.yoghurt)} L`],
      ['Product constraint', constraint],
      ['Change vs previous', `Raw ${rawDelta >= 0 ? '+' : '−'}${fmtInt(Math.abs(rawDelta))} L · Tetra ${tetraDelta >= 0 ? '+' : '−'}${fmtInt(Math.abs(tetraDelta))} L`],
    ]} note={`Why it moved: ${movement} ${standardNote}`} />;
  }

  const margin = r.marginForecast ?? r.margin ?? 0;
  const previousMargin = previous?.marginForecast ?? previous?.margin ?? margin;
  const marginDelta = margin - previousMargin;
  const heatDelta = r.thi - (previous?.thi ?? r.thi);
  const movement = marginDelta >= 0
    ? 'The margin is improving with revenue and available milk relative to the previous period.'
    : 'The margin is under pressure from the milk/product mix and continuing cost base relative to the previous period.';

  return (
    <TipShell
      title={title}
      rows={[
        ['Revenue', fmtLKR(r.revenueForecast ?? r.revenue ?? 0)],
        ['Cost', fmtLKR(r.cost ?? 0)],
        ['Margin', fmtLKR(margin)],
        ['Heat index', `${r.thi}`],
        ['Change vs previous', `${marginDelta >= 0 ? '+' : '−'}${fmtLKR(Math.abs(marginDelta))} · heat ${heatDelta >= 0 ? '+' : '−'}${Math.abs(heatDelta).toFixed(1)}`],
      ]}
      note={`Why it moved: ${movement} ${standardNote}`}
    />
  );
}
