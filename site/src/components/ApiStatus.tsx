import { useRuns, API_BASE_URL } from "@/lib/run-context";
import { resolveValidationStatus } from "@/components/primitives";
import { formatText } from "@/lib/format";
import { caseRunLabel } from "@/lib/runs";

/** Live reachability of the API, so a blank screen is never ambiguous. */
export function ApiStatus() {
  const { runs, stats, activeRunId } = useRuns();
  const activeRun = runs.data?.find((run) => run?.run_id === activeRunId);
  const status = resolveValidationStatus(
    stats.data?.validation_status ?? activeRun?.validation_status ?? null,
  );
  const caseLabel = caseRunLabel(activeRun);

  return (
    <span className="api-status">
      <span
        aria-hidden="true"
        className={`api-dot state-${runs.phase}`}
      />
      <span className="mono">{API_BASE_URL}</span>
      <span>
        {runs.phase === "error"
          ? "unreachable"
          : runs.phase === "loading"
            ? "checking"
            : runs.phase === "missing"
              ? "no run yet"
              : activeRunId
                ? `run ${activeRunId.slice(0, 8)} · ${formatText(status)}${caseLabel ? ` · ${caseLabel}` : ""}`
                : "no completed run"}
      </span>
    </span>
  );
}
