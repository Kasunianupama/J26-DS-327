/**
 * The remaining detail drawers: forecast structure, cohorts, capacity-flow
 * stages, product constraints and the findings inbox (§10, §12, §19, §21, §25).
 */

import {
  CAPACITY_FLOW,
  HERD,
  PROFILES,
  PRODUCTS,
  PRODUCT_CONSTRAINT,
  PRODUCT_META,
  PRODUCT_MONTHS,
  HERD_OUTCOMES,
  animalsInLayer,
  fmtInt,
  fmtLKR,
  groupValue,
  longDate,
  outcomeAt,
  structureForDate,
  type Animal,
  type GroupingKey,
  type Product,
} from '../../../data/component2';
import { useC2, type ForecastDomain, type OutcomeChart } from '../state';
import {
  Card, ConfidenceBadge, DelProLink, Drawer, EvidenceBadge, InfoPoint, KpiStrip, KpiTile, Meter, Note,
} from '../ui';
import { ContributionChart } from './ContributionChart';
import { FindingsList } from './Findings';

/* ------------------------------------------------------------------ */
/* "What makes up this forecast?" (§21)                                */
/* ------------------------------------------------------------------ */

const DOMAIN_NAMES: Record<ForecastDomain, 'Herd & milk' | 'Reproduction & health' | 'Products' | 'Finance & context'> = {
  herd: 'Herd & milk',
  repro: 'Reproduction & health',
  products: 'Products',
  finance: 'Finance & context',
};

export function StructureDrawer({ date, domain }: { date: string; domain: ForecastDomain }) {
  const { closeDrawer } = useC2();
  const s = structureForDate(date);
  const variation = s.variations.find((item) => item.domain === DOMAIN_NAMES[domain])!;
  const largestMagnitude = Math.max(1, ...variation.contributors.map((item) => item.magnitude));
  const dominant = [...variation.contributors].sort((a, b) => b.magnitude - a.magnitude)[0];

  const ev = s.evidence;

  return (
    <Drawer
      wide
      eyebrow={`Point explanation · ${variation.domain}`}
      title={`${variation.domain} — point explanation`}
      sub={`${longDate(date)} · only the selected chart and the evidence that is actually relevant to it. Every number below describes this single point, not the herd average.`}
      onClose={closeDrawer}
      actions={<ConfidenceBadge level={ev.confidence} />}
      summary={
        <KpiStrip>
          {variation.metrics.slice(0, 4).map((metric) => (
            <KpiTile
              key={metric.label}
              label={
                <>
                  {metric.label}
                  <InfoPoint label={metric.label}>
                    Measured at {longDate(date)} for the {variation.domain.toLowerCase()} chart only —
                    not averaged across the herd or across the horizon. {ev.confidence} confidence, with{' '}
                    {Math.round(ev.transitionDependency)}% of the estimate resting on transitions that have
                    not happened yet.
                  </InfoPoint>
                </>
              }
              value={metric.value}
              tone={metric.label.toLowerCase().includes('range') ? 'pred' : 'plain'}
            />
          ))}
          <KpiTile
            icon="confidence"
            label="Evidence quality"
            value={ev.confidence}
            tone={ev.confidence === 'High' ? 'brand' : ev.confidence === 'Moderate' ? 'caution' : 'concern'}
            foot={`${Math.round(ev.individualShare)}% individual · ${Math.round(ev.transitionDependency)}% depends on future transitions`}
          />
        </KpiStrip>
      }
    >
      <div className="pfie-section-title" style={{ marginTop: 0 }}>01 · What happened</div>
      <section className="pfie-variation">
        <b>{variation.change}</b>
        <p>{variation.explanation}</p>
      </section>

      {domain === 'herd' && (
        <section className="pfie-structure-breakdown">
          <div className="pfie-section-title">Forecast composition at this point</div>
          {s.structure.map((row) => (
            <div key={row.label} className="pfie-structure-row">
              <div className="pfie-row between">
                <span><b>{row.label}</b><small>{row.kind}</small></span>
                <span>{fmtInt(row.value)} {row.unit} · {row.share}%</span>
              </div>
              <Meter pct={row.share} tone={row.kind.startsWith('Depends') ? 'pred' : 'brand'} />
            </div>
          ))}
        </section>
      )}

      <div className="pfie-section-title">02 · Why — ranked contributors</div>
      {variation.contributors.length > 0 && (
        <ContributionChart contributors={variation.contributors} />
      )}
      <div className="pfie-contributors">
        {variation.contributors.length ? variation.contributors.map((item) => (
          <article className="pfie-contributor" key={item.label}>
            <div className="pfie-contributor-head">
              <div><b>{item.label}</b><span className="pfie-source-tag">{item.source}</span></div>
              <strong className={item.direction}>{item.effect}</strong>
            </div>
            <div className="pfie-effect-track" aria-label={`${item.label}: ${item.effect}`}>
              <i className={item.direction} style={{ width: `${Math.max(4, (item.magnitude / largestMagnitude) * 100)}%` }} />
            </div>
            <p>{item.mechanism}</p>
            <div className="pfie-contributor-evidence">
              <span>Evidence: {item.evidence}</span>
              <ConfidenceBadge level={item.confidence} hint={false} />
            </div>
          </article>
        )) : <div className="pfie-empty"><b>No chart data for this point</b>Select a point within the available chart range.</div>}
      </div>
      <Note>Contributions are target-specific and are not combined into one universal score. Positive and negative effects remain separate.</Note>

      <div className="pfie-section-title">03 · Full reasoning</div>
      <section className="pfie-reasoning-summary">
        <span>Model verdict</span>
        <b>{variation.verdict}</b>
        <p>{variation.explanation}</p>
      </section>
      <div className="pfie-reasoning-steps">
        <div><b>Observed / selected</b><p>{variation.change}. The comparison is against the immediately preceding period shown for this chart.</p></div>
        <div><b>Candidate drivers</b><p>{variation.contributors.length} relevant drivers passed the reporting threshold for {variation.domain.toLowerCase()}.</p></div>
        <div><b>Ranking</b><p>{dominant ? `${dominant.label} has the largest displayed effect (${dominant.effect}), supported by ${dominant.evidence.toLowerCase()}.` : 'No ranked driver is available.'}</p></div>
        <div><b>Residual</b><p>{variation.residual.value}. {variation.residual.explanation}</p></div>
        <div><b>What could change this conclusion</b><p>{variation.falsifier}</p></div>
      </div>

      <div className="pfie-section-title">Relevant reasoning pathways</div>
      <div className="pfie-pathways">
        {variation.pathways.map((path) => (
          <section className="pfie-pathway" key={path.title}>
            <h4>{path.title}</h4>
            <div className="pfie-pathway-flow">
              {path.nodes.map((node, index) => (
                <div className="pfie-path-node" key={`${path.title}-${node.stage}-${node.label}`}>
                  <span>{node.stage}</span>
                  <b>{node.label}</b>
                  <small>{node.detail}</small>
                  {index < path.nodes.length - 1 && <i aria-hidden>→</i>}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="pfie-section-title">04 · Relevant data coverage</div>
      <div className="pfie-coverage-list">
        {variation.coverage.map((item) => (
          <div key={item.source} className="pfie-coverage-row">
            <div className="pfie-row between"><b>{item.source}</b><span>{item.pct}%</span></div>
            <Meter pct={item.pct} tone={item.pct < 75 ? 'caution' : 'brand'} />
            <small>{item.note}</small>
          </div>
        ))}
      </div>
      <Note>Coverage gaps stay visible as gaps. Missing values are not silently replaced with zero.</Note>
    </Drawer>
  );
}

/* ------------------------------------------------------------------ */
/* Outcome point reasoning                                             */
/* ------------------------------------------------------------------ */

type OutcomeContributor = {
  label: string;
  effect: string;
  magnitude: number;
  direction: 'positive' | 'negative' | 'neutral';
  source: string;
  detail: string;
};

export function OutcomeReasoningDrawer({ date, chart }: { date: string; chart: OutcomeChart }) {
  const { closeDrawer } = useC2();
  const point = outcomeAt(date);
  const index = HERD_OUTCOMES.findIndex((item) => item.key === point.key);
  const previous = HERD_OUTCOMES[Math.max(0, index - 1)] ?? point;
  const reproduction = chart === 'reproduction';
  const highRisk = point.profiles.find((profile) => profile.tone === 'risk')?.count ?? 0;
  const previousHighRisk = previous.profiles.find((profile) => profile.tone === 'risk')?.count ?? highRisk;
  const signed = (value: number, unit: string) => `${value >= 0 ? '+' : '−'}${Math.abs(value)} ${unit}`;

  const contributors: OutcomeContributor[] = reproduction
    ? [
        { label: 'AI conversions', effect: signed(point.aiSuccess - previous.aiSuccess, 'outcomes'), magnitude: Math.abs(point.aiSuccess - previous.aiSuccess), direction: point.aiSuccess >= previous.aiSuccess ? 'positive' : 'negative', source: point.future ? 'Expected service pathway' : 'Recorded service outcomes', detail: `${point.aiSuccess} successful outcomes from ${point.aiAttempts} AI services at this point.` },
        { label: 'Carried-to-term outcomes', effect: signed(point.carriedToTerm - previous.carriedToTerm, 'outcomes'), magnitude: Math.abs(point.carriedToTerm - previous.carriedToTerm), direction: point.carriedToTerm >= previous.carriedToTerm ? 'positive' : 'negative', source: point.future ? 'Pregnancy follow-up model' : 'Recorded calving outcomes', detail: `${point.carriedToTerm} carried-to-term outcomes are ${point.future ? 'expected' : 'recorded'}.` },
        { label: 'Abortion exposure', effect: signed(-point.abortions, 'outcomes'), magnitude: point.abortions, direction: point.abortions > 0 ? 'negative' : 'neutral', source: point.future ? 'Risk-adjusted projection' : 'Recorded outcome coding', detail: `${point.abortions} ${point.future ? 'expected' : 'recorded'} abortions remain separate from carried-to-term outcomes.` },
        { label: 'Animals needing review', effect: signed(-(highRisk - previousHighRisk), 'animals'), magnitude: Math.abs(highRisk - previousHighRisk), direction: highRisk <= previousHighRisk ? 'positive' : 'negative', source: 'Profile review', detail: `${highRisk} animals are currently in the higher-risk profile.` },
      ]
    : [
        { label: 'Net transfers', effect: signed((point.transfersIn - point.transfersOut) - (previous.transfersIn - previous.transfersOut), 'head'), magnitude: Math.abs((point.transfersIn - point.transfersOut) - (previous.transfersIn - previous.transfersOut)), direction: point.transfersIn - point.transfersOut >= previous.transfersIn - previous.transfersOut ? 'positive' : 'negative', source: point.future ? 'Herd movement plan' : 'Recorded transfer register', detail: `${point.transfersIn} in and ${point.transfersOut} out at this point.` },
        { label: 'Deaths', effect: signed(-point.deaths, 'head'), magnitude: point.deaths, direction: point.deaths > 0 ? 'negative' : 'neutral', source: point.future ? 'Risk scenario' : 'Recorded mortality register', detail: `${point.deaths} ${point.future ? 'expected' : 'recorded'} deaths; the count is never converted into a probability for an individual animal.` },
        { label: 'Risk-point load', effect: signed(-(point.riskPoints - previous.riskPoints), 'points'), magnitude: Math.abs(point.riskPoints - previous.riskPoints), direction: point.riskPoints <= previous.riskPoints ? 'positive' : 'negative', source: 'Risk profile model', detail: `The risk-point load is ${point.riskPoints}, combining recorded follow-up needs and forecast uncertainty.` },
        { label: 'Higher-risk profile', effect: signed(-(highRisk - previousHighRisk), 'animals'), magnitude: Math.abs(highRisk - previousHighRisk), direction: highRisk <= previousHighRisk ? 'positive' : 'negative', source: 'Profile review', detail: `${highRisk} animals require closer follow-up at this point.` },
      ];
  const maxEffect = Math.max(1, ...contributors.map((item) => item.magnitude));
  const dominant = [...contributors].sort((a, b) => b.magnitude - a.magnitude)[0];
  const metrics = reproduction
    ? [
        ['AI services', `${point.aiAttempts}`], ['AI successful', `${point.aiSuccess}`], ['Not successful', `${point.aiFailure}`], ['Carried to term', `${point.carriedToTerm}`], ['Abortions', `${point.abortions}`],
      ]
    : [
        ['Transfers in', `${point.transfersIn}`], ['Transfers out', `${point.transfersOut}`], ['Deaths', `${point.deaths}`], ['Risk points', `${point.riskPoints}`], ['Higher-risk profile', `${highRisk} animals`],
      ];
  const pathway = reproduction
    ? [
        { stage: 'Driver', label: 'AI service record', detail: `${point.aiAttempts} ${point.future ? 'planned or expected' : 'recorded'} services` },
        { stage: 'Checkpoint', label: 'Conception and follow-up', detail: `${point.aiSuccess} successful outcomes; confirmation remains distinct` },
        { stage: 'Outcome', label: 'Carried to term / loss', detail: `${point.carriedToTerm} carried to term and ${point.abortions} abortions` },
      ]
    : [
        { stage: 'Driver', label: 'Herd movement records', detail: `${point.transfersIn} transfers in and ${point.transfersOut} out` },
        { stage: 'Risk', label: 'Risk and follow-up load', detail: `${point.riskPoints} risk points across ${highRisk} higher-risk animals` },
        { stage: 'Outcome', label: 'Herd continuity', detail: `${point.deaths} deaths ${point.future ? 'expected' : 'recorded'} at this point` },
      ];
  const coverage: [string, number, string][] = reproduction
    ? [
        ['AI and service records', 97, 'Service attempts and dates'], ['Pregnancy follow-up', 92, 'Confirmed, pending and negative checks'], ['Carried-to-term outcomes', 83, 'Recorded calving and loss outcomes'], ['Health-event coding', 84, 'Events used as risk context'],
      ]
    : [
        ['Transfer register', 98, 'Recorded herd entries and exits'], ['Mortality register', 95, 'Recorded deaths at herd level'], ['Health-event coding', 84, 'Risk and follow-up context'], ['Profile follow-up', 78, 'Outcome and review status completeness'],
      ];

  return (
    <Drawer wide title={`${reproduction ? 'AI and pregnancy outcomes' : 'Deaths, transfers and risk'} — point explanation`} sub={`${longDate(point.start)} · ${point.future ? 'expected point' : 'recorded point'} · ${point.confidence} confidence`} onClose={closeDrawer}>
      <div className="pfie-section-title" style={{ marginTop: 0 }}>01 · What happened</div>
      <section className="pfie-variation">
        <b>{point.future ? 'Expected counts for this point' : 'Recorded counts for this point'}</b>
        <p>{point.factors[0]}. {point.factors[1]}. Counts describe this month only; they are not individual-animal probabilities.</p>
        <div className="pfie-variation-metrics">
          {metrics.map(([label, value]) => <div key={label}><span>{label}</span><b>{value}</b></div>)}
        </div>
      </section>

      <div className="pfie-section-title">02 · Why — relevant contributors</div>
      <div className="pfie-contributors">
        {contributors.map((item) => (
          <article className="pfie-contributor" key={item.label}>
            <div className="pfie-contributor-head"><div><b>{item.label}</b><span className="pfie-source-tag">{item.source}</span></div><strong className={item.direction}>{item.effect}</strong></div>
            <div className="pfie-effect-track"><i className={item.direction} style={{ width: `${Math.max(4, (item.magnitude / maxEffect) * 100)}%` }} /></div>
            <p>{item.detail}</p>
          </article>
        ))}
      </div>
      <Note>These are point-specific contributors. They are shown separately and do not add up to a single success or failure score.</Note>

      <div className="pfie-section-title">03 · Full reasoning pathway</div>
      <section className="pfie-reasoning-summary"><span>Point verdict</span><b>{dominant.label} is the largest displayed change at this point.</b><p>{point.factors.join(' · ')}</p></section>
      <section className="pfie-pathway" style={{ marginTop: 10 }}>
        <h4>{reproduction ? 'AI → confirmation → carried-to-term pathway' : 'Movement → risk → herd continuity pathway'}</h4>
        <div className="pfie-pathway-flow">
          {pathway.map((node, index) => <div className="pfie-path-node" key={node.label}><span>{node.stage}</span><b>{node.label}</b><small>{node.detail}</small>{index < pathway.length - 1 && <i aria-hidden>→</i>}</div>)}
        </div>
      </section>
      <div className="pfie-reasoning-steps">
        <div><b>Recorded vs expected</b><p>{point.future ? 'This is a planning estimate built from recorded service, profile and herd-movement patterns. Its uncertainty is shown explicitly.' : 'This is a recorded monthly outcome. It describes what was captured, not a proof of cause.'}</p></div>
        <div><b>What could change it</b><p>{reproduction ? 'Late pregnancy checks, a revised service record, an unrecorded loss or an updated calving outcome.' : 'A late transfer, mortality record, health event or follow-up status update.'}</p></div>
      </div>

      <div className="pfie-section-title">04 · Relevant data coverage</div>
      <div className="pfie-coverage-list">
        {coverage.map(([source, pct, note]) => <div key={source} className="pfie-coverage-row"><div className="pfie-row between"><b>{source}</b><span>{pct}%</span></div><Meter pct={pct} tone={pct < 80 ? 'caution' : 'brand'} /><small>{note}</small></div>)}
      </div>
      <Note>Coverage gaps remain visible. Missing outcomes are not treated as a zero event.</Note>
    </Drawer>
  );
}

/* ------------------------------------------------------------------ */
/* Cohort drawer (§10)                                                 */
/* ------------------------------------------------------------------ */

export function CohortDrawer({ groupKey, value }: { groupKey: string; value: string }) {
  const { closeDrawer, openDrawer } = useC2();

  const animals: Animal[] =
    groupKey === 'State'
      ? (() => {
          const [prod, repro] = value.split(' · ');
          return HERD.filter((a) => a.prodState === prod && a.reproState === repro)
            .sort((x, y) => y.contribution90 - x.contribution90);
        })()
      : groupKey === 'Profile'
        ? HERD.filter((a) => PROFILES[a.profile].name === value)
          .sort((x, y) => y.contribution90 - x.contribution90)
      : animalsInLayer(groupKey as GroupingKey, value);

  const total = animals.reduce((s, a) => s + a.contribution90, 0);

  return (
    <Drawer
      wide
      title={value}
      sub={`${animals.length} animals · ${fmtInt(total)} L expected over 90 days · ranked by contribution`}
      onClose={closeDrawer}
    >
      {animals.length === 0 ? (
        <div className="pfie-empty">
          <b>No animals in this group</b>
          Nothing in the current herd matches {value}.
        </div>
      ) : (
        <>
          <div className="pfie-tablewrap">
            <table className="pfie-table">
              <thead>
                <tr>
                  <th>Animal</th>
                  <th className="pfie-num">90-day contribution</th>
                  <th>Next transition</th>
                  <th>Evidence</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {animals.slice(0, 60).map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => openDrawer({ kind: 'cow', animalId: a.id })}>
                    <td><b>{a.id}</b> <span style={{ color: 'var(--muted)' }}>· {a.stage}</span></td>
                    <td className="pfie-num">
                      <span className="pfie-row tight" style={{ justifyContent: 'flex-end' }}>
                        <Meter pct={(a.contribution90 / Math.max(1, animals[0].contribution90)) * 100} />
                        {fmtInt(a.contribution90)} L
                      </span>
                    </td>
                    <td style={{ color: 'var(--muted)' }}>
                      {a.prodState === 'Milking' && a.dryOffDate
                        ? `Dry-off ${longDate(a.dryOffDate).slice(0, 6)}`
                        : a.expectedCalving
                          ? `Calving ${longDate(a.expectedCalving).slice(0, 6)}`
                          : '—'}
                    </td>
                    <td><EvidenceBadge source={a.evidence} /></td>
                    <td><ConfidenceBadge level={a.confidence} hint={false} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {animals.length > 60 && (
            <p className="sub" style={{ marginTop: 10 }}>Showing the 60 largest contributors of {animals.length}.</p>
          )}
          <div className="pfie-row between" style={{ marginTop: 16 }}>
            <span className="sub">Select an animal for its predictive panel.</span>
            <DelProLink id={`the ${value} group`} />
          </div>
        </>
      )}
    </Drawer>
  );
}

/* ------------------------------------------------------------------ */
/* Capacity-flow stage drawer (§12)                                    */
/* ------------------------------------------------------------------ */

export function FlowStageDrawer({ stageId }: { stageId: string }) {
  const { closeDrawer, openDrawer } = useC2();
  const stage = CAPACITY_FLOW.find((s) => s.id === stageId);
  if (!stage) return null;
  const members = stage.members().sort((a, b) => b.contribution90 - a.contribution90);

  return (
    <Drawer wide title={stage.name} sub={stage.note} onClose={closeDrawer}>
      <div className="pfie-consequence" style={{ marginTop: 0 }}>
        <div><div className="k">Current</div><div className="v">{stage.current}</div><div className="d">Animals in this stage today</div></div>
        <div><div className="k">Expected</div><div className="v">{stage.expected || stage.current}</div><div className="d">Likely range {stage.range[0]}–{stage.range[1]}</div></div>
        <div><div className="k">Evidence split</div><div className="v">{stage.confirmed} / {stage.uncertain}</div><div className="d">Confirmed record vs uncertain</div></div>
        {stage.capacityContribution > 0 && (
          <div><div className="k">Milk-capacity contribution</div><div className="v">{fmtInt(stage.capacityContribution)} L/day</div><div className="d">Expected daily litres from this stage</div></div>
        )}
      </div>

      <div className="pfie-section-title">Important animals</div>
      <div className="pfie-tablewrap pfie-scroll">
        <table className="pfie-table">
          <thead><tr><th>Animal</th><th>State</th><th className="pfie-num">90-day litres</th><th>Evidence</th></tr></thead>
          <tbody>
            {members.slice(0, 40).map((a) => (
              <tr key={a.id} className="clickable" onClick={() => openDrawer({ kind: 'cow', animalId: a.id })}>
                <td><b>{a.id}</b></td>
                <td style={{ color: 'var(--muted)' }}>{a.prodState} · {a.reproState}</td>
                <td className="pfie-num">{fmtInt(a.contribution90)}</td>
                <td><EvidenceBadge source={a.evidence} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pfie-row between" style={{ marginTop: 14 }}>
        <span className="sub">{members.length} animals in this stage.</span>
        <DelProLink id={stage.name} />
      </div>
    </Drawer>
  );
}

/* ------------------------------------------------------------------ */
/* Product constraint drawer (§19)                                     */
/* ------------------------------------------------------------------ */

export function ProductDrawer({ product }: { product: string }) {
  const { closeDrawer, openDrawer, selectedMonth } = useC2();
  const p = product as Product;
  const pm = PRODUCT_MONTHS.find((m) => m.key === selectedMonth);
  if (!pm || !PRODUCTS.includes(p)) return null;

  const constrained = pm.shortfall[p] > 0;
  // Cows tapering or drying off inside the window are the herd contributors.
  const contributors = HERD.filter(
    (a) => a.dryOffDate && a.dryOffDate >= '2026-10-14' && a.dryOffDate <= '2026-10-28',
  ).sort((x, y) => y.currentYield - x.currentYield);

  return (
    <Drawer
      wide
      title={p}
      sub={`${pm.label} · ${PRODUCT_META[p].note}`}
      onClose={closeDrawer}
    >
      <div className="pfie-consequence" style={{ marginTop: 0 }}>
        <div><div className="k">Expected output</div><div className="v">{fmtInt(pm.output[p])} L</div><div className="d">Likely range {fmtInt(Math.round(pm.output[p] * 0.95))}–{fmtInt(Math.round(pm.output[p] * 1.05))} L</div></div>
        <div><div className="k">Revenue</div><div className="v">{fmtLKR(pm.revenue[p])}</div><div className="d">At {PRODUCT_META[p].pricePerL} LKR per litre allocated</div></div>
        <div>
          <div className="k">Constraint</div>
          <div className="v" style={{ color: constrained ? 'var(--concern)' : 'var(--brand)' }}>
            {constrained ? `Short ${fmtInt(pm.shortfall[p])} L` : 'Within plan'}
          </div>
          <div className="d">{constrained ? 'Milk supply below the planned line volume' : 'No milk constraint expected'}</div>
        </div>
      </div>

      {constrained && PRODUCT_CONSTRAINT ? (
        <>
          <div className="pfie-section-title">Constraint detail</div>
          <table className="pfie-table">
            <tbody>
              <tr><td style={{ color: 'var(--muted)' }}>First constrained week</td><td><b>{longDate(PRODUCT_CONSTRAINT.firstWeek)}</b></td></tr>
              <tr><td style={{ color: 'var(--muted)' }}>Worst week</td><td>{longDate(PRODUCT_CONSTRAINT.worstWeek)} · {fmtInt(PRODUCT_CONSTRAINT.worstWeekLitres)} L short</td></tr>
              <tr><td style={{ color: 'var(--muted)' }}>Milk shortfall</td><td>{fmtInt(pm.shortfall[p])} L across {pm.label}</td></tr>
              <tr><td style={{ color: 'var(--muted)' }}>Revenue consequence</td><td>{fmtLKR(PRODUCT_CONSTRAINT.revenueEffect)}</td></tr>
              <tr><td style={{ color: 'var(--muted)' }}>Confidence</td><td><ConfidenceBadge level={PRODUCT_CONSTRAINT.confidence} hint={false} /></td></tr>
            </tbody>
          </table>

          <div className="pfie-section-title">Herd contributors</div>
          <p className="sub" style={{ marginBottom: 10 }}>
            The animals leaving the milking herd inside the October window, ranked by the litres they currently
            supply.
          </p>
          <div className="pfie-tablewrap pfie-scroll short">
            <table className="pfie-table">
              <thead><tr><th>Animal</th><th className="pfie-num">Current litres/day</th><th>Dry-off</th><th>Confidence</th></tr></thead>
              <tbody>
                {contributors.slice(0, 25).map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => openDrawer({ kind: 'cow', animalId: a.id })}>
                    <td><b>{a.id}</b> <span style={{ color: 'var(--muted)' }}>· {a.stage}</span></td>
                    <td className="pfie-num">{a.currentYield}</td>
                    <td style={{ color: 'var(--muted)' }}>{a.dryOffDate ? longDate(a.dryOffDate) : '—'}</td>
                    <td><ConfidenceBadge level={a.confidence} hint={false} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div style={{ marginTop: 16 }}>
          <Note>
            No constraint expected for this line in {pm.label}. Expected allocation is based on current and
            historical operating patterns — the split is observed, not set here.
          </Note>
        </div>
      )}
    </Drawer>
  );
}

/* ------------------------------------------------------------------ */
/* Findings inbox drawer (§25)                                         */
/* ------------------------------------------------------------------ */

export function FindingsDrawer() {
  const { closeDrawer } = useC2();
  return (
    <Drawer title="Findings" sub="Prioritised, grouped, and navigable to the affected view." onClose={closeDrawer}>
      <FindingsList />
    </Drawer>
  );
}

export { Card, groupValue };
