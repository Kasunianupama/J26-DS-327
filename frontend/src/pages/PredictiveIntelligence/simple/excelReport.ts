/**
 * The simple view's Excel report. Each part the user ticks becomes one sheet:
 * a title, one plain sentence on how to read it, a real Excel table and, where
 * it helps, a native chart that reads that table. Numbers are the same ones the
 * page shows (herd level only; demo runs are labelled on every sheet).
 */

import {
  EVENT_SERIES, STOCK_SERIES, actualRow, addPeriods, attributionMonths, confidenceOf, findings, firstTarget, flowSplit,
  flowTotals, forecastRow, hasRealised, headline, isForecast, longDate, milkBreakdown, outcomeScore,
  periodDays, periodLabel, perDay, timeline, type PfoiRun, type SeriesId,
} from '../../../data/pfoi';
import { PLAIN_FACTOR } from '../panels/ContributionChart';
import { PLAIN_CONFIDENCE, PLAIN_SERIES, PLAIN_STATUS } from './common';
import { S, buildXlsx, type Cell, type ChartSpec, type SheetSpec, type TableSpec, type Value } from './xlsx';

export type ReportPart =
  | 'summary' | 'monthly' | 'milk' | 'reasons' | 'herd' | 'events' | 'mastitis' | 'heat' | 'breeding' | 'accuracy' | 'tests';

export const REPORT_PARTS: { id: ReportPart; label: string; what: string; chart: boolean }[] = [
  { id: 'summary', label: 'Summary and what to watch', what: 'The key numbers and the things that need attention.', chart: false },
  { id: 'monthly', label: 'All numbers by month', what: 'Every forecast number for each month, with its likely range.', chart: false },
  { id: 'milk', label: 'Milk', what: 'Recorded and expected milk per day, with a line chart.', chart: true },
  { id: 'reasons', label: 'Why milk changes', what: 'The reasons behind each month’s change, with a chart.', chart: true },
  { id: 'herd', label: 'Cows and herd groups', what: 'Animals in each group over time, with a line chart.', chart: true },
  { id: 'events', label: 'Herd events', what: 'Calvings, dry-offs, losses and exits by month, with a chart.', chart: true },
  { id: 'mastitis', label: 'Mastitis', what: 'Recorded and expected cases, with a chart.', chart: true },
  { id: 'heat', label: 'Heat', what: 'Recent heat and the usual heat for the coming weeks, with a chart.', chart: true },
  { id: 'breeding', label: 'Breeding and generations', what: 'Time to get cows in calf and fertility by generation.', chart: false },
  { id: 'accuracy', label: 'How far to trust this', what: 'How close forecasts came, record checks and coverage.', chart: true },
  { id: 'tests', label: 'How the model was tested', what: 'For advisers: which information helps, outages, signals.', chart: false },
];

const MILK = '#9A4F27';
const EXPECTED = '#5B7FA6';
const BAND = '#B9CBDD';
const COLORS = ['#9A4F27', '#5B7FA6', '#3F8C62', '#A8770A', '#A44B3C', '#6D4C8A', '#8A8F87', '#2F7F86'];

const r0 = (n: number | null | undefined) => (n === null || n === undefined || !Number.isFinite(n) ? null : Math.round(n));
const r1 = (n: number | null | undefined) => (n === null || n === undefined || !Number.isFinite(n) ? null : Math.round(n * 10) / 10);
const share = (n: number | null | undefined) => (n === null || n === undefined ? null : Math.round(n * 1000) / 1000);

/** Rows above a table: title, subtitle, how to read, and the demo label when it applies. */
function header(run: PfoiRun, title: string, how: string): Cell[][] {
  return [
    [{ v: title, s: S.title }],
    [{ v: `Farm X · forecast made on ${longDate(run.origin_date)} · records up to ${longDate(run.data_through)}`, s: S.note }],
    [{ v: how, s: S.note }],
    [run.source === 'demo' ? { v: 'PRACTICE DATA: these numbers are made up to show the layout. They are not Farm X numbers or results.', s: S.label } : null],
  ];
}

export function buildReport(run: PfoiRun, months: number, parts: ReportPart[], charts: boolean): Blob {
  return buildXlsx(reportSheets(run, months, parts, charts));
}

export function reportSheets(run: PfoiRun, months: number, parts: ReportPart[], charts: boolean): SheetSpec[] {
  const sheets: SheetSpec[] = [readMe(run, months, parts)];
  const add = (s: SheetSpec | null) => { if (s) sheets.push(charts ? s : { ...s, charts: [] }); };
  if (parts.includes('summary')) add(summary(run, months));
  if (parts.includes('monthly')) add(monthly(run, months));
  if (parts.includes('milk')) add(milk(run, months));
  if (parts.includes('reasons')) add(reasons(run));
  if (parts.includes('herd')) add(herd(run, months));
  if (parts.includes('events')) add(events(run, months));
  if (parts.includes('mastitis')) add(mastitis(run));
  if (parts.includes('heat')) add(heat(run));
  if (parts.includes('breeding')) add(breeding(run));
  if (parts.includes('accuracy')) add(accuracy(run, months));
  if (parts.includes('tests')) add(tests(run));
  return sheets;
}

/* ------------------------------------------------------------------ sheets */

function readMe(run: PfoiRun, months: number, parts: ReportPart[]): SheetSpec {
  const rows: Cell[][] = [
    [{ v: 'Farm outlook', s: S.title }],
    [{ v: `Farm X · whole-herd forecast · ${months === 1 ? 'next month' : `next ${months} months`}`, s: S.subtitle }],
    [],
    [{ v: 'Forecast made on', s: S.label }, longDate(run.origin_date)],
    [{ v: 'Farm records up to', s: S.label }, longDate(run.data_through)],
    [{ v: 'Data', s: S.label }, run.source === 'demo' ? 'PRACTICE DATA (made up, not Farm X numbers, not results)' : `Model output ${run.model_version}`],
    [],
    [{ v: 'How to read this file', s: S.subtitle }],
    ['• Each sheet is one part of the page. The table on each sheet has filter buttons; the chart next to it reads that table.'],
    ['• "Expected" is the forecast. "Likely low" and "Likely high" give the likely range: the real number will most likely fall between them.'],
    ['• Milk is in litres per day, so short months are not lower just because they have fewer days.'],
    ['• Changes are compared with the last recorded month. This is a whole-herd forecast: no individual animals are shown.'],
    [],
    [{ v: 'Sheets in this file', s: S.subtitle }],
    ...REPORT_PARTS.filter((p) => parts.includes(p.id)).map((p) => [{ v: p.label, s: S.bold }, p.what] as Cell[]),
  ];
  return { name: 'Read me', widths: [30, 100], rows };
}

function summary(run: PfoiRun, months: number): SheetSpec {
  const m = headline(run, 'month', months, 'milk_litres');
  const c = headline(run, 'month', months, 'milking');
  const h = headline(run, 'month', months, 'total_herd');
  const mast = headline(run, 'month', months, 'mastitis_episodes');
  const calv = isForecast(run, 'month', 'calvings') ? flowTotals(run, 'month', months, 'calvings') : null;
  const conf = PLAIN_CONFIDENCE[confidenceOf(m?.quality)];
  const base = m?.baselinePeriod ?? c?.baselinePeriod;
  const key: TableSpec = {
    name: 'Key_numbers', at: 6,
    head: ['Number', 'Expected', 'Likely low', 'Likely high', `Last recorded (${base ? periodLabel(base, 'month') : '—'})`, 'Change'],
    rows: [
      ['Milk a day (litres)', r0(m?.value), r0(m?.lower), r0(m?.upper), r0(m?.baseline), share(m?.changePct != null ? m.changePct / 100 : null)],
      ['Cows in milk', r0(c?.value), r0(c?.lower), r0(c?.upper), r0(c?.baseline), share(c?.changePct != null ? c.changePct / 100 : null)],
      ['Whole herd', r0(h?.value), r0(h?.lower), r0(h?.upper), r0(h?.baseline), share(h?.changePct != null ? h.changePct / 100 : null)],
      ['Calvings over the look ahead', r0(calv?.total), null, null, null, null],
      ['Mastitis cases over the look ahead', r1(mast?.pathTotal), null, null, null, null],
    ],
    styles: [undefined, S.int, S.int, S.int, S.int, S.pct],
  };
  const watch: TableSpec = {
    name: 'What_to_watch', at: key.at + key.rows.length + 3,
    head: ['Type', 'What', 'Details', 'How sure'],
    rows: findings(run).map((f) => [f.kind, f.title, f.summary, f.confidence]),
    styles: [S.wrap, S.wrap, S.wrap, S.wrap],
  };
  const rows = header(run, `Summary: ${m ? periodLabel(m.period, 'month') : ''}`,
    `${conf.dots} ${conf.label}. ${conf.help}`);
  rows[watch.at - 1] = [{ v: 'What to watch', s: S.subtitle }];
  return { name: 'Summary', widths: [34, 44, 70, 16, 22, 12], rows, tables: [key, watch] };
}

function monthly(run: PfoiRun, months: number): SheetSpec {
  const series: SeriesId[] = ['milk_litres', ...STOCK_SERIES, ...EVENT_SERIES, 'mastitis_episodes'];
  const rows: Value[][] = [];
  for (let i = 1; i <= months; i++) {
    const p = addPeriods(firstTarget(run, 'month'), 'month', i - 1);
    series.forEach((s) => {
      const f = forecastRow(run, 'month', p, s);
      if (!f) return;
      const v = (x: number) => (s === 'milk_litres' ? r0(perDay(s, x, 'month', p)) : STOCK_SERIES.includes(s) ? r0(x) : r1(x));
      rows.push([periodLabel(p, 'month'), PLAIN_SERIES[s], v(f.forecast), v(f.lower), v(f.upper), PLAIN_CONFIDENCE[confidenceOf(f.quality_flag)].label]);
    });
  }
  const t: TableSpec = { name: 'All_numbers', at: 5, head: ['Month', 'Number', 'Expected', 'Likely low', 'Likely high', 'Reliability'], rows };
  return {
    name: 'All numbers by month', widths: [12, 30, 12, 12, 12, 18],
    rows: header(run, 'All numbers by month', 'Use the filter on "Number" to see one thing, e.g. only "Cows in milk". Milk is litres per day; animals are head counts; events are per month.'),
    tables: [t],
  };
}

function milk(run: PfoiRun, months: number): SheetSpec {
  const realised = hasRealised(run);
  const rows = timeline(run, 'month', months, 12).map((p) => {
    const lyP = addPeriods(p.period, 'month', -12);
    const ly = actualRow(run, 'month', lyP, 'milk_litres');
    const band = p.future ? p.milk_litres_band as [number, number] | undefined : undefined;
    return [
      periodLabel(p.period, 'month'),
      p.future ? null : r0(p.milk_litres as number | undefined),
      /* the last recorded month also carries the expected value, so the two chart lines join */
      r0(p.milk_litres_f as number | undefined),
      r0(band?.[0]), r0(band?.[1]),
      ly?.value != null ? r0(perDay('milk_litres', ly.value, 'month', lyP)) : null,
      ...(realised ? [p.future ? r0(p.milk_litres_r as number | undefined) : null] : []),
    ];
  });
  const t: TableSpec = {
    name: 'Milk', at: 5,
    head: ['Month', 'Recorded', 'Expected', 'Likely low', 'Likely high', 'Same month last year', ...(realised ? ['What actually happened'] : [])],
    rows, styles: [undefined, S.int, S.int, S.int, S.int, S.int, S.int],
  };
  const chart: ChartSpec = {
    kind: 'line', title: 'Milk per day (litres)', table: t, catCol: 0, yTitle: 'litres a day',
    at: { col: t.head.length + 1, row: 1, w: 10, h: 20 },
    series: [
      { name: 'Recorded', col: 1, color: MILK },
      { name: 'Expected', col: 2, color: EXPECTED, dash: true },
      { name: 'Likely low', col: 3, color: BAND, dash: true },
      { name: 'Likely high', col: 4, color: BAND, dash: true },
      ...(realised ? [{ name: 'What actually happened', col: 6, color: '#17231F' }] : []),
    ],
  };
  return {
    name: 'Milk', widths: [12, 12, 12, 12, 12, 22, 24],
    rows: header(run, 'Milk per day', 'Last 12 months as recorded, then what we expect. Litres per day.'),
    tables: [t], charts: [chart],
  };
}

function reasons(run: PfoiRun): SheetSpec | null {
  const months = attributionMonths(run);
  if (!months.length) return null;
  const factors = [...new Set(months.flatMap((m) => milkBreakdown(run, m)?.parts.map((p) => p.factor) ?? []))];
  const start = firstTarget(run, 'month');
  const rows = months.map((m) => {
    const bd = milkBreakdown(run, m);
    return [
      periodLabel(m, 'month'), m >= start ? 'expected' : 'recorded', r0(bd?.end), r1(bd ? bd.end - bd.start : null),
      ...factors.map((f) => r1(bd?.parts.find((p) => p.factor === f)?.value ?? (m >= start && f === 'residual' ? null : 0))),
    ];
  });
  const head = ['Month', 'Recorded or expected', 'Milk (L/day)', 'Change from month before', ...factors.map((f) => PLAIN_FACTOR[f]?.name ?? f)];
  const t: TableSpec = { name: 'Why_milk_changes', at: 5, head, rows, styles: [undefined, undefined, S.int, S.dec1, ...factors.map(() => S.dec1)] };
  return {
    name: 'Why milk changes', widths: [12, 22, 14, 26, ...factors.map(() => 22)],
    rows: header(run, 'Why milk goes up or down', 'Each reason column is litres per day it added (+) or took away (−) compared with the month before. The reasons add up to the change.'),
    tables: [t],
    charts: [{
      kind: 'stacked', title: 'What moved milk each month (litres a day)', table: t, catCol: 0,
      at: { col: 0, row: t.at + rows.length + 3, w: 12, h: 20 },
      series: factors.map((f, i) => ({ name: PLAIN_FACTOR[f]?.name ?? f, col: 4 + i, color: COLORS[i % COLORS.length] })),
    }],
  };
}

function herd(run: PfoiRun, months: number): SheetSpec | null {
  if (!isForecast(run, 'month', 'milking')) return null;
  const groups: SeriesId[] = ['milking', 'dry', 'heifers', 'calves', 'other', 'total_herd'];
  const rows = timeline(run, 'month', months, 12).map((p) => [
    periodLabel(p.period, 'month'), p.future ? 'expected' : 'recorded',
    ...groups.map((s) => r0((p.future ? p[`${s}_f`] : p[s]) as number | undefined)),
  ]);
  const t: TableSpec = { name: 'Herd_groups', at: 5, head: ['Month', 'Recorded or expected', ...groups.map((s) => PLAIN_SERIES[s])], rows, styles: [undefined, undefined, ...groups.map(() => S.int)] };
  const moves = EVENT_SERIES.map((s) => {
    const x = flowTotals(run, 'month', months, s);
    return [PLAIN_SERIES[s], r1(x.total), share(x.total ? x.determined / x.total : null)];
  });
  const m: TableSpec = { name: 'Moves', at: t.at + rows.length + 4, head: ['Move', 'Expected over the look ahead', 'Already known from records'], rows: moves, styles: [undefined, S.dec1, S.pct] };
  const out = header(run, 'Cows and herd groups', 'Average number of animals in each group per month. Whole herd = cows in milk + dry cows + heifers + calves + bulls and other animals.');
  out[m.at - 1] = [{ v: 'Animals moving in and out', s: S.subtitle }];
  return {
    name: 'Herd', widths: [12, 22, 14, 11, 11, 11, 24, 13],
    rows: out, tables: [t, m],
    charts: [{
      kind: 'line', title: 'Animals in each group', table: t, catCol: 0, yTitle: 'animals',
      at: { col: 9, row: 1, w: 10, h: 20 },
      series: groups.slice(0, 4).map((s, i) => ({ name: PLAIN_SERIES[s], col: 2 + i, color: COLORS[i] })),
    }],
  };
}

function events(run: PfoiRun, months: number): SheetSpec | null {
  if (!isForecast(run, 'month', 'calvings')) return null;
  const cols: SeriesId[] = [...EVENT_SERIES, 'mastitis_episodes'];
  const rows = Array.from({ length: months }, (_, i) => {
    const p = addPeriods(firstTarget(run, 'month'), 'month', i);
    return [periodLabel(p, 'month'), ...cols.map((s) => r1(forecastRow(run, 'month', p, s)?.forecast)),
      share((() => { const x = flowSplit(run, 'month', p, 'calvings'); return x && x.determined + x.rate_driven ? x.determined / (x.determined + x.rate_driven) : null; })())];
  });
  const t: TableSpec = { name: 'Events_by_month', at: 5, head: ['Month', ...cols.map((s) => PLAIN_SERIES[s]), 'Calvings already known'], rows, styles: [undefined, ...cols.map(() => S.dec1), S.pct] };
  const totals = EVENT_SERIES.map((s) => {
    let f = 0; let lo = 0; let hi = 0; let ly = 0; let lyOk = true;
    for (let h = 1; h <= months; h++) {
      const p = addPeriods(firstTarget(run, 'month'), 'month', h - 1);
      const r = forecastRow(run, 'month', p, s);
      if (r) { f += r.forecast; lo += r.lower; hi += r.upper; }
      const a = actualRow(run, 'month', addPeriods(p, 'month', -12), s);
      if (a?.value != null) ly += a.value; else lyOk = false;
    }
    return [PLAIN_SERIES[s], r1(f), r1(lo), r1(hi), lyOk ? r1(ly) : null];
  });
  const tt: TableSpec = { name: 'Events_totals', at: t.at + rows.length + 4, head: ['Event', 'Expected total', 'Likely low', 'Likely high', 'Same months last year'], rows: totals, styles: [undefined, S.dec1, S.dec1, S.dec1, S.dec1] };
  const out = header(run, 'Herd events', 'Expected events per month. "Calvings already known" is the share of calvings from pregnancies already confirmed in the records.');
  out[tt.at - 1] = [{ v: 'Totals over the look ahead', s: S.subtitle }];
  return {
    name: 'Herd events', widths: [14, 14, 16, 28, 10, 16, 18, 15, 24],
    rows: out, tables: [t, tt],
    charts: [{
      kind: 'bar', title: 'Expected events per month', table: t, catCol: 0,
      at: { col: 10, row: 1, w: 10, h: 20 },
      series: cols.slice(0, 5).map((s, i) => ({ name: PLAIN_SERIES[s], col: 1 + i, color: COLORS[i] })),
    }],
  };
}

function mastitis(run: PfoiRun): SheetSpec {
  const first = addPeriods(firstTarget(run, 'month'), 'month', 0);
  const mF = forecastRow(run, 'month', first, 'mastitis_episodes');
  const cF = forecastRow(run, 'month', first, 'milking');
  const rate = mF && cF ? mF.forecast / (cF.forecast * periodDays(first, 'month')) : null;
  const rows = timeline(run, 'month', 12, 24).map((p) => [
    periodLabel(p.period, 'month'),
    typeof p.mastitis_episodes === 'number' ? r1(p.mastitis_episodes) : null,
    r1(typeof p.mastitis_episodes_f === 'number' ? p.mastitis_episodes_f
      : rate !== null && typeof p.milking === 'number' ? p.milking * periodDays(p.period, 'month') * rate : null),
  ]);
  const t: TableSpec = { name: 'Mastitis', at: 5, head: ['Month', 'Recorded cases', 'Expected cases'], rows, styles: [undefined, S.dec1, S.dec1] };
  return {
    name: 'Mastitis', widths: [12, 18, 18],
    rows: header(run, 'Mastitis: expected and recorded cases', run.mastitis_rate_period
      ? `Expected cases use how often mastitis happened in ${run.mastitis_rate_period}. If recorded stays far below expected, cases are probably not all written down. Herd level only.`
      : 'No expected cases: there is no mastitis rate from the validation start on. Recorded cases only. Herd level only.'),
    tables: [t],
    charts: [{
      kind: 'combo', title: 'Mastitis cases per month', table: t, catCol: 0,
      at: { col: 4, row: 1, w: 10, h: 20 },
      series: [{ name: 'Recorded cases', col: 1, color: '#A44B3C' }, { name: 'Expected cases', col: 2, color: EXPECTED, dash: true, kind: 'line' }],
    }],
  };
}

function heat(run: PfoiRun): SheetSpec | null {
  const h = run.heat;
  if (!h) return null;
  const rows: Value[][] = [
    ...h.recent.map((d) => [d.date, r1(d.thi_max), null, null, null, h.knot_p75]),
    ...h.climatology.map((c) => [c.date, null, r1(c.p50), r1(c.p10), r1(c.p90), h.knot_p75]),
  ];
  const t: TableSpec = { name: 'Heat', at: 5, head: ['Date', 'Recorded heat', 'Usual heat', 'Usual low', 'Usual high', 'Usual peak for this herd'], rows, styles: [undefined, S.dec1, S.dec1, S.dec1, S.dec1, S.dec1] };
  return {
    name: 'Heat', widths: [12, 16, 14, 12, 12, 26],
    rows: header(run, 'Heat stress (daily heat index, THI)', 'Higher = hotter and more humid. "Usual" comes from past years for the same dates; it is not a weather forecast. Above the herd’s usual peak, cows eat and milk less.'),
    tables: [t],
    charts: [{
      kind: 'line', title: 'Daily heat', table: t, catCol: 0,
      at: { col: 7, row: 1, w: 11, h: 20 },
      series: [
        { name: 'Recorded heat', col: 1, color: '#A44B3C' },
        { name: 'Usual heat', col: 2, color: EXPECTED, dash: true },
        { name: 'Usual peak for this herd', col: 5, color: '#A8770A', dash: true },
      ],
    }],
  };
}

function breeding(run: PfoiRun): SheetSpec {
  const STEP: Record<string, string> = { first_ai: 'Calving to first service', conception: 'Calving to confirmed in calf', calving_interval: 'Calving to next calving' };
  const timing = (run.repro_timing ?? []).filter((r) => r.step !== 'pregnancy').map((r) => [
    r.period, STEP[r.step] ?? r.step, r.median_days ?? null, r.p25_days ?? null, r.p75_days ?? null,
    share(r.by_100d), share(r.by_200d), share(r.censored_share), share(r.left_herd_share), r.n,
  ]);
  const t1: TableSpec = {
    name: 'Breeding_timing', at: 5,
    head: ['Calved in', 'Step', 'Half the cows by day', 'Most cows from day', 'Most cows to day', 'Done by day 100', 'Done by day 200', 'Still waiting', 'Left the herd first', 'Cows'],
    rows: timing, styles: [undefined, undefined, S.int, S.int, S.int, S.pct, S.pct, S.pct, S.pct, S.int],
  };
  const fert = run.fertility.map((f) => [f.period_label, `Generation ${f.generation}`, r1(f.services_per_conception), share(f.abortion_pct / 100)]);
  const t2: TableSpec = { name: 'Fertility', at: t1.at + Math.max(1, timing.length) + 4, head: ['Years', 'Generation', 'Services per pregnancy', 'Pregnancies lost'], rows: fert, styles: [undefined, undefined, S.dec1, S.pct] };
  const out = header(run, 'Breeding and generations', '"Still waiting" counts cows whose records end before the step; they are not failures. Compare generations within the same years only.');
  out[t2.at - 1] = [{ v: 'Fertility by generation', s: S.subtitle }];
  return { name: 'Breeding', widths: [12, 30, 14, 14, 14, 12, 12, 12, 14, 8], rows: out, tables: timing.length ? [t1, t2] : [t2] };
}

function accuracy(run: PfoiRun, months: number): SheetSpec {
  const tables: TableSpec[] = [];
  const out = header(run, 'How far to trust this', 'How close forecasts came, compared with simple rules of thumb, and how complete the records are.');
  let at = 5;
  const section = (title: string, t: Omit<TableSpec, 'at'>) => {
    if (!t.rows.length) return;
    out[at] = [{ v: title, s: S.subtitle }];
    tables.push({ ...t, at: at + 1 });
    at += t.rows.length + 4;
  };
  if (hasRealised(run)) {
    section('How close was this forecast? (checked against what was recorded later)', {
      name: 'How_close', head: ['Number', 'Off by on average', 'Off by (share)', 'Months inside the likely range', 'Months checked'],
      rows: (['milk_litres', 'milking', 'total_herd', 'calvings', 'dry_offs'] as SeriesId[]).filter((s) => isForecast(run, 'month', s))
        .map((s) => ({ s, x: outcomeScore(run, 'month', months, s) })).filter((r) => r.x && r.x.mae !== null)
        .map(({ s, x }) => [PLAIN_SERIES[s], r1(x!.mae), share(x!.maeShare), x!.inside, x!.scored]),
      styles: [undefined, S.dec1, S.pct, S.int, S.int],
    });
  }
  const METHOD: Record<string, string> = { pfoi: 'This forecast', persistence: 'Rule: same as last month', seasonal_naive: 'Rule: same as this month last year', sarima: 'Standard statistics method' };
  const bt = run.backtest.filter((r) => r.grain === 'month' && r.series === 'milk_litres');
  const btTable: Omit<TableSpec, 'at'> = {
    name: 'Versus_rules', head: ['Years tested', 'Months ahead', 'Method', 'Average error (L/day)', 'Real value inside the likely range'],
    rows: bt.map((r) => [r.block === 'test' ? 'Later test years' : 'Years used to build the model', r.horizon, METHOD[r.model] ?? r.model, r0(r.mae), share(r.coverage)]),
    styles: [undefined, S.int, undefined, S.int, S.pct],
  };
  const btAt = at;
  section('Milk: this forecast compared with simple rules of thumb (lower error is better)', btTable);
  section('Accuracy by how complete the records were', {
    name: 'By_record_quality', head: ['Records were', 'Off by on average', 'Inside the likely range', 'Months checked'],
    rows: run.qualityBands.map((q) => [q.band === 'high' ? 'Complete' : q.band === 'moderate' ? 'Some gaps' : 'Poor', share(q.mae_pct), share(q.coverage), q.n_periods]),
    styles: [undefined, S.pct, S.pct, S.int],
  });
  const CHECK: Record<string, string> = { freshness: 'Up to date', completeness: 'Complete', plausibility: 'Believable', source_agreement: 'Sources agree' };
  if (run.record_status) {
    section('Milk record checks', {
      name: 'Record_checks', head: ['Check', 'Result', 'Details'],
      rows: run.record_status.checks.map((c) => [CHECK[c.check] ?? c.check, c.ok === null ? 'not checked' : c.ok ? 'passed' : 'failed', c.detail]),
    });
  }
  section('What the records cover each year', {
    name: 'Coverage', head: ['Year', 'Cow-days with good milk records', 'Milk days that could be checked', 'Days with weather', 'Health records'],
    rows: run.coverage.map((c) => [String(c.year), c.reliable_cow_days, share(c.milk_days_scoreable_pct), share(c.weather_complete_pct), c.health_records]),
    styles: [undefined, S.int, S.pct, S.pct, S.int],
  });
  /* Chart: average milk error by months ahead, this forecast vs the rules (development years). */
  const hs = [...new Set(bt.map((r) => r.horizon))].sort((a, b) => a - b);
  const models = ['pfoi', 'persistence', 'seasonal_naive', 'sarima'].filter((m) => bt.some((r) => r.model === m));
  const chartT: TableSpec | null = hs.length ? {
    name: 'Error_by_months_ahead', at,
    head: ['Months ahead', ...models.map((m) => METHOD[m])],
    rows: hs.map((h) => [`${h} ahead`, ...models.map((m) => r0(bt.find((r) => r.block === 'development' && r.horizon === h && r.model === m)?.mae))]),
    styles: [undefined, ...models.map(() => S.int)],
  } : null;
  const charts: ChartSpec[] = [];
  if (chartT) {
    out[at - 1] = [{ v: 'Average milk error by months ahead (years used to build the model)', s: S.subtitle }];
    tables.push(chartT);
    charts.push({
      kind: 'bar', title: 'Average milk error (litres a day): lower is better', table: chartT, catCol: 0,
      at: { col: 7, row: btAt, w: 9, h: 18 },
      series: models.map((m, i) => ({ name: METHOD[m], col: 1 + i, color: COLORS[i] })),
    });
  }
  return { name: 'How far to trust', widths: [30, 24, 30, 24, 24, 14], rows: out, tables, charts };
}

function tests(run: PfoiRun): SheetSpec {
  const RUNG: Record<string, string> = {
    persistence: 'Simple rule: same as last period', 'current model': 'The forecast model, basic version', '+ recent records': '+ the most recent records',
    '+ heat': '+ heat stress', '+ sensors': '+ milking-sensor signals', 'oracle heat': 'Heat as it really turned out (best case)',
  };
  const tables: TableSpec[] = [];
  const out = header(run, 'How the model was tested', 'For advisers and examiners. Every result keeps the status the model run gave it.');
  let at = 5;
  const section = (title: string, t: Omit<TableSpec, 'at'>) => {
    if (!t.rows.length) return;
    out[at] = [{ v: title, s: S.subtitle }];
    tables.push({ ...t, at: at + 1 });
    at += t.rows.length + 4;
  };
  section('Which information helps (error compared with "same as last period"; below 1 is better)', {
    name: 'Evidence_ladder', head: ['Forecast', 'Ahead', 'Periods', 'Forecast uses', 'Error ratio', 'Cases', 'How far to trust'],
    rows: (run.evidence_ladder ?? []).map((r) => [r.grain, r.horizon, r.band, RUNG[r.rung] ?? r.rung, r.ratio_to_reference != null ? Math.round(r.ratio_to_reference * 100) / 100 : null, r.n, PLAIN_STATUS[r.status]?.label ?? r.status]),
    styles: [undefined, S.int, undefined, undefined, S.dec1, S.int, undefined],
  });
  section('What happens when milk records stop (1.0 = as good as with complete records)', {
    name: 'Outages', head: ['Forecast', 'Ahead', 'Days missing', 'Days since records came back', 'Error vs normal', 'Error vs simple rule', 'Cases'],
    rows: (run.outage_simulation ?? []).map((r) => [r.grain, r.horizon, r.gap_days, r.resumed_days, r1(r.ratio_to_no_outage), r1(r.ratio_to_persistence), r.n]),
    styles: [undefined, S.int, S.int, S.int, S.dec1, S.dec1, S.int],
  });
  section('Signals the model watches', {
    name: 'Signals', head: ['Signal', 'Now'],
    rows: (run.feature_registry ?? []).map((r) => [r.feature, (r.active ?? 0) > 0 ? 'Used in the forecast' : (r.probation ?? 0) > 0 ? 'On trial' : 'Watched, not used yet']),
  });
  return { name: 'Model tests', widths: [16, 8, 14, 40, 14, 18, 26], rows: out, tables };
}

