/**
 * Simple view: the reasons milk changes from one month to the next, biggest
 * first, as bars pulling down (left) or pushing up (right). Same attribution
 * parts as the detailed view's contribution chart, in English or Sinhala.
 */

import { fmtInt, type Factor } from '../../../data/pfoi';
import { PLAIN_FACTOR } from '../panels/ContributionChart';
import { Rich, useT } from './i18n';

const NO_EFFECT = 0.5;

export function Reasons({ parts, start, end, fromLabel, toLabel, isPast }: {
  parts: { factor: Factor; value: number }[]; start: number; end: number; fromLabel: string; toLabel: string; isPast: boolean;
}) {
  const t = useT();
  const shown = parts.filter((p) => Math.abs(p.value) >= NO_EFFECT).sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  const max = Math.max(1, ...shown.map((p) => Math.abs(p.value)));
  const change = end - start;
  const key = isPast
    ? (change >= 0 ? 'Milk rose from **{a} L** a day in {from} to **{b} L** in {to}.' : 'Milk fell from **{a} L** a day in {from} to **{b} L** in {to}.')
    : (change >= 0 ? 'Milk is expected to rise from **{a} L** a day in {from} to **{b} L** in {to}.' : 'Milk is expected to fall from **{a} L** a day in {from} to **{b} L** in {to}.');

  return (
    <div className="pfie-mgr-reasons">
      <p className="pfie-mgr-lead"><Rich text={t(key, { a: fmtInt(start), b: fmtInt(end), from: fromLabel, to: toLabel })} /></p>
      <div className="pfie-mgr-reasons-axis" aria-hidden><span>◀ {t('pulls milk down')}</span><span>{t('pushes milk up')} ▶</span></div>
      <ul>
        {shown.map((p) => {
          const m = PLAIN_FACTOR[p.factor];
          const up = p.value >= 0;
          const w = `${(Math.abs(p.value) / max) * 50}%`;
          return (
            <li key={p.factor}>
              <div className="txt">
                <b>{m ? t(up ? m.up : m.down) : p.factor}</b>
                {m && <small>{t(m.why)}</small>}
              </div>
              <div className="bar">
                <i className={up ? 'up' : 'down'} style={up ? { left: '50%', width: w } : { right: '50%', width: w }} />
              </div>
              <span className={`v ${up ? 'up' : 'down'}`}>{up ? '+' : '−'}{fmtInt(Math.abs(p.value))} L</span>
            </li>
          );
        })}
      </ul>
      {!shown.length && <p className="pfie-mgr-note">{t('Almost no change.')}</p>}
    </div>
  );
}
