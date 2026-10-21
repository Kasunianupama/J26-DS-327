import { useEffect, useState } from 'react';
import axios from 'axios';
import { api } from '../../services/api';
import './InterventionSimulator.css';

type Category = 'heat' | 'management';
type Feature = 'thi_mean' | 'milkings_per_day';
type ScenarioInput = { category: Category; feature: Feature; proposed_value: string; scenario_id: string };
type CowState = {
  animal_ref: string; observed_date: string | null; breed: string | null; age_days: number | null;
  lactation_no: number | null; days_in_milk: number | null; days_pregnant: number | null;
  milk_yield_l_day: number | null; milkings_per_day: number | null; dry_matter_intake: number | null;
  concentrate_intake: number | null; bcs: number | null; body_weight: number | null;
  rectal_temperature: number | null; thi_mean: number | null; n_calvings: number | null;
  recent_clinical_event_count: number | null; recent_treatment_count: number | null; data_limitations: string[];
};
type CowReference = { animal_ref: string; observed_date: string };
type ScenarioEstimate = {
  scenario_id: string; category: string; name: string; feature: string; scenario_status: string;
  baseline_value: number | null; proposed_value: number; unit: string;
  baseline_predicted_milk_yield_l_day: number | null; counterfactual_predicted_milk_yield_l_day: number | null;
  absolute_yield_change_l_day: number | null; percentage_yield_change: number | null;
  model_version: string | null; assumptions: string[]; data_limitations: string[]; warnings: string[];
};
type SimulationResponse = {
  contract_version: string; animal_ref: string; observed_date: string | null; observed_milk_yield_l_day: number | null;
  cow_state: CowState; prediction_horizon_days: number; baseline_status: string;
  baseline_predicted_milk_yield_l_day: number | null; model_version: string | null;
  scenarios: ScenarioEstimate[]; warnings: string[];
};

const featureFor: Record<Category, Feature> = {
  heat: 'thi_mean', management: 'milkings_per_day',
};
const featureName: Record<Feature, string> = {
  thi_mean: 'Temperature humidity index', milkings_per_day: 'Milkings per day',
};
const unitFor: Record<Feature, string> = {
  thi_mean: 'THI', milkings_per_day: 'milkings/day',
};
const emptyScenario = (n: number): ScenarioInput => ({ category: 'heat', feature: 'thi_mean', proposed_value: '', scenario_id: `whatif-${n}` });
function nextScenarioId(rows: ScenarioInput[]) {
  let index = rows.length + 1;
  while (rows.some((row) => row.scenario_id === `whatif-${index}`)) index += 1;
  return `whatif-${index}`;
}
const show = (value: number | string | null | undefined, suffix = '') => value == null ? 'Unavailable' : `${value}${suffix}`;
const showTwoDecimals = (value: number | null | undefined, suffix = '') => value == null ? 'Unavailable' : `${value.toFixed(2)}${suffix}`;

export default function InterventionSimulatorPage() {
  const [animalRef, setAnimalRef] = useState('');
  const [animalOptions, setAnimalOptions] = useState<CowReference[]>([]);
  const [state, setState] = useState<CowState | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioInput[]>([emptyScenario(1)]);
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.get<CowReference[]>('/interventions/cows')
      .then((response) => { if (active) setAnimalOptions(response.data); })
      .catch((cause) => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, []);

  async function loadState() {
    setBusy(true); setError(''); setResult(null);
    try {
      const response = await api.get<CowState>(`/interventions/cows/${encodeURIComponent(animalRef)}/state`);
      setState(response.data);
    } catch (cause) { setState(null); setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  function updateScenario(index: number, patch: Partial<ScenarioInput>) {
    setScenarios((current) => current.map((row, i) => {
      if (i !== index) return row;
      const next = { ...row, ...patch };
      if (patch.category) next.feature = featureFor[patch.category];
      return next;
    }));
  }

  async function simulate() {
    setBusy(true); setError(''); setResult(null);
    const requestBody = {
      animal_ref: animalRef,
      prediction_horizon_days: 1,
      scenarios: scenarios.map((row) => ({
        scenario_id: row.scenario_id,
        category: row.category,
        name: row.category === 'heat' ? 'Hypothetical THI exposure change' : 'Hypothetical milking frequency change',
        feature: row.feature,
        proposed_value: Number(row.proposed_value),
        unit: unitFor[row.feature],
        intervention_description: row.category === 'heat'
          ? 'Hypothetical THI exposure change; not a cooling intervention or verified causal effect.'
          : 'Hypothetical milking frequency change; operational feasibility is not validated, and no causal effect is asserted.',
      })),
    };
    try {
      const response = await api.post<SimulationResponse>('/interventions/simulate-counterfactual', requestBody);
      setResult(response.data);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  const hasValidInputs = scenarios.length > 0 && scenarios.length <= 8 && scenarios.every((s) => s.proposed_value.trim() !== '' && Number.isFinite(Number(s.proposed_value)));

  return (
    <main className="didt-live">
      <header className="didt-live__hero">
        <div><p className="didt-live__eyebrow">COMPONENT 1 · RESEARCH PROTOTYPE</p><h1>Counterfactual milk-yield simulator</h1>
          <p>Compares one-day-ahead predictions for an observed Farm X cow state and user-specified model-input changes.</p></div>
        <span className="didt-live__tag">Estimates are not causal effects</span>
      </header>

      <section className="didt-live__card">
        <h2>Load a cow’s current state</h2>
        <p>Enter an approved animal reference. No bundled demo cow records are shown as Farm X data.</p>
        <div className="didt-live__row"><label>Available animal<select value={animalRef} onChange={(e) => { setAnimalRef(e.target.value); setState(null); setResult(null); }}>
          <option value="">{animalOptions.length ? 'Select an approved animal reference' : 'Approved references unavailable'}</option>
          {animalOptions.map((animal) => <option key={animal.animal_ref} value={animal.animal_ref}>{animal.animal_ref} · latest record {animal.observed_date}</option>)}
        </select></label>
          <button type="button" onClick={loadState} disabled={busy || !animalRef.trim()}>{busy ? 'Loading…' : 'Load actual state'}</button></div>
        {state && <>
          <div className="didt-live__facts">
            {([['Observed date', state.observed_date], ['Breed', state.breed], ['Age', show(state.age_days, ' days')],
              ['Lactation number', state.lactation_no], ['Days in milk', state.days_in_milk], ['Observed milk yield', showTwoDecimals(state.milk_yield_l_day, ' L/day')],
              ['Milkings/day', state.milkings_per_day], ['Dry matter intake', state.dry_matter_intake], ['Concentrate intake', state.concentrate_intake],
              ['BCS', state.bcs], ['Body weight', state.body_weight], ['THI', showTwoDecimals(state.thi_mean)], ['Days pregnant', state.days_pregnant]] as [string, unknown][])
              .map(([label, value]) => <div key={label}><span>{label}</span><b>{value == null ? 'Unavailable' : String(value)}</b></div>)}
          </div>
          {!!state.data_limitations.length && <aside className="didt-live__notice"><b>Data limitations</b><ul>{state.data_limitations.map((item) => <li key={item}>{item}</li>)}</ul></aside>}
        </>}
      </section>

      {state && <section className="didt-live__card">
        <div className="didt-live__card-head"><div><h2>What-if scenarios</h2><p>Submit up to eight independent alternatives in one request.</p></div>
          <button className="didt-live__secondary" type="button" onClick={() => setScenarios((rows) => rows.length < 8 ? [...rows, { ...emptyScenario(0), scenario_id: nextScenarioId(rows) }] : rows)} disabled={scenarios.length >= 8}>Add scenario</button></div>
        {scenarios.map((scenario, index) => <div className="didt-live__scenario" key={scenario.scenario_id}>
          <label>Input category<select value={scenario.category} onChange={(e) => updateScenario(index, { category: e.target.value as Category })}>
            <option value="heat">THI exposure input</option><option value="management">Milking frequency input</option>
          </select></label>
          <label>Proposed {featureName[scenario.feature]}<input type="number" step="any" value={scenario.proposed_value} onChange={(e) => updateScenario(index, { proposed_value: e.target.value })} placeholder={`Current: ${show(state[scenario.feature as keyof CowState] as number | null)}`} /></label>
          <div className="didt-live__unit">Unit: {unitFor[scenario.feature]}</div>
          {scenarios.length > 1 && <button className="didt-live__remove" type="button" onClick={() => setScenarios((rows) => rows.filter((_, i) => i !== index))}>Remove</button>}
        </div>)}
        <p className="didt-live__small">Available scenarios: hypothetical THI exposure changes and milking frequency changes. Feed and concentrate interventions are unavailable because the required intervention data and semantics are not sufficiently supported. Milking frequency operational feasibility is not validated.</p>
        <button type="button" onClick={simulate} disabled={busy || !hasValidInputs}>{busy ? 'Estimating…' : 'Run counterfactual estimates'}</button>
      </section>}

      {error && <div className="didt-live__error" role="alert">{error}</div>}
      {result && <>
        <section className="didt-live__grid">
          <article className="didt-live__card"><h2>Observed baseline state</h2><strong>{show(result.observed_milk_yield_l_day, ' L/cow/day')}</strong>
            <p>Observed date: {result.observed_date ?? 'Unavailable'}</p></article>
          <article className="didt-live__card"><h2>Baseline prediction</h2><strong className="didt-live__value">{show(result.baseline_predicted_milk_yield_l_day, ' L/cow/day')}</strong>
            <p>Status: {result.baseline_status} · Horizon: {result.prediction_horizon_days} day after observed date</p><p>Model: {result.model_version ?? 'Unavailable'}</p></article>
        </section>
        <section className="didt-live__card"><h2>Scenario comparison</h2>
          {result.scenarios.map((item) => <article className="didt-live__result" key={item.scenario_id}>
            <div className="didt-live__card-head"><div><h3>{item.name}</h3><p>{item.scenario_id} · {item.feature}: {show(item.baseline_value)} → {item.proposed_value} {item.unit}</p></div><b className="didt-live__status">{item.scenario_status}</b></div>
            <div className="didt-live__facts didt-live__facts--compact">
              <div><span>Baseline prediction</span><b>{show(item.baseline_predicted_milk_yield_l_day, ' L/day')}</b></div>
              <div><span>Counterfactual prediction</span><b>{show(item.counterfactual_predicted_milk_yield_l_day, ' L/day')}</b></div>
              <div><span>Absolute predicted change</span><b>{show(item.absolute_yield_change_l_day, ' L/day')}</b></div>
              <div><span>Percentage predicted change</span><b>{show(item.percentage_yield_change, '%')}</b></div>
            </div>
            {item.assumptions.map((assumption) => <p className="didt-live__small" key={assumption}>{assumption}</p>)}
            {item.warnings.map((warning) => <p className="didt-live__finding" key={warning}>{warning}</p>)}
            {item.data_limitations.map((limitation) => <p className="didt-live__small" key={limitation}>{limitation}</p>)}
          </article>)}
          {result.warnings.map((warning) => <p className="didt-live__small" key={warning}>{warning}</p>)}
        </section>
      </>}
      <p className="didt-live__disclaimer">A prediction difference is a model-based counterfactual estimate, not evidence that an intervention will cause a real-world yield change.</p>
    </main>
  );
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    return typeof detail === 'string' ? detail : error.response ? `Request failed (${error.response.status}).` : 'The API is unavailable.';
  }
  return 'The request could not be completed.';
}
