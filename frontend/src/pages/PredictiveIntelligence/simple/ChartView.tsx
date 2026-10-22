/** Full-screen viewing and history controls for the simple landing charts. */
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { addPeriods, earliestActual, firstTarget, periodStart, periodsUntilOrigin, type Grain, type PfoiRun } from '../../../data/pfoi';
import { Box, HISTORY } from './common';
import { DateField } from '../DateField';
import { Icon } from '../icons';
import { useLang, useT } from './i18n';
import './chartView.css';

/** `earliest` limits the picker for charts whose data starts later than the milk records. */
export function useChartStart(run: PfoiRun, grain: Grain, earliest?: string) {
  const t = useT();
  // A different forecast or grain starts with its own default window.
  const [choice, setChoice] = useState({ run, grain, date: '' });
  const min = earliest && earliest > earliestActual(run, grain) ? periodStart(earliest, grain) : earliestActual(run, grain);
  const max = firstTarget(run, grain);
  const defaultStart = addPeriods(max, grain, -HISTORY[grain]);
  const chosen = choice.run === run && choice.grain === grain ? choice.date : '';
  const start = chosen || defaultStart;
  const controls = (
    <div className="pfie-chart-timeline pfie-noprint">
      <span className="pfie-chart-timeline-label">{t('Timeline starts')}</span>
      <DateField label={t('Timeline starts')} value={start}
        min={min < defaultStart ? min : defaultStart} max={max}
        onChange={(value) => setChoice({ run, grain, date: periodStart(value, grain) })} />
      {chosen && <button className="pfie-mgr-textbtn" onClick={() => setChoice({ run, grain, date: '' })}>{t('Reset timeline')}</button>}
    </div>
  );
  return { history: chosen ? periodsUntilOrigin(run, grain, chosen) : HISTORY[grain], controls };
}

export function ChartView({ title, actions, controls, children }: {
  title: string; actions: ReactNode; controls: ReactNode;
  children: (expanded: boolean) => ReactNode;
}) {
  const t = useT();
  const { lang } = useLang();
  const [expanded, setExpanded] = useState(false);
  const [workspace, setWorkspace] = useState<HTMLElement | null>(null);
  const back = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const wasExpanded = useRef(false);
  const titleId = useId();
  useEffect(() => { setWorkspace(opener.current?.closest('main') ?? null); }, []);
  useEffect(() => {
    if (!expanded) {
      if (wasExpanded.current) opener.current?.focus();
      wasExpanded.current = false;
      return;
    }
    wasExpanded.current = true;
    const previousScroll = window.scrollY;
    window.scrollTo({ top: 0, behavior: 'auto' });
    back.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.scrollTo({ top: previousScroll, behavior: 'auto' });
    };
  }, [expanded]);

  /* Clicking the chart explains a point; full screen has its own button. */
  const content = (full: boolean) => (
    <Box title={<span id={full ? titleId : undefined}>{title}</span>} actions={<>
      {actions}
      <button ref={full ? undefined : opener} className="pfie-mgr-iconbtn" aria-expanded={full}
        aria-label={full ? t('Close full screen') : t('Full screen')} title={full ? t('Close full screen') : t('Full screen')} onClick={() => setExpanded(!full)}>
        {full ? <>✕ <span>{t('Close full screen')}</span></> : <Icon name="maximize" size={16} />}
      </button>
    </>}>
      {controls}
      {children(full)}
    </Box>
  );
  return <>
    {!expanded && content(false)}
    {expanded && workspace && createPortal(
      <section className={`pfie pfie-chart-dialog pfie-mgr lang-${lang}`} lang={lang} aria-labelledby={titleId}>
        <nav className="pfie-chart-backbar" aria-label={t('Chart navigation')}>
          <button ref={back} type="button" className="pfie-btn" onClick={() => setExpanded(false)}>
            <Icon name="arrowLeft" size={16} /> {t('Back')}
          </button>
        </nav>
        {content(true)}
      </section>, workspace,
    )}
  </>;
}
