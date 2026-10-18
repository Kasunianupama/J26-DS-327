/**
 * Component 1 (PFOI): which run the page is showing.
 *
 * Every chart can be traced to a model version, a core version and an origin
 * date. A demo run is labelled as such in the header, not in a footnote.
 */

import { longDate } from '../../data/pfoi';
import { useRun } from './source';

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
          Run <b>{run.model_version}</b> · core <b>{run.core_version}</b>
        </span>
      </div>
    </>
  );
}
