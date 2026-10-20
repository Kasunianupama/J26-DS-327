/**
 * Component 1 (PFOI): "Forecast as of" bar.
 *
 * Picks the forecast date the whole page shows and says what kind of view it is:
 * a final-test date (frozen model, outcomes known), a development date, or the
 * published outlook. For past dates a score strip compares the forecasts up to the
 * selected horizon with what was then recorded. The outcomes are display only;
 * the model never saw them.
 */

import {
  GRAIN_LABEL, SERIES_META, TEST_BLOCK_START,
  fmt1, fmtInt, hasRealised, isForecast, longDate, outcomeScore, periodLabel, targetPeriod,
  type Grain, type OutcomeScore, type SeriesId,
} from '../../../data/pfoi';
import { usePfoi } from '../state';
import { useRun, useRunPicker } from '../source';

const SCORED: SeriesId[] = ['milk_litres', 'milking', 'total_herd', 'calvings', 'dry_offs'];

export function OutcomeBar() {
  const run = useRun();
  const { grain, horizon } = usePfoi();
  const { origins, origin, setOrigin, loading } = useRunPicker();
  const at = origins.indexOf(origin);
  const realised = hasRealised(run);
  const kind = realised
    ? run.origin_date >= TEST_BLOCK_START ? 'test' : 'development'
    : 'published';
  const label = { test: 'Test-period comparison', development: 'Development comparison', published: 'Published outlook' }[kind];
  const series = SCORED.filter((s) => isForecast(run, grain, s));
  const scores = realised
    ? series.map((s) => outcomeScore(run, grain, horizon, s)).filter((x): x is OutcomeScore => !!x)
    : [];
  const last = targetPeriod(run, grain, horizon);

  return (
    <section className={`pfie-asof kind-${kind}`} aria-label="Forecast date">
      <div className="pfie-asof-head">
        <span className="pfie-field">Forecast as of</span>
        <span className="pfie-asof-nav">
          <button className="pfie-btn ghost" disabled={at <= 0} onClick={() => setOrigin(origins[at - 1])} aria-label="Earlier forecast date">‹</button>
          <select value={origin} onChange={(e) => setOrigin(e.target.value)} aria-label="Forecast date">
            {origins.map((o) => <option key={o} value={o}>{longDate(o)}</option>)}
          </select>
          <button className="pfie-btn ghost" disabled={at >= origins.length - 1} onClick={() => setOrigin(origins[at + 1])} aria-label="Later forecast date">›</button>
          {at < origins.length - 1 && (
            <button className="pfie-btn primary" onClick={() => setOrigin(origins[at + 1])}>
              Next date ▶
            </button>
          )}
        </span>
        <span className={`pfie-asof-badge kind-${kind}`}>{run.source === 'demo' ? `Demo · ${label === 'Published outlook' ? 'Outlook' : label}` : label}</span>
        {loading && <span className="pfie-asof-note">Loading…</span>}
        <span className="pfie-asof-note">
          {kind === 'published'
            ? 'No recorded outcomes are supplied for these forecasts. This does not indicate that the forecast is current.'
            : <>Model {run.model_version} used only data before {longDate(run.origin_date)}. What was recorded afterwards
                {run.realised_through ? <> (to {longDate(run.realised_through)})</> : null} is drawn on top; the model never saw it.</>}
        </span>
      </div>

      {realised && (
        <div className="pfie-asof-scores">
          <span className="pfie-asof-scope">
            {run.source === 'demo' ? 'Synthetic comparison' : `${run.model_version} forecast vs recorded`}, {horizon} {horizon === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many} ahead
            (to {periodLabel(last, grain)})
          </span>
          {scores.map((s) => <ScoreChip key={s.series} s={s} grain={grain} />)}
        </div>
      )}
      {realised && <p className="pfie-chart-note">
        Forecast error is calculated only where recorded outcomes are scoreable. Missing, incomplete or excluded
        records are recording limitations; this comparison alone does not explain a discrepancy's cause.
      </p>}
    </section>
  );
}

function ScoreChip({ s, grain }: { s: OutcomeScore; grain: Grain }) {
  const meta = SERIES_META[s.series];
  const unit = s.series === 'milk_litres' ? 'L/day' : meta.unit === 'head' ? 'head' : `per ${grain}`;
  const num = (v: number) => (Math.abs(v) >= 100 ? fmtInt(v) : fmt1(v));
  if (!s.scored || s.mae === null || s.bias === null) {
    return (
      <span className="pfie-score empty" title="Every period here falls in a data gap or an incomplete record">
        <i style={{ background: meta.color }} /><b>{meta.label}</b> no scoreable outcome ({s.periods} periods missing or excluded)
      </span>
    );
  }
  const bias = Math.abs(s.bias) < 0.05 ? 0 : s.bias;
  const direction = Math.abs(s.bias) < 0.05 * (s.mae || 1) ? 'about right on average' : s.bias > 0 ? 'forecast too low' : 'forecast too high';
  return (
    <span
      className="pfie-score"
      title={`Mean absolute error ${num(s.mae)} ${unit} over ${s.scored} of ${s.periods} periods; average outcome − forecast ${bias >= 0 ? '+' : '−'}${num(Math.abs(bias))} ${unit}; ${s.inside} of ${s.scored} outcomes inside the 5–95% range.`}
    >
      <i style={{ background: meta.color }} />
      <b>{meta.label}</b>
      <span>off by <b>{num(s.mae)}</b> {unit}{s.maeShare !== null ? ` (${Math.round(s.maeShare * 100)}%)` : ''}</span>
      <span className="muted">{direction}</span>
      <span className="muted">{s.inside}/{s.scored} in range{s.scored < s.periods ? ` · ${s.periods - s.scored} not scored` : ''}</span>
    </span>
  );
}
