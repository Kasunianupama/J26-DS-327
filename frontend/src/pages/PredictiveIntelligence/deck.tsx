/**
 * Component 1 (PFOI): the metric deck above the canvas.
 *
 * The numbers describe the selected grain and horizon. Every forecast tile
 * carries its range and quality, so a number is never shown without the
 * uncertainty that belongs to it.
 */

import {
  GRAIN_LABEL,
  confidenceOf,
  flowTotals,
  isForecast,
  fmt1,
  fmtInt,
  headline,
  lastActual,
  periodLabel,
} from '../../data/pfoi';
import { DeltaChip, KpiStrip, KpiTile } from './ui';
import { usePfoi } from './state';
import { useRun } from './source';

export function MetricDeck() {
  const { grain, horizon, go, openDrawer } = usePfoi();
  const run = useRun();
  const reach = `${horizon} ${horizon === 1 ? GRAIN_LABEL[grain].one : GRAIN_LABEL[grain].many}`;
  const milk = headline(run, grain, horizon, 'milk_litres');
  const milking = headline(run, grain, horizon, 'milking');
  const herd = headline(run, grain, horizon, 'total_herd');
  const mastitis = headline(run, grain, horizon, 'mastitis_episodes');
  const calvings = isForecast(run, grain, 'calvings') ? flowTotals(run, grain, horizon, 'calvings') : null;
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
