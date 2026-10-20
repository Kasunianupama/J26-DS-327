/**
 * Component 1 (PFOI): Model evaluation.
 *
 * Which model additions help (evidence ladder, F7), what happens when milk records stop
 * (simulated outages, F3) and which signals the model already uses (F8). Every result
 * carries the status the model run gave it; development and post-test numbers stay apart.
 */

import { useRun } from '../source';
import { Note } from '../ui';
import { EvidenceLadder, OutageRecovery, SensorRegistry } from '../panels/Pp1Panels';

export function ModelEvaluation() {
  const run = useRun();
  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <Note tone="info" title="How to read model evaluation.">
        Design choices were made on 2017–2023 (development). 2024–26 has already been looked at, so results there
        are labelled post-test development, not an untouched test. Each result carries its status badge and its n.
      </Note>
      {run.source === 'demo' && (
        <Note tone="concern" title="These are demo numbers, not results.">
          Every value below is synthetic and shows only how the evaluation will be reported.
        </Note>
      )}
      <EvidenceLadder />
      <OutageRecovery />
      <SensorRegistry />
    </div>
  );
}
