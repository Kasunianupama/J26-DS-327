/**
 * Component 1 (PFOI): where the page gets its run, and which forecast date it shows.
 *
 * The backend lists the forecast dates with a published page document
 * (`GET /predictive/pfoi/runs`) and serves one per date
 * (`GET /predictive/pfoi/run?origin=`). Each run has the same `PfoiRun` shape, so
 * the charts do not change; runs at past dates also carry the recorded outcomes
 * (`realised`). The page opens on the first date of the final test block, so it
 * starts with forecasts that can be checked. If the API is unreachable or nothing is
 * published, the labelled demo runs (`source: 'demo'`) are used instead.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../../services/api';
import {
  DEMO_ORIGINS, demoRunAt,
  type PfoiRun, type RunOrigin,
} from '../../data/pfoi';

interface RunCtx {
  run: PfoiRun;
  /** Forecast dates the page can show, oldest first. */
  origins: string[];
  origin: string;
  setOrigin: (o: string) => void;
  /** True while a model run for the chosen date is being fetched. */
  loading: boolean;
}

const RunContext = createContext<RunCtx | undefined>(undefined);

const HIDDEN_ORIGINS = new Set([
  '2017-01-01',
  '2023-06-01',
  '2023-10-01',
  '2023-11-01',
  '2024-07-01',
  '2026-01-01',
  '2026-04-01',
  '2026-05-01',
]);

const visibleOrigins = (origins: string[]) => origins.filter((origin) => !HIDDEN_ORIGINS.has(origin));

/** Older published runs stored MAE percentages as 25.05; the UI contract uses 0.2505. */
const normalizeRun = (run: PfoiRun): PfoiRun => ({
  ...run,
  qualityBands: (run.qualityBands ?? []).map((row) => ({
    ...row,
    mae_pct: row.mae_pct > 1 ? row.mae_pct / 100 : row.mae_pct,
  })),
});

/** February 2018 when published, otherwise the earliest available date. */
const startOrigin = (origins: string[]) => origins.find((o) => o === '2018-02-01') ?? origins[0];

export function RunProvider({ children }: { children: ReactNode }) {
  const demoOrigins = visibleOrigins(DEMO_ORIGINS);
  const [origins, setOrigins] = useState<string[]>(demoOrigins);
  const [origin, setOriginState] = useState<string>(startOrigin(demoOrigins));
  const [model, setModel] = useState(false);
  const [runs, setRuns] = useState<Record<string, PfoiRun>>({});
  const [loading, setLoading] = useState(false);

  /* Which dates are published. */
  useEffect(() => {
    let alive = true;
    api.get<{ source: string; runs: RunOrigin[] }>('/predictive/pfoi/runs')
      .then((r) => {
        const list = visibleOrigins((r.data?.runs ?? []).map((x) => x.origin_date).sort());
        if (!alive || r.data?.source !== 'model' || !list.length) return;
        setModel(true);
        setOrigins(list);
        setOriginState(startOrigin(list));
      })
      .catch(() => { /* not published or API offline: keep the labelled demo runs */ });
    return () => { alive = false; };
  }, []);

  /* The run for the chosen date (fetched once per date). */
  useEffect(() => {
    if (!model || runs[origin]) return;
    let alive = true;
    setLoading(true);
    api.get<PfoiRun>('/predictive/pfoi/run', { params: { origin } })
      .then((r) => { if (alive && r.data?.source === 'model') setRuns((m) => ({ ...m, [origin]: normalizeRun(r.data) })); })
      .catch(() => { /* keep showing the previous run */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [model, origin, runs]);

  const setOrigin = useCallback((o: string) => setOriginState(o), []);

  /* While a model run loads, keep the last one shown rather than flashing the demo. */
  const [shown, setShown] = useState<PfoiRun>(() => demoRunAt(startOrigin(demoOrigins)));
  useEffect(() => {
    if (!model) setShown(demoRunAt(origin));
    else if (runs[origin]) setShown(runs[origin]);
  }, [model, origin, runs]);

  const value = useMemo<RunCtx>(
    () => ({ run: shown, origins, origin, setOrigin, loading }),
    [shown, origins, origin, setOrigin, loading],
  );
  return <RunContext.Provider value={value}>{children}</RunContext.Provider>;
}

function useRunCtx() {
  const c = useContext(RunContext);
  if (!c) throw new Error('useRun must be used inside RunProvider');
  return c;
}

export function useRun() {
  return useRunCtx().run;
}

/** The forecast-date picker's state. */
export function useRunPicker() {
  const { origins, origin, setOrigin, loading, run } = useRunCtx();
  return { origins, origin, setOrigin, loading, shownOrigin: run.origin_date };
}
