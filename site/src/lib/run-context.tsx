/**
 * App-wide run selection and shared run state.
 *
 * Runs are immutable artefacts: the site selects one, and every screen reads
 * the same stats payload. Nothing here fabricates a run — when the API serves
 * no completed run, the context stays in an explicit "missing" state and each
 * screen renders its own empty state from it.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { asRunList } from "@/lib/client";
import { useApi, type AsyncState } from "@/hooks/useApi";
import type { RunDetail, RunStats, RunSummary } from "@/lib/api";

export type RunContextValue = {
  runs: AsyncState<RunSummary[]>;
  /** Null while no completed run is available. Never a placeholder id. */
  activeRunId: string | null;
  setActiveRunId: (id: string) => void;
  stats: AsyncState<RunStats | null>;
  detail: AsyncState<RunDetail | null>;
  /** True when the API is reachable but has no completed run to show. */
  hasNoRun: boolean;
  reloadAll: () => void;
};

const RunContext = createContext<RunContextValue | null>(null);

const PREF_KEY = "bkkflow.activeRunId";

export function RunProvider({ children }: { children: ReactNode }) {
  const [activeRunId, setActiveRunIdState] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem(PREF_KEY);
    } catch {
      return null;
    }
  });

  const rawRuns = useApi<unknown>("/v1/runs", []);
  const runs = useMemo<AsyncState<RunSummary[]>>(
    () => ({
      phase: rawRuns.phase,
      data: asRunList(rawRuns.data),
      error: rawRuns.error,
      loadedAt: rawRuns.loadedAt,
      reload: rawRuns.reload,
    }),
    [rawRuns.phase, rawRuns.data, rawRuns.error, rawRuns.loadedAt, rawRuns.reload],
  );

  // Keep the selection valid: prefer an explicit choice, else the newest run.
  useEffect(() => {
    if (runs.phase !== "ready") return;
    const list = runs.data ?? [];
    if (list.length === 0) {
      if (activeRunId !== null) setActiveRunIdState(null);
      return;
    }
    const known = list.some((run) => run?.run_id === activeRunId);
    if (!known) {
      setActiveRunIdState(typeof list[0]?.run_id === "string" ? list[0].run_id : null);
    }
  }, [runs.phase, runs.data, activeRunId]);

  const setActiveRunId = useCallback((id: string) => {
    setActiveRunIdState(id);
    try {
      window.localStorage.setItem(PREF_KEY, id);
    } catch {
      /* selection is a convenience, not state the model depends on */
    }
  }, []);

  const stats = useApi<RunStats | null>(
    activeRunId ? `/v1/runs/${encodeURIComponent(activeRunId)}/stats` : null,
    [activeRunId],
  );

  const detail = useApi<RunDetail | null>(
    activeRunId ? `/v1/runs/${encodeURIComponent(activeRunId)}` : null,
    [activeRunId],
  );

  const reloadAll = useCallback(() => {
    runs.reload();
    stats.reload();
    detail.reload();
  }, [runs, stats, detail]);

  const hasNoRun =
    activeRunId === null && (runs.phase === "ready" || runs.phase === "missing");

  const value = useMemo<RunContextValue>(
    () => ({
      runs,
      activeRunId,
      setActiveRunId,
      stats,
      detail,
      hasNoRun,
      reloadAll,
    }),
    [runs, activeRunId, setActiveRunId, stats, detail, hasNoRun, reloadAll],
  );

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>;
}

export function useRuns(): RunContextValue {
  const value = useContext(RunContext);
  if (!value) throw new Error("useRuns must be used inside <RunProvider>");
  return value;
}

/** The API base URL, shown so a reader can tell where the data came from. */
export { API_BASE_URL } from "@/lib/client";
