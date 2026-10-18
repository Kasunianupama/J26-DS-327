/**
 * Component 1 (PFOI): the metric deck above the canvas.
 *
 * The numbers describe the selected grain and horizon. Every forecast tile
 * carries its range and quality, so a number is never shown without the
 * uncertainty that belongs to it.
 */

import {
  GRAIN_LABEL,
  MODEL_LABEL,
  confidenceOf,
  flowTotals,
  fmt1,
  fmtInt,
  fmtPct,
  headline,
  lastActual,
  periodLabel,
  type BenchmarkModel,
} from '../../data/pfoi';
import { DeltaChip, KpiStrip, KpiTile } from './ui';
import { usePfoi } from './state';
import { useRun } from './source';

export function MetricDeck() {
  const { workspace } = usePfoi();
  return workspace === 'confidence' ? <ConfidenceDeck /> : <OutlookDeck />;
}

function OutlookDeck() {
  const { grain, horizon, go, openDrawer } = usePfoi();
  const run = useRun();
  const reach = `${horizon} ${horizon === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many}`;
  const milk = headline(run, grain, horizon, 'milk_litres');
  const milking = headline(run, grain, horizon, 'milking');
  const herd = headline(run, grain, horizon, 'total_herd');
  const mastitis = headline(run, grain, horizon, 'mastitis_episodes');
  const calvings = grain === 'day' ? null : flowTotals(run, grain, horizon, 'calvings');
  const dailyOnly = (label: string) => {
    const last = lastActual(run, 'week', label === 'Milking cows' ? 'milking' : 'total_herd');
    return last ? `Not forecast daily · last week ${fmtInt(last.value)} head` : 'Not forecast at daily grain';
  };

  return (
    <KpiStrip className="pfie-deck">
      <KpiTile
        icon="droplet"
        label={`Milk in ${milk ? periodLabel(milk.period, grain) : '—'}`}
        value={milk ? fmtInt(milk.value) : '—'}
        unit="L/day"
        delta={milk?.changePct != null ? <DeltaChip value={milk.changePct} /> : undefined}
        spark={milk?.path}
        sparkTone={milk && (milk.changePct ?? 0) < 0 ? 'concern' : 'brand'}
        foot={milk ? `Range ${fmtInt(milk.lower)}–${fmtInt(milk.upper)} · ${confidenceOf(milk.quality).toLowerCase()} confidence` : undefined}
        onClick={milk ? () => openDrawer({ kind: 'point', period: milk.period, grain }) : undefined}
      />
      <KpiTile
        icon="herd"
        label="Milking cows"
        value={milking ? fmtInt(milking.value) : '—'}
        unit={milking ? 'head' : undefined}
        delta={milking?.changePct != null ? <DeltaChip value={milking.changePct} /> : undefined}
        foot={milking ? `Range ${fmtInt(milking.lower)}–${fmtInt(milking.upper)} · daily average` : dailyOnly('Milking cows')}
        onClick={() => go('herd', 'flow')}
      />
      <KpiTile
        icon="scale"
        label="Total herd"
        value={herd ? fmtInt(herd.value) : '—'}
        unit={herd ? 'head' : undefined}
        delta={herd?.changePct != null ? <DeltaChip value={herd.changePct} /> : undefined}
        foot={herd ? `Range ${fmtInt(herd.lower)}–${fmtInt(herd.upper)}` : dailyOnly('Total herd')}
        onClick={() => go('herd', 'flow')}
      />
      <KpiTile
        icon="calendar"
        label={`Calvings over ${reach}`}
        value={calvings ? fmtInt(calvings.total) : '—'}
        tone="pred"
        foot={calvings && calvings.total > 0
          ? `${Math.round((calvings.determined / calvings.total) * 100)}% already determined by recorded conceptions`
          : 'Herd events are forecast weekly and monthly'}
        onClick={() => go('herd', 'events')}
      />
      <KpiTile
        icon="flag"
        label={`Mastitis episodes over ${reach}`}
        value={mastitis ? fmt1(mastitis.pathTotal) : '—'}
        tone="caution"
        foot={mastitis ? `Expected = cows at risk × rate from ${run.mastitis_rate_period}` : 'Mastitis is forecast weekly and monthly'}
        onClick={() => go('herd', 'events')}
      />
    </KpiStrip>
  );
}

function ConfidenceDeck() {
  const { grain, horizon } = usePfoi();
  const run = useRun();
  const rows = run.backtest.filter((r) => r.block === 'development' && r.grain === grain && r.horizon === horizon && r.series === 'milk_litres');
  const pfoi = rows.find((r) => r.model === 'pfoi');
  const best = rows.filter((r) => r.model !== 'pfoi').sort((a, b) => a.mae - b.mae)[0];
  const milk = headline(run, grain, horizon, 'milk_litres');
  const recent = run.coverage[run.coverage.length - 1];
  const skill = pfoi && best ? (1 - pfoi.mae / best.mae) * 100 : null;

  return (
    <KpiStrip className="pfie-deck">
      <KpiTile
        icon="confidence"
        label="Milk MAE · development block"
        value={pfoi ? fmtInt(pfoi.mae) : '—'}
        unit="L/day"
        foot={pfoi ? `${horizon}${GRAIN_LABEL[grain].short} ahead · ${pfoi.n_origins} origins` : 'No backtest at this horizon'}
      />
      <KpiTile
        icon="scale"
        label="Against the best benchmark"
        value={skill !== null ? `${skill >= 0 ? '' : '−'}${Math.abs(skill).toFixed(1)}%` : '—'}
        tone={skill !== null && skill < 0 ? 'concern' : 'brand'}
        foot={best ? `Error reduction vs ${MODEL_LABEL[best.model as BenchmarkModel]} (MAE ${fmtInt(best.mae)})` : undefined}
      />
      <KpiTile
        icon="outlook"
        label="Interval coverage"
        value={pfoi?.coverage != null ? fmtPct(pfoi.coverage, 0) : '—'}
        tone={pfoi?.coverage != null && pfoi.coverage < 0.85 ? 'caution' : 'plain'}
        foot="Share of actuals inside the 5–95% range; the target is 90%"
      />
      <KpiTile
        icon="flag"
        label="Quality at this horizon"
        value={milk ? confidenceOf(milk.quality) : '—'}
        tone="pred"
        foot="From record completeness and horizon length"
      />
      <KpiTile
        icon="calendar"
        label={`Reliable cow-days · ${recent?.year ?? '—'}`}
        value={recent ? fmtInt(recent.reliable_cow_days) : '—'}
        foot="Per-cow records available to check the lactation curves"
      />
    </KpiStrip>
  );
}
