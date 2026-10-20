/**
 * Simple view, "Why milk changes" tab: the reasons for any month's change, and
 * a month-by-month list with the biggest reason. Reads the attribution rows,
 * which are published by month.
 */

import { useState } from 'react';
import { addPeriods, attributionMonths, firstTarget, fmtInt, milkBreakdown } from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { PLAIN_FACTOR } from '../panels/ContributionChart';
import { periodText, useLang, useT } from './i18n';
import { Reasons } from './Reasons';
import { PickHint, PointExplanation, usePointPick } from './PointExplain';
import { Box, MonthlyOnlyNote, SimpleTable, litres } from './common';

export function ReasonsTab() {
  const { grain } = usePfoi();
  return (
    <>
      <MonthlyOnlyNote grain={grain} />
      <WhyMilkChanges />
      <MonthByMonth />
    </>
  );
}

function WhyMilkChanges() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { horizon, grain } = usePfoi();
  const months = attributionMonths(run);
  const start = firstTarget(run, 'month');
  const ahead = months.filter((m) => m >= start);
  const fallback = (grain === 'month' ? ahead[Math.min(horizon, ahead.length) - 1] : ahead[0]) ?? months[months.length - 1];
  const [pick, setPick] = useState<string | null>(null);
  const month = pick && months.includes(pick) ? pick : fallback;
  const bd = month ? milkBreakdown(run, month) : null;
  if (!months.length || !month) return null;

  return (
    <Box
      title={`${t('Why milk goes up or down')}`}
      actions={
        <label className="pfie-mgr-select">{t('Month')}
          <select value={month} onChange={(e) => setPick(e.target.value)}>
            {months.map((m) => <option key={m} value={m}>{periodText(m, 'month', lang)} {m >= start ? `(${t('expected')})` : `(${t('recorded')})`}</option>)}
          </select>
        </label>
      }
    >
      {bd ? (
        <Reasons
          parts={bd.parts.filter((p) => bd.isPast || p.factor !== 'residual')}
          start={bd.start} end={bd.end} isPast={bd.isPast}
          fromLabel={periodText(addPeriods(month, 'month', -1), 'month', lang)} toLabel={periodText(month, 'month', lang)}
        />
      ) : <p className="pfie-mgr-note">{t('No reasons are published for this month.')}</p>}
    </Box>
  );
}

function MonthByMonth() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const start = firstTarget(run, 'month');
  const months = attributionMonths(run).filter((m) => milkBreakdown(run, m));
  const [all, setAll] = useState(false);
  const listed = all ? months : months.filter((m) => m >= addPeriods(start, 'month', -6));
  const { picked, pick, clear } = usePointPick();
  const rows = listed.map((m) => {
    const bd = milkBreakdown(run, m)!;
    const parts = bd.parts.filter((p) => bd.isPast || p.factor !== 'residual');
    const top = [...parts].sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
    const change = bd.end - bd.start;
    const plain = top ? PLAIN_FACTOR[top.factor] : undefined;
    return [
      <>{periodText(m, 'month', lang)}{m >= start && <span className="pfie-mgr-tag">{t('expected')}</span>}</>,
      litres(bd.end),
      <span className={change > 0.5 ? 'up' : change < -0.5 ? 'down' : ''}>{change >= 0 ? '▲ +' : '▼ −'}{fmtInt(Math.abs(change))}</span>,
      top && plain ? t(top.value >= 0 ? plain.up : plain.down) : '—',
    ];
  });

  return (
    <Box
      title={`${t('Month by month')}`}
      actions={months.length > listed.length || all
        ? <button className="pfie-btn" onClick={() => setAll((x) => !x)}>{all ? t('Show recent months') : t('Show all months')}</button>
        : undefined}
    >
      <SimpleTable
        head={[t('Month'), t('Milk (L a day)'), t('Change'), t('Biggest reason')]} rows={rows} textCols={[3]}
        onRow={(i) => pick(listed[i] === picked ? null : listed[i])} selected={listed.indexOf(picked ?? '')}
      />
      <PickHint picked={picked} />
      {picked && <MonthPoint at={picked} onClose={clear} />}
    </Box>
  );
}

/** The month-by-month list explains at month level, whatever the switch says. */
function MonthPoint({ at, onClose }: { at: string; onClose: () => void }) {
  const { grain, setGrain } = usePfoi();
  /* A month row is a month: show it as one even while Daily or Weekly is selected. */
  if (grain !== 'month') {
    return (
      <div className="pfie-mgr-point">
        <PointMonthNotice onMonthly={() => setGrain('month')} />
      </div>
    );
  }
  return <PointExplanation kind="milk" at={at} onClose={onClose} />;
}

function PointMonthNotice({ onMonthly }: { onMonthly: () => void }) {
  const t = useT();
  return (
    <p className="pfie-mgr-lead">{t('This list is by month.')} <button className="pfie-btn" onClick={onMonthly}>{t('Switch to Monthly')}</button>
    </p>
  );
}
