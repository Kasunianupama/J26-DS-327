/** Full-screen viewing and history controls for the simple landing charts. */
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { addPeriods, earliestActual, firstTarget, periodStart, periodsUntilOrigin, type Grain, type PfoiRun } from '../../../data/pfoi';
import { Box, HISTORY } from './common';
import { periodText, useLang, useT } from './i18n';
import './chartView.css';

export function useChartStart(run: PfoiRun, grain: Grain) {
  const t = useT();
  const { lang } = useLang();
  // A different forecast or grain starts with its own default window.
  const [choice, setChoice] = useState({ run, grain, date: '' });
  const min = earliestActual(run, grain);
  const max = firstTarget(run, grain);
  const defaultStart = addPeriods(max, grain, -HISTORY[grain]);
  const chosen = choice.run === run && choice.grain === grain ? choice.date : '';
  const start = chosen || defaultStart;
  const controls = (
    <div className="pfie-chart-timeline pfie-noprint">
      <label>
        <span>{t('Timeline starts')}</span>
        <input type="date" value={start} min={min < defaultStart ? min : defaultStart} max={max}
          onChange={(e) => {
            const value = e.target.value;
            if (!value) { setChoice({ run, grain, date: '' }); return; }
            if (!e.target.validity.valid) return;
            setChoice({ run, grain, date: periodStart(value, grain) });
          }} />
      </label>
      <button className="pfie-mgr-textbtn" disabled={!chosen} onClick={() => setChoice({ run, grain, date: '' })}>{t('Reset timeline')}</button>
      <span className="muted">{periodText(start, grain, lang)}</span>
    </div>
  );
  return { history: chosen ? periodsUntilOrigin(run, grain, chosen) : HISTORY[grain], controls };
}

export function ChartView({ title, actions, controls, asTable, children }: {
  title: string; actions: ReactNode; controls: ReactNode; asTable: boolean;
  children: (expanded: boolean) => ReactNode;
}) {
  const t = useT();
  const { lang } = useLang();
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const wasExpanded = useRef(false);
  const titleId = useId();
  useEffect(() => {
    if (!expanded) {
      if (wasExpanded.current) opener.current?.focus();
      wasExpanded.current = false;
      return;
    }
    wasExpanded.current = true;
    const element = dialog.current;
    const previousOverflow = document.body.style.overflow;
    element?.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      element?.close();
      document.body.style.overflow = previousOverflow;
    };
  }, [expanded]);

  const content = (full: boolean) => (
    <Box title={<span id={full ? titleId : undefined}>{title}</span>} actions={<>
      {actions}
      <button ref={full ? undefined : opener} className="pfie-mgr-outline" aria-haspopup={full ? undefined : 'dialog'} onClick={() => setExpanded(!full)}>{full ? t('Close full screen') : t('Full screen')}</button>
    </>}>
      {controls}
      {!full && !asTable && <button className="pfie-mgr-textbtn pfie-noprint" onClick={() => setExpanded(true)}>{t('Click the chart to view full screen')}</button>}
      <div className={!full && !asTable ? 'pfie-chart-preview' : undefined}
        onClick={!full && !asTable ? (e) => {
          if (e.target instanceof Element && e.target.closest('.recharts-wrapper')) setExpanded(true);
        } : undefined}>
        {children(full)}
      </div>
    </Box>
  );
  return <>
    {!expanded && content(false)}
    <dialog ref={dialog} className={`pfie-chart-dialog pfie-mgr lang-${lang}`} lang={lang} aria-labelledby={titleId}
      onCancel={() => setExpanded(false)} onClose={() => setExpanded(false)}
      onClick={(e) => { if (e.target === e.currentTarget) setExpanded(false); }}>
      {expanded && content(true)}
    </dialog>
  </>;
}
