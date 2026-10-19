import { useRun } from '../source';
import { Card, Note } from '../ui';

export function ModelEvaluation() {
  const run = useRun();
  return (
    <div className="pfie-stack" style={{ gap: 20 }}>
      <Card title="Model evaluation" sub="Development evaluation · 2019–2023 · Candidate configurations">
        <p>
          This evaluation compares candidate configurations on historical forecasts from 2019–2023.
          It does not establish the accuracy of the displayed outlook or explain every discrepancy in a 2026 forecast.
        </p>
      </Card>
      <Note tone="info" title="Candidate results are not supplied to this prototype.">
        No candidate accuracy figures or selected configuration are available in the published run.
        The Forecast Confidence view reports the displayed {run.source === 'demo' ? 'synthetic demo' : run.model_version} run's
        backtest figures separately.
      </Note>
      <Card title="Before publishing a replacement outlook" sub="A candidate evaluation does not update the displayed forecast">
        <p>
          Select and freeze a configuration, generate an outlook with that configuration, and publish it with its
          model version and data cutoff. Report evaluation dates, horizons, scoreable period counts and record-quality
          exclusions alongside its metrics. Identify any previously inspected test periods as post-hoc evaluation.
        </p>
      </Card>
    </div>
  );
}
