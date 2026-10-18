/**
 * Component 1 (PFOI): where the page gets its run.
 *
 * Until the model writes `c1_output` and the Step 6 route serves it, this
 * provides the deterministic demo run, and says so (`source: 'demo'`). Step 6
 * replaces `loadRun` with an API call that returns the same `PfoiRun` shape.
 */

import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { demoRun, type PfoiRun } from '../../data/pfoi';

const loadRun = (): PfoiRun => demoRun();

const RunContext = createContext<PfoiRun | undefined>(undefined);

export function RunProvider({ children }: { children: ReactNode }) {
  const run = useMemo(loadRun, []);
  return <RunContext.Provider value={run}>{children}</RunContext.Provider>;
}

export function useRun() {
  const run = useContext(RunContext);
  if (!run) throw new Error('useRun must be used inside RunProvider');
  return run;
}
