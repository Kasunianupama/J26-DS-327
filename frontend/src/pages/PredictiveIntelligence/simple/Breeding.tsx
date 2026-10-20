/**
 * Simple view, "Breeding" tab: calving-to-conception timing, fertility by
 * generation within each period, the herd's make-up by generation and the
 * results by generation. Same rows as the detailed Herd and Generations tabs.
 */

import { useState } from 'react';
import { firstTarget, fmtInt, type ReproStepRow } from '../../../data/pfoi';
import { useRun } from '../source';
import { Rich, periodText, useLang, useT } from './i18n';
import { Box, DemoLine, Explain, NotInRun, SimpleTable, pct } from './common';

const GENS = ['0', '1', '2', '3+'] as const;

export function BreedingTab() {
  return (
    <>
      <Timing />
      <Fertility />
      <MakeUp />
      <Outcomes />
    </>
  );
}

const STEP: Record<ReproStepRow['step'], string> = {
  first_ai: 'Calving to first service',
  conception: 'Calving to confirmed in calf',
  calving_interval: 'Calving to next calving',
  pregnancy: 'Pregnancy kept to calving',
};

function Timing() {
  const run = useRun();
  const t = useT();
  const rows = run.repro_timing ?? [];
  const periods = [...new Set(rows.map((r) => r.period))];
  const [pick, setPick] = useState<string | null>(null);
  if (!rows.length) return <Box title={t('Time to get cows in calf')}><NotInRun /></Box>;
  const p = pick && periods.includes(pick) ? pick : periods[periods.length - 1];
  const at = (s: ReproStepRow['step']) => rows.find((r) => r.period === p && r.step === s);
  const conc = at('conception');
  const preg = at('pregnancy');
  const calved = preg ? preg.calved_of_resolved ?? preg.calved_share : null;

  return (
    <Box
      title={`${t('Time to get cows in calf')}`}
      actions={
        <label className="pfie-mgr-select">{t('Calved in')}
          <select value={p} onChange={(e) => setPick(e.target.value)}>{periods.map((x) => <option key={x} value={x}>{x}</option>)}</select>
        </label>
      }
    >
      <div className="pfie-mgr-facts">
        <div className="pfie-mgr-fact"><span className="lbl">{t('Half confirmed in calf by')}</span><b>{t('day {n}', { n: conc?.median_days ?? '–' })}</b></div>
        {calved != null && <div className="pfie-mgr-fact"><span className="lbl">{t('Pregnancies that ended in a calving')}</span><b>{pct(calved)}</b></div>}
      </div>
      <SimpleTable
        head={[t('Step'), t('Half the cows by'), t('Most cows between'), t('By day 100'), t('By day 200'), t('Still waiting'), t('Left the herd first')]}
        rows={(['first_ai', 'conception', 'calving_interval'] as const).map((s) => at(s)).filter((r): r is ReproStepRow => !!r).map((r) => [
          <b>{t(STEP[r.step])}</b>,
          r.median_days != null ? t('day {n}', { n: r.median_days }) : '–',
          r.p25_days != null && r.p75_days != null ? `${r.p25_days} – ${r.p75_days}` : '–',
          r.by_100d !== undefined ? pct(r.by_100d) : '–',
          r.by_200d !== undefined ? pct(r.by_200d) : '–',
          r.censored_share !== undefined ? pct(r.censored_share) : '–',
          r.left_herd_share !== undefined ? pct(r.left_herd_share) : '–',
        ])}
      />
      <Explain>{t('"First service" is the first recorded insemination. "Still waiting" means the records end before it happened; these are not failures.')}</Explain>
      <DemoLine run={run} />
    </Box>
  );
}

function Fertility() {
  const run = useRun();
  const t = useT();
  const periods = [...new Set(run.fertility.map((f) => f.period_label))];
  const gens = GENS.filter((g) => run.fertility.some((f) => f.generation === g));
  if (!periods.length) return null;
  const cell = (p: string, g: string) => run.fertility.find((f) => f.period_label === p && f.generation === g);
  return (
    <Box title={`${t('Fertility by generation')}`}>
      <SimpleTable
        head={[t('Years'), t('Measure'), ...gens.map((g) => t('Gen {g}', { g }))]}
        textCols={[1]}
        rows={periods.flatMap((p) => [
          [<b>{p}</b>, t('Services per pregnancy'), ...gens.map((g) => { const c = cell(p, g); return c ? c.services_per_conception.toFixed(1) : '–'; })],
          ['', t('Pregnancies lost'), ...gens.map((g) => { const c = cell(p, g); return c ? `${c.abortion_pct.toFixed(1)}%` : '–'; })],
        ])}
      />
      <Explain title={t('What is a generation?')}>
        <Rich text={t('How many generations of a cow\'s mother line were born on this farm (0 = the starting point). **Fewer services per pregnancy is better.** Compare within the same years only.')} />
      </Explain>
    </Box>
  );
}

function MakeUp() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const start = firstTarget(run, 'month');
  const periods = [...new Set(run.generations.map((g) => g.period))].sort();
  if (!periods.length) return null;
  const recorded = periods.filter((p) => p < start);
  const pickPeriods = [recorded[0], recorded[recorded.length - 1], periods[periods.length - 1]]
    .filter((p, i, a): p is string => !!p && a.indexOf(p) === i);
  const share = (p: string, g: string) => run.generations.find((x) => x.period === p && x.generation === g)?.share;
  return (
    <Box title={`${t('Herd make-up by generation')}`}>
      <SimpleTable
        head={[t('Generation'), ...pickPeriods.map((p) => `${periodText(p, 'month', lang)}${p >= start ? ` (${t('expected')})` : ''}`)]}
        rows={GENS.map((g) => [t('Gen {g}', { g }), ...pickPeriods.map((p) => { const s = share(p, g); return s != null ? pct(s) : '–'; })])}
      />
    </Box>
  );
}

const OUTCOME: Record<string, { label: string; fmt: (v: number) => string }> = {
  yield_vs_expected: { label: 'Milk as % of expected (100% = as expected)', fmt: (v) => `${Math.round(v * 100)}%` },
  yield_record_coverage: { label: 'Milking days with a yield record', fmt: pct },
  productive_share: { label: 'Days in milk', fmt: pct },
  days_to_first_service_median: { label: 'Days to first service', fmt: (v) => fmtInt(v) },
  days_to_conception_median: { label: 'Days to confirmed in calf', fmt: (v) => fmtInt(v) },
  conceived_by_150d: { label: 'In calf by day 150', fmt: pct },
  pregnancy_calved_share: { label: 'Pregnancies that ended in a calving', fmt: pct },
  pregnancy_pending_share: { label: 'Pregnancies still going', fmt: pct },
  alarm_share: { label: 'Cow-days with a sensor alarm', fmt: (v) => `${(v * 100).toFixed(1)}%` },
  persistent_alarm_share: { label: 'Cow-days with alarms several days running', fmt: (v) => `${(v * 100).toFixed(1)}%` },
};

function Outcomes() {
  const run = useRun();
  const t = useT();
  const rows = run.generation_outcomes ?? [];
  if (!rows.length) return <Box title={t('Results by generation')}><NotInRun /></Box>;
  const periods = [...new Set(rows.map((r) => r.period))].sort();
  const gens = [...new Set(rows.map((r) => r.generation_group))].sort();
  const outcomes = Object.keys(OUTCOME).filter((o) => rows.some((r) => r.outcome === o));
  const cell = (o: string, p: string, g: string) => rows.find((r) => r.outcome === o && r.period === p && r.generation_group === g);
  return (
    <Box title={`${t('Results by generation')}`}>
      <SimpleTable
        head={[t('Result'), t('Calved in'), ...gens.map((g) => t('Gen {g}', { g }))]}
        textCols={[1]}
        rows={outcomes.flatMap((o) => periods.filter((p) => gens.some((g) => cell(o, p, g))).map((p, i) => [
          i === 0 ? <b>{t(OUTCOME[o].label)}</b> : '',
          p,
          ...gens.map((g) => { const c = cell(o, p, g); return c ? OUTCOME[o].fmt(c.value) : '–'; }),
        ]))}
      />
      <Explain>{t('These show differences, not causes: generations also differ in age and years. Sensor alarms are signals, not diagnoses.')}</Explain>
      <DemoLine run={run} />
    </Box>
  );
}
