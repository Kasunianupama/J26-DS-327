/**
 * Component 1 (PFOI): which run the page is showing.
 *
 * Every chart can be traced to a model version, a core version and an origin
 * date. A demo run is labelled as such in the header, not in a footnote.
 */

import { longDate } from '../../data/pfoi';
import { useModelOrigin, useRun } from './source';

export function RunStatus() {
  const run = useRun();
  const demo = run.source === 'demo';
  return (
    <>
      <span
        className={`pfie-live${demo ? ' demo' : ''}`}
        title={demo
          ? 'Synthetic demo data with the shape of the planned c1_output tables. Not Farm X data and not a model result.'
          : 'Outputs written by the PFOI model run'}
      >
        <i aria-hidden />{demo ? 'Demo data' : 'Model output'}
      </span>
      <div className="pfie-stamp">
        <span title="First day the forecast covers. No fact dated on or after it is used.">
          Origin <b>{longDate(run.origin_date)}</b>
        </span>
        <span title={`Model ${run.model_version} · core ${run.core_version}`}>
          Run <b>{run.model_version}</b>{run.run_kind ? <> ({run.run_kind})</> : null} · core <b>{run.core_version}</b>
        </span>
      </div>
      <ModelNotice />
    </>
  );
}

/** Says which model's forecast is on screen; warns when an older model's forecast is shown because
 *  the current model has none for this date. */
export function ModelNotice() {
  const run = useRun();
  const { current, isCurrent, currentFrom, currentTo } = useModelOrigin();
  if (run.source === 'demo') return null;
  const kind = run.run_kind ? ` · ${run.run_kind} forecast` : '';
  if (isCurrent) {
    return <p className="pfie-model-notice" style={{ margin: '4px 0', fontSize: 12, color: '#4a6a5c' }}>
      Forecast by <b>{run.model_version}</b>{kind}.</p>;
  }
  return (
    <p className="pfie-model-notice old" role="note" style={{ margin: '6px 0', padding: '6px 10px', fontSize: 12.5,
      background: '#fbf3e4', border: '1px solid #e6cf9f', borderRadius: 8, color: '#5c4310' }}>
      ◆ This date shows an <b>older model</b>, <b>{run.model_version}</b>. The current model, <b>{current}</b>,
      has no forecast for {longDate(run.origin_date)}{currentFrom && currentTo
        ? <> — its forecasts cover {longDate(currentFrom)} to {longDate(currentTo)}</> : null}.
    </p>
  );
}

/** Metadata belongs to the displayed run, including while another date loads. */
export function ForecastInfo() {
  const run = useRun();
  const generated = new Date(run.generated_at);
  const generatedLabel = Number.isNaN(generated.getTime()) ? 'Not supplied' : generated.toLocaleString('en-GB', {
    timeZone: 'Asia/Colombo', dateStyle: 'medium', timeStyle: 'short',
  }) + ' (Sri Lanka time)';
  return (
    <section className="pfie-forecast-info" aria-label="Displayed forecast information">
      <b>{run.source === 'demo' ? 'Synthetic demo' : run.model_version === 'pfoi-1.0.0' ? 'Published baseline' : 'Published model output'}</b>
      <dl>
        <div><dt>Model</dt><dd>{run.model_version}</dd></div>
        <div><dt>Forecast as of</dt><dd>{longDate(run.origin_date)}</dd></div>
        <div><dt>Data through</dt><dd>{longDate(run.data_through)}</dd></div>
        <div><dt>Generated</dt><dd>{generatedLabel}</dd></div>
        <div><dt>Published</dt><dd>Not supplied</dd></div>
      </dl>
      <p>
        {run.source === 'demo' ? 'This synthetic preview is not evidence of forecast accuracy.' : <>This outlook uses {run.model_version}.</>}
        {' '}The candidate evaluation covers 2019–2023 and does not establish the accuracy of this outlook.
      </p>
    </section>
  );
}
