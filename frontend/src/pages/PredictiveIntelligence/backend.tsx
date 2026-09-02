import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../../services/api';
import type { Finding, HorizonId } from '../../data/component2';

export interface BackendOverview {
  label: string;
  days: number;
  start_date: string;
  end_date: string;
  average_daily_milk: number;
  average_per_cow: number;
  early_milk: number;
  late_milk: number;
  change_percent: number;
  dry_offs: number;
  entries: number;
  net_movement: number;
  confidence: 'High' | 'Moderate' | 'Limited';
  low_point: {
    date: string;
    expected: number;
    lower: number;
    upper: number;
    milkers: number;
    confidence: 'High' | 'Moderate' | 'Limited';
  };
  margin_gap_lkr_thousands: number;
  spark: number[];
}

export interface PredictiveSnapshot {
  farm: { id: string; name: string; populated: boolean };
  farms: { id: string; name: string; populated: boolean }[];
  generated_at: string;
  data_through: string;
  horizon: HorizonId;
  overview: BackendOverview;
  findings: Finding[];
  workspaces: Record<string, unknown>;
  source: 'deterministic_synthetic_backend';
  data_notice: string;
}

interface BackendState {
  snapshot: PredictiveSnapshot | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

const Context = createContext<BackendState | undefined>(undefined);

export function PredictiveBackendProvider({ farmId, horizon, children }: {
  farmId: string;
  horizon: HorizonId;
  children: ReactNode;
}) {
  const [snapshot, setSnapshot] = useState<PredictiveSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.get<PredictiveSnapshot>(`/predictive/farms/${farmId}/snapshot`, {
      params: { horizon },
      signal: controller.signal,
    }).then(({ data }) => {
      setSnapshot(data);
      setLoading(false);
    }).catch((requestError: unknown) => {
      if (controller.signal.aborted) return;
      setError(requestError instanceof Error ? requestError.message : 'Predictive backend unavailable');
      setLoading(false);
    });
    return () => controller.abort();
  }, [farmId, horizon, revision]);

  const value = useMemo(() => ({
    snapshot,
    loading,
    error,
    reload: () => setRevision((current) => current + 1),
  }), [snapshot, loading, error]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function usePredictiveBackend() {
  const context = useContext(Context);
  if (!context) throw new Error('PredictiveBackendProvider required');
  return context;
}
