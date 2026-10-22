import { useEffect, useMemo, useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Assessment, DomainName, loadLegacyV1, loadLegacyV2, loadPublishedV3Assessments, publishedV3Mode, loadPredictions } from './member4Api';
import { combinedInsight, dailyChartRows, domainInsight, domainSummary, historyForAssessment, indicatorLabel, preferredAssessmentVersion, formatChartScore, riskCategoryLabel } from './dashboardInsights.mjs';
import { compareV3, previewV3 } from './v3Preview.mjs';

type Resource<T> = { loading: boolean; data: T[]; error: string };
function useResource<T>(loader: (signal: AbortSignal) => Promise<T[]>, refresh: number): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ loading: true, data: [], error: '' });
  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true, data: [], error: '' });
    loader(controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ loading: false, data, error: '' });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ loading: false, data: [],
        error: error instanceof Error && !('isAxiosError' in error) ? error.message : 'Authorized API unavailable. No replacement values are displayed.' });
    });
    return () => controller.abort();
  }, [loader, refresh]);
  return state;
}
const label = (value: string) => value.replace(/_/g, ' ');
const number = (value: number | null | undefined) => value == null ? 'Unavailable' : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
const domains: DomainName[] = ['climate', 'biological', 'operational'];

type RiskKind = DomainName | 'combined';
function RiskIcon({ kind }: { kind: RiskKind | 'trend' | 'refresh' }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === 'combined' && <><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z" /><path d="m8 12 3 3 5-6" /></>}
    {kind === 'climate' && <><path d="M14 4a3 3 0 0 0-6 0v10a5 5 0 1 0 6 0Z" /><path d="M11 8v10m7-12h3m-3 4h2" /><circle cx="11" cy="18" r="1" /></>}
    {kind === 'biological' && <><path d="M20 5c-3-3-6-1-8 1-2-2-5-4-8-1-4 4 1 9 8 15 7-6 12-11 8-15Z" /><path d="M5 11h4l2-3 2 6 2-3h4" /></>}
    {kind === 'operational' && <><path d="m10 3-1 3-3 1-3 3 2 2-1 4 3 2 3-1 2 4 3-2 1-3 4-1 1-4-3-2-1-4-4-1Z" /><circle cx="12" cy="12" r="3" /></>}
    {kind === 'trend' && <><path d="M4 4v16h17M7 15l4-5 4 3 5-7" /><path d="M16 6h4v4" /></>}
    {kind === 'refresh' && <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1" /></>}
  </svg>;
}
function RiskCard({ kind, value, category, explanation, loading, preview = false }: {
  kind: RiskKind; value: number | null | undefined; category?: string; explanation: string; loading: boolean; preview?: boolean;
}) {
  const available = value != null;
  // Color follows the stored combined category only; domain hues identify domains,
  // not invented clinical bands. Gauge length is the published score, not confidence.
  const band = kind === 'combined' && category ? category : 'neutral';
  return <article className={`m4-score m4-${kind} m4-band-${band}`} aria-busy={loading}>
    <div className="m4-card-heading"><span className="m4-icon-tile"><RiskIcon kind={kind} /></span>
      <h2>{kind === 'combined' ? 'Farm Risk Score' : `${kind[0].toUpperCase()}${kind.slice(1)} Risk`}</h2></div>
    {preview && <span className="m4-preview-card-label">Experimental Preview — Not Published</span>}
    <div className="m4-score-visual"><div className="m4-score-number">
      <strong className={available ? '' : 'm4-score-empty'}>{loading ? 'Loading' : available ? number(value) : 'Unavailable'}</strong>
      <span>{available ? '/100' : 'No data available'}</span></div>
      <svg className="m4-ring" viewBox="0 0 72 72" aria-hidden="true"><circle className="m4-ring-track" cx="36" cy="36" r="29" />
        {available && <circle className="m4-ring-value" cx="36" cy="36" r="29" pathLength="100" strokeDasharray={`${value} 100`} />}
        <text x="36" y="41" textAnchor="middle">{available ? '/100' : '—'}</text></svg></div>
    {(kind === 'combined' || !available) && <span className={`m4-risk-badge ${!available ? 'm4-risk-badge-muted' : ''}`}>
      <i aria-hidden="true" />{available ? riskCategoryLabel(category) : 'Awaiting data'}</span>}
    <p className="m4-card-explanation">{explanation}</p>
  </article>;
}

function State({ resource }: { resource: Resource<unknown> }) {
  return <div className={`m4-state ${resource.loading ? 'm4-is-loading' : ''}`} role="status">
    <span className="m4-state-mark" aria-hidden="true">{resource.loading ? '◌' : 'i'}</span>
    <div><strong>{resource.loading ? 'Loading your overview' : 'No data available for display'}</strong>
      <p>{resource.loading ? 'Getting the latest available assessments…' : 'Member 4 outputs are not available right now.'}</p>
      {resource.error && <details><summary>Connection details</summary><p>{resource.error}</p></details>}</div></div>;
}
function RiskChart({ rows, detailed, twoFactor }: { rows: Assessment[]; detailed: boolean; twoFactor: boolean }) {
  // Keep one explicit selected scoring run, and retain nulls without interpolation.
  const data = dailyChartRows(rows);
  if (!data.length) return <div className="m4-chart-empty" role="status"><span className="m4-icon-tile"><RiskIcon kind="trend" /></span>
    <div><strong>Your historical trend will appear here</strong><p>No assessment history available for display.</p></div></div>;
  return <div className="m4-chart" role="img" aria-label="Historical farm risk scores, zero to one hundred">
    <ResponsiveContainer width="100%" height={280}><LineChart data={data}>
      <CartesianGrid strokeDasharray="3 3" vertical={false} />
      <XAxis dataKey="date" minTickGap={65} tick={{ fontSize: 11 }} />
      <YAxis domain={[0, 100]} width={35} tick={{ fontSize: 11 }} />
      <Tooltip formatter={value => formatChartScore(value)} /><Legend />
      <Line type="linear" dataKey="Combined" stroke="#a95a2c" strokeWidth={3} dot={false} connectNulls={false} />
      {detailed && <Line type="linear" dataKey="Climate" stroke="#bd8a37" dot={false} connectNulls={false} />}
      {detailed && !twoFactor && <Line type="linear" dataKey="Biological" stroke="#668264" dot={false} connectNulls={false} />}
      {detailed && <Line type="linear" dataKey="Operational" stroke="#b87150" dot={false} connectNulls={false} />}
    </LineChart></ResponsiveContainer>
    <details><summary>Accessible chart data</summary><div className="m4-table-wrap"><table>
      <thead><tr><th>Date</th><th>Combined</th><th>Climate</th>{!twoFactor && <th>Biological</th>}<th>Operational</th></tr></thead>
      <tbody>{data.map(r => <tr key={r.date}><td>{r.date}</td>{(twoFactor ? [r.Combined, r.Climate, r.Operational] : [r.Combined, r.Climate, r.Biological, r.Operational]).map((v, i) => <td key={i}>{formatChartScore(v)}</td>)}</tr>)}</tbody>
    </table></div></details>
  </div>;
}
export function FarmLevelDashboard() {
  const [detailed, setDetailed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const v1 = useResource(loadLegacyV1, refresh);
  const v2 = useResource(loadLegacyV2, refresh);
  const published = useResource(loadPublishedV3Assessments, refresh);
  const [chosenVersion, setChosenVersion] = useState<'v1' | 'v2' | 'v3' | null>(null);
  const activeVersion = publishedV3Mode || chosenVersion === 'v3' ? 'v3' : preferredAssessmentVersion(chosenVersion, v2.error ? 0 : v2.data.length);
  const isPreview = activeVersion === 'v3' && !publishedV3Mode;
  const visibleDomains: DomainName[] = activeVersion === 'v3' ? ['climate', 'operational'] : domains;
  const previewRows = useMemo(() => v2.data.map(previewV3), [v2.data]);
  const comparison = useMemo(() => compareV3(v2.data), [v2.data]);
  const assessments = publishedV3Mode ? published : activeVersion === 'v3' ? { ...v2, data: previewRows } : activeVersion === 'v2' ? v2 : v1;
  const predictions = useResource(loadPredictions, refresh);
  const [selectedId, setSelectedId] = useState('');
  const [predictionId, setPredictionId] = useState('');
  const [range, setRange] = useState('30');
  const selected = assessments.data.find(r => r.output_id === selectedId) ?? assessments.data[assessments.data.length - 1];
  const selectedPreview = isPreview ? previewRows.find(r => r.output_id === selected?.output_id) : undefined;
  const previewIndicators = selected?.domains.find(d => d.domain === 'operational')?.indicators;
  const previewOperationalText = !selected || selectedPreview?.preview.reason ? selectedPreview?.preview.reason ?? 'Assessment inputs are unavailable.'
    : `Average of the blood alarm indicator (${number(previewIndicators?.find(i => i.feature === 'n_blood_alarms')?.score)}/100) and conductivity alarm indicator (${number(previewIndicators?.find(i => i.feature === 'n_conductivity_alarms')?.score)}/100).`;
  const prediction = predictions.data.find(r => r.prediction_id === predictionId) ?? predictions.data[predictions.data.length - 1];
  const { rows: uniqueHistory, duplicateDates } = historyForAssessment(assessments.data, selected, range);
  return <main className="m4-dashboard">
    <header className="m4-header"><div><p className="m4-eyebrow">RISK MANAGEMENT</p>
      <h1>Farm Risk Intelligence</h1><p>Farm X · recorded farm risk overview</p></div>
      <button className="m4-button" onClick={() => setRefresh(v => v + 1)}><RiskIcon kind="refresh" /> Refresh</button></header>
    <div className="m4-toolbar">
      <div className="m4-toggle" role="group" aria-label="Dashboard view">
        <button aria-pressed={!detailed} onClick={() => setDetailed(false)}>Simple view</button>
        <button aria-pressed={detailed} onClick={() => setDetailed(true)}>Detailed view</button>
      </div>
      {!publishedV3Mode && <label>Scoring version<select value={activeVersion} onChange={e => { setChosenVersion(e.target.value as 'v1' | 'v2' | 'v3'); setSelectedId(''); }}>
        <option value="v1">V1 · Original</option><option value="v2">V2 · Operational calibration</option>
        <option value="v3">V3 Preview — Climate and Operational Risk Model</option>
      </select></label>}
      <label>Assessment date<select value={selected?.output_id ?? ''} disabled={!assessments.data.length}
        onChange={e => setSelectedId(e.target.value)}>
        {!assessments.data.length && <option value="">No assessment available</option>}
        {assessments.data.map(r => <option key={r.output_id} value={r.output_id}>{r.assessment_date}</option>)}
      </select></label>
    </div>
    {isPreview && <aside className="m4-preview-notice"><strong>Experimental Preview — Not Published</strong>
      <span>Climate and Operational Risk Model · Combined Risk = (Climate + Operational) / 2. Operational Risk averages the two calibrated alarm indicator scores. Stored assessments are unchanged.</span></aside>}
    {(assessments.loading || assessments.error || !assessments.data.length) && <State resource={assessments} />}
    <section className="m4-main-score" aria-label="Farm risk score">
      <RiskCard kind="combined" value={selected?.combined_score} category={selected?.risk_category}
        explanation={combinedInsight(selected)} loading={assessments.loading} preview={isPreview} />
    </section>
    <section className="m4-factor-section" aria-label="Risk factors"><h2 className="m4-section-heading">Risk Factors</h2><div className={`m4-score-grid${activeVersion === 'v3' ? ' m4-two-factor-grid' : ''}`}>
      {visibleDomains.map(kind => { const domain = selected?.domains.find(d => d.domain === kind); return <RiskCard key={kind}
        kind={kind} value={domain?.score} explanation={activeVersion === 'v3' && kind === 'operational' ? previewOperationalText : domainSummary(selected, kind)} loading={assessments.loading} preview={isPreview} />; })}
    </div></section>
    <section className="m4-panel m4-trend-panel"><div className="m4-section-title"><div><h2><span className="m4-inline-icon"><RiskIcon kind="trend" /></span>Historical Risk Trend</h2>
      <p>{isPreview ? 'Experimental Preview — Not Published · V3 values derived from V2 inputs.' : publishedV3Mode ? 'Climate and Operational Risk Model · published historical assessments.' : 'Recorded farm assessments over time.'} Gaps indicate unavailable scores.</p></div>
      <label>History window<select value={range} onChange={e => setRange(e.target.value)}>
        <option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option><option value="all">All available history</option>
      </select></label></div>
      {duplicateDates > 0 && <p className="m4-calibration">Dates with multiple publications are withheld from this chart pending run selection.</p>}
      <RiskChart rows={uniqueHistory} detailed={detailed} twoFactor={activeVersion === 'v3'} />
    </section>
    {isPreview && <section className="m4-panel m4-preview-comparison"><div className="m4-section-title"><h2>Stored V2 vs V3 Preview</h2><span className="m4-chip">Experimental Preview — Not Published</span></div>
      <p>Operational Risk across all available V2 dates, comparing only days eligible for both methods.</p>
      <p>V2 Combined Risk uses its stored three-domain weighted model. V3 Combined Risk uses Climate and Operational Risk only, equally weighted. Combined scores reflect different methodologies.</p>
      <div className="m4-contributions"><div><span>Stored V2 · MAX</span><strong>{number(comparison.v2.mean)} average</strong><small>{comparison.v2.at100} of {comparison.eligibleDays} paired days at 100</small></div>
        <div><span>V3 Preview · Average</span><strong>{number(comparison.v3.mean)} average</strong><small>{comparison.v3.at100} of {comparison.eligibleDays} paired days at 100</small></div></div>
      <p>{comparison.unavailableDays} days unavailable for paired comparison; {comparison.duplicateDates} duplicate dates withheld. Lower saturation does not establish better scientific validity.</p>
      {selectedPreview && <p>Selected date: stored V2 Operational {number(selectedPreview.preview.stored_operational_score)} → V3 Preview {number(selectedPreview.domains.find(d => d.domain === 'operational')?.score)}; stored V2 Combined {number(selectedPreview.preview.stored_combined_score)} → V3 Preview {number(selectedPreview.combined_score)}.</p>}
      {selectedPreview?.preview.reason && <p className="m4-calibration">{selectedPreview.preview.reason}</p>}
    </section>}
    {!detailed && <section className="m4-panel m4-contributor-panel"><div className="m4-section-title"><h2>Recorded Risk Contributors</h2><span className="m4-chip">Assessment overview</span></div>
      <div className={`m4-contributor-grid${activeVersion === 'v3' ? ' m4-two-factor-grid' : ''}`}>{visibleDomains.map(kind => {
        const insight = domainInsight(selected, kind);
        return <div className={`m4-contributor m4-${kind}`} key={kind}><span className="m4-icon-tile"><RiskIcon kind={kind} /></span>
          <div><h3>{insight.title}</h3><strong className="m4-recorded-value">{insight.value}</strong>
            <p>{domainSummary(selected, kind)}</p></div></div>;
      })}</div></section>}
    {detailed && <section className="m4-panel"><h2>What contributes to this score?</h2>
      <p>Recorded indicators and stored research rules. Missing values remain unavailable.</p>
      {!selected ? <p className="m4-state">Detailed scoring evidence unavailable.</p> : <>
        <div className="m4-contributions">{visibleDomains.map(d => <div key={d}><span className="m4-capitalize">{d}</span>
          <strong>{number(selected.contributions[d])} points</strong><small>Weight {activeVersion === 'v3' ? '50' : number(selected.scoring_config[`${d}_weight`] * 100)}%</small></div>)}</div>
        {selected.domains.map(domain => <details key={domain.domain} className="m4-detail">
          <summary className="m4-capitalize">{domain.domain} indicators · {label(domain.status)}</summary>
          <p>{domainInsight(selected, domain.domain).text}</p>
          <p>{isPreview && domain.domain === 'operational' ? 'Preview calculation' : 'Stored calculation'}: {domain.explanation}</p>
          <div className="m4-table-wrap"><table><thead><tr><th>Indicator</th><th>Recorded / derived value</th><th>Indicator score</th><th>Research thresholds</th><th>Explanation</th></tr></thead>
          <tbody>{domain.indicators.map(indicator => { const rule = selected.scoring_config[`${domain.domain}_rules`].find(r => r.feature === indicator.feature);
            return <tr key={indicator.feature}><th>{indicatorLabel(indicator.feature)}<br /><small>{indicator.feature}</small></th><td>{number(indicator.value)}</td><td>{number(indicator.score)}</td>
              <td>{rule ? <>{number(rule.lower)} to {number(rule.upper)}<br />{label(rule.direction)}<br />{rule.rationale}</> : 'Unavailable'}</td><td>{indicator.explanation}</td></tr>; })}</tbody></table></div>
        </details>)}
      </>}
    </section>}
    {detailed && <section className="m4-panel m4-experiment"><p className="m4-eyebrow">EXPLORATORY 2022 PERIOD · NOT LIVE VALIDATED</p>
      <h2>Experimental Random Forest</h2><p>This historical experiment is separate from 2025–2026 risk assessments. Its model score is not calibrated risk or model confidence.</p>
      {(predictions.loading || predictions.error || !predictions.data.length) ? <State resource={predictions} /> : <>
        <label>Experimental prediction date<select value={prediction?.prediction_id ?? ''} onChange={e => setPredictionId(e.target.value)}>
          {predictions.data.map(p => <option value={p.prediction_id} key={p.prediction_id}>{p.assessment_date}</option>)}
        </select></label>
        {prediction && <div className="m4-experiment-values"><div><span>Experimental decline probability</span><strong>{(prediction.predicted_decline_probability * 100).toFixed(1)}%</strong></div>
          <div><span>Retrospective outcome</span><strong>{prediction.actual_outcome === null ? 'Unavailable' : prediction.actual_outcome ? 'Decline recorded' : 'No target decline recorded'}</strong></div>
          <div><span>Saved decision threshold</span><strong>{prediction.saved_threshold === null ? 'Unavailable — no classification' : number(prediction.saved_threshold)}</strong></div>
          <p>Artifact {prediction.artifact_version} · {label(prediction.experiment_partition)} · {label(prediction.classification_status)}</p>
        </div>}
      </>}
      <p className="m4-calibration">Previously evaluated results had excessive false alarms. A historical classifier result is not a recommended warning or an action alert.</p>
    </section>}
    {detailed && <details className="m4-panel"><summary>Model Information</summary>
      <p>Risk thresholds require further validation.</p>
      <p>Research only · live_warning_allowed=false. These historical results are not validated live warnings.</p>
      <p>Model: {activeVersion === 'v3' ? publishedV3Mode ? 'Climate and Operational Risk Model' : 'V3 Climate and Operational Risk Model — Experimental Preview — Not Published' : activeVersion.toUpperCase()}.</p>
      <p>Recording completeness, delayed entry and corrections can limit interpretation. Alarm counts do not establish equipment failure. Missing required scores remain unavailable.</p>
      {activeVersion !== 'v3' && <p>Biological Risk retains its original stored score and unverified health-record completeness. Zero does not establish absence of health problems.</p>}
      {selected && <><p>{isPreview ? 'Source V2 configuration version' : 'Configuration version'}: {selected.scoring_config.version}.</p>
        {activeVersion === 'v3'
          ? <p>Operational Risk = (Blood Alarm Indicator Score + Conductivity Alarm Indicator Score) / 2, using the stored V2 calibrated indicator rules. Climate Risk retains its stored value. Combined Risk = (Climate Risk + Operational Risk) / 2 using unrounded values; each domain contributes 50%. Missing either domain withholds Combined Risk. Source V2 weights are not used in V3.</p>
          : <p>Method: maximum eligible indicator score per domain, then fixed weighted sum. Weights: Climate {number(selected.scoring_config.climate_weight * 100)}%, Biological {number(selected.scoring_config.biological_weight * 100)}%, Operational {number(selected.scoring_config.operational_weight * 100)}%. {selected.scoring_config.rationale}</p>}
        <p>{isPreview ? 'Two-domain preview coverage' : 'Completeness'}: {selected.data_completeness} · availability: {selected.provenance.availability}.</p>
        <p>Core version: {selected.provenance.core_version ?? 'Unknown'} · basis: {isPreview ? 'Browser-only experimental view derived from stored V2 indicators' : selected.score_basis ? label(selected.score_basis) : 'Quality-gated research assessment'}.</p>
        <p>Category boundaries: medium starts at {selected.scoring_config.medium_starts_at}, high starts at {selected.scoring_config.high_starts_at}. Existing source boundaries are applied to the displayed combined score.</p>
        {activeVersion !== 'v3' && <p>{selected.assumptions}</p>}
        <ul>{selected.explanations.map((e, i) => <li key={i}>{e}</li>)}</ul></>}
      <p>The 2022 Random Forest experiment is separate and not live validated. {prediction ? `Artifact version ${prediction.artifact_version}; ${label(prediction.experiment_partition)}.` : 'No experimental artifact information loaded.'} No historical score or experimental prediction is a future alert.</p>
    </details>}
  </main>;
}
