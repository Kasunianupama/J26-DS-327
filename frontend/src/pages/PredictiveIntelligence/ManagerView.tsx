/**
 * Component 1 (PFOI): the simple view for farm staff.
 *
 * Landing: the short answer plus milk, herd population and herd-events charts.
 * Everything else is one tab away, so the page stays short. Weekly / Monthly
 * and the look ahead are shared with the detailed view; English or
 * Sinhala is chosen at the top. Numbers are rounded, changes are compared with
 * the last recorded period, and any point can be clicked for an explanation.
 */

import { useEffect, useRef, useState } from 'react';
import {
  confidenceOf, findings, flowTotals, fmtInt, headline, horizonOptions, isForecast, milkBreakdown,
  type Finding, type Grain, type PfoiRun,
} from '../../data/pfoi';
import { useModelOrigin, useRun, useRunPicker } from './source';
import { ModelNotice } from './RunStatus';
import { usePfoi } from './state';
import { Icon } from './icons';
import { LangProvider, Rich, aheadText, dateLabel, periodText, useLang, useT, type T } from './simple/i18n';
import { NavProvider, PLAIN_CONFIDENCE, PLAIN_PULL, hasRange, litres, useNav, type TabId } from './simple/common';
import { HerdEventsChart, OverviewCharts } from './simple/Charts';
import { PointExplanation } from './simple/PointExplain';
import { ReasonsTab } from './simple/Milk';
import { PeriodTab } from './simple/Month';
import { HerdTab } from './simple/Herd';
import { EventsTab } from './simple/Events';
import { HeatTab } from './simple/Heat';
import { BreedingTab } from './simple/Breeding';
import { TrustTab } from './simple/Trust';
import { TestingTab } from './simple/Testing';
import { ExportDialog } from './simple/ExportDialog';

export { PLAIN_CONFIDENCE };

export function ManagerView({ onDetailed }: { onDetailed: () => void }) {
  return (
    <LangProvider>
      <NavProvider>
        <Simple onDetailed={onDetailed} />
      </NavProvider>
    </LangProvider>
  );
}

const GRAINS: { id: Grain; label: string }[] = [
  { id: 'day', label: 'Daily' },
  { id: 'week', label: 'Weekly' },
  { id: 'month', label: 'Monthly' },
];

function Simple({ onDetailed }: { onDetailed: () => void }) {
  const run = useRun();
  const t = useT();
  const { lang, setLang } = useLang();
  const { grain, setGrain, horizon, setHorizon } = usePfoi();
  const options = horizonOptions(run, grain);
  const h = options.includes(horizon) ? horizon : options[options.length - 1];
  const rs = run.record_status;
  const [exporting, setExporting] = useState(false);
  const [help, setHelp] = useState(false);
  const [eventAt, setEventAt] = useState<string | null>(null);

  useEffect(() => { setEventAt(null); }, [run.origin_date, grain, horizon]);

  return (
    <div className={`pfie-mgr lang-${lang}`} lang={lang === 'si' ? 'si' : 'en'}>
      <section className="pfie-mgr-toolbar" aria-label={t('Settings')}>
        <div className="tb-row">
          <ForecastDate />
          <span className="spacer" />
          <span className="tb-actions pfie-noprint">
            <span className="pfie-mgr-seg small" role="group" aria-label="Language / භාෂාව">
              <button aria-pressed={lang === 'en'} onClick={() => setLang('en')}>English</button>
              <button aria-pressed={lang === 'si'} onClick={() => setLang('si')}>සිංහල</button>
            </span>
            <button className="pfie-mgr-outline" onClick={() => setExporting(true)}>{t('Download for Excel')}</button>
          </span>
        </div>

        <div className="tb-row tb-controls pfie-noprint">
          <span className="tb-field">
            <span className="tb-label">{t('Show by')}</span>
            <span className="pfie-mgr-seg" role="group" aria-label={t('Show by')}>
              {GRAINS.map((g) => <button key={g.id} aria-pressed={grain === g.id} onClick={() => setGrain(g.id)}>{t(g.label)}</button>)}
            </span>
          </span>
          <span className="tb-field">
            <span className="tb-label">{t('Look ahead')}</span>
            <span className="pfie-mgr-seg" role="group" aria-label={t('Look ahead')}>
              {options.map((o) => <button key={o} aria-pressed={h === o} onClick={() => setHorizon(o)}>{aheadText(t, grain, o)}</button>)}
            </span>
          </span>
        </div>

        <div className="tb-row pfie-mgr-key">
          <span><i className="solid" />{t('Recorded')}</span>
          <span><i className="dash" />{t('Expected')}</span>
          <span><i className="band" />{t('Likely range')}</span>
          <span className="muted">{t('Click a point to explain it')}</span>
          <span className="spacer" />
          <button className="pfie-mgr-textbtn pfie-noprint" aria-expanded={help} onClick={() => setHelp((x) => !x)}>{help ? t('Hide help') : t('Help')}</button>
        </div>
      </section>
      {help && (
        <ul className="pfie-mgr-howto">
          <li> <Rich text={t('**Top:** the answer, milk, herd and herd-events charts.')} /></li>
          <li> <Rich text={t('**Tabs below:** pick one to see more.')} /></li>
          <li> <Rich text={t('**Weekly / Monthly** and **Next …** change every chart.')} /></li>
          <li> <Rich text={t('**Click a point** or a table row to get it explained.')} /></li>
        </ul>
      )}

      {run.source === 'demo' && <p className="pfie-mgr-demo" role="note">{t('Practice data: made-up numbers, not real Farm X numbers.')}</p>}
      {rs && rs.status !== 'current' && (
        <p className={`pfie-mgr-alert ${rs.status === 'withheld' ? 'concern' : 'caution'}`} role="status">
           {rs.status === 'withheld' ? t('No milk forecast: recent milk records are missing.') : t('Milk records are out of date, so the milk range is wider.')}
        </p>
      )}

      <ShortAnswer steps={h} />

      <OverviewCharts />

      <div className="pfie-mgr-charts pfie-mgr-secondary-charts">
        <HerdEventsChart selection={{ picked: eventAt, pick: setEventAt }} />
        {eventAt && <div className="pfie-overview-explanation">
          <PointExplanation
            kind="events"
            at={eventAt}
            onClose={() => setEventAt(null)}
            series={['calvings', 'dry_offs', 'abortions', 'deaths', 'culls_sales']}
          />
        </div>}
      </div>

      <Tabs />

      <div className="pfie-mgr-foot pfie-noprint">
        <button className="pfie-btn" onClick={() => setExporting(true)}>{t('Download for Excel')}</button>
        <button className="pfie-btn" onClick={() => window.print()}>{t('Print')}</button>
        <span className="spacer" />
        <button className="pfie-btn ghost" onClick={() => { window.scrollTo({ top: 0 }); onDetailed(); }}>{t('Detailed view')} <Icon name="arrowRight" size={13} />
        </button>
      </div>
      <p className="pfie-mgr-note">{t('Whole-herd forecast only: no individual animals are shown.')}</p>

      {exporting && <ExportDialog months={grain === 'month' ? h : Math.min(12, Math.max(1, Math.round(h / (grain === 'week' ? 4.35 : 30.4))))} onClose={() => setExporting(false)} />}
    </div>
  );
}

/* ------------------------------------------------------------------ top */

function ForecastDate() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { origins, origin, setOrigin, loading } = useRunPicker();
  const { models, current } = useModelOrigin();
  const latest = origins[origins.length - 1];
  const [open, setOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    selectedRef.current?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (!pickerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const chooseOrigin = (next: string) => {
    setOrigin(next);
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <span className="tb-field">
      <span className="tb-label">{t('Forecast date')}</span>
      {origins.length > 1 ? (
        <>
          <div className="pfie-mgr-dateselect pfie-noprint" ref={pickerRef}>
            <button
              ref={triggerRef}
              type="button"
              className="pfie-mgr-date-trigger"
              aria-label={t('Forecast date')}
              aria-haspopup="listbox"
              aria-expanded={open}
              onClick={() => setOpen((shown) => !shown)}
            >
              <span>{dateLabel(origin, lang)}</span>
              {origin === latest && <small>{t('latest')}</small>}
              <i aria-hidden />
            </button>
            {open && (
              <div className="pfie-mgr-date-menu" role="listbox" aria-label={t('Forecast date')}>
                {[...origins].reverse().map((o) => (
                  <button
                    key={o}
                    ref={o === origin ? selectedRef : undefined}
                    type="button"
                    role="option"
                    aria-selected={o === origin}
                    onClick={() => chooseOrigin(o)}
                  >
                    <span>{dateLabel(o, lang)}</span>
                    {o === latest && <small>{t('latest')}</small>}
                    {models[o] && models[o] !== current && <small title={models[o]} style={{ color: '#8a6414' }}>{t('older model')}</small>}
                    {o === origin && <b aria-hidden>✓</b>}
                  </button>
                ))}
              </div>
            )}
          </div>
          <b className="pfie-printonly">{dateLabel(run.origin_date, lang)}</b>
          {origin !== latest && <button className="pfie-mgr-textbtn pfie-noprint" onClick={() => setOrigin(latest)}>{t('Go to latest')}</button>}
        </>
      ) : <b>{dateLabel(run.origin_date, lang)}</b>}
      {loading && <span className="muted">…</span>}
      <ModelNotice />
    </span>
  );
}

/* ------------------------------------------------------------------ short answer */

const UNIT: Record<Grain, string> = { day: 'day', week: 'week', month: 'month' };

function ShortAnswer({ steps }: { steps: number }) {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain } = usePfoi();
  const milk = headline(run, grain, steps, 'milk_litres');
  const cows = isForecast(run, grain, 'milking') ? headline(run, grain, steps, 'milking') : null;
  const mastitis = isForecast(run, grain, 'mastitis_episodes') ? headline(run, grain, steps, 'mastitis_episodes') : null;
  const calvings = isForecast(run, grain, 'calvings') ? flowTotals(run, grain, steps, 'calvings') : null;
  const base = milk?.baselinePeriod ?? cows?.baselinePeriod ?? null;
  const level = confidenceOf(milk?.quality);
  const conf = PLAIN_CONFIDENCE[level];
  const confidenceEvidence = run.qualityBands.find((row) => row.band === milk?.quality);
  const ahead = aheadText(t, grain, steps);

  const change = (pctV: number | null | undefined) => {
    if (pctV == null || !base) return null;
    const r = Math.round(pctV);
    return { r, text: r === 0 ? t('same as {b}', { b: periodText(base, grain, lang) }) : t(r > 0 ? '{n}% more than {b}' : '{n}% less than {b}', { n: Math.abs(r), b: periodText(base, grain, lang) }) };
  };
  const mc = change(milk?.changePct);
  const cc = change(cows?.changePct);

  return (
    <section className="pfie-mgr-answer" aria-label={t('The short answer')}>
      <div className="pfie-mgr-summary">
        <p>
          {milk ? <Rich text={t('**{p}:** about **{l} litres of milk a day**.', { p: periodText(milk.period, grain, lang), l: litres(milk.value) })} />
            : t('No milk forecast for this date.')}
          {mc && <> {mc.r > 0 ? '▲' : mc.r < 0 ? '▼' : '●'} <Rich text={`**${mc.text}**`} /> ({t('last recorded {u}', { u: t(UNIT[grain]) })}).</>}
        </p>
        <span className="pfie-mgr-conf-wrap">
          <span className={`pfie-mgr-conf conf-${level}`}><span aria-hidden>{conf.dots}</span> {t(conf.label)}</span>
          <button type="button" className="pfie-mgr-conf-info" aria-label={t('Show confidence details')} aria-describedby="pfie-confidence-tooltip">i</button>
          <span id="pfie-confidence-tooltip" className="pfie-mgr-conf-tip" role="tooltip">
            <strong>{t(conf.label)}</strong>
            <span><i>{t('Forecast')}</i><b>{milk ? `${litres(milk.value)} L/${t('day')}` : '—'}</b></span>
            <span><i>{t('Likely range')}</i><b>{milk ? `${litres(milk.lower)}–${litres(milk.upper)} L/${t('day')}` : '—'}</b></span>
            <span><i>{t('Look ahead')}</i><b>{ahead}</b></span>
            {confidenceEvidence && <span className="wide"><i>{t('Past tests')}</i><b>{Math.round(confidenceEvidence.coverage * 100)}% {t('Inside the likely range').toLowerCase()}</b></span>}
          </span>
        </span>
      </div>

      <div className="pfie-mgr-tiles">
        <Tile label={t('Milk a day')} value={milk ? litres(milk.value) : '—'} unit="L"
          change={mc} foot={milk ? (hasRange(milk.lower, milk.upper) ? t('likely {a} – {b}', { a: litres(milk.lower), b: litres(milk.upper) }) : t('no likely range published')) : undefined} />
        <Tile label={t('Cows in milk')} value={cows ? fmtInt(cows.value) : '—'}
          change={cc} foot={cows && hasRange(cows.lower, cows.upper) ? t('likely {a} – {b}', { a: fmtInt(cows.lower), b: fmtInt(cows.upper) }) : undefined} />
        {calvings && Math.round(calvings.total) > 0 && (
          <Tile label={`${t('Calvings')} · ${ahead}`} value={fmtInt(calvings.total)}
            foot={t('{n}% already known in calf', { n: Math.round((calvings.determined / calvings.total) * 100) })} />
        )}
        {mastitis && Math.round(mastitis.pathTotal) > 0 && (
          <Tile label={`${t('Mastitis cases')} · ${ahead}`} value={`~${fmtInt(mastitis.pathTotal)}`} foot={t('rough guide')} />
        )}
      </div>
    </section>
  );
}

function Tile({ label, value, unit, change, foot }: {
  label: string; value: string; unit?: string; change?: { r: number; text: string } | null; foot?: string;
}) {
  return (
    <div className="pfie-mgr-tile">
      <span className="lbl">{label}</span>
      <span className="val">{value}{unit && <i> {unit}</i>}</span>
      {change && <span className={`chg ${change.r > 0 ? 'up' : change.r < 0 ? 'down' : 'flat'}`}>{change.r > 0 ? '▲' : change.r < 0 ? '▼' : '●'} {change.text}</span>}
      {foot && <span className="foot">{foot}</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ tabs */

const TABS: { id: TabId; label: string }[] = [
  { id: 'watch', label: 'What to watch' },
  { id: 'reasons', label: 'Why milk changes' },
  { id: 'period', label: 'One date' },
  { id: 'herd', label: 'Herd movement' },
  { id: 'events', label: 'Herd events' },
  { id: 'heat', label: 'Heat' },
  { id: 'breeding', label: 'Breeding' },
  { id: 'trust', label: 'How far to trust' },
  { id: 'tests', label: 'Model tests' },
];

function Tabs() {
  const t = useT();
  const run = useRun();
  const { tab, go } = useNav();
  const attention = findings(run).filter((f) => watchItem(run, t, f, 'en')?.act).length;
  return (
    <section className="pfie-mgr-tabsec" id="mgr-tabs">
      <nav className="pfie-mgr-tabs pfie-noprint" role="tablist" aria-label={t('More')}>
        {TABS.map((x, i) => (
          <button key={x.id} role="tab" aria-selected={tab === x.id} onClick={() => go(x.id)}>
            <span className="num" aria-hidden>{i + 1}</span>
            <span>{t(x.label)}</span>
            {x.id === 'watch' && attention > 0 && <span className="count">{attention}</span>}
          </button>
        ))}
      </nav>
      <div className="pfie-mgr-tabbody" role="tabpanel">
        {tab === 'watch' && <WatchList />}
        {tab === 'reasons' && <ReasonsTab />}
        {tab === 'period' && <PeriodTab />}
        {tab === 'herd' && <HerdTab />}
        {tab === 'events' && <EventsTab />}
        {tab === 'heat' && <HeatTab />}
        {tab === 'breeding' && <BreedingTab />}
        {tab === 'trust' && <TrustTab />}
        {tab === 'tests' && <TestingTab />}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ what to watch */

type Watch = { title: string; text: string; tone: 'concern' | 'caution' | 'info'; act: boolean; go?: TabId };

function watchItem(run: PfoiRun, t: T, f: Finding, lang: 'en' | 'si'): Watch | null {
  switch (f.id) {
    case 'milk-withheld':
      return { title: t('No milk forecast this time'), text: t('Recent milk records are missing. Check milk recording.'), tone: 'concern', act: true, go: 'trust' };
    case 'milk-stale':
      return { title: t('Milk records are out of date'), text: t('The milk range is wider until new records come in.'), tone: 'caution', act: true, go: 'trust' };
    case 'milk-low': {
      const m = f.link.period;
      const bd = m ? milkBreakdown(run, m) : null;
      const pull = bd?.parts.filter((p) => p.factor !== 'residual' && p.value < 0).sort((a, b) => a.value - b.value)[0];
      return {
        title: t('Lowest milk month: {m}', { m: m ? periodText(m, 'month', lang) : '' }),
        text: [bd ? t('About {l} litres a day.', { l: litres(bd.end) }) : '', pull ? t('Main reason: {r}.', { r: t(PLAIN_PULL[pull.factor]) }) : ''].join(' ').trim(),
        tone: 'caution', act: true, go: 'reasons',
      };
    }
    case 'calvings-next': {
      const c = flowTotals(run, 'month', 3, 'calvings');
      return {
        title: t('About {n} calvings in the next 3 months', { n: fmtInt(c.total) }),
        text: c.total > 0 ? t('{n}% already known in calf. Plan pens and labour.', { n: Math.round((c.determined / c.total) * 100) }) : '',
        tone: 'info', act: true, go: 'events',
      };
    }
    case 'heat-ahead':
      return { title: t('Hot weather: watch for heat stress'), text: t('Hot days lower milk. Based on usual weather, not a forecast.'), tone: 'caution', act: true, go: 'heat' };
    case 'abortion-shift': {
      const g0 = run.fertility.filter((r) => r.generation === '0');
      const a = g0[0];
      const b = g0[g0.length - 1];
      return {
        title: t('More pregnancies lost than before'),
        text: a && b ? t('{b}% in {pb}, up from {a}% in {pa}.', { a: a.abortion_pct, pa: a.period_label, b: b.abortion_pct, pb: b.period_label }) : '',
        tone: 'caution', act: true, go: 'breeding',
      };
    }
    case 'mastitis-gap':
      return { title: t('Fewer mastitis cases recorded than expected'), text: t('Some cases may not be written down.'), tone: 'info', act: false, go: 'events' };
    case 'curve-evidence':
      return { title: t('Recent per-cow milk records are thin'), text: t('The model learns mostly from older years.'), tone: 'info', act: false, go: 'trust' };
    case 'sensors-shadow':
      return { title: t('Milking-sensor signals not used yet'), text: t('Not enough history yet.'), tone: 'info', act: false, go: 'tests' };
    default:
      return { title: f.title, text: f.summary, tone: f.severity === 'attention' ? 'caution' : 'info', act: f.kind !== 'Data limitation' };
  }
}

function WatchList() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { go } = useNav();
  const items = findings(run).map((f) => ({ id: f.id, w: watchItem(run, t, f, lang) })).filter((x): x is { id: string; w: Watch } => !!x.w);
  const groups = [
    { title: t('Needs attention'), list: items.filter((i) => i.w.act) },
    { title: t('About the records'), list: items.filter((i) => !i.w.act) },
  ].filter((g) => g.list.length);
  if (!groups.length) return <p className="pfie-mgr-note">{t('Nothing stands out.')}</p>;
  return (
    <div className="pfie-mgr-watchgrid">
      {groups.map((g) => (
        <div className="pfie-mgr-card" key={g.title}>
          <h3>{g.title}</h3>
          <ul className="pfie-mgr-watch">
            {g.list.map(({ id, w }) => (
              <li key={id} className={w.tone}>
                <div>
                  <b>{w.title}</b>
                  {w.text && <span>{w.text}</span>}
                </div>
                {w.go && <button className="pfie-mgr-link pfie-noprint" onClick={() => go(w.go!)}>{t('Show')} →</button>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
