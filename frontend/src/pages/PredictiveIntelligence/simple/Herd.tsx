/**
 * Simple view, "Herd movement" tab: the herd movement picture (as in the
 * detailed view), the groups now and at the end of the look ahead, and the
 * animals moving in and out. Follows the Daily / Weekly / Monthly switch.
 */

import { EVENT_SERIES, flowTotals, headline, isForecast, lastActual, type SeriesId } from '../../../data/pfoi';
import { useRun } from '../source';
import { usePfoi } from '../state';
import { HerdMovement } from '../panels/HerdMovement';
import { aheadText, periodText, useLang, useT } from './i18n';
import { Box, Explain, NotInRun, PLAIN_SERIES, SimpleTable, about, hasRange, pct, whole } from './common';

const GROUPS: SeriesId[] = ['milking', 'dry', 'heifers', 'calves', 'other', 'total_herd'];

export function HerdTab() {
  const t = useT();
  return (
    <>
      <div className="pfie-mgr-movement">
        <HerdMovement />
        <Explain title={t('How to read this picture')}>{t('Each circle is a group of animals; the number is how many are in it. Arrows show animals moving between groups: calves growing into heifers, heifers calving and starting to milk, cows dried off, and animals born, bought, sold, culled or dying. Press Play to watch it move.')}
        </Explain>
      </div>
      <NowAndLater />
      <MovesAhead />
    </>
  );
}

function NowAndLater() {
  const run = useRun();
  const t = useT();
  const { lang } = useLang();
  const { grain, horizon } = usePfoi();
  if (!isForecast(run, grain, 'milking')) return <Box title={t('Herd groups: now and later')}><NotInRun /></Box>;
  const target = headline(run, grain, horizon, 'milking')?.period;
  const base = lastActual(run, grain, 'milking')?.period;
  return (
    <Box title={`${t('Herd groups: now and later')}`}>
      <SimpleTable
        head={[t('Group'), base ? periodText(base, grain, lang) : t('Now'), target ? periodText(target, grain, lang) : t('Later'), t('Likely range'), t('Change')]}
        rows={GROUPS.map((s) => {
          const now = lastActual(run, grain, s);
          const h = headline(run, grain, horizon, s);
          const d = now && h ? Math.round(h.value - now.value) : null;
          return [
            s === 'total_herd' ? <b>{t(PLAIN_SERIES[s])}</b> : t(PLAIN_SERIES[s]),
            now ? whole(now.value) : '—',
            <b>{h ? whole(h.value) : '—'}</b>,
            h && hasRange(h.lower, h.upper) ? `${whole(h.lower)} – ${whole(h.upper)}` : '—',
            d === null ? '—' : <span className={d > 0 ? 'up' : d < 0 ? 'down' : ''}>{d > 0 ? '▲ +' : d < 0 ? '▼ −' : ''}{whole(Math.abs(d))}</span>,
          ];
        })}
      />
    </Box>
  );
}

function MovesAhead() {
  const run = useRun();
  const t = useT();
  const { grain, horizon } = usePfoi();
  if (!isForecast(run, grain, 'calvings')) return null;
  return (
    <Box title={`${t('Animals moving in and out')} · ${aheadText(t, grain, horizon)}`}>
      <SimpleTable
        head={[t('Move'), t('Expected'), t('Already known')]}
        rows={EVENT_SERIES.map((s) => {
          const x = flowTotals(run, grain, horizon, s);
          return [<b>{t(PLAIN_SERIES[s])}</b>, about(x.total), x.total ? pct(x.determined / x.total) : '—'];
        })}
      />
    </Box>
  );
}
