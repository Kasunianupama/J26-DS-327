/** Local aggregate briefing; real farm data never goes to an external AI service. */
import { useState } from 'react';
import { api } from '../../services/api';
import './PublishedBrief.css';

type MilkPeriod = {
  current_litres: number | null; previous_litres: number | null;
  current_observed_days: number; previous_observed_days: number; change_pct: number | null;
};
type Brief = {
  source: string; demo: boolean; core_version: string; observed_date: string;
  latest_period: { start: string; end: string }; previous_period: { start: string; end: string };
  herd: { total_animals: number | null; milking: number | null; dry: number | null;
    pregnant_nonmilking: number | null; unknown_state: number | null };
  milk: { delpro: MilkPeriod; shipments: MilkPeriod };
  historical_weather: { observed_days: number; complete_days: number;
    mean_daily_thi: number | null; max_hourly_thi: number | null };
  warnings: string[]; interpretation: string; teammate_models: string;
};

function number(value: number | null, digits = 0) {
  return value == null ? 'Unavailable' : new Intl.NumberFormat('en', {
    maximumFractionDigits: digits,
  }).format(value);
}

export function PublishedBrief() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  async function load() {
    setLoading(true); setError(''); setBrief(null);
    try {
      const { data } = await api.get<Brief>('/agent/briefing');
      if (data.demo !== false || data.source !== 'published_core_aggregates') throw new Error();
      setBrief(data);
    } catch {
      setError('Published data unavailable. Check the backend and your local C3 configuration. Demo data has not been substituted.');
    } finally { setLoading(false); }
  }
  return <section className="published-brief" aria-labelledby="published-title">
    <header><p className="published-label">PUBLISHED FARM RECORDS · HISTORICAL</p>
      <h1 id="published-title">Farm X historical briefing</h1>
      <p>Recorded herd, milk and weather summaries. This view uses English and does not provide diagnoses or forecasts.</p>
      <button onClick={() => void load()} disabled={loading}>{loading ? 'Loading…' : brief ? 'Refresh briefing' : 'Load published briefing'}</button>
    </header>
    <div aria-live="polite">{loading && <p>Loading local aggregates…</p>}{error && <p className="published-error" role="alert">{error}</p>}</div>
    {brief && <>
      <p className="published-provenance">Records through <strong>{brief.observed_date}</strong> · Source: <code>{brief.core_version}</code></p>
      <aside className="published-warnings" aria-label="Data limitations"><h2>Data limitations</h2>
        <ul>{brief.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
      </aside>
      <section><h2>Reconstructed herd · {brief.observed_date}</h2>
        <dl className="published-stats">
          <div><dt>Total animals</dt><dd>{number(brief.herd.total_animals)}</dd></div>
          <div><dt>Milking</dt><dd>{number(brief.herd.milking)}</dd></div>
          <div><dt>Dry</dt><dd>{number(brief.herd.dry)}</dd></div>
          <div><dt>Pregnant heifers and dry cows</dt><dd>{number(brief.herd.pregnant_nonmilking)}</dd></div>
          <div><dt>Unknown state</dt><dd>{number(brief.herd.unknown_state)}</dd></div>
        </dl><p>Pregnant milking cows are not included in the pregnancy count above.</p>
      </section>
      <section><h2>Historical milk comparison</h2>
        <p>Latest: {brief.latest_period.start} to {brief.latest_period.end}. Previous: {brief.previous_period.start} to {brief.previous_period.end}.</p>
        <div className="published-table-scroll"><table><caption>Sources remain separate; totals can cover fewer than seven days.</caption>
          <thead><tr><th scope="col">Source</th><th scope="col">Latest litres</th><th scope="col">Latest days</th><th scope="col">Previous litres</th><th scope="col">Previous days</th><th scope="col">Change</th></tr></thead>
          <tbody>{([['DelPro', brief.milk.delpro], ['Shipments', brief.milk.shipments]] as const).map(([name, milk]) => <tr key={name}>
            <th scope="row">{name}</th><td>{number(milk.current_litres, 1)}</td><td>{milk.current_observed_days}/7</td>
            <td>{number(milk.previous_litres, 1)}</td><td>{milk.previous_observed_days}/7</td>
            <td>{milk.change_pct == null ? 'Unavailable' : `${number(milk.change_pct, 1)}%`}</td>
          </tr>)}</tbody>
        </table></div>
      </section>
      <section><h2>Historical weather · latest seven-day period</h2>
        <p>{brief.historical_weather.observed_days}/7 observed days; {brief.historical_weather.complete_days}/7 complete days.</p>
        <dl className="published-stats"><div><dt>Mean daily THI</dt><dd>{number(brief.historical_weather.mean_daily_thi, 1)}</dd></div>
          <div><dt>Maximum hourly THI</dt><dd>{number(brief.historical_weather.max_hourly_thi, 1)}</dd></div></dl>
        <p>Reanalysis estimates; not a weather forecast.</p>
      </section>
      <section><h2>Teammate predictions</h2><p>{brief.teammate_models}</p>
        <p>C1 model selection is awaiting confirmation. C2 and C4 outputs are not connected.</p>
      </section><p>{brief.interpretation}</p>
    </>}
  </section>;
}
