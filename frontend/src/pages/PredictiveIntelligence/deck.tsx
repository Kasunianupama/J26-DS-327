/**
 * Component 2 — the contextual metric deck.
 *
 * The five numbers above the canvas belong to the workspace you are actually
 * in. Switching to Products & Income should change what the deck measures, not
 * just what is underneath it — otherwise the deck is page furniture rather than
 * a read on the thing being examined.
 */

import { useMemo } from 'react';
import {
  AI_SUMMARY,
  DATA_THROUGH,
  EXPECTED_EXITS,
  FINDINGS,
  GENETICS_SUMMARY,
  HERD_OUTCOMES,
  PRODUCT_CONSTRAINT,
  TODAY,
  fmtInt,
  fmtLKR,
  financeMonth,
  longDate,
  overallOutcomeSummary,
  productMonth,
  structureForDate,
} from '../../data/component2';
import { DeltaChip, KpiStrip, KpiTile } from './ui';
import { horizonSummary } from './summary';
import { useC2, type CapacityTab, type Workspace } from './state';

export function MetricDeck() {
  const {
    workspace, capacityTab, horizon, selectedDate, selectedMonth,
    acknowledged, snoozed, go, setSelectedDate, setSelectedMonth, openDrawer,
  } = useC2();
  const s = useMemo(() => horizonSummary(horizon), [horizon]);

  /* ---------------- Farm Outlook ---------------- */
  if (workspace === 'future') {
    return (
      <KpiStrip className="pfie-deck">
        <KpiTile
          icon="droplet" label="Expected daily milk" value={fmtInt(s.averageDailyMilk)} unit="L/day"
          delta={<DeltaChip value={s.changePct} />}
          spark={s.spark} sparkTone={s.changePct < 0 ? 'concern' : 'brand'}
          foot={`Averaged across the selected ${s.label.toLowerCase()}`}
          onClick={() => { setSelectedDate(s.lowPoint.date); go('capacity', 'milk'); }}
        />
        <KpiTile
          icon="scale" label="Per milking cow" value={s.averagePerCow.toFixed(1)} unit="L/day"
          foot={`${fmtInt(s.last.milkers)} milking animals expected at the end of the range`}
          onClick={() => go('capacity', 'reproduction')}
        />
        <KpiTile
          icon="herd" label="Herd movement" value={`${s.dryOffs} out · ${s.entries} in`}
          tone={s.netMovement < 0 ? 'caution' : 'plain'}
          foot={`Net ${s.netMovement >= 0 ? '+' : ''}${s.netMovement} milking animals over the range`}
          onClick={() => go('capacity', 'outcomes')}
        />
        <KpiTile
          icon="calendar" label="Lowest expected point" value={longDate(s.lowPoint.date)} tone="pred"
          foot={`${fmtInt(s.lowPoint.expected ?? 0)} L/day · ${s.lowPoint.confidence.toLowerCase()} confidence`}
          onClick={() => openDrawer({ kind: 'structure', date: s.lowPoint.date, domain: 'herd' })}
        />
        <KpiTile
          icon="wallet" label="Margin vs budget" value={fmtLKR(s.marginGap)}
          tone={s.marginGap < 0 ? 'concern' : 'brand'}
          foot={`Expected ${s.finance?.label ?? 'period-end'} margin against plan`}
          onClick={() => { setSelectedMonth(s.endMonth); go('commerce'); }}
        />
      </KpiStrip>
    );
  }

  /* ---------------- Herd & Production ---------------- */
  if (workspace === 'capacity') return <CapacityDeck tab={capacityTab} />;

  /* ---------------- Products & Income ---------------- */
  if (workspace === 'commerce') {
    const product = productMonth(selectedMonth);
    const finance = financeMonth(selectedMonth);
    const allocated = product
      ? Object.values(product.allocation).reduce((sum, litres) => sum + litres, 0)
      : 0;
    const shortfall = product?.shortfall['Tetra pack'] ?? 0;
    const marginGap = finance ? (finance.marginForecast ?? finance.margin ?? 0) - finance.budgetMargin : 0;
    const revenue = finance?.revenueForecast ?? finance?.revenue ?? 0;
    const revenueGap = revenue - (finance?.budgetRevenue ?? 0);

    return (
      <KpiStrip className="pfie-deck">
        <KpiTile
          icon="droplet" label={`Expected milk · ${product?.label ?? selectedMonth}`}
          value={fmtInt(product?.milk ?? 0)} unit="L"
          foot="Total supply available to allocate in this month"
        />
        <KpiTile
          icon="products" label="Allocated to product" value={fmtInt(allocated)} unit="L"
          foot="Raw-milk contract is filled first, then the packing line"
        />
        <KpiTile
          icon="wallet" label="Expected revenue" value={fmtLKR(revenue)} tone="brand"
          delta={finance ? <DeltaChip value={(revenueGap / Math.max(1, finance.budgetRevenue)) * 100} /> : undefined}
          foot="Derived from the allocation, not forecast separately"
        />
        <KpiTile
          icon="trendDown" label="Tetra-pack shortfall"
          value={shortfall ? `−${fmtInt(shortfall)}` : 'Within plan'} unit={shortfall ? 'L' : undefined}
          tone={shortfall ? 'concern' : 'plain'}
          foot={PRODUCT_CONSTRAINT
            ? `Worst week ${longDate(PRODUCT_CONSTRAINT.worstWeek)} · ${PRODUCT_CONSTRAINT.weeksAffected} weeks affected`
            : 'All product lines stay within the planned allocation'}
          onClick={() => openDrawer({ kind: 'product', product: 'Tetra pack' })}
        />
        <KpiTile
          icon="scale" label="Margin vs budget" value={fmtLKR(marginGap)}
          tone={marginGap < 0 ? 'concern' : 'brand'}
          foot={`Expected ${finance?.label ?? 'month'} margin against plan`}
        />
      </KpiStrip>
    );
  }

  /* ---------------- Forecast Confidence ---------------- */
  if (workspace === 'evidence') {
    const structure = structureForDate(selectedDate);
    const ev = structure.evidence;
    const limitedDays = s.points.filter((p) => p.confidence === 'Limited').length;
    const lagDays = Math.round((TODAY.getTime() - DATA_THROUGH.getTime()) / 86_400_000);

    return (
      <KpiStrip className="pfie-deck">
        <KpiTile
          icon="confidence" label="Forecast confidence" value={s.confidence}
          tone={s.confidence === 'High' ? 'brand' : s.confidence === 'Moderate' ? 'caution' : 'concern'}
          foot={`Weakest level found across the selected ${s.label.toLowerCase()}`}
        />
        <KpiTile
          icon="spark" label="Individual evidence" value={Math.round(ev.individualShare)} unit="%"
          foot="Share built from the animals' own recorded history"
        />
        <KpiTile
          icon="herd" label="Peer-derived" value={Math.round(ev.peerShare)} unit="%"
          tone="pred" foot="Share inferred from comparable animals instead"
        />
        <KpiTile
          icon="trendUp" label="Transition dependency" value={Math.round(ev.transitionDependency)} unit="%"
          tone={ev.transitionDependency > 20 ? 'caution' : 'plain'}
          foot="Depends on calvings and dry-offs that have not happened yet"
        />
        <KpiTile
          icon="calendar" label="Limited-confidence days" value={limitedDays}
          tone={limitedDays > 0 ? 'concern' : 'plain'}
          foot={`Data is ${lagDays} day${lagDays === 1 ? '' : 's'} behind today`}
        />
      </KpiStrip>
    );
  }

  /* ---------------- Daily Operations ---------------- */
  const open = FINDINGS.filter((f) => !acknowledged.has(f.id) && !snoozed.has(f.id));
  const critical = open.filter((f) => f.severity === 'critical').length;
  const attention = open.filter((f) => f.severity === 'attention').length;
  const lagDays = Math.round((TODAY.getTime() - DATA_THROUGH.getTime()) / 86_400_000);

  return (
    <KpiStrip className="pfie-deck">
      <KpiTile icon="flag" label="Open findings" value={open.length}
        tone={open.length > 0 ? 'caution' : 'plain'} foot="Outstanding across every workspace" />
      <KpiTile icon="trendDown" label="Critical" value={critical}
        tone={critical > 0 ? 'concern' : 'plain'} foot="Severity that changes a plan, not just a number" />
      <KpiTile icon="confidence" label="Needs attention" value={attention}
        foot="Worth a look this week" />
      <KpiTile icon="operations" label="Acknowledged" value={acknowledged.size}
        tone="brand" foot={`${snoozed.size} snoozed for later`} />
      <KpiTile icon="calendar" label="Data freshness" value={lagDays} unit={lagDays === 1 ? 'day' : 'days'}
        foot={`Recorded data runs through ${longDate(DATA_THROUGH.toISOString().slice(0, 10))}`} />
    </KpiStrip>
  );
}

/* ------------------------------------------------------------------ */

function CapacityDeck({ tab }: { tab: CapacityTab }) {
  const { horizon, selectedMonth, go, openDrawer } = useC2();
  const s = useMemo(() => horizonSummary(horizon), [horizon]);

  if (tab === 'reproduction') {
    return (
      <KpiStrip className="pfie-deck">
        <KpiTile icon="herd" label="Milking head at range end" value={fmtInt(s.last.milkers)}
          foot={`${fmtInt(s.first.milkers)} today · net ${s.netMovement >= 0 ? '+' : ''}${s.netMovement} over the range`} />
        <KpiTile icon="spark" label="AI success rate" value={AI_SUMMARY.successRate} unit="%"
          tone={AI_SUMMARY.successRate < AI_SUMMARY.peerBaseline ? 'caution' : 'brand'}
          delta={<DeltaChip value={AI_SUMMARY.successRate - AI_SUMMARY.peerBaseline} unit=" pts" />}
          foot={`Against a peer baseline of ${AI_SUMMARY.peerBaseline}%`} />
        <KpiTile icon="scale" label="Services per conception" value={AI_SUMMARY.servicesPerConception.toFixed(2)}
          foot={`${AI_SUMMARY.services} services across ${AI_SUMMARY.servedAnimals} served animals`} />
        <KpiTile icon="trendUp" label="Expected lactation entries" value={s.entries} tone="brand"
          foot={`Across the selected ${s.label.toLowerCase()}`} />
        <KpiTile icon="trendDown" label="Expected dry-offs" value={s.dryOffs} tone="caution"
          foot={`Plus ${EXPECTED_EXITS.culls90} culls and ${EXPECTED_EXITS.mortality90} mortalities over 90 days`} />
      </KpiStrip>
    );
  }

  if (tab === 'outcomes') {
    const future = HERD_OUTCOMES.filter((point) => point.future).slice(0, 6);
    const deaths = future.reduce((sum, p) => sum + p.deaths, 0);
    const abortions = future.reduce((sum, p) => sum + p.abortions, 0);
    const toTerm = future.reduce((sum, p) => sum + p.carriedToTerm, 0);
    const exitsOut = future.reduce((sum, p) => sum + p.transfersOut, 0);
    const highRisk = future[0]?.profiles.find((p) => p.tone === 'risk')?.count ?? 0;

    return (
      <KpiStrip className="pfie-deck">
        <KpiTile icon="confidence" label="High-risk animals" value={highRisk} tone="concern"
          foot="Repeat breeders, no service on record, or three-plus health events" />
        <KpiTile icon="trendDown" label="Recorded abortion rate" value={overallOutcomeSummary.recordedAbortionRate} unit="%"
          foot="Across every recorded pregnancy outcome to date" />
        <KpiTile icon="herd" label="Expected to carry to term" value={toTerm} tone="brand"
          foot={`Against ${abortions} expected losses over the next six months`} />
        <KpiTile icon="operations" label="Expected exits" value={exitsOut + deaths}
          tone={exitsOut + deaths > 0 ? 'caution' : 'plain'}
          foot={`${exitsOut} transfers or sales and ${deaths} mortalities over six months`} />
        <KpiTile icon="calendar" label="Forecast confidence" value={s.confidence}
          tone={s.confidence === 'High' ? 'brand' : s.confidence === 'Moderate' ? 'caution' : 'concern'}
          foot="Individual outcome prediction stays withheld at this evidence level" />
      </KpiStrip>
    );
  }

  if (tab === 'genetics') {
    const ranked = [...GENETICS_SUMMARY].sort((a, b) => b.animals - a.animals);
    const largest = ranked[0];
    const unknown = GENETICS_SUMMARY.find((g) => g.group === 'Unknown parentage');
    const milkers = GENETICS_SUMMARY.reduce((sum, g) => sum + g.milkers, 0);
    const avgPeak =
      GENETICS_SUMMARY.reduce((sum, g) => sum + g.avgPeak * g.milkers, 0) / Math.max(1, milkers);

    return (
      <KpiStrip className="pfie-deck">
        <KpiTile icon="herd" label="Genetic groups tracked" value={GENETICS_SUMMARY.length}
          foot="Founder imports through to unknown parentage" />
        <KpiTile icon="spark" label="Largest group" value={largest.group.split(' ')[0]} tone="brand"
          foot={`${largest.animals} animals · ${largest.share}% of the herd`} />
        <KpiTile icon="droplet" label="Average peak yield" value={avgPeak.toFixed(1)} unit="L/day"
          foot={`Weighted across ${milkers} milking animals`} />
        <KpiTile icon="products" label="Milk share · largest group" value={largest.milkShare} unit="%"
          foot="Share of expected 90-day contribution" />
        <KpiTile icon="confidence" label="Unknown parentage" value={unknown?.animals ?? 0}
          tone={(unknown?.animals ?? 0) > 0 ? 'caution' : 'plain'}
          foot="Lineage inference falls back to peer groups for these animals" />
      </KpiStrip>
    );
  }

  /* milk supply */
  return (
    <KpiStrip className="pfie-deck">
      <KpiTile icon="droplet" label="Expected daily milk" value={fmtInt(s.averageDailyMilk)} unit="L/day"
        delta={<DeltaChip value={s.changePct} />}
        spark={s.spark} sparkTone={s.changePct < 0 ? 'concern' : 'brand'}
        foot={`Averaged across the selected ${s.label.toLowerCase()}`} />
      <KpiTile icon="scale" label="Per milking cow" value={s.averagePerCow.toFixed(1)} unit="L/day"
        foot="Expected yield per milking animal per day" />
      <KpiTile icon="herd" label="Milking head at range end" value={fmtInt(s.last.milkers)}
        foot={`${fmtInt(s.first.milkers)} today · net ${s.netMovement >= 0 ? '+' : ''}${s.netMovement} over the range`} />
      <KpiTile icon="trendDown" label="Expected dry-offs" value={s.dryOffs} tone="caution"
        foot={`Offset by ${s.entries} expected lactation entries`} />
      <KpiTile icon="calendar" label="Lowest expected point" value={longDate(s.lowPoint.date)} tone="pred"
        foot={`${fmtInt(s.lowPoint.expected ?? 0)} L/day · ${s.lowPoint.confidence.toLowerCase()} confidence`}
        onClick={() => openDrawer({ kind: 'structure', date: s.lowPoint.date, domain: 'herd' })} />
    </KpiStrip>
  );
}

/* ------------------------------------------------------------------ */

/** Findings that actually point into the workspace you are looking at. */
export function signalsFor(workspace: Workspace, acknowledged: Set<string>, snoozed: Set<string>) {
  const rank: Record<string, number> = { critical: 0, attention: 1, routine: 2 };
  const open = FINDINGS.filter((f) => !acknowledged.has(f.id) && !snoozed.has(f.id));
  const scoped = workspace === 'future'
    ? open
    : open.filter((f) => f.links.some((l) => l.workspace === workspace));
  return (scoped.length > 0 ? scoped : open)
    .slice()
    .sort((a, b) => rank[a.severity] - rank[b.severity])
    .slice(0, 3);
}
