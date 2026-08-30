/**
 * Breeding attention list.
 *
 * The likelihood ranking answers "who is most likely to hold if served now?".
 * It cannot answer "who has quietly fallen out of the breeding programme?",
 * because an animal with no recent service has nothing to rank. This panel
 * covers that gap: one group per rule, each stating the threshold it fired on
 * so the rule itself can be argued with.
 */

import { useState } from 'react';
import {
  BREEDING_ALERTS,
  BREEDING_ALERT_SUMMARY,
  SEVERITY_META,
  type BreedingAlertId,
} from '../../../data/component2';
import { useC2 } from '../state';
import { Card, ConfidenceBadge, DelProLink, EmptyState, KpiStrip, KpiTile, Note } from '../ui';
import { Icon } from '../icons';

export function BreedingAlerts() {
  const { openDrawer } = useC2();
  const [open, setOpen] = useState<BreedingAlertId | null>(BREEDING_ALERTS[0]?.id ?? null);

  if (BREEDING_ALERTS.length === 0) {
    return (
      <Card icon="flag" title="Breeding attention" sub="Animals that have fallen out of the breeding programme.">
        <EmptyState title="No animal is currently past a breeding threshold">
          Every milking animal has a service, a check or a confirmed pregnancy within its expected window.
        </EmptyState>
      </Card>
    );
  }

  return (
    <Card
      icon="flag"
      title="Breeding attention"
      sub="Absences rather than rankings: services never recorded, returns never re-served, checks never done. Each group states the day threshold it fired on."
      actions={<DelProLink id="the service record" />}
    >
      <KpiStrip>
        <KpiTile
          icon="herd"
          label="Animals needing a decision"
          value={BREEDING_ALERT_SUMMARY.animals}
          tone={BREEDING_ALERT_SUMMARY.animals > 0 ? 'caution' : 'plain'}
          foot={`Across ${BREEDING_ALERTS.length} rules · an animal can trip more than one`}
        />
        <KpiTile
          icon="trendDown"
          label="On a critical rule"
          value={BREEDING_ALERT_SUMMARY.critical}
          tone={BREEDING_ALERT_SUMMARY.critical > 0 ? 'concern' : 'plain'}
          foot="No service on record, or a return to heat never re-served"
        />
        <KpiTile
          icon="calendar"
          label="Total rule hits"
          value={BREEDING_ALERT_SUMMARY.total}
          foot="Counting every rule an animal trips"
        />
      </KpiStrip>

      <div className="pfie-alertgroups">
        {BREEDING_ALERTS.map((alert) => {
          const sev = SEVERITY_META[alert.severity];
          const expanded = open === alert.id;
          return (
            <section key={alert.id} className={`pfie-alertgroup sev-${alert.severity}${expanded ? ' open' : ''}`}>
              <button
                className="pfie-alertgroup-head"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : alert.id)}
              >
                <span className="count">{alert.animals.length}</span>
                <span className="text">
                  <b style={{ color: sev.color }}>{alert.label}</b>
                  <small>{alert.rule}</small>
                </span>
                <ConfidenceBadge level={alert.confidence} hint={false} />
                <span className="chev" aria-hidden>{expanded ? '⌄' : '›'}</span>
              </button>

              {expanded && (
                <div className="pfie-alertgroup-body">
                  <p className="why"><b>Why it matters.</b> {alert.consequence}</p>
                  <p className="why"><b>What to do.</b> {alert.action}</p>
                  <ul className="pfie-alertchips">
                    {alert.animals.slice(0, 24).map((a) => (
                      <li key={a.id}>
                        <button onClick={() => openDrawer({ kind: 'cow', animalId: a.id })}>
                          <b>{a.id}</b>
                          <span>
                            {a.dim} DIM
                            {a.daysSinceLastAI !== null ? ` · ${a.daysSinceLastAI}d since service` : ' · never served'}
                            {a.aiAttempts > 0 ? ` · ${a.aiAttempts} services` : ''}
                          </span>
                          <Icon name="arrowRight" size={12} />
                        </button>
                      </li>
                    ))}
                  </ul>
                  {alert.animals.length > 24 && (
                    <p className="more">{alert.animals.length - 24} more animals trip this rule.</p>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>

      <Note tone="caution" title="These are thresholds, not diagnoses.">
        Each rule compares a recorded date against a day count. A missing service can be a recording gap rather
        than a missed heat, and the two need different responses — check DelPro before acting on a group.
      </Note>
    </Card>
  );
}
