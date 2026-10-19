/**
 * Component 1 (PFOI): shared page state.
 *
 * Grain, horizon and the selected period live here so moving between
 * workspaces keeps context: pick a month on the timeline, open the milk
 * breakdown, and the same month is still selected.
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
import { HORIZONS, type Grain, type HerdTab, type Workspace } from '../../data/pfoi';

export type { HerdTab, Workspace };

/** Anything that can occupy the full-page detail view. */
export type DrawerState =
  | { kind: 'none' }
  | { kind: 'point'; period: string; grain: Grain }
  | { kind: 'findings' };

interface Ctx {
  grain: Grain;
  setGrain: (g: Grain) => void;
  horizon: number;
  setHorizon: (h: number) => void;
  /** Show recorded history from this date (null = all recorded history). Kept across grains. */
  historyFrom: string | null;
  setHistoryFrom: (d: string | null) => void;
  workspace: Workspace;
  herdTab: HerdTab;
  go: (w: Workspace, tab?: HerdTab) => void;

  /** Period selected on the timeline (start date at the current grain), or null for the horizon target. */
  selectedPeriod: string | null;
  setSelectedPeriod: (p: string | null) => void;
  /** Month shown in the milk waterfall. */
  breakdownMonth: string | null;
  setBreakdownMonth: (m: string | null) => void;

  drawer: DrawerState;
  detailDepth: number;
  openDrawer: (d: DrawerState) => void;
  popDrawer: () => void;
  closeDrawer: () => void;

  acknowledged: Set<string>;
  acknowledge: (id: string) => void;
  restoreFindings: () => void;
}

const PfoiContext = createContext<Ctx | undefined>(undefined);

export function PfoiProvider({ children }: { children: ReactNode }) {
  const [grain, setGrainState] = useState<Grain>('month');
  const [horizon, setHorizon] = useState<number>(6);
  const [historyFrom, setHistoryFrom] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>('outlook');
  const [herdTab, setHerdTab] = useState<HerdTab>('milk');
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [breakdownMonth, setBreakdownMonth] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());

  /* Changing grain keeps the horizon's reach roughly the same, but always on a
     horizon the model actually publishes for that grain. */
  const setGrain = useCallback((g: Grain) => {
    setGrainState(g);
    setSelectedPeriod(null);
    setHorizon((h) => {
      const options = HORIZONS[g];
      return options.includes(h) ? h : options[Math.min(options.length - 1, Math.floor(options.length / 2))];
    });
  }, []);

  /* Detail views live in history: the browser Back button and the in-page
     Back control are the same gesture. */
  const navigate = useNavigate();
  const location = useLocation();
  const histState = (location.state ?? null) as { pfoiDetail?: DrawerState; pfoiDepth?: number } | null;
  const drawer: DrawerState = histState?.pfoiDetail ?? { kind: 'none' };
  const detailDepth = histState?.pfoiDepth ?? 0;

  const openDrawer = useCallback((d: DrawerState) => {
    navigate(`/predictive/detail/${d.kind}`, {
      state: { ...(histState ?? {}), pfoiDetail: d, pfoiDepth: detailDepth + 1 },
    });
  }, [navigate, histState, detailDepth]);

  const popDrawer = useCallback(() => {
    if (detailDepth > 0) navigate(-1);
  }, [navigate, detailDepth]);

  const closeDrawer = useCallback(() => {
    if (detailDepth > 0) navigate(-detailDepth);
    else navigate('/predictive', { replace: true, state: { ...(histState ?? {}), pfoiDetail: undefined, pfoiDepth: 0 } });
  }, [navigate, histState, detailDepth]);

  const go = useCallback((w: Workspace, tab?: HerdTab) => {
    setWorkspace(w);
    if (tab) setHerdTab(tab);
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      grain, setGrain,
      horizon, setHorizon,
      historyFrom, setHistoryFrom,
      workspace, herdTab, go,
      selectedPeriod, setSelectedPeriod,
      breakdownMonth, setBreakdownMonth,
      drawer, detailDepth, openDrawer, popDrawer, closeDrawer,
      acknowledged,
      acknowledge: (id) => setAcknowledged((s) => new Set(s).add(id)),
      restoreFindings: () => setAcknowledged(new Set()),
    }),
    [grain, setGrain, horizon, historyFrom, workspace, herdTab, go, selectedPeriod, breakdownMonth,
     drawer, detailDepth, openDrawer, popDrawer, closeDrawer, acknowledged],
  );

  return <PfoiContext.Provider value={value}>{children}</PfoiContext.Provider>;
}

export function usePfoi() {
  const c = useContext(PfoiContext);
  if (!c) throw new Error('usePfoi must be used inside PfoiProvider');
  return c;
}
