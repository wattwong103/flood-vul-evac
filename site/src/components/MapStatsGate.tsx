import type { ReactNode } from "react";
import type { AsyncState } from "@/hooks/useApi";
import type { RunStats } from "@/lib/api";
import { ErrorState, LoadingState } from "@/components/primitives";

/** The selected run's scope must be known before loading its geometry. */
export function MapStatsGate({ stats, runId, children }: {
  stats: AsyncState<RunStats | null>; runId: string | null; children: ReactNode;
}) {
  if (stats.phase === "error" && stats.error)
    return <ErrorState error={stats.error} onRetry={stats.reload} context="Map run statistics." />;
  if (stats.phase === "missing")
    return <p role="status">Map details are unavailable because this run has no statistics.</p>;
  if (stats.phase !== "ready" || !stats.data || stats.data.run_id !== runId)
    return <LoadingState label="Reading run statistics before loading map details" />;
  return children;
}
