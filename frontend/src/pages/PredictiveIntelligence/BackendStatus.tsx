import { useEffect, useState } from 'react';
import { DATA_THROUGH, isoDate, longDate } from '../../data/component2';
import { usePredictiveBackend } from './backend';

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Colombo', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
const dateFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Colombo', day: '2-digit', month: 'short', year: 'numeric',
});

export function BackendStatus() {
  const { snapshot, loading, error } = usePredictiveBackend();
  const generatedAt = snapshot?.generated_at;
  const [liveTime, setLiveTime] = useState<Date | null>(null);

  useEffect(() => {
    const serverTime = generatedAt ? Date.parse(generatedAt) : NaN;
    if (!Number.isFinite(serverTime) || error) {
      setLiveTime(null);
      return;
    }
    // Advance from the backend timestamp, not the user's potentially skewed clock.
    const receivedAt = performance.now();
    const tick = () => setLiveTime(new Date(serverTime + performance.now() - receivedAt));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [generatedAt, error]);

  const updatedAt = generatedAt ? new Date(generatedAt) : null;
  const validUpdate = updatedAt && Number.isFinite(updatedAt.getTime()) ? updatedAt : null;
  const status = error ? (snapshot ? 'Cached' : 'Fallback') : loading ? 'Connecting' : 'Backend';

  return <>
    <span className="pfie-live" title={error
      ? `Backend unavailable; showing ${snapshot ? 'last successful snapshot' : 'prototype fallback'}: ${error}`
      : 'Live backend clock · Sri Lanka time (UTC+05:30) · synced every minute'}>
      <i aria-hidden />{status}{!error && !loading && liveTime ? ` · ${timeFormat.format(liveTime)}` : ''}
    </span>
    <div className="pfie-stamp">
      <span title={validUpdate ? `Snapshot updated ${dateFormat.format(validUpdate)} at ${timeFormat.format(validUpdate)} (Sri Lanka time)` : 'No successful backend update yet'}>
        Updated <b>{validUpdate ? dateFormat.format(validUpdate) : '—'}</b>
      </span>
      <span title="Latest date covered by the source records, not the current clock date">
        Data through <b>{longDate(snapshot?.data_through ?? isoDate(DATA_THROUGH))}</b>
      </span>
    </div>
  </>;
}
