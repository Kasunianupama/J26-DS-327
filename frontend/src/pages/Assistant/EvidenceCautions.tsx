/** Keep essential limitations visible while retaining all supplied technical notes. */
import { t, type Language } from './i18n';
import type { Reply } from './chatTypes';

export function EvidenceCautions({ reply, language }: { reply: Reply; language: Language }) {
  const kind = reply.evidence?.kind;
  const primary = kind === 'c4_risk' ? 'Historical research result. It cannot provide live alerts or confirm causes.' :
    kind === 'c1_forecast' ? 'Development forecast. It has not been checked against your current records.' :
    kind === 'c2_live_simulation' ? 'Model-based what-if estimate. Actual outcomes may differ; feasibility has not been checked.' :
    reply.evidence?.milk_report ? 'Missing measurements are not filled in. Weekly changes are shown only when coverage supports comparison.' : null;
  const evidence = reply.evidence;
  const point = evidence?.forecast, lower = evidence?.lower, upper = evidence?.upper;
  const outside = kind === 'c1_forecast' && typeof point === 'number' &&
    ((typeof lower === 'number' && point < lower) || (typeof upper === 'number' && point > upper));
  if (!primary && !reply.warnings?.length) return null;
  return <div className="c3-limitations"><strong>{t(language,'Keep in mind')}</strong>
    {primary && <p>{t(language,primary)}</p>}
    {outside && <p>{t(language,'The forecast falls outside the supplied range and needs review.')}</p>}
    {!!reply.warnings?.length && (primary ? <details className="c3-technical-notes"><summary>{t(language,'Technical notes')}</summary>
      <ul>{reply.warnings.map((warning,index) => <li key={index}>{warning}</li>)}</ul></details> :
      <ul>{reply.warnings.map((warning,index) => <li key={index}>{warning}</li>)}</ul>)}
  </div>;
}
