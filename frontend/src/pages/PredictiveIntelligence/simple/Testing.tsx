/**
 * Simple view, "Model tests" tab: which information helps, what happens when
 * milk records stop, and which sensor signals are used yet. Same rows as the
 * detailed Model evaluation tab; every result keeps its status.
 */

import { useState } from 'react';
import { type EvidenceStatus, type LadderRow } from '../../../data/pfoi';
import { useRun } from '../source';
import { Rich, useT, type T } from './i18n';
import { Box, DemoLine, Explain, NotInRun, PLAIN_STATUS, SimpleTable } from './common';

export function TestingTab() {
  return (
    <>
      <Ladder />
      <Outage />
      <Signals />
    </>
  );
}

const ahead = (t: T, g: string, x: string) => {
  const n = Number(x);
  if (g === 'monthly') return n === 1 ? t('Next month') : t('Next {n} months', { n });
  if (g === 'weekly') return n === 1 ? t('Next week') : t('Next {n} weeks', { n });
  return n === 1 ? t('Tomorrow') : t('Next {n} days', { n });
};
const BAND: Record<LadderRow['band'], string> = { all: 'All periods', normal: 'Normal weather', heat: 'Hot periods', recovery: 'After a gap in records' };
/* Ladder steps are labelled by the model run (`--rung`); the usual ones in plain words, others as given. */
const RUNG: Record<string, string> = {
  persistence: 'Simple rule: same as last time',
  'current model': 'The forecast model, basic version',
  '+ recent records': '+ the most recent records',
  '+ heat': '+ heat stress',
  '+ sensors': '+ milking-sensor signals',
  'oracle heat': 'Heat as it really turned out (best case)',
};

function Status({ s }: { s: EvidenceStatus }) {
  const t = useT();
  const m = PLAIN_STATUS[s] ?? { label: s, tone: 'muted' as const };
  return <span className={`pfie-status ${m.tone}`}>{t(m.label)}</span>;
}

function Ladder() {
  const run = useRun();
  const t = useT();
  const rows = run.evidence_ladder ?? [];
  const cells = [...new Set(rows.map((r) => `${r.grain}|${r.horizon}`))];
  const [cellPick, setCell] = useState<string | null>(null);
  const [band, setBand] = useState<LadderRow['band']>('all');
  if (!rows.length) return <Box title={t('Which information helps the forecast')}><NotInRun /></Box>;
  const cell = cellPick && cells.includes(cellPick) ? cellPick : cells[0];
  const [grain, h] = cell.split('|');
  const bands = [...new Set(rows.map((r) => r.band))] as LadderRow['band'][];
  const b = bands.includes(band) ? band : 'all';
  const sel = rows.filter((r) => r.grain === grain && String(r.horizon) === h && r.band === b);

  return (
    <Box
      title={`${t('Which information helps the forecast')}`}
      actions={
        <>
          <select value={cell} onChange={(e) => setCell(e.target.value)} aria-label={t('Look ahead')}>
            {cells.map((c) => { const [g, x] = c.split('|'); return <option key={c} value={c}>{ahead(t, g, x)}</option>; })}
          </select>
          <select value={b} onChange={(e) => setBand(e.target.value as LadderRow['band'])} aria-label={t('Periods')}>
            {bands.map((x) => <option key={x} value={x}>{t(BAND[x])}</option>)}
          </select>
        </>
      }
    >
      <SimpleTable
        head={[t('Forecast uses'), t('Error compared with "same as last time"'), t('Cases'), t('How far to trust this result')]}
        textCols={[3]}
        rows={sel.map((r) => [
          <b>{t(RUNG[r.rung] ?? r.rung)}</b>,
          r.ratio_to_reference == null ? '–' : (
            <span className={r.ratio_to_reference < 1 ? 'up' : r.ratio_to_reference > 1 ? 'down' : ''}>
              {r.ratio_to_reference < 1 ? t('{n}% smaller', { n: Math.round((1 - r.ratio_to_reference) * 100) })
                : r.ratio_to_reference > 1 ? t('{n}% bigger', { n: Math.round((r.ratio_to_reference - 1) * 100) }) : t('the same')}
            </span>
          ),
          r.n,
          <Status s={r.status} />,
        ])}
      />
      <Explain><Rich text={t('If the error gets smaller as a line is added, that information helps. **"Best case only"** uses the weather that really happened, which nobody knows in advance.')} /></Explain>
      <DemoLine run={run} />
    </Box>
  );
}

function Outage() {
  const run = useRun();
  const t = useT();
  const rows = run.outage_simulation ?? [];
  const cells = [...new Set(rows.map((r) => `${r.grain}|${r.horizon}`))];
  const [cellPick, setCell] = useState<string | null>(null);
  const [gapPick, setGap] = useState<number>(90);
  if (!rows.length) return <Box title={t('What happens when milk records stop')}><NotInRun /></Box>;
  const cell = cellPick && cells.includes(cellPick) ? cellPick : cells.find((c) => c.startsWith('weekly')) ?? cells[0];
  const [grain, h] = cell.split('|');
  const gaps = [...new Set(rows.filter((r) => r.gap_days > 0).map((r) => r.gap_days))].sort((a, b) => a - b);
  const gap = gaps.includes(gapPick) ? gapPick : gaps[0];
  const pts = rows.filter((r) => r.grain === grain && String(r.horizon) === h && r.gap_days === gap).sort((a, b) => a.resumed_days - b.resumed_days);
  const times = (x: number) => `${x.toFixed(1)}×`;
  const week = pts.find((p) => p.resumed_days === 7);

  return (
    <Box
      title={`${t('What happens when milk records stop')}`}
      actions={
        <>
          <select value={gap} onChange={(e) => setGap(Number(e.target.value))} aria-label={t('Records missing for')}>
            {gaps.map((g) => <option key={g} value={g}>{t('{n} days missing', { n: g })}</option>)}
          </select>
          <select value={cell} onChange={(e) => setCell(e.target.value)} aria-label={t('Look ahead')}>
            {cells.map((c) => { const [g, x] = c.split('|'); return <option key={c} value={c}>{ahead(t, g, x)}</option>; })}
          </select>
        </>
      }
    >
      <div className="pfie-mgr-facts">
        {pts[0] && <div className="pfie-mgr-fact warn"><span className="lbl">{t('While records are missing')}</span><b>{t('{x} the normal error', { x: times(pts[0].ratio_to_no_outage) })}</b></div>}
        {week && <div className="pfie-mgr-fact"><span className="lbl">{t('One week after they return')}</span><b>{t('{x} the normal error', { x: times(week.ratio_to_no_outage) })}</b></div>}
      </div>
      <SimpleTable
        head={[t('Days since records came back'), t('Error compared with normal'), t('Error compared with "same as last time"')]}
        rows={pts.map((p) => [p.resumed_days === 0 ? t('still missing') : t('{n} days', { n: p.resumed_days }), times(p.ratio_to_no_outage), times(p.ratio_to_persistence)])}
      />
      <Explain>{t('1.0× = as good as with complete records. Keep milk recording going.')}</Explain>
      <DemoLine run={run} />
    </Box>
  );
}

const SIGNAL: Record<string, string> = {
  persistent_alarm_share_7d: 'Cows with alarms on 3 or more of the last 7 days',
  combined_alarm_share_7d: 'Cows with both blood and conductivity alarms',
  attach_problem_share_7d: 'Milkings with kick-offs or re-attaches',
  low_yield_share_7d: 'Milkings flagged as low yield',
  yield_vs_expected_7d: 'Milk per milking compared with expected',
  linked_share_28d: 'Milkings linked to a cow',
  entry_lag_28d: 'Days until records are entered',
  heat_load_7d: 'Heat over the last 7 days',
  thi_max_3d: 'Peak heat over the last 3 days',
  mastitis_per_cow_28d: 'Recorded mastitis per cow',
};

function Signals() {
  const run = useRun();
  const t = useT();
  const rows = run.feature_registry ?? [];
  if (!rows.length) return <Box title={t('Signals the model watches')}><NotInRun /></Box>;
  const state = (r: (typeof rows)[number]) => ((r.active ?? 0) > 0 ? 'used' : (r.probation ?? 0) > 0 ? 'trial' : 'watched');
  const word = { used: 'Used in the forecast', trial: 'On trial', watched: 'Watched, not used yet' };
  const tone = { used: 'ok', trial: 'caution', watched: 'muted' };
  return (
    <Box title={`${t('Signals the model watches')}`}>
      <SimpleTable
        head={[t('Signal'), t('Now')]}
        textCols={[1]}
        rows={rows.map((r) => [t(SIGNAL[r.feature] ?? r.feature), <span className={`pfie-status ${tone[state(r)]}`}>{t(word[state(r)])}</span>])}
      />
      <DemoLine run={run} />
    </Box>
  );
}
