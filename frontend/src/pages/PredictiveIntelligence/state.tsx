/**
 * Component 2 — shared workspace state.
 *
 * Selections (date, month, cow, cohort, horizon) live here so that moving
 * between workspaces keeps context: pick October in Future, open Products &
 * Finance, and October is still selected.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { FARMS, HARD_MINIMUM_DAYS, TODAY_ISO, type FarmId, type HorizonId } from '../../data/component2';

export type Workspace = 'future' | 'capacity' | 'commerce' | 'evidence' | 'operations';
export type CapacityTab = 'milk' | 'reproduction' | 'outcomes' | 'genetics';
export type Grain = 'day' | 'week' | 'month';
export type ForecastDomain = 'herd' | 'repro' | 'products' | 'finance';
export type OutcomeChart = 'reproduction' | 'movement';

/** Anything that can occupy the right-hand detail drawer. */
export type DrawerState =
  | { kind: 'none' }
  | { kind: 'cow'; animalId: string }
  | { kind: 'cohort'; groupKey: string; value: string }
  | { kind: 'structure'; date: string; domain: ForecastDomain }
  | { kind: 'outcome'; date: string; chart: OutcomeChart }
  | { kind: 'flow-stage'; stageId: string }
  | { kind: 'product'; product: string }
  | { kind: 'findings' };

interface Ctx {
  farm: FarmId;
  setFarm: (f: FarmId) => void;
  horizon: HorizonId;
  setHorizon: (h: HorizonId) => void;
  workspace: Workspace;
  capacityTab: CapacityTab;
  go: (w: Workspace, tab?: CapacityTab) => void;

  /** Locked date on the master timeline, shared across every workspace. */
  selectedDate: string;
  setSelectedDate: (d: string) => void;
  /** Second date, used by the milk-change waterfall. */
  compareDate: string | null;
  setCompareDate: (d: string | null) => void;
  selectedMonth: string;
  setSelectedMonth: (m: string) => void;

  search: string;
  setSearch: (s: string) => void;

  /** The open detail view. Backed by history, so Back closes it. */
  drawer: DrawerState;
  /** How many detail views are stacked on top of the workspace. */
  detailDepth: number;
  openDrawer: (d: DrawerState) => void;
  /** Step back one detail view. */
  popDrawer: () => void;
  /** Leave every stacked detail view and return to the workspace. */
  closeDrawer: () => void;

  acknowledged: Set<string>;
  snoozed: Set<string>;
  acknowledge: (id: string) => void;
  snooze: (id: string) => void;
  restoreFindings: () => void;

  /** Timeline granularity — drives the master timeline and the scrub step. */
  grain: Grain;
  setGrain: (g: Grain) => void;
  playing: boolean;
  setPlaying: (v: boolean) => void;
  speed: number;
  setSpeed: (v: number) => void;

  /**
   * Planned rest windows the user has set on the dry-off plan, in days, keyed
   * by animal id. Prototype-local — Component 2 proposes, DelPro records.
   */
  dryRest: Record<string, number>;
  setDryRest: (animalId: string, days: number) => void;
  clearDryRest: (animalId: string) => void;

  replayOn: boolean;
  setReplayOn: (v: boolean) => void;
  replayVintage: string;
  setReplayVintage: (v: string) => void;
}

const C2Context = createContext<Ctx | undefined>(undefined);

export function C2Provider({ children }: { children: ReactNode }) {
  const [farm, setFarm] = useState<FarmId>(FARMS[0].id);
  const [horizon, setHorizon] = useState<HorizonId>('90d');
  const [workspace, setWorkspace] = useState<Workspace>('future');
  const [capacityTab, setCapacityTab] = useState<CapacityTab>('milk');
  const [selectedDate, setSelectedDate] = useState<string>(TODAY_ISO);
  const [compareDate, setCompareDate] = useState<string | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<string>('2026-10');
  const [search, setSearch] = useState('');
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());
  const [snoozed, setSnoozed] = useState<Set<string>>(new Set());
  const [grain, setGrain] = useState<Grain>('month');
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [dryRest, setDryRestState] = useState<Record<string, number>>({});
  const [replayOn, setReplayOn] = useState(false);
  const [replayVintage, setReplayVintage] = useState('2026-08-01');

  /* Detail views live in history rather than in component state. Opening one
     pushes an entry, so the browser Back button and the in-page Back control
     are the same gesture, and a deep link back out never strands the user. */
  const navigate = useNavigate();
  const location = useLocation();
  const histState = (location.state ?? null) as { c2detail?: DrawerState; c2depth?: number } | null;
  const drawer: DrawerState = histState?.c2detail ?? { kind: 'none' };
  const detailDepth = histState?.c2depth ?? 0;

  const openDrawer = useCallback((d: DrawerState) => {
    setPlaying(false);
    /* A detail view is a real address, so the URL, the browser Back button and
       the in-page Back control all agree on where the user is. */
    navigate(`/predictive/detail/${d.kind}`, {
      state: { ...(histState ?? {}), c2detail: d, c2depth: detailDepth + 1 },
    });
  }, [navigate, histState, detailDepth]);

  const popDrawer = useCallback(() => {
    if (detailDepth > 0) navigate(-1);
  }, [navigate, detailDepth]);

  const closeDrawer = useCallback(() => {
    if (detailDepth > 0) navigate(-detailDepth);
    else navigate('/predictive', { replace: true, state: { ...(histState ?? {}), c2detail: undefined, c2depth: 0 } });
  }, [navigate, histState, detailDepth]);

  /* The hard minimum is a floor the interface never lets the user cross. */
  const setDryRest = useCallback((animalId: string, days: number) => {
    setDryRestState((current) => ({ ...current, [animalId]: Math.max(HARD_MINIMUM_DAYS, Math.round(days)) }));
  }, []);
  const clearDryRest = useCallback((animalId: string) => {
    setDryRestState((current) => {
      const next = { ...current };
      delete next[animalId];
      return next;
    });
  }, []);

  const go = useCallback((w: Workspace, tab?: CapacityTab) => {
    setWorkspace(w);
    if (tab) setCapacityTab(tab);
  }, []);

  /** Selecting a date keeps the month in step, so finance follows the timeline. */
  const selectDate = useCallback((d: string) => {
    setSelectedDate(d);
    setSelectedMonth(d.slice(0, 7));
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      farm, setFarm,
      horizon, setHorizon,
      workspace, capacityTab, go,
      selectedDate, setSelectedDate: selectDate,
      compareDate, setCompareDate,
      selectedMonth, setSelectedMonth,
      search, setSearch,
      grain, setGrain,
      playing, setPlaying,
      speed, setSpeed,
      drawer, detailDepth, openDrawer, popDrawer, closeDrawer,
      acknowledged, snoozed,
      acknowledge: (id) => setAcknowledged((s) => new Set(s).add(id)),
      snooze: (id) => setSnoozed((s) => new Set(s).add(id)),
      restoreFindings: () => { setAcknowledged(new Set()); setSnoozed(new Set()); },
      dryRest, setDryRest, clearDryRest,
      replayOn, setReplayOn,
      replayVintage, setReplayVintage,
    }),
    [farm, horizon, workspace, capacityTab, go, selectedDate, selectDate, compareDate,
     selectedMonth, search, drawer, detailDepth, openDrawer, popDrawer, closeDrawer,
     acknowledged, snoozed, replayOn, replayVintage, grain, playing, speed,
     dryRest, setDryRest, clearDryRest],
  );

  return <C2Context.Provider value={value}>{children}</C2Context.Provider>;
}

export function useC2() {
  const c = useContext(C2Context);
  if (!c) throw new Error('useC2 must be used inside C2Provider');
  return c;
}
