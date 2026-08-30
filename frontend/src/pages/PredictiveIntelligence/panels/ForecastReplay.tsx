/**
 * Forecast replay (§9) — what did the system predict then, and what happened?
 */

import { REPLAY_VINTAGES, fmtInt, fmtPct, longDate } from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, ForecastValue, Note } from '../ui';

export function ForecastReplay() {
  const { replayOn, setReplayOn, replayVintage, setReplayVintage } = useC2();
  const v = REPLAY_VINTAGES.find((x) => x.madeOn === replayVintage) ?? REPLAY_VINTAGES[0];

  return (
    <Card
      title="Forecast replay"
      sub="Step back to an earlier run and compare what was known then against what actually happened."
      actions={
        <button className={`pfie-btn${replayOn ? ' primary' : ''}`} onClick={() => setReplayOn(!replayOn)}>
          {replayOn ? 'Replay on' : 'Turn on replay'}
        </button>
      }
    >
      {!replayOn ? (
        <p className="sub">
          Replay is off. Turn it on to pick a historical forecast date and see the run that was current then.
        </p>
      ) : (
        <>
          <div className="pfie-row" style={{ marginBottom: 16 }}>
            <label className="pfie-field">
              Forecast made on
              <select value={replayVintage} onChange={(e) => setReplayVintage(e.target.value)}>
                {REPLAY_VINTAGES.map((r) => (
                  <option key={r.madeOn} value={r.madeOn}>{r.label} — for {r.targetLabel}</option>
                ))}
              </select>
            </label>
            <ConfidenceBadge level={v.confidenceThen} />
          </div>

          <div className="pfie-consequence">
            <div>
              <div className="k">Predicted then</div>
              <div className="v">{fmtInt(v.predicted)} L</div>
              <div className="d">{v.targetLabel}, forecast on {longDate(v.madeOn)}</div>
            </div>
            <div>
              <div className="k">Actual</div>
              <div className="v">{v.actual !== null ? `${fmtInt(v.actual)} L` : 'Not yet known'}</div>
              <div className="d">{v.actual !== null ? 'Recorded outturn' : 'This period has not completed'}</div>
            </div>
            <div>
              <div className="k">Forecast error</div>
              <div className="v" style={{ color: v.errorPct === null ? 'var(--muted)' : v.errorPct < 0 ? 'var(--concern)' : 'var(--brand)' }}>
                {v.errorPct === null ? '—' : fmtPct(v.errorPct)}
              </div>
              <div className="d">{v.errorPct === null ? 'Available once the period closes' : 'Predicted against recorded'}</div>
            </div>
          </div>

          <div className="pfie-grid c2" style={{ marginTop: 18 }}>
            <div>
              <div className="pfie-section-title">What was known then</div>
              <ul className="pfie-stack" style={{ gap: 6, fontSize: 12.5 }}>
                {v.knownThen.map((k) => <li key={k}>• {k}</li>)}
              </ul>
            </div>
            <div>
              <div className="pfie-section-title">Information that had not yet arrived</div>
              <ul className="pfie-stack" style={{ gap: 6, fontSize: 12.5 }}>
                {v.laterInformation.map((k) => <li key={k}>• {k}</li>)}
              </ul>
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <Note tone="info">
              Replay shows the run as it stood, without hindsight. Differences between the runs come from
              records that arrived afterwards, not from a change of method.
            </Note>
          </div>
        </>
      )}
    </Card>
  );
}

export function ReplayCompareStrip() {
  const { replayOn, replayVintage } = useC2();
  if (!replayOn) return null;
  const v = REPLAY_VINTAGES.find((x) => x.madeOn === replayVintage);
  if (!v) return null;
  return (
    <Note tone="caution" title={`Replaying the run from ${v.label}.`}>
      Predicted {fmtInt(v.predicted)} L for {v.targetLabel}
      {v.actual !== null ? `, actual ${fmtInt(v.actual)} L (${fmtPct(v.errorPct ?? 0)}).` : '. That period has not closed yet.'}
    </Note>
  );
}

export { ForecastValue };
