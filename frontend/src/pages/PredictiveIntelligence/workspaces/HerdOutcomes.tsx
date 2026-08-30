/** Past records and future outlook for AI outcomes, pregnancy loss and herd movement. */

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { HERD_OUTCOMES, TODAY_ISO, outcomeAt, type HerdOutcomePoint } from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, Note, TipShell } from '../ui';

export function HerdOutcomes() {
  const { selectedDate, setSelectedDate, openDrawer } = useC2();
  const selected = outcomeAt(selectedDate);
  const today = HERD_OUTCOMES.find((point) => point.future)?.label;

  const selectPoint = (chart: 'reproduction' | 'movement', label?: string | number) => {
    const point = HERD_OUTCOMES.find((item) => item.label === String(label));
    if (!point) return;
    setSelectedDate(point.start);
    openDrawer({ kind: 'outcome', date: point.start, chart });
  };

  return (
    <div className="pfie-stack">
      <Card
        title="Herd outcomes & risk"
        sub="Recorded outcomes are solid. Future outcomes are expected counts, with confidence shown for each point. Select any month to inspect its contributors."
        actions={<ConfidenceBadge level={selected.confidence} />}
      >
        <div className="pfie-outcome-selected">
          <div><span>Selected point</span><b>{selected.label}</b></div>
          <div><span>Evidence status</span><b>{selected.future ? 'Expected' : 'Recorded'}</b></div>
          <div><span>Risk points</span><b>{selected.riskPoints}</b></div>
          <div><span>Confidence</span><ConfidenceBadge level={selected.confidence} hint={false} /></div>
        </div>
        <div className="pfie-grid c2" style={{ marginTop: 18 }}>
          <OutcomeChart title="AI, carried-to-term & abortion outcomes" kind="reproduction" today={today} onSelect={(label) => selectPoint('reproduction', label)} />
          <OutcomeChart title="Deaths, transfers & risk points" kind="movement" today={today} onSelect={(label) => selectPoint('movement', label)} />
        </div>
      </Card>

      <div className="pfie-grid side">
        <Card title={`Contributors — ${selected.label}`} sub={selected.future ? 'Expected drivers at this forecast point.' : 'Recorded contributors at this historical point.'}>
          <ul className="pfie-outcome-factors">
            {selected.factors.map((factor) => <li key={factor}>{factor}</li>)}
          </ul>
          <Note tone={selected.future ? 'info' : 'default'}>
            {selected.future
              ? 'Future counts are a planning estimate, not individual event probabilities. Confidence falls as the date relies on unconfirmed pregnancies, services and transfers.'
              : 'Past counts describe recorded events. They do not by themselves prove why an outcome occurred.'}
          </Note>
        </Card>

        <Card title="Profiles at this point" sub="Animals grouped by the type of follow-up or forecast risk they carry.">
          <div className="pfie-outcome-profiles">
            {selected.profiles.map((profile) => (
              <div className={`profile ${profile.tone}`} key={profile.label}>
                <div className="pfie-row between"><b>{profile.label}</b><strong>{profile.count}</strong></div>
                <p>{profile.description}</p>
                <div>{profile.drivers.map((driver) => <span key={driver}>{driver}</span>)}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function OutcomeChart({
  title, kind, today, onSelect,
}: {
  title: string;
  kind: 'reproduction' | 'movement';
  today?: string;
  onSelect: (label?: string | number) => void;
}) {
  const reproduction = kind === 'reproduction';
  return (
    <section className="pfie-outcome-chart">
      <h3>{title}</h3>
      <ResponsiveContainer width="100%" height={270}>
        <ComposedChart data={HERD_OUTCOMES} margin={{ top: 12, right: 10, left: -12, bottom: 0 }} onClick={(event) => onSelect(event?.activeLabel)}>
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#70827a' }} axisLine={{ stroke: '#e2e9e5' }} tickLine={false} minTickGap={28} />
          <YAxis tick={{ fontSize: 10, fill: '#70827a' }} axisLine={false} tickLine={false} width={30} />
          <Tooltip content={<OutcomeTip kind={kind} />} cursor={{ fill: 'rgba(147,162,155,.12)' }} />
          {reproduction ? (
            <>
              <Bar dataKey="aiSuccess" fill="#1f6b4a" name="AI successful" isAnimationActive={false} />
              <Bar dataKey="aiFailure" fill="#b8860b" name="AI not successful" isAnimationActive={false} />
              <Line dataKey="carriedToTerm" stroke="#5b7fa6" strokeWidth={2} dot={false} name="Carried to term" isAnimationActive={false} />
              <Line dataKey="abortions" stroke="#a44b3c" strokeWidth={2} dot={false} name="Abortions" isAnimationActive={false} />
            </>
          ) : (
            <>
              <Bar dataKey="transfersIn" fill="#1f6b4a" name="Transfers in" isAnimationActive={false} />
              <Bar dataKey="transfersOut" fill="#b8860b" name="Transfers out" isAnimationActive={false} />
              <Bar dataKey="deaths" fill="#a44b3c" name="Deaths" isAnimationActive={false} />
              <Line dataKey="riskPoints" stroke="#5b7fa6" strokeWidth={2} dot={false} name="Risk points" isAnimationActive={false} />
            </>
          )}
          {today && <ReferenceLine x={today} stroke="#1d2b26" strokeWidth={1.5} label={{ value: 'Today', position: 'insideTopLeft', fontSize: 10, fontWeight: 700 }} />}
        </ComposedChart>
      </ResponsiveContainer>
    </section>
  );
}

function OutcomeTip({ active, payload, kind }: { active?: boolean; payload?: { payload?: HerdOutcomePoint }[]; kind: 'reproduction' | 'movement' }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const rows: [string, string][] = kind === 'reproduction'
    ? [
        ['AI services', `${point.aiAttempts}`],
        ['AI successful', `${point.aiSuccess}`],
        ['AI not successful', `${point.aiFailure}`],
        ['Carried to term', `${point.carriedToTerm}`],
        ['Abortions', `${point.abortions}`],
      ]
    : [
        ['Transfers in', `${point.transfersIn}`],
        ['Transfers out', `${point.transfersOut}`],
        ['Deaths', `${point.deaths}`],
        ['Risk points', `${point.riskPoints}`],
        ['Higher-risk profile', `${point.profiles.find((profile) => profile.tone === 'risk')?.count ?? 0} animals`],
      ];
  return <TipShell title={`${point.future ? 'Expected' : 'Recorded'} — ${point.label}`} rows={rows} note={`${point.confidence} confidence. ${point.factors[0]}. Click to open the full reasoning for this chart and point.`} />;
}
