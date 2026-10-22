/** Local C4 question answering; no cloud model or browser speech service. */
import { useState } from 'react';
import { api } from '../../services/api';
import './LocalRiskChat.css';

type Reply = {
  status: string; answer: string; provider: string; cloud_processing: boolean; demo: boolean;
  warnings?: string[];
  evidence?: {
    assessment_date: string; generated_at: string | null; assessment_cutoff: string | null;
    contract_version: string; scoring_version: string; model_status: string;
    score_basis: string; source_core_version: null; research_only: boolean;
    live_warning_allowed: boolean; source: string;
    climate_score: number | null; biological_score: number | null;
    operational_score: number | null; combined_score: number | null;
  };
};
type Turn = { id: string; question: string; reference: string; reply?: Reply; error?: string };

export function LocalRiskChat() {
  const [query, setQuery] = useState('');
  const [reference, setReference] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  async function ask(question = query) {
    if (!question.trim() || loading) return;
    const turn: Turn = { id: crypto.randomUUID(), question, reference };
    setTurns(items => [...items, turn]); setQuery(''); setLoading(true);
    try {
      const { data } = await api.post<Reply>('/agent/local-query', {
        query: question, reference_date: reference || null,
      });
      if (data.cloud_processing !== false || data.provider !== 'local_template' || data.demo !== false) throw new Error();
      setTurns(items => items.map(item => item.id === turn.id ? { ...item, reply: data } : item));
    } catch {
      setTurns(items => items.map(item => item.id === turn.id ? { ...item,
        error: 'Local service unavailable. Check the backend and C3 database configuration. No cloud or demo fallback was used.' } : item));
    } finally { setLoading(false); }
  }
  return <section className="local-risk-chat" aria-labelledby="local-risk-title">
    <header><p className="local-risk-label">LOCAL DATA · ENGLISH · NO CLOUD MODEL</p>
      <h1 id="local-risk-title">Ask about C4 historical assessments</h1>
      <p>Answers use local records and factual templates. C4 assessments are experimental research outputs, not live alerts. Qwen is not used in this view yet.</p>
    </header>
    <label className="local-risk-date" htmlFor="risk-reference">Reference date
      <input id="risk-reference" type="date" value={reference} disabled={loading} onChange={event => setReference(event.target.value)} />
    </label>
    <div className="local-risk-examples">
      <button disabled={loading} onClick={() => void ask('Show C4 historical risk assessment.')}>Show historical assessment</button>
      <button disabled={loading} onClick={() => void ask('Can C4 give a live risk warning today?')}>Can this provide live warnings?</button>
    </div>
    <div className="local-risk-turns" aria-live="polite">{turns.map(turn => <article key={turn.id}>
      <p className="local-risk-question">{turn.question}{turn.reference && <small>Reference date: {turn.reference}</small>}</p>
      {!turn.reply && !turn.error && <p>Checking local evidence…</p>}
      {turn.error && <p role="alert" className="published-error">{turn.error}</p>}
      {turn.reply && <>
        <p className="local-risk-answer">{turn.reply.answer}</p>
        {turn.reply.evidence && <p className="local-risk-source">Historical C4 research · Assessment: {turn.reply.evidence.assessment_date} · Generated: {turn.reply.evidence.generated_at ?? 'Not supplied'}</p>}
        {turn.reply.evidence && <details><summary>Evidence and limitations</summary>
          <dl><dt>Source</dt><dd>{turn.reply.evidence.source}</dd>
            <dt>Contract / scoring version</dt><dd>{turn.reply.evidence.contract_version} / {turn.reply.evidence.scoring_version}</dd>
            <dt>Model status</dt><dd>{turn.reply.evidence.model_status}</dd>
            <dt>Score basis</dt><dd>{turn.reply.evidence.score_basis}</dd>
            <dt>Source core version</dt><dd>Not supplied; compatibility unverified</dd>
            <dt>Assessment cutoff</dt><dd>{turn.reply.evidence.assessment_cutoff ?? 'Not supplied'}</dd>
            <dt>Research only / live warning allowed</dt><dd>{String(turn.reply.evidence.research_only)} / {String(turn.reply.evidence.live_warning_allowed)}</dd>
          </dl>
          <p>Producer scores (scale and thresholds unconfirmed):</p>
          <ul>{(['climate_score', 'biological_score', 'operational_score', 'combined_score'] as const).map(name => <li key={name}>{name.replace(/_/g, ' ')}: {turn.reply?.evidence?.[name] == null ? 'Unavailable' : turn.reply.evidence[name]}</li>)}</ul>
          <ul>{turn.reply.warnings?.map(warning => <li key={warning}>{warning}</li>)}</ul>
        </details>}
      </>}
    </article>)}</div>
    <form className="local-risk-composer" onSubmit={event => { event.preventDefault(); void ask(); }}>
      <label htmlFor="local-risk-question">Your historical-assessment question</label>
      <div><input id="local-risk-question" value={query} maxLength={1500} onChange={event => setQuery(event.target.value)} placeholder="Show C4's historical assessment for YYYY-MM-DD" />
        <button type="submit" disabled={loading || !query.trim()}>{loading ? 'Checking…' : 'Ask locally'}</button></div>
    </form>
  </section>;
}
