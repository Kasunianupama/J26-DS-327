import { useEffect, useState } from 'react';
import { C1Forecast, loadC1 } from './member4Api';
import { futureOutlook } from './forecastOutlook.mjs';

export function EarlyWarningOutlook({ refresh }: { refresh: number }) {
  const [days, setDays] = useState(1);
  const [target, setTarget] = useState('');
  const [rows, setRows] = useState<C1Forecast[]>([]);
  const [status, setStatus] = useState('loading');
  // Re-evaluate the calendar while the dashboard remains open overnight.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 60000); return () => window.clearInterval(timer); }, []);
  useEffect(() => {
    const controller = new AbortController(); setStatus('loading'); setRows([]);
    loadC1(controller.signal).then(data => { if (!controller.signal.aborted) { setRows(data); setStatus('ready'); } })
      .catch(() => { if (!controller.signal.aborted) setStatus('unavailable'); });
    return () => controller.abort();
  }, [refresh]);
  const tomorrow = new Date(Date.parse(now.toISOString().slice(0, 10)) + 86400000).toISOString().slice(0, 10);
  const start = target || tomorrow;
  const outlook = futureOutlook(rows, start, days, now);
  const format = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return <section className="m4-panel m4-future-outlook" aria-label="Future forecast context, separate from historical scores">
    <div className="m4-section-title"><div><h2><span className="m4-outlook-icon" aria-hidden="true">↗</span> Early Warning Outlook</h2>
      <p>Upcoming milk-production context, separate from your historical farm scores.</p></div>
      <span className="m4-chip">{status === 'loading' ? 'Checking forecasts' : outlook.available ? 'Forecast context' : 'Outlook unavailable'}</span></div>
    <div className="m4-toolbar m4-outlook-toolbar"><div className="m4-toggle" role="group" aria-label="Forecast horizon">
      <button aria-pressed={days === 1} onClick={() => { setDays(1); setTarget(''); }}>Tomorrow</button>
      <button aria-pressed={days === 7} onClick={() => { setDays(7); setTarget(''); }}>Next 7 Days</button></div>
      <label>Target start date (UTC)<input type="date" min={tomorrow} value={start} onChange={event => setTarget(event.target.value)} /></label></div>
    <div className="m4-outlook-meta"><span>Forecast origin: <strong>{outlook.origin ?? 'Unavailable'}</strong></span>
      <span>Target: <strong>{outlook.dates.length ? `${outlook.dates[0]}${days === 7 ? ` – ${outlook.dates[6]}` : ''}` : 'Choose a future date'}</strong></span></div>
    {status === 'loading' ? <p role="status">Checking available C1 milk forecasts…</p> : !outlook.available ?
      <p className="m4-state" role="status">{status === 'unavailable' ? 'Current C1 forecast information is unavailable or does not meet the required quality and provenance checks.' : outlook.reason}</p> :
      <div className="m4-forecast-cards">{outlook.rows.map(row => <article key={row.target_period}>
        <span>{row.target_period}</span><strong>{format(row.forecast)} <small>litres/day</small></strong>
        <p>{row.lower != null && row.upper != null ? `Supplied range: ${format(row.lower)}–${format(row.upper)} litres/day` : 'Uncertainty range not provided'}</p>
        <span className="m4-risk-badge">Quality: {row.quality_flag}</span></article>)}</div>}
    <p className="m4-outlook-caption">Milk forecasts describe expected herd production. No Low/Medium/High warning is assigned without an approved policy.</p>
  </section>;
}
