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
import { FARMS, TODAY_ISO, type FarmId, type HorizonId } from '../../data/component2';

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

  drawer: DrawerState;
  openDrawer: (d: DrawerState) => void;
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
  const [drawer, setDrawer] = useState<DrawerState>({ kind: 'none' });
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());
  const [snoozed, setSnoozed] = useState<Set<string>>(new Set());
  const [grain, setGrain] = useState<Grain>('month');
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [replayOn, setReplayOn] = useState(false);
  const [replayVintage, setReplayVintage] = useState('2026-08-01');

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
      drawer,
      openDrawer: (d: DrawerState) => { setPlaying(false); setDrawer(d); },
      closeDrawer: () => setDrawer({ kind: 'none' }),
      acknowledged, snoozed,
      acknowledge: (id) => setAcknowledged((s) => new Set(s).add(id)),
      snooze: (id) => setSnoozed((s) => new Set(s).add(id)),
      restoreFindings: () => { setAcknowledged(new Set()); setSnoozed(new Set()); },
      replayOn, setReplayOn,
      replayVintage, setReplayVintage,
    }),
    [farm, horizon, workspace, capacityTab, go, selectedDate, selectDate, compareDate,
     selectedMonth, search, drawer, acknowledged, snoozed, replayOn, replayVintage,
     grain, playing, speed],
  );

  return <C2Context.Provider value={value}>{children}</C2Context.Provider>;
}

export function useC2() {
  const c = useContext(C2Context);
  if (!c) throw new Error('useC2 must be used inside C2Provider');
  return c;
}
