import { useEffect, useState } from 'react';
import axios from 'axios';
import { api } from '../../services/api';
import {
  describeCombinedIntervention,
  describeIntervention,
  conciseRecommendationExplanation,
  filterScenarioMessages,
  formatChange,
  formatMilkYield,
  formatNumber,
  initialSliderValue,
  isSupportedSliderValue,
  scenarioLabel,
  sliderBounds,
  supportLabel,
  validatedModelRange,
} from './presentation.mjs';
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
type ModelRange = { minimum: number; maximum: number } | null;
type ModelSupport = {
  status: 'LOADING' | 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE';
  model_version: string | null;
  features: { thi_mean: ModelRange; milkings_per_day: ModelRange };
};
type ScenarioEstimate = {
  scenario_id: string; category: string; name: string; feature: string; scenario_status: string;
  model_support_status: string;
  baseline_value: number | null; proposed_value: number; unit: string;
  baseline_predicted_milk_yield_l_day: number | null; counterfactual_predicted_milk_yield_l_day: number | null;
  absolute_yield_change_l_day: number | null; percentage_yield_change: number | null;
  model_version: string | null; assumptions: string[]; data_limitations: string[]; warnings: string[];
};
type CombinedScenarioEstimate = {
  scenario_id: string; name: string; scenario_status: string; model_support_status: string;
  baseline_thi_mean: number | null; proposed_thi_mean: number;
  baseline_milkings_per_day: number | null; proposed_milkings_per_day: number;
  baseline_predicted_milk_yield_l_day: number | null; counterfactual_predicted_milk_yield_l_day: number | null;
  absolute_yield_change_l_day: number | null; percentage_yield_change: number | null;
  model_version: string | null;
  operational_feasibility_validated: boolean; assumptions: string[]; warnings: string[]; data_limitations: string[];
};
type RankedAlternative = {
  rank: number; scenario_id: string; alternative_type: 'individual' | 'combined'; name: string;
  scenario_status: string; predicted_milk_yield_l_day: number;
  baseline_predicted_milk_yield_l_day: number; absolute_yield_change_l_day: number;
  percentage_yield_change: number | null; model_version: string | null; model_support_status: string;
  operational_feasibility_validated: boolean;
};
type ScenarioRecommendation = RankedAlternative & { explanation: string; limitations: string[] };
type SimulationResponse = {
  contract_version: string; animal_ref: string; observed_date: string | null; observed_milk_yield_l_day: number | null;
  cow_state: CowState; prediction_horizon_days: number; baseline_status: string;
  baseline_predicted_milk_yield_l_day: number | null; model_version: string | null;
  scenarios: ScenarioEstimate[]; combined_scenario: CombinedScenarioEstimate | null;
  ranked_alternatives: RankedAlternative[]; recommendation: ScenarioRecommendation | null;
  recommendation_explanation: string; warnings: string[];
};

function alternativeDetails(alternative: RankedAlternative, response: SimulationResponse) {
  if (alternative.alternative_type === 'combined') {
    const combined = response.combined_scenario;
    return {
      label: scenarioLabel('combined'),
      changes: combined ? describeCombinedIntervention(
        combined.baseline_thi_mean,
        combined.proposed_thi_mean,
        combined.baseline_milkings_per_day,
        combined.proposed_milkings_per_day,
      ) : ['Proposed changes unavailable'],
      warnings: filterScenarioMessages(combined?.warnings ?? [], response.cow_state.data_limitations),
    };
  }

  const scenario = response.scenarios.find((item) => item.scenario_id === alternative.scenario_id);
  return {
    label: scenarioLabel('individual', scenario?.feature),
    changes: scenario ? [describeIntervention(scenario.feature, scenario.baseline_value, scenario.proposed_value)] : ['Proposed changes unavailable'],
    warnings: filterScenarioMessages(scenario?.warnings ?? [], response.cow_state.data_limitations),
  };
}

function formatSliderValue(feature: Feature, value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'Unavailable';
  return feature === 'milkings_per_day' && Number.isInteger(value) ? String(value) : formatNumber(value);
}

function SupportedRangeSlider({
  id, feature, title, unit, currentValue, proposedValue, range, onChange,
}: {
  id: string; feature: Feature; title: string; unit: string; currentValue: number | null;
  proposedValue: string; range: ModelRange; onChange: (value: string) => void;
}) {
  const modelRange = validatedModelRange(range);
  const bounds = sliderBounds(feature, range);
  const rangeDescriptionId = `${id}-range-description`;
  return <div className="didt-live__slider-control">
    <label htmlFor={id}>Proposed {title}</label>
    <div className="didt-live__slider-references">
      <span>Current: <b>{formatSliderValue(feature, currentValue)} {unit}</b></span>
      {modelRange && <span>Model-supported training range: <b>{formatNumber(modelRange.minimum)}–{formatNumber(modelRange.maximum)} {unit}</b></span>}
    </div>
    {bounds ? <>
      <input
        id={id}
        type="range"
        min={bounds.minimum}
        max={bounds.maximum}
        step={bounds.step}
        value={proposedValue || String(bounds.minimum)}
        aria-describedby={rangeDescriptionId}
        onChange={(event) => onChange(event.target.value)}
      />
      <output htmlFor={id} aria-live="polite">Proposed: {proposedValue ? formatSliderValue(feature, Number(proposedValue)) : 'Select a value'} {proposedValue ? unit : ''}</output>
      <small id={rangeDescriptionId}>{feature === 'milkings_per_day'
        ? 'The slider uses whole milkings/day values within the model-supported range.'
        : 'The slider uses the model-supported THI range.'}</small>
    </> : <p id={rangeDescriptionId} className="didt-live__range-unavailable" role="status">
      Model-supported range unavailable; no range is assumed and this slider cannot be used.
    </p>}
  </div>;
}

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
  const [modelSupport, setModelSupport] = useState<ModelSupport>({
    status: 'LOADING', model_version: null, features: { thi_mean: null, milkings_per_day: null },
  });
  const [scenarios, setScenarios] = useState<ScenarioInput[]>([emptyScenario(1)]);
  const [combinedEnabled, setCombinedEnabled] = useState(false);
  const [combinedThi, setCombinedThi] = useState('');
  const [combinedMilkings, setCombinedMilkings] = useState('');
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.get<CowReference[]>('/interventions/cows')
      .then((response) => { if (active) setAnimalOptions(response.data); })
      .catch((cause) => { if (active) setError(errorMessage(cause)); });
    api.get<ModelSupport>('/interventions/model-support')
      .then((response) => { if (active) setModelSupport(response.data); })
      .catch(() => {
        if (active) setModelSupport({ status: 'UNAVAILABLE', model_version: null, features: { thi_mean: null, milkings_per_day: null } });
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!state || modelSupport.status === 'LOADING') return;
    setScenarios((current) => current.map((row) => {
      const feature = featureFor[row.category];
      return { ...row, feature, proposed_value: initialSliderValue(feature, state[feature], modelSupport.features[feature]) };
    }));
    setCombinedThi(initialSliderValue('thi_mean', state.thi_mean, modelSupport.features.thi_mean));
    setCombinedMilkings(initialSliderValue('milkings_per_day', state.milkings_per_day, modelSupport.features.milkings_per_day));
  }, [state, modelSupport]);

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
      if (patch.category) {
        next.feature = featureFor[patch.category];
        next.proposed_value = state
          ? initialSliderValue(next.feature, state[next.feature], modelSupport.features[next.feature])
          : '';
      }
      return next;
    }));
  }

  async function simulate() {
    if (!hasValidInputs) return;
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
      combined_scenario: combinedEnabled ? {
        scenario_id: 'combined-thi-milkings',
        thi_mean: Number(combinedThi),
        milkings_per_day: Number(combinedMilkings),
      } : null,
    };
    try {
      const response = await api.post<SimulationResponse>('/interventions/simulate-counterfactual', requestBody);
      setResult(response.data);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  const hasValidInputs = (scenarios.length > 0 || combinedEnabled) && scenarios.length <= 8
    && modelSupport.status !== 'LOADING'
    && scenarios.every((scenario) => scenario.proposed_value.trim() !== ''
      && isSupportedSliderValue(scenario.feature, Number(scenario.proposed_value), modelSupport.features[scenario.feature]))
    && (!combinedEnabled || (
      combinedThi.trim() !== ''
      && isSupportedSliderValue('thi_mean', Number(combinedThi), modelSupport.features.thi_mean)
      && combinedMilkings.trim() !== ''
      && isSupportedSliderValue('milkings_per_day', Number(combinedMilkings), modelSupport.features.milkings_per_day)
    ));
  const recommendationDetails = result?.recommendation ? alternativeDetails(result.recommendation, result) : null;
  const recommendationChange = result?.recommendation
    ? formatChange(result.recommendation.absolute_yield_change_l_day, result.recommendation.percentage_yield_change)
    : null;

  return (
    <main className="didt-live">
      <header className="didt-live__hero">
        <div><p className="didt-live__eyebrow">COMPONENT 1 · RESEARCH PROTOTYPE</p><h1>Counterfactual milk-yield simulator</h1>
          <p>Compares one-day-ahead predictions for an observed Farm X cow state and user-specified model-input changes.</p></div>
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
              ['Milkings/day', state.milkings_per_day], ['Body weight', state.body_weight],
              ['THI', showTwoDecimals(state.thi_mean)], ['Days pregnant', state.days_pregnant]] as [string, unknown][])
              .map(([label, value]) => <div key={label}><span>{label}</span><b>{value == null ? 'Unavailable' : String(value)}</b></div>)}
          </div>
        </>}
      </section>

      {state && <section className="didt-live__card">
        <div className="didt-live__card-head"><div><h2>What-if scenarios</h2><p>Submit up to eight independent alternatives and one optional combined alternative. Each is compared with the same baseline.</p></div>
          <button className="didt-live__secondary" type="button" onClick={() => setScenarios((rows) => {
            if (rows.length >= 8) return rows;
            const row = { ...emptyScenario(0), scenario_id: nextScenarioId(rows) };
            row.proposed_value = state ? initialSliderValue(row.feature, state[row.feature], modelSupport.features[row.feature]) : '';
            return [...rows, row];
          })} disabled={scenarios.length >= 8}>Add scenario</button></div>
        {modelSupport.status === 'LOADING' && <p className="didt-live__small" role="status">Loading model-supported slider ranges…</p>}
        {modelSupport.model_version && <p className="didt-live__small">Slider bounds come from model training support ({modelSupport.model_version}); they do not establish farm feasibility.</p>}
        {modelSupport.status === 'UNAVAILABLE' && <p className="didt-live__notice" role="status">Model-supported ranges are unavailable. Scenario sliders remain disabled until the predictor can provide its training-support metadata.</p>}
        {scenarios.map((scenario, index) => <div className="didt-live__scenario" key={scenario.scenario_id}>
          <label>Input category<select value={scenario.category} onChange={(e) => updateScenario(index, { category: e.target.value as Category })}>
            <option value="heat">THI exposure input</option><option value="management">Milking frequency input</option>
          </select></label>
          <SupportedRangeSlider
            id={`scenario-${index}-${scenario.feature}`}
            feature={scenario.feature}
            title={featureName[scenario.feature]}
            unit={unitFor[scenario.feature]}
            currentValue={state[scenario.feature]}
            proposedValue={scenario.proposed_value}
            range={modelSupport.features[scenario.feature]}
            onChange={(value) => updateScenario(index, { proposed_value: value })}
          />
          {(scenarios.length > 1 || combinedEnabled) && <button className="didt-live__remove" type="button" onClick={() => setScenarios((rows) => rows.filter((_, i) => i !== index))}>Remove</button>}
        </div>)}
        <div className="didt-live__scenario didt-live__scenario--combined">
          <label><input type="checkbox" checked={combinedEnabled} onChange={(event) => {
            const enabled = event.target.checked;
            setCombinedEnabled(enabled);
            if (!enabled) setScenarios((rows) => rows.length ? rows : [emptyScenario(1)]);
          }} /> Evaluate combined THI and milking-frequency alternative</label>
          {combinedEnabled && <>
            <SupportedRangeSlider id="combined-thi-slider" feature="thi_mean" title="THI" unit="THI"
              currentValue={state.thi_mean} proposedValue={combinedThi} range={modelSupport.features.thi_mean}
              onChange={setCombinedThi} />
            <SupportedRangeSlider id="combined-milkings-slider" feature="milkings_per_day" title="milking frequency" unit="milkings/day"
              currentValue={state.milkings_per_day} proposedValue={combinedMilkings} range={modelSupport.features.milkings_per_day}
              onChange={setCombinedMilkings} />
          </>}
        </div>
        <p className="didt-live__small">Available scenarios: hypothetical THI exposure changes and milking frequency changes. Feed and concentrate interventions are unavailable because the required intervention data and semantics are not sufficiently supported.</p>
        <button type="button" onClick={simulate} disabled={busy || !hasValidInputs}>{busy ? 'Estimating…' : 'Run counterfactual estimates'}</button>
      </section>}

      {error && <div className="didt-live__error" role="alert">{error}</div>}
      {result && <>
        <section className="didt-live__grid">
          <article className="didt-live__card"><h2>Observed baseline state</h2><strong>{show(result.observed_milk_yield_l_day, ' L/cow/day')}</strong>
            <p>Observed date: {result.observed_date ?? 'Unavailable'}</p></article>
          <article className="didt-live__card"><h2>Baseline prediction</h2><strong className="didt-live__value">{formatMilkYield(result.baseline_predicted_milk_yield_l_day)}</strong>
            <p>Status: {result.baseline_status} · Horizon: {result.prediction_horizon_days} day after observed date</p><p>Model: {result.model_version ?? 'Unavailable'}</p></article>
        </section>
        <section className="didt-live__card"><h2>Individual scenario comparison</h2>
          {result.scenarios.map((item) => {
            const visibleWarnings = filterScenarioMessages(item.warnings, state?.data_limitations);
            const visibleAssumptions = filterScenarioMessages(item.assumptions, state?.data_limitations);
            const visibleLimitations = filterScenarioMessages(item.data_limitations, state?.data_limitations);
            return <article className="didt-live__result" key={item.scenario_id}>
            <div className="didt-live__card-head"><div><h3>{scenarioLabel('individual', item.feature)}</h3><p>{describeIntervention(item.feature, item.baseline_value, item.proposed_value)}</p></div><b className="didt-live__status">{supportLabel(item.scenario_status, item.model_support_status, item.counterfactual_predicted_milk_yield_l_day != null)}</b></div>
            <div className="didt-live__facts didt-live__facts--compact">
              <div><span>Baseline prediction</span><b>{formatMilkYield(item.baseline_predicted_milk_yield_l_day)}</b></div>
              <div><span>Counterfactual prediction</span><b>{formatMilkYield(item.counterfactual_predicted_milk_yield_l_day)}</b></div>
              <div><span>Change vs. baseline</span><b>{formatChange(item.absolute_yield_change_l_day, item.percentage_yield_change).text}</b></div>
            </div>
            {visibleAssumptions.map((assumption) => <p className="didt-live__small" key={assumption}>{assumption}</p>)}
            {visibleWarnings.map((warning) => <p className="didt-live__finding" key={warning}>{warning}</p>)}
            {item.counterfactual_predicted_milk_yield_l_day == null && visibleWarnings.length === 0 && <p className="didt-live__finding">The model did not return a milk-yield estimate for this scenario.</p>}
            {visibleLimitations.map((limitation) => <p className="didt-live__small" key={limitation}>{limitation}</p>)}
          </article>;
          })}
        </section>
        {result.combined_scenario && <section className="didt-live__card">
          <h2>Combined scenario</h2>
          <p>{supportLabel(result.combined_scenario.scenario_status, result.combined_scenario.model_support_status, result.combined_scenario.counterfactual_predicted_milk_yield_l_day != null)}</p>
          <p>Model: {result.combined_scenario.model_version ?? result.model_version ?? 'Unavailable'}</p>
          {describeCombinedIntervention(result.combined_scenario.baseline_thi_mean, result.combined_scenario.proposed_thi_mean, result.combined_scenario.baseline_milkings_per_day, result.combined_scenario.proposed_milkings_per_day).map((change) => <p key={change}>{change}</p>)}
          <div className="didt-live__facts didt-live__facts--compact">
            <div><span>Baseline prediction</span><b>{formatMilkYield(result.combined_scenario.baseline_predicted_milk_yield_l_day)}</b></div>
            <div><span>Combined predicted yield</span><b>{formatMilkYield(result.combined_scenario.counterfactual_predicted_milk_yield_l_day)}</b></div>
            <div><span>Change vs. baseline</span><b>{formatChange(result.combined_scenario.absolute_yield_change_l_day, result.combined_scenario.percentage_yield_change).text}</b></div>
          </div>
          {filterScenarioMessages(result.combined_scenario.assumptions, state?.data_limitations).map((assumption) => <p className="didt-live__small" key={assumption}>{assumption}</p>)}
          {filterScenarioMessages(result.combined_scenario.warnings, state?.data_limitations).map((warning) => <p className="didt-live__finding" key={warning}>{warning}</p>)}
          {result.combined_scenario.counterfactual_predicted_milk_yield_l_day == null && filterScenarioMessages(result.combined_scenario.warnings, state?.data_limitations).length === 0 && <p className="didt-live__finding">The model did not return a milk-yield estimate for this scenario.</p>}
          {filterScenarioMessages(result.combined_scenario.data_limitations, state?.data_limitations).map((limitation) => <p className="didt-live__small" key={limitation}>{limitation}</p>)}
        </section>}
        <section className="didt-live__card didt-live__ranking" aria-labelledby="ranking-heading">
          <header className="didt-live__ranking-head">
            <div><p className="didt-live__eyebrow">Decision support</p><h2 id="ranking-heading">Ranking and recommendation</h2></div>
            <p className="didt-live__small">Alternatives are shown in the order returned by the model-based ranking.</p>
          </header>

          {result.recommendation && recommendationDetails && recommendationChange ? <article className="didt-live__recommended" aria-labelledby="recommended-heading">
            <h3 className="didt-live__eyebrow" id="recommended-heading">Recommended scenario</h3>
            <div className="didt-live__recommended-title"><h4>{recommendationDetails.label}</h4>
              <span className="didt-live__support">{supportLabel(result.recommendation.scenario_status, result.recommendation.model_support_status, true)}</span></div>
            <div className="didt-live__recommended-metrics">
              <div className="didt-live__recommended-yield"><span>Predicted next-day milk yield</span><strong>{formatMilkYield(result.recommendation.predicted_milk_yield_l_day)}</strong></div>
              <div className={`didt-live__recommended-change didt-live__recommended-change--${recommendationChange.kind}`}>
                <span>{recommendationChange.kind === 'negative' ? 'Predicted decrease vs. baseline' : recommendationChange.kind === 'positive' ? 'Change vs. baseline' : 'Change vs. baseline'}</span>
                <strong>{recommendationChange.text}</strong>
              </div>
            </div>
            <div className="didt-live__proposed-changes" aria-label="Proposed changes">
              {recommendationDetails.changes.map((change) => <span key={change}>{change}</span>)}
            </div>
            <p className="didt-live__recommendation-explanation">{conciseRecommendationExplanation(result.recommendation.explanation)}</p>
            <p className="didt-live__small">Model version: {result.recommendation.model_version ?? 'Unavailable'}.</p>
            {recommendationDetails.warnings.map((warning) => <p className="didt-live__finding" key={warning}>{warning}</p>)}
            {filterScenarioMessages(result.recommendation.limitations, state?.data_limitations).map((limitation) => <p className="didt-live__finding" key={limitation}>{limitation}</p>)}
          </article> : <div className="didt-live__ranking-empty" role="status">
            <h3>No supported scenario could be recommended.</h3>
            <p>{result.recommendation_explanation}</p>
          </div>}

          <div className="didt-live__alternatives-head"><h3>Evaluated alternatives</h3><p>Ranked by predicted next-day milk yield</p></div>
          {result.ranked_alternatives.length > 0 ? <ol className="didt-live__ranked-list" aria-label="Alternatives in model ranking order">
            {result.ranked_alternatives.map((alternative) => {
              const details = alternativeDetails(alternative, result);
              const change = formatChange(alternative.absolute_yield_change_l_day, alternative.percentage_yield_change);
              return <li className={`didt-live__ranked-item${alternative.rank === 1 ? ' didt-live__ranked-item--top' : ''}`} key={alternative.scenario_id}>
                <article className="didt-live__ranked-card" aria-labelledby={`scenario-title-${alternative.rank}`}>
                  <header className="didt-live__ranked-title">
                    <span className="didt-live__rank-badge" aria-label={`Rank ${alternative.rank}`}>#{alternative.rank}</span>
                    <div><h4 id={`scenario-title-${alternative.rank}`}>{details.label}</h4><span className="didt-live__scenario-type">{alternative.alternative_type === 'combined' ? 'Combined alternative' : 'Individual alternative'}</span></div>
                    <span className="didt-live__support">{supportLabel(alternative.scenario_status, alternative.model_support_status, true)}</span>
                  </header>
                  <div className="didt-live__ranked-changes">{details.changes.map((item) => <span key={item}>{item}</span>)}</div>
                  <dl className="didt-live__ranked-metrics">
                    <div><dt>Predicted milk yield</dt><dd>{formatMilkYield(alternative.predicted_milk_yield_l_day)}</dd></div>
                    <div className={`didt-live__delta didt-live__delta--${change.kind}`}><dt>{change.kind === 'negative' ? 'Predicted decrease vs. baseline' : 'Change vs. baseline'}</dt><dd>{change.text}</dd></div>
                  </dl>
                  {details.warnings.map((warning) => <p className="didt-live__finding" key={warning}>{warning}</p>)}
                </article>
              </li>;
            })}
          </ol> : <p className="didt-live__ranking-empty" role="status">No valid alternatives are available to rank.</p>}
          <p className="didt-live__ranking-disclaimer">These are model-based estimates, not guaranteed real-world outcomes. Farm feasibility and causal intervention effects have not been established.</p>
        </section>
        {filterScenarioMessages(result.warnings, state?.data_limitations).map((warning) => <p className="didt-live__small" key={warning}>{warning}</p>)}
      </>}
      {!result && <p className="didt-live__disclaimer">A prediction difference is a model-based counterfactual estimate, not evidence that an intervention will cause a real-world yield change.</p>}
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
