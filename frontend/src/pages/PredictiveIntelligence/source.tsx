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
  /** Model version published for each date (newest build per date). */
  models: Record<string, string>;
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

/* The listed dates are hidden only when an older model is the one published for them. */
const visibleOrigins = (origins: string[], models: Record<string, string> = {}, current?: string) =>
  origins.filter((origin) => !HIDDEN_ORIGINS.has(origin) || (!!current && models[origin] === current));

/** The current model: the one published for the newest date. */
const currentModel = (models: Record<string, string>) => {
  const dates = Object.keys(models).sort();
  return dates.length ? models[dates[dates.length - 1]] : undefined;
};

/** Older published runs stored MAE percentages as 25.05; the UI contract uses 0.2505. */
const normalizeRun = (run: PfoiRun): PfoiRun => ({
  ...run,
  qualityBands: (run.qualityBands ?? []).map((row) => ({
    ...row,
    mae_pct: row.mae_pct > 1 ? row.mae_pct / 100 : row.mae_pct,
  })),
});

/** Demo: February 2018 when present, else the earliest date. Model output: the newest date (the current model's). */
const startOrigin = (origins: string[], model = false) =>
  model ? origins[origins.length - 1] : origins.find((o) => o === '2018-02-01') ?? origins[0];

export function RunProvider({ children }: { children: ReactNode }) {
  const demoOrigins = visibleOrigins(DEMO_ORIGINS);
  const [origins, setOrigins] = useState<string[]>(demoOrigins);
  const [origin, setOriginState] = useState<string>(startOrigin(demoOrigins));
  const [model, setModel] = useState(false);
  const [runs, setRuns] = useState<Record<string, PfoiRun>>({});
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState<Record<string, string>>({});

  /* Which dates are published, and by which model. */
  useEffect(() => {
    let alive = true;
    api.get<{ source: string; runs: RunOrigin[] }>('/predictive/pfoi/runs')
      .then((r) => {
        const byDate: Record<string, string> = Object.fromEntries((r.data?.runs ?? []).map((x) => [x.origin_date, x.model_version]));
        const list = visibleOrigins(Object.keys(byDate).sort(), byDate, currentModel(byDate));
        if (!alive || r.data?.source !== 'model' || !list.length) return;
        setModel(true);
        setModels(byDate);
        setOrigins(list);
        setOriginState(startOrigin(list, true));
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
    () => ({ run: shown, origins, origin, setOrigin, loading, models }),
    [shown, origins, origin, setOrigin, loading, models],
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

/** Which model's forecast is shown, and how it relates to the current model (the newest date's). */
export function useModelOrigin() {
  const { models, origins, run } = useRunCtx();
  const current = currentModel(models) ?? null;
  const own = origins.filter((o) => models[o] === current);
  return {
    models, current, shown: run.model_version,
    isCurrent: !current || run.source === 'demo' || run.model_version === current,
    currentFrom: own[0] ?? null, currentTo: own[own.length - 1] ?? null,
  };
}

/** The forecast-date picker's state. */
export function useRunPicker() {
  const { origins, origin, setOrigin, loading, run } = useRunCtx();
  return { origins, origin, setOrigin, loading, shownOrigin: run.origin_date };
}
