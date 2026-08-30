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
  DISEASE_CATEGORIES,
  DISEASE_COLOR,
  TREATMENT_CATEGORIES,
  TREATMENT_COLOR,
  FINANCE_MONTHS,
  HISTORY_DAYS,
  HORIZONS,
  MAX_FORECAST_DAYS,
  POPULATION_SERIES,
  PRODUCT_META,
  PRODUCT_WEEKS,
  TODAY_ISO,
  WINDOW_END,
  WINDOW_START,
  fmtInt,
  fmtLKR,
  measuresFor,
  round,
  costByCategory,
  COST_CATEGORIES,
  COST_CATEGORY_COLOR,
  PRODUCT_MONTHS,
  monthly,
  weekly,
  type Bucket,
  type DiseaseCategory,
  type TreatmentCategory,
  type PopulationSeriesKey,
} from '../../../data/component2';
import { useC2, type ForecastDomain } from '../state';
import { ConfidenceBadge, HATCH_DEFS, TipShell, type TipRow } from '../ui';

type BandId = ForecastDomain | 'population';
type HistoryRange = '6m' | '1y' | '2y' | 'all';
/** The timeline is where a long view belongs, so it can outrun the page horizon. */
type FutureRange = 'match' | '12m' | '18m' | '24m';
type Expansion = BandId | 'all' | 'compact';

/** Litres and head counts share an x axis but never a y axis. */
type HerdMeasure = 'litres' | 'head' | 'both';
type PopulationMode = 'lines' | 'stacked' | 'total';
/**
 * The health band is mix-and-match rather than one-of: abortions, disease and
 * temperature only mean anything next to each other, so any combination has to
 * be drawable. Presets are shortcuts into that set, not modes.
 */
type ReproSeries =
  | 'calvings' | 'dryOffs'
  | 'abortions' | 'deaths'
  | 'disease' | 'diseaseSplit'
  | 'vaccinations' | 'treatments' | 'treatmentSplit'
  | 'thi';

const REPRO_SERIES: { key: ReproSeries; label: string; color: string; group: string }[] = [
  { key: 'calvings', label: 'Calvings', color: '#5b7fa6', group: 'Transitions' },
  { key: 'dryOffs', label: 'Dry-offs', color: '#b8860b', group: 'Transitions' },
  { key: 'abortions', label: 'Abortions', color: '#a44b3c', group: 'Outcomes' },
  { key: 'deaths', label: 'Deaths', color: '#6c321a', group: 'Outcomes' },
  { key: 'disease', label: 'Disease total', color: '#8a6cb5', group: 'Disease' },
  { key: 'diseaseSplit', label: 'Disease by category', color: '#8a6cb5', group: 'Disease' },
  { key: 'vaccinations', label: 'Vaccinations', color: '#1f6b4a', group: 'Care' },
  { key: 'treatments', label: 'Treatments total', color: '#9a4f27', group: 'Care' },
  { key: 'treatmentSplit', label: 'Treatments by type', color: '#9a4f27', group: 'Care' },
  { key: 'thi', label: 'Heat index', color: '#a8770a', group: 'Context' },
];

const REPRO_PRESETS: { label: string; series: ReproSeries[] }[] = [
  { label: 'Calvings & dry-offs', series: ['calvings', 'dryOffs'] },
  { label: 'Losses vs heat', series: ['abortions', 'deaths', 'thi'] },
  { label: 'Disease & treatment', series: ['diseaseSplit', 'treatments', 'thi'] },
  { label: 'Preventive care', series: ['vaccinations', 'treatmentSplit'] },
  { label: 'Everything', series: ['abortions', 'deaths', 'disease', 'vaccinations', 'treatments', 'thi'] },
];
type FinanceMeasure = 'margin' | 'revenue' | 'cost' | 'all';
type FinanceMacro = 'none' | 'cpiInflation' | 'feedPriceIndex' | 'farmgatePriceIndex';

/** The structure drawer only knows the four forecast domains. */
const DOMAIN_FOR: Record<BandId, ForecastDomain> = {
  herd: 'herd',
  population: 'herd',
  repro: 'repro',
  products: 'products',
  finance: 'finance',
};

const BANDS: { id: BandId; label: string; hint: string }[] = [
  { id: 'herd', label: 'Herd & milk', hint: 'Expected litres and milking head' },
  { id: 'population', label: 'Herd population', hint: 'Milking, dry, pregnant, heifers, calves and males' },
  { id: 'repro', label: 'Reproduction & health', hint: 'Transitions, outcomes, disease and preventive care' },
  { id: 'products', label: 'Products', hint: 'Allocation across the four product lines' },
  { id: 'finance', label: 'Finance & context', hint: 'Revenue, cost, margin and macroeconomic context' },
];

/** One colour per health series, shared by the chart, the chips and the tooltip. */
const HEALTH_COLOR = {
  calvings: '#5b7fa6',
  dryOffs: '#b8860b',
  abortions: '#a44b3c',
  deaths: '#6c321a',
  vaccinations: '#1f6b4a',
  vetTreatments: '#9a4f27',
  disease: '#8a6cb5',
  thi: '#a8770a',
} as const;

const REVENUE_COLOR: Record<string, string> = {
  revRaw: '#1f6b4a',
  revTetra: '#5b7fa6',
  revYoghurt: '#b8860b',
  revOther: '#8a9a94',
};

const MACRO_META: Record<Exclude<FinanceMacro, 'none'>, { label: string; unit: string; domain: [number, number] }> = {
  cpiInflation: { label: 'CPI inflation', unit: '%', domain: [0, 14] },
  feedPriceIndex: { label: 'Feed price index', unit: '', domain: [90, 135] },
  farmgatePriceIndex: { label: 'Farmgate price index', unit: '', domain: [90, 135] },
};

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

  /* population, at the start of the bucket */
  milking: number;
  dry: number;
  pregnant: number;
  heifer: number;
  calf: number;
  male: number;
  totalHerd: number;

  /* health over the bucket */
  abortions: number;
  deaths: number;
  diseaseTotal: number;
  vaccinations: number;
  vetTreatments: number;
  disease: Record<DiseaseCategory, number>;
  treatments: Record<TreatmentCategory, number>;

  /* finance detail */
  revRaw: number;
  revTetra: number;
  revYoghurt: number;
  revOther: number;
  costByCat: Record<string, number>;
  profit: number;
  revenueAny: number;
  costAny: number;
  budgetMargin: number;

  /* macroeconomic context */
  cpiInflation: number;
  feedPriceIndex: number;
  farmgatePriceIndex: number;
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
    const m = measuresFor(b, granularity);
    const pm = PRODUCT_MONTHS.find((x) => x.key === b.start.slice(0, 7));
    const pmRevenue = pm?.revenue;
    /* A week carries roughly a quarter of the month's cost. */
    const costShare = granularity === 'week' ? 7 / 30.44 : 1;
    const costSplit = Object.entries(costByCategory(b.milkers, b.total)).reduce(
      (acc, [k, v]) => ({ ...acc, [k]: Math.round(v * costShare) }),
      {} as Record<string, number>,
    );

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

      milking: m.milking,
      dry: m.dry,
      pregnant: m.pregnant,
      heifer: m.heifer,
      calf: m.calf,
      male: m.male,
      totalHerd: m.totalHerd,

      abortions: m.abortions,
      deaths: m.deaths,
      diseaseTotal: m.diseaseTotal,
      vaccinations: m.vaccinations,
      vetTreatments: m.vetTreatments,
      disease: m.disease,
      treatments: m.treatments,
      /* Recharts reads flat keys, so each category is also lifted to the row. */
      ...DISEASE_CATEGORIES.reduce((acc, c) => ({ ...acc, [`d_${c}`]: m.disease[c] }), {}),
      ...TREATMENT_CATEGORIES.reduce((acc, c) => ({ ...acc, [`t_${c}`]: m.treatments[c] }), {}),

      revRaw: pmRevenue?.['Raw milk'] ?? 0,
      revTetra: pmRevenue?.['Tetra pack'] ?? 0,
      revYoghurt: pmRevenue?.Yoghurt ?? 0,
      revOther: pmRevenue?.['Other by-products'] ?? 0,
      costByCat: costSplit,
      profit: fm?.marginForecast ?? fm?.margin ?? 0,
      revenueAny: fm?.revenueForecast ?? fm?.revenue ?? 0,
      costAny: fm?.cost ?? fm?.costForecast ?? 0,
      budgetMargin: fm?.budgetMargin ?? 0,
      ...Object.entries(costSplit).reduce((acc, [k, v]) => ({ ...acc, [`c_${k}`]: v }), {}),

      cpiInflation: m.cpiInflation,
      feedPriceIndex: m.feedPriceIndex,
      farmgatePriceIndex: m.farmgatePriceIndex,
    } as Row;
  });
}

export function MasterTimeline() {
  const { horizon, selectedDate, setSelectedDate, compareDate, setCompareDate, openDrawer } = useC2();
  /* Opens focused rather than fully expanded: one readable chart plus four
     context strips fits a laptop screen, where five full charts do not. */
  const [expanded, setExpanded] = useState<Expansion>('herd');
  const [collapsed, setCollapsed] = useState<Set<BandId>>(new Set());
  const [historyRange, setHistoryRange] = useState<HistoryRange>('all');
  const [futureRange, setFutureRange] = useState<FutureRange>('18m');
  const [fullScreenBand, setFullScreenBand] = useState<BandId | null>(null);
  const [selectedBand, setSelectedBand] = useState<BandId>('herd');
  const [herdMeasure, setHerdMeasure] = useState<HerdMeasure>('litres');
  const [populationMode, setPopulationMode] = useState<PopulationMode>('lines');
  const [populationSeries, setPopulationSeries] = useState<Set<PopulationSeriesKey>>(
    () => new Set(POPULATION_SERIES.map((s) => s.key)),
  );
  const [reproSeries, setReproSeries] = useState<Set<ReproSeries>>(
    () => new Set<ReproSeries>(['calvings', 'dryOffs', 'thi']),
  );
  const [financeMacro, setFinanceMacro] = useState<FinanceMacro>('cpiInflation');
  const [financeMeasure, setFinanceMeasure] = useState<FinanceMeasure>('margin');
  const bandRefs = useRef<Partial<Record<BandId, HTMLDivElement>>>({});

  useEffect(() => {
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) setFullScreenBand(null);
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, []);

  const horizonDays = HORIZONS.find((option) => option.id === horizon)?.days ?? 365;
  const ahead = futureRange === 'match' ? horizonDays
    : futureRange === '12m' ? 365
    : futureRange === '18m' ? 548
    : MAX_FORECAST_DAYS;
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

  /* Clicking a point summarises it across every band first. The full
     explanation is one more click away, so a click is never a navigation. */
  const [peek, setPeek] = useState<{ label: string; band: BandId } | null>(null);
  const onChartClick = (domain: BandId, e: { activeLabel?: string | number } | null) => {
    if (!e?.activeLabel) return;
    const row = rows.find((r) => r.label === String(e.activeLabel));
    if (!row) return;
    setSelectedBand(domain);
    setSelectedDate(row.start);
    setPeek({ label: row.label, band: domain });
  };
  const peekRow = peek ? rows.find((r) => r.label === peek.label) ?? null : null;

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

  const fmtThousands = (v: number | string) => {
    const n = Number(v);
    return Math.abs(n) >= 1000 ? `${Math.round(n / 1000)}k` : `${Math.round(n)}`;
  };

  /**
   * The y axis is always drawn. A chart whose scale is invisible cannot be read,
   * and the compact strips are the ones most likely to be misjudged.
   */
  const yAxis = (opts: {
    id?: string;
    orientation?: 'left' | 'right';
    unit: string;
    format?: (v: number | string) => string;
    domain?: [number | string, number | string];
    compact: boolean;
  }) => (
    <YAxis
      {...(opts.id ? { yAxisId: opts.id } : {})}
      orientation={opts.orientation ?? 'left'}
      tick={{ fontSize: opts.compact ? 9 : 10, fill: '#93a29b' }}
      axisLine={false}
      tickLine={false}
      width={opts.compact ? 40 : 56}
      tickCount={opts.compact ? 3 : 5}
      {...(opts.domain ? { domain: opts.domain } : {})}
      tickFormatter={opts.format ?? ((v) => `${Math.round(Number(v))}`)}
      label={
        opts.compact
          ? undefined
          : {
              value: opts.unit,
              angle: -90,
              position: 'insideLeft',
              offset: opts.orientation === 'right' ? -8 : 8,
              style: { fontSize: 9.5, fill: '#93a29b', letterSpacing: 0.5 },
            }
      }
    />
  );

  /* Reference markers stay on each chart's default y axis. Only a chart's
     *second* axis is ever named, which keeps every unnamed child valid. */
  const markers = () => {
    const on = {};
    const out = [];
    if (todayRow) {
      out.push(
        <ReferenceLine
          key="today"
          {...on}
          x={todayRow.label}
          stroke="#1d2b26"
          strokeWidth={1.5}
          label={{ value: 'Today', position: 'insideTopLeft', fill: '#1d2b26', fontSize: 10, fontWeight: 700 }}
        />,
      );
    }
    if (eventStart && eventEnd) {
      out.push(
        <ReferenceArea key="window" {...on} x1={eventStart.label} x2={eventEnd.label} fill="#a44b3c" fillOpacity={0.07} />,
      );
    }
    if (selectedRow) {
      out.push(
        <ReferenceLine key="selected" {...on} x={selectedRow.label} stroke="#5b7fa6" strokeWidth={2} strokeDasharray="4 3" />,
      );
    }
    if (compareDate) {
      const r = rows.find((x, i) => x.start <= compareDate && (!rows[i + 1] || rows[i + 1].start > compareDate));
      if (r) {
        out.push(
          <ReferenceLine key="compare" {...on} x={r.label} stroke="#b8860b" strokeWidth={2} strokeDasharray="2 3" />,
        );
      }
    }
    return out;
  };

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
            <span className="pfie-seg" role="group" aria-label="Forecast shown">
              {([
                ['match', 'Match horizon'],
                ['12m', '+12 months'],
                ['18m', '+18 months'],
                ['24m', '+24 months'],
              ] as [FutureRange, string][]).map(([id, label]) => (
                <button key={id} aria-pressed={futureRange === id} onClick={() => setFutureRange(id)}>
                  {label}
                </button>
              ))}
            </span>
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
            <button className="pfie-btn primary" onClick={() => openDrawer({ kind: 'structure', date: selectedDate, domain: DOMAIN_FOR[selectedBand] })}>
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
                <BandControls
                  band={b.id}
                  herdMeasure={herdMeasure} setHerdMeasure={setHerdMeasure}
                  populationMode={populationMode} setPopulationMode={setPopulationMode}
                  populationSeries={populationSeries} setPopulationSeries={setPopulationSeries}
                  reproSeries={reproSeries} setReproSeries={setReproSeries}
                  financeMacro={financeMacro} setFinanceMacro={setFinanceMacro}
                  financeMeasure={financeMeasure} setFinanceMeasure={setFinanceMeasure}
                />
                <ResponsiveContainer width="100%" height={h}>
                  {b.id === 'herd' ? (
                    <ComposedChart {...shared} onClick={(event) => onChartClick('herd', event)}>
                      {HATCH_DEFS}
                      {axis(!isExpandedView('herd'))}
                      {herdMeasure !== 'head' &&
                        yAxis({ unit: 'litres', format: fmtThousands, compact: !isExpandedView('herd') })}
                      {herdMeasure !== 'litres' &&
                        yAxis({
                          ...(herdMeasure === 'both' ? { id: 'H', orientation: 'right' as const } : {}),
                          unit: 'head',
                          compact: !isExpandedView('herd'),
                        })}
                      <Tooltip content={<BandTip band="herd" rows={rows} />} cursor={{ stroke: '#93a29b', strokeDasharray: '3 3' }} />
                      {herdMeasure !== 'head' && [
                        <Area key="band" dataKey="band" stroke="none" fill="url(#pfieHatchLight)" fillOpacity={0.85} isAnimationActive={false} name="Likely range" />,
                        <Line key="observed" dataKey="observed" stroke="#1f6b4a" strokeWidth={2} dot={false} isAnimationActive={false} name="Recorded litres" />,
                        <Line key="expected" dataKey="expected" stroke="#5b7fa6" strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} name="Expected litres" />,
                      ]}
                      {herdMeasure !== 'litres' && (
                        <Line
                          {...(herdMeasure === 'both' ? { yAxisId: 'H' } : {})}
                          dataKey="milkers"
                          stroke="#9a4f27"
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={false}
                          name="Milking head"
                        />
                      )}
                      {markers()}
                    </ComposedChart>
                  ) : b.id === 'population' ? (
                    <ComposedChart {...shared} onClick={(event) => onChartClick('population', event)}>
                      <defs>
                        {POPULATION_SERIES.map((series) => (
                          <linearGradient key={series.key} id={`pfiePop-${series.key}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={series.color} stopOpacity={0.55} />
                            <stop offset="100%" stopColor={series.color} stopOpacity={0.08} />
                          </linearGradient>
                        ))}
                      </defs>
                      {axis(!isExpandedView('population'))}
                      {yAxis({ unit: 'animals', compact: !isExpandedView('population') })}
                      <Tooltip content={<BandTip band="population" rows={rows} />} cursor={{ stroke: '#93a29b', strokeDasharray: '3 3' }} />
                      {populationMode === 'total' ? (
                        <Area dataKey="totalHerd" stroke="#1f6b4a" strokeWidth={2} fill="url(#pfiePop-milking)" isAnimationActive={false} name="Total herd" />
                      ) : (
                        POPULATION_SERIES.filter((series) => populationSeries.has(series.key)).map((series) =>
                          populationMode === 'stacked' ? (
                            <Area
                              key={series.key}
                              dataKey={series.key}
                              stackId="pop"
                              stroke={series.color}
                              strokeWidth={1.2}
                              fill={series.color}
                              fillOpacity={0.62}
                              isAnimationActive={false}
                              name={series.label}
                            />
                          ) : (
                            <Line
                              key={series.key}
                              dataKey={series.key}
                              stroke={series.color}
                              strokeWidth={2}
                              dot={false}
                              isAnimationActive={false}
                              name={series.label}
                            />
                          ),
                        )
                      )}
                      {markers()}
                    </ComposedChart>
                  ) : b.id === 'repro' ? (
                    <ComposedChart
                      {...shared}
                      stackOffset={reproSeries.has('calvings') && reproSeries.has('dryOffs') ? 'sign' : undefined}
                      onClick={(event) => onChartClick('repro', event)}
                    >
                      {axis(!isExpandedView('repro'))}
                      {yAxis({ unit: 'events', compact: !isExpandedView('repro') })}
                      {reproSeries.has('thi') &&
                        yAxis({ id: 'T', orientation: 'right', unit: 'THI', domain: [60, 92], compact: !isExpandedView('repro') })}
                      <Tooltip content={<BandTip band="repro" rows={rows} reproSeries={reproSeries} />} cursor={{ fill: 'rgba(147,162,155,.12)' }} />
                      <ReferenceLine y={0} stroke="#dfe6e2" />

                      {/* Calvings above the line, dry-offs below it: the bar that
                          crosses zero is the herd's net movement for the period. */}
                      {reproSeries.has('calvings') && (
                        <Bar dataKey="calvings" stackId="t" fill="#5b7fa6" name="Calvings — entering the milking herd" isAnimationActive={false} radius={[3, 3, 0, 0]} />
                      )}
                      {reproSeries.has('dryOffs') && (
                        <Bar dataKey="dryOffs" stackId="t" fill="#b8860b" name="Dry-offs — leaving the milking herd" isAnimationActive={false} radius={[0, 0, 3, 3]} />
                      )}

                      {reproSeries.has('vaccinations') && (
                        <Bar dataKey="vaccinations" stackId="care" fill="#1f6b4a" fillOpacity={0.5} name="Vaccinations" isAnimationActive={false} />
                      )}
                      {reproSeries.has('treatments') && !reproSeries.has('treatmentSplit') && (
                        <Bar dataKey="vetTreatments" stackId="care" fill="#9a4f27" fillOpacity={0.55} name="Veterinary treatments" isAnimationActive={false} radius={[3, 3, 0, 0]} />
                      )}
                      {reproSeries.has('treatmentSplit') &&
                        TREATMENT_CATEGORIES.map((category) => (
                          <Bar
                            key={category}
                            dataKey={`t_${category}`}
                            stackId="care"
                            fill={TREATMENT_COLOR[category]}
                            name={category}
                            isAnimationActive={false}
                          />
                        ))}

                      {reproSeries.has('diseaseSplit') &&
                        DISEASE_CATEGORIES.map((category) => (
                          <Bar
                            key={category}
                            dataKey={`d_${category}`}
                            stackId="disease"
                            fill={DISEASE_COLOR[category]}
                            name={category}
                            isAnimationActive={false}
                          />
                        ))}
                      {reproSeries.has('disease') && !reproSeries.has('diseaseSplit') && (
                        <Line dataKey="diseaseTotal" stroke="#8a6cb5" strokeWidth={2} dot={false} isAnimationActive={false} name="Disease events" />
                      )}

                      {reproSeries.has('abortions') && (
                        <Line dataKey="abortions" stroke="#a44b3c" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} name="Abortions" />
                      )}
                      {reproSeries.has('deaths') && (
                        <Line dataKey="deaths" stroke="#6c321a" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 2 }} isAnimationActive={false} name="Deaths" />
                      )}
                      {reproSeries.has('thi') && (
                        <Line yAxisId="T" dataKey="thi" stroke="#a8770a" strokeWidth={1.4} strokeDasharray="4 3" dot={false} isAnimationActive={false} name="Heat index" />
                      )}
                      {markers()}
                    </ComposedChart>
                  ) : b.id === 'products' ? (
                    <ComposedChart {...shared} onClick={(event) => onChartClick('products', event)}>
                      {axis(!isExpandedView('products'))}
                      {yAxis({ unit: 'litres', format: fmtThousands, compact: !isExpandedView('products') })}
                      <Tooltip content={<BandTip band="products" rows={rows} />} cursor={{ fill: 'rgba(147,162,155,.12)' }} />
                      <Area dataKey="raw" stackId="p" stroke={PRODUCT_META['Raw milk'].color} fill={PRODUCT_META['Raw milk'].color} fillOpacity={0.75} isAnimationActive={false} name="Raw milk" />
                      <Area dataKey="tetra" stackId="p" stroke={PRODUCT_META['Tetra pack'].color} fill={PRODUCT_META['Tetra pack'].color} fillOpacity={0.75} isAnimationActive={false} name="Tetra pack" />
                      <Area dataKey="yoghurt" stackId="p" stroke={PRODUCT_META.Yoghurt.color} fill={PRODUCT_META.Yoghurt.color} fillOpacity={0.75} isAnimationActive={false} name="Yoghurt" />
                      <Area dataKey="other" stackId="p" stroke={PRODUCT_META['Other by-products'].color} fill={PRODUCT_META['Other by-products'].color} fillOpacity={0.75} isAnimationActive={false} name="Other" />
                      {markers()}
                    </ComposedChart>
                  ) : (
                    <ComposedChart {...shared} onClick={(event) => onChartClick('finance', event)}>
                      {HATCH_DEFS}
                      {axis(!isExpandedView('finance'))}
                      {yAxis({ unit: 'LKR k', format: fmtThousands, compact: !isExpandedView('finance') })}
                      {financeMacro !== 'none' &&
                        yAxis({
                          id: 'X',
                          orientation: 'right',
                          unit: MACRO_META[financeMacro].unit || 'index',
                          domain: MACRO_META[financeMacro].domain,
                          compact: !isExpandedView('finance'),
                        })}
                      <Tooltip content={<BandTip band="finance" rows={rows} macro={financeMacro} financeMeasure={financeMeasure} />} cursor={{ stroke: '#93a29b', strokeDasharray: '3 3' }} />
                      <ReferenceLine y={0} stroke="#dfe6e2" />

                      {financeMeasure === 'margin' && [
                        <Bar key="m" dataKey="margin" fill="#1f6b4a" name="Recorded margin" isAnimationActive={false} radius={[3, 3, 0, 0]} />,
                        <Bar key="mf" dataKey="marginForecast" fill="url(#pfieHatch)" stroke="#5b7fa6" name="Expected margin" isAnimationActive={false} radius={[3, 3, 0, 0]} />,
                        <Line key="budget" dataKey="budgetMargin" stroke="#9a4f27" strokeWidth={1.6} strokeDasharray="5 4" dot={false} isAnimationActive={false} name="Budget margin" />,
                      ]}

                      {/* Revenue stacks by product line, so a margin move can be
                          traced to the line that produced or lost it. */}
                      {financeMeasure === 'revenue' &&
                        (['revRaw', 'revTetra', 'revYoghurt', 'revOther'] as const).map((key, i) => (
                          <Area
                            key={key}
                            dataKey={key}
                            stackId="rev"
                            stroke={REVENUE_COLOR[key]}
                            strokeWidth={1.1}
                            fill={REVENUE_COLOR[key]}
                            fillOpacity={0.72}
                            isAnimationActive={false}
                            name={['Raw milk', 'Tetra pack', 'Yoghurt', 'Other by-products'][i]}
                          />
                        ))}

                      {financeMeasure === 'cost' &&
                        COST_CATEGORIES.map((category) => (
                          <Bar
                            key={category}
                            dataKey={`c_${category}`}
                            stackId="cost"
                            fill={COST_CATEGORY_COLOR[category] ?? '#8a9a94'}
                            name={category}
                            isAnimationActive={false}
                          />
                        ))}

                      {/* Revenue against cost, with the profit line between them:
                          the shape of the squeeze, not just its result. */}
                      {financeMeasure === 'all' && [
                        <Bar key="rev" dataKey="revenueAny" fill="#1f6b4a" fillOpacity={0.75} name="Revenue" isAnimationActive={false} radius={[3, 3, 0, 0]} />,
                        <Bar key="cost" dataKey="costAny" fill="#a44b3c" fillOpacity={0.6} name="Cost" isAnimationActive={false} radius={[3, 3, 0, 0]} />,
                        <Line key="profit" dataKey="profit" stroke="#1d2b26" strokeWidth={2.2} dot={false} isAnimationActive={false} name="Profit / loss" />,
                        <Line key="budget" dataKey="budgetMargin" stroke="#9a4f27" strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} name="Budget margin" />,
                      ]}

                      {financeMacro !== 'none' && (
                        <Line
                          yAxisId="X"
                          dataKey={financeMacro}
                          stroke="#7a4a8f"
                          strokeWidth={1.8}
                          dot={false}
                          isAnimationActive={false}
                          name={MACRO_META[financeMacro].label}
                        />
                      )}
                      {markers()}
                    </ComposedChart>
                  )}
                </ResponsiveContainer>

                {peekRow && peek?.band === b.id && (
                  <PointSummary
                    row={peekRow}
                    band={b.id}
                    onClose={() => setPeek(null)}
                    onExplain={() => openDrawer({ kind: 'structure', date: peekRow.start, domain: DOMAIN_FOR[b.id] })}
                  />
                )}
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

/**
 * The step between a click and the full explanation.
 *
 * A point on one band is rarely interesting on its own — the question is
 * always "and what was happening everywhere else?". This summarises the
 * clicked period across every band, and only then offers the full reasoning.
 */
function PointSummary({
  row,
  band,
  onClose,
  onExplain,
}: {
  row: Row;
  band: BandId;
  onClose: () => void;
  onExplain: () => void;
}) {
  const milk = row.expected ?? row.observed ?? 0;
  const net = row.calvings - Math.abs(row.dryOffs);
  const bandLabel = BANDS.find((b) => b.id === band)?.label ?? 'chart';

  const groups: { title: string; items: [string, string, string?][] }[] = [
    {
      title: 'Herd & milk',
      items: [
        [row.future ? 'Expected milk' : 'Recorded milk', `${fmtInt(milk)} L`, '#1f6b4a'],
        ['Milking head', `${row.milkers}`, '#9a4f27'],
        ...(row.band ? ([['Likely range', `${fmtInt(row.band[0])}–${fmtInt(row.band[1])} L`]] as [string, string][]) : []),
      ],
    },
    {
      title: 'Population',
      items: [
        ['Total herd', `${row.totalHerd}`],
        ['Pregnant', `${row.pregnant}`, '#9a4f27'],
        ['Dry', `${row.dry}`, '#8a9a94'],
      ],
    },
    {
      title: 'Reproduction & health',
      items: [
        ['Calvings · dry-offs', `${row.calvings} · ${Math.abs(row.dryOffs)}`, '#5b7fa6'],
        ['Net movement', `${net >= 0 ? '+' : '−'}${Math.abs(net)}`],
        ['Disease · treatments', `${row.diseaseTotal} · ${row.vetTreatments}`, '#8a6cb5'],
        ['Abortions · deaths', `${row.abortions} · ${row.deaths}`, '#a44b3c'],
        ['Heat index', `${row.thi}`, '#a8770a'],
      ],
    },
    {
      title: 'Products',
      items: [
        ['Raw milk', `${fmtInt(row.raw)} L`, PRODUCT_META['Raw milk'].color],
        ['Tetra pack', `${fmtInt(row.tetra)} L`, PRODUCT_META['Tetra pack'].color],
        ['Tetra shortfall', row.tetraShort ? `−${fmtInt(row.tetraShort)} L` : 'Within plan'],
      ],
    },
    {
      title: 'Finance & context',
      items: [
        ['Revenue', fmtLKR(row.revenueAny), '#1f6b4a'],
        ['Cost', fmtLKR(row.costAny), '#a44b3c'],
        [row.profit >= 0 ? 'Profit' : 'Loss', fmtLKR(row.profit), '#1d2b26'],
        ['CPI inflation', `${row.cpiInflation}%`, '#7a4a8f'],
      ],
    },
  ];

  return (
    <section className="pfie-peek" aria-label={`Summary for ${row.label}`}>
      <header>
        <div>
          <span className="pfie-peek-eyebrow">
            {row.future ? 'Expected point' : 'Recorded point'} · selected from {bandLabel}
          </span>
          <h4>{row.label}</h4>
        </div>
        <div className="pfie-row tight">
          <button className="pfie-btn primary" onClick={onExplain}>Open the full explanation →</button>
          <button className="pfie-close" onClick={onClose} aria-label="Close summary">×</button>
        </div>
      </header>
      <div className="pfie-peek-grid">
        {groups.map((group) => (
          <div className="pfie-peek-group" key={group.title}>
            <h5>{group.title}</h5>
            <dl>
              {group.items.map(([k, v, color]) => (
                <div key={k}>
                  <dt>{color && <i style={{ background: color }} aria-hidden />}{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
      <p className="pfie-peek-foot">
        Every figure describes this one period. {row.future
          ? `${row.confidence} confidence — part of it depends on transitions that have not happened yet.`
          : 'Recorded from the herd and finance ledgers.'}
      </p>
    </section>
  );
}

/**
 * Per-band measure controls.
 *
 * Each band answers a different question, so each gets its own axis choices
 * rather than one global toggle that means something different in every chart.
 */
function BandControls({
  band,
  herdMeasure, setHerdMeasure,
  populationMode, setPopulationMode,
  populationSeries, setPopulationSeries,
  reproSeries, setReproSeries,
  financeMacro, setFinanceMacro,
  financeMeasure, setFinanceMeasure,
}: {
  band: BandId;
  herdMeasure: HerdMeasure; setHerdMeasure: (v: HerdMeasure) => void;
  populationMode: PopulationMode; setPopulationMode: (v: PopulationMode) => void;
  populationSeries: Set<PopulationSeriesKey>; setPopulationSeries: (v: Set<PopulationSeriesKey>) => void;
  reproSeries: Set<ReproSeries>; setReproSeries: (v: Set<ReproSeries>) => void;
  financeMacro: FinanceMacro; setFinanceMacro: (v: FinanceMacro) => void;
  financeMeasure: FinanceMeasure; setFinanceMeasure: (v: FinanceMeasure) => void;
}) {
  if (band === 'products') return null;

  const seg = <T extends string>(label: string, value: T, onChange: (v: T) => void, options: [T, string][]) => (
    <span className="pfie-row tight">
      <span className="pfie-bandctl-label">{label}</span>
      <span className="pfie-seg" role="group" aria-label={label}>
        {options.map(([id, text]) => (
          <button key={id} aria-pressed={value === id} onClick={() => onChange(id)}>{text}</button>
        ))}
      </span>
    </span>
  );

  return (
    <div className="pfie-bandctl">
      {band === 'herd' && seg<HerdMeasure>('Measure', herdMeasure, setHerdMeasure, [
        ['litres', 'Litres'],
        ['head', 'Milking head'],
        ['both', 'Both axes'],
      ])}

      {band === 'population' && (
        <>
          {seg<PopulationMode>('View', populationMode, setPopulationMode, [
            ['lines', 'Separate lines'],
            ['stacked', 'Stacked area'],
            ['total', 'Total herd'],
          ])}
          {populationMode !== 'total' && (
            <span className="pfie-row tight">
              <span className="pfie-bandctl-label">Groups</span>
              {POPULATION_SERIES.map((series) => {
                const on = populationSeries.has(series.key);
                return (
                  <button
                    key={series.key}
                    className={`pfie-serieschip${on ? ' on' : ''}`}
                    aria-pressed={on}
                    onClick={() => {
                      const next = new Set(populationSeries);
                      /* Never leave the chart empty — the last group stays on. */
                      if (on && next.size > 1) next.delete(series.key);
                      else next.add(series.key);
                      setPopulationSeries(next);
                    }}
                  >
                    <i style={{ background: series.color }} aria-hidden />
                    {series.label}
                  </button>
                );
              })}
            </span>
          )}
        </>
      )}

      {band === 'repro' && (
        <>
          <span className="pfie-row tight">
            <span className="pfie-bandctl-label">Presets</span>
            {REPRO_PRESETS.map((preset) => (
              <button
                key={preset.label}
                className="pfie-btn ghost"
                onClick={() => setReproSeries(new Set(preset.series))}
              >
                {preset.label}
              </button>
            ))}
          </span>
          <span className="pfie-row tight">
            <span className="pfie-bandctl-label">Series</span>
            {REPRO_SERIES.map((series) => {
              const on = reproSeries.has(series.key);
              return (
                <button
                  key={series.key}
                  className={`pfie-serieschip${on ? ' on' : ''}`}
                  aria-pressed={on}
                  title={`${series.group} · ${series.label}`}
                  onClick={() => {
                    const next = new Set(reproSeries);
                    /* Never leave the chart empty. */
                    if (on && next.size > 1) next.delete(series.key);
                    else next.add(series.key);
                    setReproSeries(next);
                  }}
                >
                  <i style={{ background: series.color }} aria-hidden />
                  {series.label}
                </button>
              );
            })}
          </span>
        </>
      )}

      {band === 'finance' && (
        <>
          {seg<FinanceMeasure>('Measure', financeMeasure, setFinanceMeasure, [
            ['margin', 'Margin & budget'],
            ['revenue', 'Revenue by product'],
            ['cost', 'Cost by category'],
            ['all', 'Revenue, cost & profit'],
          ])}
          {seg<FinanceMacro>('Context', financeMacro, setFinanceMacro, [
            ['cpiInflation', 'CPI inflation'],
            ['feedPriceIndex', 'Feed price'],
            ['farmgatePriceIndex', 'Farmgate price'],
            ['none', 'None'],
          ])}
        </>
      )}
    </div>
  );
}

/** A tooltip stays within the domain the user is hovering. */
function BandTip({ band, active, label, rows, reproSeries, macro, financeMeasure }: {
  band: BandId;
  active?: boolean;
  label?: string | number;
  rows?: Row[];
  reproSeries?: Set<ReproSeries>;
  macro?: FinanceMacro;
  financeMeasure?: FinanceMeasure;
}) {
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

  if (band === 'population') {
    const delta = r.totalHerd - (previous?.totalHerd ?? r.totalHerd);
    const color = (k: string) => POPULATION_SERIES.find((x) => x.key === k)?.color;
    return <TipShell title={title} rows={[
      ['Milking', `${r.milking}`, color('milking')],
      ['Dry', `${r.dry}`, color('dry')],
      ['Pregnant', `${r.pregnant}`, color('pregnant')],
      ['Heifers', `${r.heifer}`, color('heifer')],
      ['Calves', `${r.calf}`, color('calf')],
      ['Male / bull', `${r.male}`, color('male')],
      ['Total herd', `${r.totalHerd}`],
    ]} note={`Counts are the herd as it stands at the start of this period, so pregnant animals also appear in milking or dry. Total ${delta >= 0 ? 'up' : 'down'} ${Math.abs(delta)} on the previous period. ${standardNote}`} />;
  }

  if (band === 'repro') {
    /* The tooltip mirrors whatever the user has chosen to draw, in the same
       order and the same colours, so the two always read as one thing. */
    const on = reproSeries ?? new Set<ReproSeries>();
    const tipRows: TipRow[] = [];
    if (on.has('calvings')) tipRows.push(['Calvings (entering)', `${r.calvings}`, '#5b7fa6']);
    if (on.has('dryOffs')) tipRows.push(['Dry-offs (leaving)', `${Math.abs(r.dryOffs)}`, '#b8860b']);
    if (on.has('calvings') && on.has('dryOffs')) {
      const net = r.calvings - Math.abs(r.dryOffs);
      tipRows.push(['Net milking movement', `${net >= 0 ? '+' : '−'}${Math.abs(net)}`]);
    }
    if (on.has('abortions')) tipRows.push(['Abortions', `${r.abortions}`, '#a44b3c']);
    if (on.has('deaths')) tipRows.push(['Deaths', `${r.deaths}`, '#6c321a']);
    if (on.has('diseaseSplit')) {
      DISEASE_CATEGORIES.forEach((c) => tipRows.push([c, `${r.disease[c]}`, DISEASE_COLOR[c]]));
    }
    if (on.has('disease') || on.has('diseaseSplit')) {
      tipRows.push(['Disease events', `${r.diseaseTotal}`, on.has('diseaseSplit') ? undefined : '#8a6cb5']);
    }
    if (on.has('vaccinations')) tipRows.push(['Vaccinations', `${r.vaccinations}`, '#1f6b4a']);
    if (on.has('treatmentSplit')) {
      TREATMENT_CATEGORIES.forEach((c) => tipRows.push([c, `${r.treatments[c]}`, TREATMENT_COLOR[c]]));
    }
    if (on.has('treatments') || on.has('treatmentSplit')) {
      tipRows.push(['Treatments total', `${r.vetTreatments}`, on.has('treatmentSplit') ? undefined : '#9a4f27']);
    }
    if (on.has('thi')) tipRows.push(['Heat index (THI)', `${r.thi}`, '#a8770a']);

    const note = on.has('calvings') || on.has('dryOffs')
      ? `Calvings are drawn above the line (animals entering the milking herd) and dry-offs below it (animals leaving), so the bar crossing zero is the net movement for the period. ${standardNote}`
      : `Counts for this period only, not rates. ${standardNote}`;

    return <TipShell title={title} rows={tipRows} note={note} />;
  }

  if (band === 'products') {
    const rawDelta = r.raw - (previous?.raw ?? r.raw);
    const tetraDelta = r.tetra - (previous?.tetra ?? r.tetra);
    const movement = constraint === 'None'
      ? 'All product lines remain within plan; output changes follow the available milk supply.'
      : `The raw-milk contract is allocated first, so tetra pack absorbs the ${constraint.toLowerCase()} supply constraint.`;
    return <TipShell title={title} rows={[
      ['Raw milk', `${fmtInt(r.raw)} L`, PRODUCT_META['Raw milk'].color],
      ['Tetra pack', `${fmtInt(r.tetra)} L`, PRODUCT_META['Tetra pack'].color],
      ['Yoghurt', `${fmtInt(r.yoghurt)} L`, PRODUCT_META.Yoghurt.color],
      ['Product constraint', constraint],
      ['Change vs previous', `Raw ${rawDelta >= 0 ? '+' : '−'}${fmtInt(Math.abs(rawDelta))} L · Tetra ${tetraDelta >= 0 ? '+' : '−'}${fmtInt(Math.abs(tetraDelta))} L`],
    ]} note={`Why it moved: ${movement} ${standardNote}`} />;
  }

  const margin = r.marginForecast ?? r.margin ?? 0;
  const previousMargin = previous?.marginForecast ?? previous?.margin ?? margin;
  const marginDelta = margin - previousMargin;
  const movement = marginDelta >= 0
    ? 'The margin is improving with revenue and available milk relative to the previous period.'
    : 'The margin is under pressure from the milk/product mix and continuing cost base relative to the previous period.';

  /* Feed leads farmgate, so the gap between them is the squeeze on the margin. */
  const priceGap = round(r.feedPriceIndex - r.farmgatePriceIndex, 1);
  const macroRows: TipRow[] =
    macro && macro !== 'none'
      ? [[MACRO_META[macro].label, `${r[macro]}${MACRO_META[macro].unit}`, '#7a4a8f']]
      : [];
  const macroNote = `Feed cost sits ${priceGap >= 0 ? `${priceGap} points above` : `${Math.abs(priceGap)} points below`} the farmgate price index — input prices move before the milk price follows.`;

  if (financeMeasure === 'revenue') {
    return (
      <TipShell
        title={title}
        rows={[
          ['Raw milk', fmtLKR(r.revRaw), REVENUE_COLOR.revRaw],
          ['Tetra pack', fmtLKR(r.revTetra), REVENUE_COLOR.revTetra],
          ['Yoghurt', fmtLKR(r.revYoghurt), REVENUE_COLOR.revYoghurt],
          ['Other by-products', fmtLKR(r.revOther), REVENUE_COLOR.revOther],
          ['Total revenue', fmtLKR(r.revenueAny)],
          ...macroRows,
        ]}
        note={`Revenue follows the allocation, not the other way round: the raw-milk contract is filled first, so a supply shortfall shows up in the packed lines. ${standardNote}`}
      />
    );
  }

  if (financeMeasure === 'cost') {
    const previousCost = previous?.costAny ?? r.costAny;
    const costDelta = r.costAny - previousCost;
    const biggest = COST_CATEGORIES.reduce(
      (top, c) => ((r.costByCat[c] ?? 0) > (r.costByCat[top] ?? 0) ? c : top),
      COST_CATEGORIES[0],
    );
    return (
      <TipShell
        title={title}
        rows={[
          ...COST_CATEGORIES.map((c) => [c, fmtLKR(r.costByCat[c] ?? 0), COST_CATEGORY_COLOR[c]] as TipRow),
          ['Total cost', fmtLKR(r.costAny)],
          ['Change vs previous', `${costDelta >= 0 ? '+' : '−'}${fmtLKR(Math.abs(costDelta))}`],
          ...macroRows,
        ]}
        note={`${biggest} is the largest line in this period. Costs are driven by herd counts and milk volume rather than forecast on their own, so a cost move is a herd move first. ${macroNote} ${standardNote}`}
      />
    );
  }

  if (financeMeasure === 'all') {
    const profitable = r.profit >= 0;
    const vsBudget = r.profit - r.budgetMargin;
    return (
      <TipShell
        title={title}
        rows={[
          ['Revenue', fmtLKR(r.revenueAny), '#1f6b4a'],
          ['Cost', fmtLKR(r.costAny), '#a44b3c'],
          [profitable ? 'Profit' : 'Loss', fmtLKR(r.profit), '#1d2b26'],
          ['Budget margin', fmtLKR(r.budgetMargin), '#9a4f27'],
          ['Against budget', `${vsBudget >= 0 ? '+' : '−'}${fmtLKR(Math.abs(vsBudget))}`],
          ...macroRows,
        ]}
        note={`${movement} ${macroNote} ${standardNote}`}
      />
    );
  }

  return (
    <TipShell
      title={title}
      rows={[
        ['Revenue', fmtLKR(r.revenueForecast ?? r.revenue ?? 0), '#1f6b4a'],
        ['Cost', fmtLKR(r.cost ?? 0), '#a44b3c'],
        ['Margin', fmtLKR(margin), '#1d2b26'],
        ['Budget margin', fmtLKR(r.budgetMargin), '#9a4f27'],
        ...macroRows,
        ['Change vs previous', `${marginDelta >= 0 ? '+' : '−'}${fmtLKR(Math.abs(marginDelta))}`],
      ]}
      note={`Why it moved: ${movement} ${macroNote} ${standardNote}`}
    />
  );
}
