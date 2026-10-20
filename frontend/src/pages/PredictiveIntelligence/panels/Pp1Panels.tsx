/**
 * Component 1 (PFOI): PP1 development panels (docs/pp1_frontend_plan.md, F1–F8).
 *
 * Each panel opens with one plain-language sentence, then the numbers. Status badges come
 * from the run document (the model decides what is evaluated), never from this code. A run
 * without a section shows "not available for this run". Herd level only.
 */

import { useMemo, useState } from 'react';
import {
  Area, Bar, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  STATUS_META, fmt1, fmtInt, fmtPct, longDate,
  type GenerationOutcomeRow, type LadderRow, type PfoiRun, type RecordCheck, type ReproStepRow,
} from '../../../data/pfoi';
import { useRun } from '../source';
import { Card, EmptyState, Note, Segmented } from '../ui';

/* ------------------------------------------------------------------ shared */

export function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, tone: 'muted' as const };
  return <span className={`pfie-status ${meta.tone}`}>{meta.label}</span>;
}

function NotAvailable({ what }: { what: string }) {
  return <EmptyState title="Not available for this run">{what} is published by development builds (pfoi-1.2.0-dev) only.</EmptyState>;
}

const DemoNote = ({ run }: { run: PfoiRun }) => (run.source === 'demo'
  ? <p className="pfie-chart-note">Demo values: synthetic, not Farm X data and not results.</p>
  : null);

/* ------------------------------------------------------------------ F1 record status */

const CHECK_LABEL: Record<RecordCheck['check'], string> = {
  freshness: 'Freshness',
  completeness: 'Completeness',
  plausibility: 'Plausibility',
  source_agreement: 'Source agreement',
};

const STATUS_TEXT = {
  current: { title: 'Milk records are current', tone: 'ok' },
  stale: { title: 'Milk records need care', tone: 'caution' },
  withheld: { title: 'No milk forecast: trusted milk records are missing', tone: 'concern' },
} as const;

export function RecordStatusBanner() {
  const run = useRun();
  const [open, setOpen] = useState(false);
  const rs = run.record_status;
  if (!rs) return null;
  const meta = STATUS_TEXT[rs.status];
  const sentence = rs.status === 'withheld'
    ? (rs.reason_text ?? 'There is no trusted recent milk level, so no milk number is given. Herd numbers are still forecast.')
    : rs.status === 'stale'
      ? `The last trusted milk day was ${rs.staleness_days ?? '?'} days before the forecast date, or a record check failed, so milk ranges are wider.`
      : `Milk was recorded and checked up to ${rs.last_trusted_day ? longDate(rs.last_trusted_day) : 'the forecast date'}.`;
  return (
    <section className={`pfie-rs ${meta.tone}`} role="status" aria-live="polite">
      <div className="pfie-rs-main">
        <span className="pfie-rs-light" aria-hidden />
        <div>
          <b>{meta.title}</b>
          <p>{sentence}</p>
        </div>
        <button className="pfie-btn ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? 'Hide checks' : 'Show the record checks'}
        </button>
      </div>
      {open && (
        <div className="pfie-rs-checks">
          {rs.checks.map((c) => (
            <div key={c.check} className={`pfie-rs-check ${c.ok === null ? 'na' : c.ok ? 'ok' : 'fail'}`}>
              <span className="lbl">{CHECK_LABEL[c.check]}</span>
              <b>{c.value === null ? 'n/a' : c.check === 'source_agreement' ? fmtPct(c.value, 0) : c.check === 'plausibility' ? `${fmt1(c.value)} L` : fmtInt(c.value)}</b>
              <span className="det">{c.detail}</span>
              <span className="mark">{c.ok === null ? 'not checked' : c.ok ? 'passes' : 'fails'}</span>
            </div>
          ))}
          <p className="pfie-chart-note">
            {rs.fresh_days} trusted milk days in the last {rs.lookback_days}. Ranges:{' '}
            {run.interval_method?.milk === 'aci_quality_band' ? 'adaptive, scaled by record quality' : 'from past errors'}
            {run.interval_method?.staleness_scale && run.interval_method.staleness_scale !== 'not used'
              ? `; widening for stale records: ${run.interval_method.staleness_scale}` : ''}. {rs.rule}.
          </p>
        </div>
      )}
    </section>
  );
}

/** F2: the milk card shown instead of a number when the forecast is withheld. */
export function MilkWithheldCard() {
  const run = useRun();
  const rs = run.record_status;
  if (!rs?.milk_withheld) return null;
  return (
    <Card icon="flag" title="Milk forecast withheld" sub={`Forecast date ${longDate(run.origin_date)}`}>
      <p>
        There were no trusted milk records in the {rs.lookback_days} days before this date and no earlier
        calibration, so the page shows no milk number rather than a guess. Missing records are not zero
        milk. The herd forecast (cows in milk, calvings, dry-offs) still runs, because it comes from herd records.
      </p>
      <p className="pfie-chart-note">Last trusted milk day: {rs.last_trusted_day ? longDate(rs.last_trusted_day) : 'none'}.</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ F4 heat outlook */

export function HeatOutlook() {
  const run = useRun();
  const h = run.heat;
  const data = useMemo(() => {
    if (!h) return [];
    const rows: Record<string, number | string | null | [number, number]>[] = h.recent.map((r) => ({
      date: r.date, recent: r.thi_max,
    }));
    h.climatology.forEach((c) => rows.push({ date: c.date, usual: c.p50, band: [c.p10, c.p90] }));
    return rows;
  }, [h]);
  if (!h) return <Card icon="flag" title="Heat outlook"><NotAvailable what="The heat outlook" /></Card>;
  const hotDays = h.knot_p75 !== null ? h.climatology.slice(0, 30).filter((c) => c.p50 > (h.knot_p75 as number)).length : 0;
  return (
    <Card
      icon="flag"
      title="Heat outlook"
      sub={`Daily max THI · weather up to ${longDate(h.last_weather_day)} (published about ${h.weather_lag_days} days late)`}
    >
      <p>
        {h.hot_run_days && h.hot_run_days > 0
          ? <>The last {fmtInt(h.hot_run_days)} available days were hotter than this herd&apos;s usual peak heat. </>
          : <>Recent heat is within this herd&apos;s usual range. </>}
        In past years, {hotDays} of the next 30 days were usually above that level. This is the usual weather for the
        time of year, not a weather forecast.
      </p>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#70827a' }} minTickGap={36} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={36} domain={['auto', 'auto']} />
          <Area dataKey="band" stroke="none" fill="#5b7fa6" fillOpacity={0.15} isAnimationActive={false} name="Usual range (10–90%)" />
          <Line dataKey="usual" stroke="#5b7fa6" strokeDasharray="5 4" dot={false} isAnimationActive={false} name="Usual (median of past years)" />
          <Line dataKey="recent" stroke="#a44b3c" strokeWidth={2} dot={false} isAnimationActive={false} name="Recorded" />
          {h.knot_p75 !== null && <ReferenceLine y={h.knot_p75} stroke="#a8770a" strokeDasharray="3 3" label={{ value: "Herd's 75th pct", fontSize: 10, fill: '#a8770a', position: 'insideTopLeft' }} />}
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="pfie-chart-note">
        Heat is measured against this herd&apos;s own past daily max THI (75th percentile {h.knot_p75 ?? '–'}, 90th {h.knot_p90 ?? '–'}),
        not a universal threshold. Source: {h.source}. Whether heat improves the milk forecast is shown in Model evaluation.
      </p>
      <DemoNote run={run} />
    </Card>
  );
}

/* ------------------------------------------------------------------ F5 reproduction timeline */

const STEP_LABEL: Record<ReproStepRow['step'], string> = {
  first_ai: 'Calving → first recorded service',
  conception: 'Calving → known conception',
  pregnancy: 'Pregnancy kept to calving',
  calving_interval: 'Calving → next calving',
};

export function ReproTimeline() {
  const run = useRun();
  const rows = run.repro_timing;
  const periods = [...new Set((rows ?? []).map((r) => r.period))];
  const [period, setPeriod] = useState<string | null>(null);
  if (!rows?.length) return <Card icon="herd" title="Reproductive timing"><NotAvailable what="Reproductive timing" /></Card>;
  const p = period && periods.includes(period) ? period : periods[periods.length - 1];
  const at = (step: ReproStepRow['step']) => rows.find((r) => r.period === p && r.step === step);
  const conc = at('conception');
  return (
    <Card
      icon="herd"
      title="Reproductive timing"
      sub="From calving to the next calving, herd level"
      actions={<Segmented label="Calvings" value={p} onChange={setPeriod} options={periods.map((x) => ({ id: x, label: x }))} />}
    >
      <p>
        For cows that calved in {p}, half had a known conception by about day{' '}
        <b>{conc?.median_days ?? '–'}</b>. Cows still open at the end of the record count as <i>still open</i>,
        not as failures, and cows that left the herd are counted separately.
      </p>
      <div className="pfie-tablewrap">
        <table className="pfie-table">
          <thead>
            <tr><th>Step</th><th className="num">Median days</th><th className="num">Middle half</th><th className="num">By day 100</th><th className="num">By day 200</th><th className="num">Still open</th><th className="num">Left herd</th><th className="num">n</th></tr>
          </thead>
          <tbody>
            {(['first_ai', 'conception', 'calving_interval'] as const).map((s) => {
              const r = at(s);
              if (!r) return null;
              return (
                <tr key={s}>
                  <td>{STEP_LABEL[s]}</td>
                  <td className="num">{r.median_days ?? '–'}</td>
                  <td className="num">{r.p25_days ?? '–'}–{r.p75_days ?? '–'}</td>
                  <td className="num">{r.by_100d !== undefined ? fmtPct(r.by_100d, 0) : '–'}</td>
                  <td className="num">{r.by_200d !== undefined ? fmtPct(r.by_200d, 0) : '–'}</td>
                  <td className="num">{r.censored_share !== undefined ? fmtPct(r.censored_share, 0) : '–'}</td>
                  <td className="num">{r.left_herd_share !== undefined ? fmtPct(r.left_herd_share, 0) : '–'}</td>
                  <td className="num">{fmtInt(r.n)}</td>
                </tr>
              );
            })}
            {at('pregnancy') && (() => {
              const r = at('pregnancy')!;
              const calved = r.calved_of_resolved ?? r.calved_share;
              const lost = r.lost_of_resolved ?? r.lost_share;
              return (
                <tr>
                  <td>{STEP_LABEL.pregnancy}</td>
                  <td className="num" colSpan={3}>{calved != null ? `${fmtPct(calved, 0)} calved` : '–'}{r.calved_of_resolved != null ? ' (of known outcomes)' : ''}</td>
                  <td className="num" colSpan={2}>{lost != null ? `${fmtPct(lost, 0)} lost` : '–'}</td>
                  <td className="num">{r.censored_share !== undefined ? `${fmtPct(r.censored_share, 0)} still pregnant` : '–'}</td>
                  <td className="num">{fmtInt(r.n)}</td>
                </tr>
              );
            })()}
          </tbody>
        </table>
      </div>
      <p className="pfie-chart-note">
        &quot;First service&quot; is the first <i>recorded</i> insemination: no record does not prove no service.
        Conceptions count once a pregnancy check or calving confirmed them. These timings feed the future calvings
        and the milking herd above.
      </p>
      <DemoNote run={run} />
    </Card>
  );
}

/* ------------------------------------------------------------------ F6 generation outcomes */

const OUTCOME_LABEL: Record<string, { label: string; fmt: (v: number) => string; note?: string }> = {
  yield_vs_expected: { label: 'Yield vs expected', fmt: (v) => `${fmt1(v * 100)}%`, note: 'same parity, lactation stage and heat' },
  yield_record_coverage: { label: 'Yield records per milking day', fmt: (v) => fmtPct(v, 0), note: 'low = weak yield evidence' },
  productive_share: { label: 'Days in milk (calved cows)', fmt: (v) => fmtPct(v, 0) },
  days_to_first_service_median: { label: 'Days to first recorded service', fmt: (v) => fmtInt(v) },
  days_to_conception_median: { label: 'Days to known conception', fmt: (v) => fmtInt(v) },
  conceived_by_150d: { label: 'Conceived by day 150', fmt: (v) => fmtPct(v, 0) },
  pregnancy_calved_share: { label: 'Pregnancies that calved', fmt: (v) => fmtPct(v, 0), note: 'of those with a known outcome' },
  pregnancy_pending_share: { label: 'Pregnancies still running', fmt: (v) => fmtPct(v, 0), note: 'not failures' },
  alarm_share: { label: 'Cow-days with a sensor alarm', fmt: (v) => fmtPct(v, 1), note: 'signals, not diagnoses' },
  persistent_alarm_share: { label: 'Cow-days in a persistent alarm run', fmt: (v) => fmtPct(v, 1), note: 'signals, not diagnoses' },
};

export function GenerationOutcomes() {
  const run = useRun();
  const rows = run.generation_outcomes;
  if (!rows?.length) return <Card title="Outcomes by generation"><NotAvailable what="Outcomes by generation" /></Card>;
  const periods = [...new Set(rows.map((r) => r.period))].sort();
  const gens = [...new Set(rows.map((r) => r.generation_group))].sort();
  const outcomes = Object.keys(OUTCOME_LABEL).filter((o) => rows.some((r) => r.outcome === o));
  const cell = (o: string, p: string, g: string): GenerationOutcomeRow | undefined =>
    rows.find((r) => r.outcome === o && r.period === p && r.generation_group === g);
  return (
    <Card title="Outcomes by generation" sub="Separate outcomes, compared within the same calving period">
      <Note tone="info" title="Associations, not genetics.">
        Generation counts farm-born generations in the maternal line. Generations differ in age, parity and time,
        so each is compared only within a calving period; yield also within parity, stage and heat. There is no
        single efficiency score and no feed efficiency (no intake records).
      </Note>
      <div className="pfie-tablewrap">
        <table className="pfie-table">
          <thead>
            <tr><th>Outcome</th><th>Period</th>{gens.map((g) => <th key={g} className="num">Gen {g}</th>)}</tr>
          </thead>
          <tbody>
            {outcomes.flatMap((o) => periods.filter((p) => gens.some((g) => cell(o, p, g))).map((p, i) => (
              <tr key={`${o}-${p}`}>
                <td>{i === 0 ? <>{OUTCOME_LABEL[o].label}{OUTCOME_LABEL[o].note && <span className="pfie-chart-note"> · {OUTCOME_LABEL[o].note}</span>}</> : ''}</td>
                <td>{p}</td>
                {gens.map((g) => {
                  const c = cell(o, p, g);
                  return <td key={g} className="num" title={c ? `n = ${fmtInt(c.n)}` : undefined}>{c ? OUTCOME_LABEL[o].fmt(c.value) : '–'}</td>;
                })}
              </tr>
            )))}
          </tbody>
        </table>
      </div>
      <p className="pfie-chart-note">Hover a value for its n (cow-days or lactations).</p>
      <DemoNote run={run} />
    </Card>
  );
}

/* ------------------------------------------------------------------ F3 outage recovery */

export function OutageRecovery() {
  const run = useRun();
  const rows = run.outage_simulation ?? [];
  const cells = [...new Set(rows.map((r) => `${r.grain}|${r.horizon}`))];
  const [cellPick, setCell] = useState<string | null>(null);
  const [gap, setGap] = useState<number>(90);
  if (!rows.length) return <Card title="What happens when milk records stop"><NotAvailable what="The outage simulation" /></Card>;
  const cell = cellPick && cells.includes(cellPick) ? cellPick : cells.find((c) => c.startsWith('weekly')) ?? cells[0];
  const [grain, h] = cell.split('|');
  const gaps = [...new Set(rows.filter((r) => r.gap_days > 0).map((r) => r.gap_days))].sort((a, b) => a - b);
  const g = gaps.includes(gap) ? gap : gaps[0];
  const pts = rows.filter((r) => r.grain === grain && String(r.horizon) === h && r.gap_days === g)
    .sort((a, b) => a.resumed_days - b.resumed_days)
    .map((r) => ({ back: `${r.resumed_days} d`, cost: r.ratio_to_no_outage, vsPers: r.ratio_to_persistence, n: r.n }));
  const ongoing = pts[0];
  const week = pts.find((p) => p.back === '7 d');
  return (
    <Card
      title="What happens when milk records stop"
      sub="Simulated outages on 2017–2023: recorded milk hidden from the model, still used for scoring"
      actions={
        <>
          <Segmented label="Outage" value={String(g)} onChange={(v) => setGap(Number(v))} options={gaps.map((x) => ({ id: String(x), label: `${x} d` }))} />
          <select value={cell} onChange={(e) => setCell(e.target.value)} aria-label="Forecast step">
            {cells.map((c) => { const [gr, hh] = c.split('|'); return <option key={c} value={c}>{gr} · {hh} ahead</option>; })}
          </select>
        </>
      }
    >
      <p>
        {ongoing && <>While a {g}-day outage is still going on, the forecast error is <b>{fmt1(ongoing.cost)}×</b> the normal error. </>}
        {week && <>One week after records return it is <b>{fmt1(week.cost)}×</b>.</>}
      </p>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={pts} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="back" tick={{ fontSize: 11, fill: '#70827a' }} label={{ value: 'days of records back', fontSize: 10, fill: '#70827a', position: 'insideBottomRight', offset: -2 }} />
          <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={36} domain={[0.8, 'auto']} />
          <ReferenceLine y={1} stroke="#93a29b" strokeDasharray="3 3" />
          <Line dataKey="cost" name="Error vs no outage" stroke="#9a4f27" strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="vsPers" name="Error vs persistence (same outage)" stroke="#5b7fa6" strokeDasharray="5 4" isAnimationActive={false} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </LineChart>
      </ResponsiveContainer>
      <p className="pfie-chart-note">
        1.0 = as good as with complete records. Only milk is hidden here; in a real outage herd events are missed
        too, so real outages are likely worse. n = {fmtInt(pts[0]?.n ?? 0)} forecast periods per point.
      </p>
      <DemoNote run={run} />
    </Card>
  );
}

/* ------------------------------------------------------------------ F7 evidence ladder */

const BAND_LABEL: Record<LadderRow['band'], string> = { all: 'All periods', normal: 'Normal', heat: 'Heat', recovery: 'After a break' };

export function EvidenceLadder() {
  const run = useRun();
  const rows = run.evidence_ladder ?? [];
  const cells = [...new Set(rows.map((r) => `${r.grain}|${r.horizon}`))];
  const [cellPick, setCell] = useState<string | null>(null);
  const [band, setBand] = useState<LadderRow['band']>('all');
  if (!rows.length) return <Card title="Which additions help"><NotAvailable what="The evidence ladder" /></Card>;
  const cell = cellPick && cells.includes(cellPick) ? cellPick : cells[0];
  const [grain, h] = cell.split('|');
  const bands = [...new Set(rows.map((r) => r.band))] as LadderRow['band'][];
  const sel = rows.filter((r) => r.grain === grain && String(r.horizon) === h && r.band === (bands.includes(band) ? band : 'all'));
  const data = sel.map((r) => ({ rung: r.rung, ratio: r.ratio_to_reference ?? null, n: r.n, status: r.status }));
  return (
    <Card
      title="Which additions help"
      sub="Each step scored on exactly the same forecast periods · error relative to persistence (below 1 = better)"
      actions={
        <>
          <Segmented label="Periods" value={bands.includes(band) ? band : 'all'} onChange={setBand} options={bands.map((b) => ({ id: b, label: BAND_LABEL[b] }))} />
          <select value={cell} onChange={(e) => setCell(e.target.value)} aria-label="Forecast step">
            {cells.map((c) => { const [gr, hh] = c.split('|'); return <option key={c} value={c}>{gr} · {hh} ahead</option>; })}
          </select>
        </>
      }
    >
      <p>
        Read from top to bottom: each line adds one thing to the model. A bar below 1 beats &quot;same as last
        period&quot;. The badge says how far each number can be trusted.
      </p>
      <ResponsiveContainer width="100%" height={Math.max(160, 34 * data.length)}>
        <ComposedChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="#eef2f0" horizontal={false} />
          <XAxis type="number" domain={[0, 'auto']} tick={{ fontSize: 11, fill: '#70827a' }} />
          <YAxis type="category" dataKey="rung" width={130} tick={{ fontSize: 11, fill: '#34483f' }} />
          <ReferenceLine x={1} stroke="#93a29b" strokeDasharray="3 3" />
          <Bar dataKey="ratio" fill="#9a4f27" isAnimationActive={false} />
          <Tooltip />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="pfie-tablewrap">
        <table className="pfie-table">
          <thead><tr><th>Step</th><th className="num">vs persistence</th><th className="num">n</th><th>Status</th></tr></thead>
          <tbody>
            {sel.map((r) => (
              <tr key={r.rung}>
                <td>{r.rung}</td>
                <td className="num">{r.ratio_to_reference != null ? r.ratio_to_reference.toFixed(2) : '–'}</td>
                <td className="num">{fmtInt(r.n)}</td>
                <td><StatusBadge status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="pfie-chart-note">
        &quot;Oracle&quot; uses the weather that actually happened in the forecast period: it shows the most heat
        information could add, and is never an operational result. 2024–26 numbers are post-test development, not
        an untouched test.
      </p>
      <DemoNote run={run} />
    </Card>
  );
}

/* ------------------------------------------------------------------ F8 sensor registry */

const FEATURE_LABEL: Record<string, string> = {
  persistent_alarm_share_7d: 'Cows with alarms on 3+ of 7 days',
  combined_alarm_share_7d: 'Cows with blood and conductivity alarms',
  attach_problem_share_7d: 'Sessions with kick-offs or re-attaches',
  low_yield_share_7d: 'Sessions flagged low yield',
  yield_vs_expected_7d: 'Session milk vs expected',
  linked_share_28d: 'Sessions linked to a cow',
  entry_lag_28d: 'Days until records are entered',
  heat_load_7d: 'Heat load, last 7 available days',
  thi_max_3d: 'Peak heat, last 3 available days',
  mastitis_per_cow_28d: 'Recorded mastitis per cow',
};

export function SensorRegistry() {
  const run = useRun();
  const rows = run.feature_registry ?? [];
  if (!rows.length) return <Card title="Signals the model watches"><NotAvailable what="The signal registry" /></Card>;
  const statusOf = (r: (typeof rows)[number]) => ((r.active ?? 0) > 0 ? 'active' : (r.probation ?? 0) > 0 ? 'probation' : 'shadow');
  return (
    <Card title="Signals the model watches" sub="A new signal is used only after enough months of evidence">
      <p>
        <b>Shadow</b> = recorded and watched, not used. <b>Probation</b> = used with a strong pull towards no effect.
        <b> Active</b> = used. Missing records count as missing, never as &quot;no problem&quot;; alarms are signals, not diagnoses.
      </p>
      <div className="pfie-tablewrap">
        <table className="pfie-table">
          <thead><tr><th>Signal</th><th>Now</th><th className="num">Forecast dates shadow / probation / active</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.feature}>
                <td>{FEATURE_LABEL[r.feature] ?? r.feature}</td>
                <td><span className={`pfie-status ${statusOf(r) === 'active' ? 'ok' : statusOf(r) === 'probation' ? 'caution' : 'muted'}`}>{statusOf(r)}</span></td>
                <td className="num">{fmtInt(r.shadow ?? 0)} / {fmtInt(r.probation ?? 0)} / {fmtInt(r.active ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DemoNote run={run} />
    </Card>
  );
}

/* ------------------------------------------------------------------ 1c what-if scenarios */

const SCEN_SERIES: { id: 'milk_litres' | 'milking' | 'total_herd'; label: string }[] = [
  { id: 'milk_litres', label: 'Milk' },
  { id: 'milking', label: 'Milking cows' },
  { id: 'total_herd', label: 'Total herd' },
];

export function ScenarioBands() {
  const run = useRun();
  const rows = run.scenarios ?? [];
  const kinds = [...new Set(rows.map((r) => r.kind))];
  const [kindPick, setKind] = useState<string | null>(null);
  const [seriesPick, setSeries] = useState<'milk_litres' | 'milking' | 'total_herd'>('milking');
  if (!rows.length) return <Card title="What if it happens again?"><NotAvailable what="Scenarios" /></Card>;
  const kind = kindPick && kinds.includes(kindPick) ? kindPick : (kinds.find((k) => k.includes('contraction')) ?? kinds[0]);
  const seriesOpts = SCEN_SERIES.filter((x) => rows.some((r) => r.kind === kind && r.series === x.id));
  const series = seriesOpts.some((x) => x.id === seriesPick) ? seriesPick : seriesOpts[0]?.id;
  const sel = rows.filter((r) => r.kind === kind && r.series === series).sort((a, b) => a.horizon - b.horizon);
  const data = sel.map((r) => ({ period: r.target_period.slice(0, 7), forecast: r.forecast, scenario: r.scenario, band: [r.low, r.high] as [number, number] }));
  const label = sel[0]?.label ?? kind;
  return (
    <Card
      icon="flag"
      title="What if it happens again?"
      sub="Forecast if the next months go the way they did after earlier episodes of this kind"
      actions={
        <>
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Scenario">
            {kinds.map((k) => <option key={k} value={k}>{rows.find((r) => r.kind === k)?.label ?? k}</option>)}
          </select>
          {series && <Segmented label="Series" value={series} onChange={setSeries} options={seriesOpts} />}
        </>
      }
    >
      <p>{sel[0]?.sentence ?? ''}</p>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="period" tick={{ fontSize: 11, fill: '#70827a' }} />
          <YAxis tick={{ fontSize: 11, fill: '#70827a' }} width={52} tickFormatter={(v: number) => fmtInt(v)} />
          <Area dataKey="band" stroke="none" fill="#a44b3c" fillOpacity={0.14} isAnimationActive={false} name={`If ${label} repeat (range)`} />
          <Line dataKey="forecast" stroke="#5b7fa6" strokeDasharray="5 4" dot={false} isAnimationActive={false} name="Forecast" />
          <Line dataKey="scenario" stroke="#a44b3c" strokeWidth={2} dot={false} isAnimationActive={false} name={`If ${label} repeat`} />
          <Tooltip formatter={(v: number | [number, number]) => (Array.isArray(v) ? `${fmtInt(v[0])}–${fmtInt(v[1])}` : fmtInt(v))} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="pfie-chart-note">
        Based on {sel[0]?.n_episodes ?? 0} earlier episode{(sel[0]?.n_episodes ?? 0) === 1 ? '' : 's'} in this herd.
        Management decisions such as a removal campaign cannot be forecast from herd records; this shows what
        happened before, not a prediction that it will happen.
      </p>
      <DemoNote run={run} />
    </Card>
  );
}
