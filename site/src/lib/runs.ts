/**
 * Ordinary runs and sensitivity-ensemble case runs share one run list.
 *
 * A case run varies one factor of the baseline to show how much the result
 * moves; it is not a scenario a reader should land on by default, and wherever
 * it is listed it says which case it is.
 */

import type { RunSummary } from "./api";
// The extension lets the Node test runner resolve this runtime import.
import { formatTimestamp } from "./format.ts";

/** The sensitivity case a run belongs to, or null for an ordinary run. */
export function caseIdOf(run: RunSummary | null | undefined): string | null {
  const caseId = run?.active_scenario?.case_id;
  return typeof caseId === "string" && caseId ? caseId : null;
}

/** The run the site opens on: the newest ordinary run, else the newest run. */
export function defaultRunId(runs: readonly RunSummary[]): string | null {
  const chosen = runs.find((run) => caseIdOf(run) === null) ?? runs[0];
  return typeof chosen?.run_id === "string" ? chosen.run_id : null;
}

/** Keep a choice the list still has; otherwise fall back to the default run. */
export function resolveActiveRunId(
  runs: readonly RunSummary[],
  current: string | null,
): string | null {
  if (current !== null && runs.some((run) => run?.run_id === current)) return current;
  return defaultRunId(runs);
}

/** "sensitivity case <id>" for a case run; null for an ordinary run. */
export function caseRunLabel(run: RunSummary | null | undefined): string | null {
  const caseId = caseIdOf(run);
  return caseId ? `sensitivity case ${caseId}` : null;
}

/** One line of the run picker. */
export function runOptionLabel(run: RunSummary): string {
  return [
    run.run_id.slice(0, 8),
    formatTimestamp(run.created_at),
    run.status || null,
    caseRunLabel(run),
  ]
    .filter(Boolean)
    .join(" · ");
}
