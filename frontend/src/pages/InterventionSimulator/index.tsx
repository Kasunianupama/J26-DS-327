import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  cows,
  defaultSettings,
  defaultWeights,
  featureInfluence,
  generateScenarioSet,
  rankScenarios,
  simulateScenario,
  type CowProfile,
  type InterventionSettings,
  type InterventionType,
  type InterventionScenario,
  type OptimizationWeights,
  type RankedScenario,
} from '../../data/interventionMockData';
import './InterventionSimulator.css';

const interventionLabels: Record<InterventionType, string> = {
  feed: 'Feed Optimization',
  supplement: 'Nutritional Supplementation',
  heat: 'Heat-Stress Reduction',
  health: 'Health Treatment',
  reproduction: 'Reproductive Management',
};

const loadingSteps = [
  'Generating counterfactual scenario...',
  'Checking biological consistency...',
  'Estimating expected outcome...',
];

export default function InterventionSimulatorPage() {
  const [cowId, setCowId] = useState('COW-1047');
  const [intervention, setIntervention] = useState<InterventionType>('feed');
  const [settings, setSettings] = useState<InterventionSettings>(defaultSettings);
  const [weights, setWeights] = useState<OptimizationWeights>(defaultWeights);
  const [simulation, setSimulation] = useState<InterventionScenario>(() =>
    simulateScenario(cows[0], 'feed', defaultSettings),
  );
  const [loadingIndex, setLoadingIndex] = useState<number | null>(null);
  const [decision, setDecision] = useState<'approved' | 'rejected' | null>(null);

  const cow = cows.find((item) => item.id === cowId) ?? cows[0];
  const scenarios = useMemo(() => generateScenarioSet(cow), [cow]);
  const ranked = useMemo(() => rankScenarios(scenarios, weights), [scenarios, weights]);
  const recommendation = ranked[0];
  const normalizedWeights = normalizeWeights(weights);

  function runSimulation() {
    setDecision(null);
    setLoadingIndex(0);
    window.setTimeout(() => setLoadingIndex(1), 450);
    window.setTimeout(() => setLoadingIndex(2), 900);
    window.setTimeout(() => {
      setSimulation(simulateScenario(cow, intervention, settings));
      setLoadingIndex(null);
    }, 1350);
  }

  function selectCow(nextCowId: string) {
    const nextCow = cows.find((item) => item.id === nextCowId) ?? cows[0];
    const nextSettings = {
      ...defaultSettings,
      feedQuantity: Math.min(22, nextCow.state.feedIntake + 2),
      energyDensity: nextCow.state.energyDensity,
      targetThi: Math.max(66, nextCow.state.thi - 4),
    };
    setCowId(nextCowId);
    setSettings(nextSettings);
    setSimulation(simulateScenario(nextCow, 'feed', nextSettings));
    setIntervention('feed');
    setDecision(null);
  }

  return (
    <div className="bis">
      <header className="bis-hero">
        <div>
          <p className="bis-eyebrow">INTERVENTION SIMULATOR</p>
          <h1>Dairy Intervention Digital Twin</h1>
          <p>Explore biologically plausible what-if interventions before making a real-world decision.</p>
        </div>
        <div className="bis-status" aria-label="System readiness">
          <StatusPill label="Digital Twin" value="Ready" />
          <StatusPill label="Prediction Model" value="Ready" />
          <StatusPill label="Biological Validator" value="Ready" />
        </div>
      </header>

      <Workflow />

      <section className="bis-grid two">
        <CowSelector cow={cow} onSelect={selectCow} />
        <BaselinePrediction cow={cow} />
      </section>

      <CurrentState cow={cow} />

      <section className="bis-card bis-simulator" aria-labelledby="bis-title">
        <div className="bis-section-head">
          <div>
            <p className="bis-kicker">Biological Intervention Simulator (BIS)</p>
            <h2 id="bis-title">What-if intervention simulator</h2>
            <p title="An estimated outcome under an alternative intervention while keeping the observed biological state fixed.">
              Change one controllable intervention while keeping the remaining observed biological state constant.
            </p>
          </div>
          <button className="bis-primary" type="button" onClick={runSimulation} disabled={loadingIndex !== null}>
            {loadingIndex === null ? 'Run What-If Simulation' : loadingSteps[loadingIndex]}
          </button>
        </div>

        <InterventionControls
          cow={cow}
          intervention={intervention}
          settings={settings}
          onInterventionChange={setIntervention}
          onSettingsChange={setSettings}
        />

        <CounterfactualResult cow={cow} scenario={simulation} settings={settings} intervention={intervention} />
      </section>

      <BiologicalValidator scenario={simulation} />

      <ScenarioComparison baseline={cow.baselineMilkYield} scenarios={scenarios} ranked={ranked} recommendation={recommendation} />

      <section className="bis-grid two align-start">
        <OptimizationPanel weights={weights} normalizedWeights={normalizedWeights} onChange={setWeights} />
        <InterventionRanking ranked={ranked} />
      </section>

      {recommendation && (
        <RecommendationCard
          baseline={cow.baselineMilkYield}
          recommendation={recommendation}
          alternatives={ranked.slice(1, 3)}
        />
      )}

      {recommendation && (
        <HumanReview
          decision={decision}
          onAccept={() => setDecision('approved')}
          onReject={() => setDecision('rejected')}
          onModify={() => {
            setDecision(null);
            document.getElementById('bis-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }}
        />
      )}

      <ResearchValidation cow={cow} scenario={simulation} recommendation={recommendation} />
    </div>
  );
}

function normalizeWeights(weights: OptimizationWeights) {
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0) || 1;
  return {
    milk: Math.round((weights.milk / total) * 100),
    welfare: Math.round((weights.welfare / total) * 100),
    cost: Math.round((weights.cost / total) * 100),
    feasibility: Math.round((weights.feasibility / total) * 100),
    resources: Math.round((weights.resources / total) * 100),
  };
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return <span className="bis-status-pill"><b>{label}</b>{value}</span>;
}

function Workflow() {
  return (
    <nav className="bis-workflow" aria-label="DIDT workflow">
      {['Select Cow', 'Baseline', 'What-If Intervention', 'Validate', 'Compare', 'Recommendation'].map((step, index) => (
        <span key={step}><b>{index + 1}</b>{step}</span>
      ))}
    </nav>
  );
}

function CowSelector({ cow, onSelect }: { cow: CowProfile; onSelect: (cowId: string) => void }) {
  return (
    <section className="bis-card">
      <div className="bis-section-head compact">
        <div>
          <p className="bis-kicker">Select Animal</p>
          <h2>{cow.id}</h2>
        </div>
        <label className="bis-field">
          Cow ID
          <select value={cow.id} onChange={(event) => onSelect(event.target.value)}>
            {cows.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
          </select>
        </label>
      </div>
      <dl className="bis-facts">
        <div><dt>Breed</dt><dd>{cow.breed}</dd></div>
        <div><dt>Age</dt><dd>{cow.ageYears} years</dd></div>
        <div><dt>Parity</dt><dd>{cow.parity}</dd></div>
        <div><dt>Lactation Stage</dt><dd>{cow.lactationStage}</dd></div>
        <div><dt>Days in Milk</dt><dd>{cow.daysInMilk}</dd></div>
        <div><dt>Health</dt><dd>{cow.healthStatus}</dd></div>
      </dl>
    </section>
  );
}

function CurrentState({ cow }: { cow: CowProfile }) {
  const metrics = [
    ['Milk Yield', `${cow.state.milkYield.toFixed(1)} kg/day`],
    ['Feed Intake', `${cow.state.feedIntake.toFixed(1)} kg/day`],
    ['Body Condition Score', cow.state.bcs.toFixed(1)],
    ['Temperature-Humidity Index', cow.state.thi],
    ['Health Risk', cow.state.healthRisk],
    ['Milking Frequency', cow.state.milkingFrequency],
    ['Lactation Day', cow.daysInMilk],
  ];
  return (
    <section className="bis-card">
      <div className="bis-section-head compact">
        <div>
          <p className="bis-kicker">Current / Observed Biological State</p>
          <h2>Current Cow State</h2>
          <p title="The observed/current cow state used as the reference.">
            This is the observed baseline state used for counterfactual simulation.
          </p>
        </div>
      </div>
      <div className="bis-metrics">
        {metrics.map(([label, value]) => (
          <div className="bis-metric" key={label}>
            <span>{label}</span>
            <b>{value}</b>
          </div>
        ))}
      </div>
    </section>
  );
}

function BaselinePrediction({ cow }: { cow: CowProfile }) {
  return (
    <section className="bis-card">
      <p className="bis-kicker">Baseline Prediction</p>
      <div className="bis-big-value">
        <span>Baseline expected milk yield</span>
        <b>{cow.baselineMilkYield.toFixed(1)} kg/day</b>
      </div>
      <div className="bis-inline-stats">
        <span>Expected range: <b>{cow.expectedRange[0].toFixed(1)} - {cow.expectedRange[1].toFixed(1)} kg/day</b></span>
        <span>Confidence: <b>{cow.confidence}%</b></span>
      </div>
      <h3>Illustrative feature contribution</h3>
      <div className="bis-influence">
        {featureInfluence.map((item) => (
          <div key={item.name}>
            <span>{item.name}</span>
            <i><em style={{ width: `${item.value}%` }} /></i>
          </div>
        ))}
      </div>
    </section>
  );
}

function InterventionControls({
  cow,
  intervention,
  settings,
  onInterventionChange,
  onSettingsChange,
}: {
  cow: CowProfile;
  intervention: InterventionType;
  settings: InterventionSettings;
  onInterventionChange: (value: InterventionType) => void;
  onSettingsChange: (value: InterventionSettings) => void;
}) {
  const update = <K extends keyof InterventionSettings>(key: K, value: InterventionSettings[K]) =>
    onSettingsChange({ ...settings, [key]: value });

  return (
    <div className="bis-controls">
      <div className="bis-intervention-tabs" role="tablist" aria-label="Intervention type">
        {(Object.keys(interventionLabels) as InterventionType[]).map((key) => (
          <button key={key} type="button" aria-pressed={intervention === key} onClick={() => onInterventionChange(key)}>
            {interventionLabels[key]}
          </button>
        ))}
      </div>

      <div className="bis-control-panel">
        {intervention === 'feed' && (
          <>
            <Slider label="Feed quantity" current={`${cow.state.feedIntake.toFixed(1)} kg/day`} min={18} max={24} step={0.1} value={settings.feedQuantity} unit="kg/day" onChange={(value) => update('feedQuantity', value)} />
            <Slider label="Feed energy density" current={`${cow.state.energyDensity.toFixed(1)} MJ/kg`} min={9.5} max={12} step={0.1} value={settings.energyDensity} unit="MJ/kg" onChange={(value) => update('energyDensity', value)} />
          </>
        )}
        {intervention === 'supplement' && (
          <>
            <label className="bis-field">Supplement
              <select value={settings.supplement} onChange={(event) => update('supplement', event.target.value as InterventionSettings['supplement'])}>
                <option>None</option><option>Protein Supplement</option><option>Energy Supplement</option>
              </select>
            </label>
            <Slider label="Dosage" current="0 kg/day" min={0} max={2.5} step={0.1} value={settings.dosage} unit="kg/day" onChange={(value) => update('dosage', value)} />
          </>
        )}
        {intervention === 'heat' && (
          <>
            <label className="bis-field">Cooling strategy
              <select value={settings.cooling} onChange={(event) => update('cooling', event.target.value as InterventionSettings['cooling'])}>
                <option>None</option><option>Fans</option><option>Fans + sprinklers</option>
              </select>
            </label>
            <Slider label="Estimated THI after intervention" current={`${cow.state.thi}`} min={64} max={cow.state.thi} step={1} value={settings.targetThi} unit="THI" onChange={(value) => update('targetThi', value)} />
          </>
        )}
        {intervention === 'health' && (
          <>
            <div className="bis-note warning"><b>Research prototype only.</b> This interface does not recommend real medical treatment.</div>
            <p className="bis-current-line">Current health condition: <b>{cow.healthStatus}</b></p>
            <label className="bis-field">Treatment scenario
              <select value={settings.treatment} onChange={(event) => update('treatment', event.target.value as InterventionSettings['treatment'])}>
                <option>No treatment</option><option>Early treatment</option>
              </select>
            </label>
          </>
        )}
        {intervention === 'reproduction' && (
          <>
            <p className="bis-current-line">Current reproductive status: <b>{cow.reproductiveStatus}</b></p>
            <label className="bis-field">Management intervention
              <select value={settings.reproductiveAction} onChange={(event) => update('reproductiveAction', event.target.value as InterventionSettings['reproductiveAction'])}>
                <option>No change</option><option>Breeding timing review</option><option>Pregnancy check scheduling</option>
              </select>
            </label>
            <label className="bis-field">Expected effect window
              <select value={settings.effectWindow} onChange={(event) => update('effectWindow', event.target.value as InterventionSettings['effectWindow'])}>
                <option>7 days</option><option>14 days</option><option>21 days</option>
              </select>
            </label>
          </>
        )}
      </div>
    </div>
  );
}

function Slider({ label, current, min, max, step, value, unit, onChange }: {
  label: string;
  current: string;
  min: number;
  max: number;
  step: number;
  value: number;
  unit: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="bis-slider">
      <span><b>{label}</b><small>Current: {current}</small></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <output>{value.toFixed(step < 1 ? 1 : 0)} {unit}</output>
    </label>
  );
}

function CounterfactualResult({ cow, scenario, settings, intervention }: {
  cow: CowProfile;
  scenario: InterventionScenario;
  settings: InterventionSettings;
  intervention: InterventionType;
}) {
  const changed = intervention === 'feed'
    ? [`Feed: ${cow.state.feedIntake.toFixed(1)} kg/day`, `Feed: ${settings.feedQuantity.toFixed(1)} kg/day`]
    : intervention === 'heat'
      ? [`THI: ${cow.state.thi}`, `THI: ${settings.targetThi}`]
      : intervention === 'supplement'
        ? ['Supplement: None', `Supplement: ${settings.supplement}`]
        : intervention === 'health'
          ? [`Health: ${cow.healthStatus}`, `Treatment scenario: ${settings.treatment}`]
          : [`Reproduction: ${cow.reproductiveStatus}`, `Management: ${settings.reproductiveAction}`];
  return (
    <div className="bis-counterfactual">
      <div>
        <h3>Current / Observed</h3>
        <p>{changed[0]}</p>
        <p>Milk: {cow.baselineMilkYield.toFixed(1)} kg/day</p>
        <p>THI: {cow.state.thi}</p>
        <p>Health: {cow.healthStatus}</p>
      </div>
      <div className="bis-vs">VS</div>
      <div>
        <h3>What-if / Counterfactual</h3>
        <p>{changed[1]}</p>
        <p>Milk: {scenario.predictedMilk.toFixed(1)} kg/day</p>
        <p>THI: {intervention === 'heat' ? settings.targetThi : cow.state.thi}</p>
        <p>Health: {cow.healthStatus}</p>
      </div>
      <aside>
        <span>Estimated counterfactual outcome</span>
        <b>{scenario.milkDelta >= 0 ? '+' : ''}{scenario.milkDelta.toFixed(1)} kg/day</b>
        <small>{scenario.percentDelta >= 0 ? '+' : ''}{scenario.percentDelta.toFixed(1)}% vs baseline</small>
      </aside>
    </div>
  );
}

function BiologicalValidator({ scenario }: { scenario: InterventionScenario }) {
  return (
    <section className={`bis-card bis-validator ${scenario.validation.status === 'Rejected' ? 'invalid' : ''}`}>
      <div className="bis-section-head compact">
        <div>
          <p className="bis-kicker">Biological Consistency Validator (BCV)</p>
          <h2 title="Checks whether the simulated scenario satisfies predefined biological and operational constraints.">Biological Consistency Check</h2>
        </div>
        <strong className="bis-validation-state">{scenario.validation.status === 'Validated' ? 'PASS - VALIDATED' : 'REJECTED'}</strong>
      </div>
      <ul className="bis-checks">
        {scenario.validation.checks.map((check) => (
          <li key={check.label} className={check.passed ? 'pass' : 'fail'}>
            <span aria-hidden>{check.passed ? '✓' : '!'}</span>{check.label}
          </li>
        ))}
      </ul>
      <p className="bis-note">{scenario.validation.message}</p>
    </section>
  );
}

function ScenarioComparison({ baseline, scenarios, ranked, recommendation }: {
  baseline: number;
  scenarios: InterventionScenario[];
  ranked: RankedScenario[];
  recommendation?: RankedScenario;
}) {
  const chartData = [{ name: 'Baseline', milk: baseline }, ...scenarios.map((scenario) => ({ name: scenario.interventionLabel, milk: scenario.predictedMilk }))];
  return (
    <section className="bis-card">
      <div className="bis-section-head compact">
        <div>
          <p className="bis-kicker">Counterfactual Scenario Comparison</p>
          <h2>Multiple intervention alternatives</h2>
        </div>
      </div>
      <div className="bis-comparison">
        <div className="bis-chart" aria-label="Predicted milk chart">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: -18, bottom: 18 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-12} textAnchor="end" height={54} />
              <YAxis domain={[Math.max(0, baseline - 3), 'dataMax + 1']} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(value) => [`${value} kg/day`, 'Predicted milk']} />
              <Bar dataKey="milk" fill="#5b7fa6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bis-table-wrap">
          <table className="bis-table">
            <thead><tr><th>Intervention</th><th>Predicted Milk</th><th>Delta Milk</th><th>Cost</th><th>Welfare</th><th>Feasibility</th><th>Validation</th><th>Overall Score</th></tr></thead>
            <tbody>
              {scenarios.map((scenario) => {
                const scoredScenario = ranked.find((item) => item.id === scenario.id);
                const best = recommendation?.id === scenario.id;
                return (
                  <tr key={scenario.id} className={best ? 'best' : undefined}>
                    <td><b>{scenario.interventionLabel}</b><small>{scenario.label}</small></td>
                    <td>{scenario.predictedMilk.toFixed(1)} kg/day</td>
                    <td>{scenario.milkDelta >= 0 ? '+' : ''}{scenario.milkDelta.toFixed(1)}</td>
                    <td>{scenario.cost}</td>
                    <td>{scenario.welfare}</td>
                    <td>{scenario.feasibility}</td>
                    <td>{scenario.validation.status}</td>
                    <td>{scoredScenario?.score ?? '-'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function OptimizationPanel({ weights, normalizedWeights, onChange }: {
  weights: OptimizationWeights;
  normalizedWeights: OptimizationWeights;
  onChange: (weights: OptimizationWeights) => void;
}) {
  const items: { key: keyof OptimizationWeights; label: string }[] = [
    { key: 'milk', label: 'Milk Yield Improvement' },
    { key: 'welfare', label: 'Animal Welfare' },
    { key: 'cost', label: 'Feed Cost' },
    { key: 'feasibility', label: 'Operational Feasibility' },
    { key: 'resources', label: 'Resource Availability' },
  ];
  return (
    <section className="bis-card">
      <p className="bis-kicker">Intervention Optimization Engine (IOE)</p>
      <h2 title="Ranks feasible interventions using multiple decision objectives.">Intervention Optimization</h2>
      <p>Compare feasible strategies using multiple decision criteria. Displayed weights are normalized to total 100%.</p>
      <div className="bis-weight-list">
        {items.map((item) => (
          <label className="bis-slider compact-slider" key={item.key}>
            <span><b>{item.label}</b><small>{normalizedWeights[item.key]}%</small></span>
            <input type="range" min={5} max={60} step={1} value={weights[item.key]} onChange={(event) => onChange({ ...weights, [item.key]: Number(event.target.value) })} />
          </label>
        ))}
      </div>
    </section>
  );
}

function InterventionRanking({ ranked }: { ranked: RankedScenario[] }) {
  return (
    <section className="bis-card">
      <p className="bis-kicker">Ranked Intervention Strategies</p>
      <h2>Feasible strategy ranking</h2>
      <div className="bis-ranking">
        {ranked.slice(0, 4).map((scenario, index) => (
          <article key={scenario.id} className={index === 0 ? 'top' : undefined}>
            <strong>#{index + 1}</strong>
            <div>
              <h3>{scenario.interventionLabel}</h3>
              <p>Milk benefit: {scenario.milkDelta >= 0 ? '+' : ''}{scenario.milkDelta.toFixed(1)} kg/day</p>
              <small>Welfare: {scenario.welfare} · Cost: {scenario.cost} · Feasibility: {scenario.feasibility}</small>
            </div>
            <b>{scenario.score}</b>
          </article>
        ))}
      </div>
    </section>
  );
}

function RecommendationCard({ baseline, recommendation, alternatives }: {
  baseline: number;
  recommendation: RankedScenario;
  alternatives: RankedScenario[];
}) {
  return (
    <section className="bis-card bis-recommendation">
      <div>
        <p className="bis-kicker">Intervention Recommendation Engine (IRE)</p>
        <h2>✓ Recommended Intervention</h2>
        <h3>{recommendation.interventionLabel}</h3>
        <div className="bis-reco-grid">
          <span>Expected milk yield <b>{recommendation.predictedMilk.toFixed(1)} kg/day</b></span>
          <span>Baseline <b>{baseline.toFixed(1)} kg/day</b></span>
          <span>Expected improvement <b>+{recommendation.milkDelta.toFixed(1)} kg/day</b></span>
          <span title="Prototype estimate of prediction certainty; not a guarantee.">Confidence <b>{recommendation.confidence}%</b></span>
          <span>Overall score <b>{recommendation.score} / 100</b></span>
        </div>
      </div>
      <div className="bis-why">
        <h3>Why was this recommended?</h3>
        <p>Selected because it provides a strong predicted milk-yield improvement while maintaining high animal-welfare compatibility, moderate cost, and high operational feasibility.</p>
        <ul>
          <li>✓ High expected milk benefit</li>
          <li>✓ High welfare compatibility</li>
          <li>✓ Available farm resources</li>
          <li>✓ Validated biological scenario</li>
          <li>✓ Lower cost than higher-feed alternatives</li>
        </ul>
        <p className="bis-alt">Alternative options: {alternatives.map((item) => item.interventionLabel).join(', ')}</p>
      </div>
      <div className="bis-uncertainty">
        <h3>Confidence / Uncertainty</h3>
        <p>Prediction confidence: <b>{recommendation.confidence}%</b></p>
        <p>Expected milk range: <b>{(recommendation.predictedMilk - 0.6).toFixed(1)} - {(recommendation.predictedMilk + 0.5).toFixed(1)} kg/day</b></p>
        <p>Risk: <b>{recommendation.confidence > 80 ? 'Low' : 'Moderate'}</b></p>
        <small>Confidence reflects the prototype's estimated certainty and is not a clinical or causal guarantee.</small>
      </div>
    </section>
  );
}

function HumanReview({ decision, onAccept, onReject, onModify }: {
  decision: 'approved' | 'rejected' | null;
  onAccept: () => void;
  onReject: () => void;
  onModify: () => void;
}) {
  return (
    <section className="bis-card bis-review">
      <div>
        <p className="bis-kicker">Farm Manager Review</p>
        <h2>Human decision gate</h2>
        <p>The system provides decision support. Final intervention decisions remain under human control.</p>
      </div>
      <div className="bis-actions">
        <button className="bis-primary" type="button" onClick={onAccept}>Accept Recommendation</button>
        <button type="button" onClick={onModify}>Modify Scenario</button>
        <button className="danger" type="button" onClick={onReject}>Reject</button>
      </div>
      {decision && (
        <strong className={`bis-decision ${decision}`}>
          {decision === 'approved'
            ? 'Recommendation approved for decision-support record.'
            : 'Recommendation rejected by manager.'}
        </strong>
      )}
    </section>
  );
}

function ResearchValidation({ cow, scenario, recommendation }: {
  cow: CowProfile;
  scenario: InterventionScenario;
  recommendation?: RankedScenario;
}) {
  return (
    <details className="bis-card bis-details">
      <summary>Research Validation</summary>
      <div className="bis-research-grid">
        <span>Baseline prediction <b>{cow.baselineMilkYield.toFixed(1)} kg/day</b></span>
        <span>Counterfactual prediction <b>{scenario.predictedMilk.toFixed(1)} kg/day</b></span>
        <span>Estimated uplift <b>{scenario.milkDelta >= 0 ? '+' : ''}{scenario.milkDelta.toFixed(1)} kg/day</b></span>
        <span>Scenario validation <b>{scenario.validation.status === 'Validated' ? 'PASS' : 'REJECTED'}</b></span>
        <span>Recommendation rank <b>{recommendation ? '#1' : 'Unavailable'}</b></span>
        <span>Historical comparison <b>Available in research dataset</b></span>
      </div>
      <p>Prototype demonstration data. No experimental MAE, RMSE, R2, clinical accuracy, or causal validation metric is claimed by this frontend.</p>
    </details>
  );
}
