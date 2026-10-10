import { validationChecks } from "@/lib/validation";
/**
 * Run detail — the PFLOW stage rail, the manifest, and the validation report.
 *
 * Per-stage status and row counts come from `run_state.json` via
 * `GET /v1/runs/{id}`, with `stats.json`'s `stages` used as a fallback.
 */

import {
  CircleAlert,
  Download,
  FileWarning,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ErrorState,
  LoadingState,
  NoRunState,
  PageIntro,
  Panel,
  ValidationStamp,
  ValidationStatusNote,
} from "@/components/primitives";
import { useApi } from "@/hooks/useApi";
import type { AsyncPhase } from "@/hooks/useApi";
import { ApiError } from "@/lib/client";
import { API_BASE_URL, useRuns } from "@/lib/run-context";
import type { StageRecord } from "@/lib/api";
import {
  formatCount,
  formatDuration,
  formatText,
  formatTimestamp,
  normaliseStatus,
} from "@/lib/format";

/** The PFLOW stage sequence, as the plan defines it. */
const PILOT_RAIL = [
  "people",
  "activities",
  "trips",
  "trajectories",
  "flood",
  "evacuation",
];

const STATUS_GLYPH: Record<string, string> = {
  completed: "✓",
  done: "✓",
  success: "✓",
  running: "◐",
  in_progress: "◐",
  pending: "○",
  queued: "○",
  skipped: "–",
  failed: "✕",
  error: "✕",
  partial: "◑",
};

function statusGlyph(status: string): string {
  return STATUS_GLYPH[normaliseStatus(status)] ?? "?";
}

function stageName(value: string | null | undefined): string {
  return formatText(value).toLowerCase();
}

function cityRail(stages: StageRecord[]): string[] {
  return [...new Set(
    stages.flatMap((stage) => {
      const value = stage.stage?.trim();
      return value ? [stageName(value)] : [];
    }),
  )];
}

export function StageRail({
  scale,
  stages,
}: {
  scale: string | null | undefined;
  stages: StageRecord[];
}) {
  const names = scale === "city" ? cityRail(stages) : PILOT_RAIL;
  return (
    <>
      <ol className="stage-rail">
        {names.map((name) => {
          const match = stages.find(
            (stage) => stageName(stage.stage).includes(name) ||
              name.includes(stageName(stage.stage)),
          );
          const state = normaliseStatus(match?.status ?? null) || "not reported";
          return (
            <li key={name} className={`stage state-${state.replace(/\s+/g, "-")}`}>
              <span className="stage-glyph" aria-hidden="true">
                {statusGlyph(state)}
              </span>
              <div>
                <b>{name}</b>
                <small>{state}</small>
              </div>
              <span className="stage-rows">
                {match && match.rows !== undefined && match.rows !== null
                  ? `${formatCount(match.rows)} rows`
                  : "row count not reported"}
              </span>
              <span className="stage-time">
                {match ? formatDuration(match.seconds ?? null) : ""}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="panel-note">
        <CircleAlert size={14} aria-hidden="true" />
        {scale === "city"
          ? "City stages are shown in their recorded order; no unreported stage is inferred."
          : "A stage the run never reported is shown as “not reported”, which is not the same as completed."}
      </p>
    </>
  );
}

const MISSING_DETAIL_ERROR = new ApiError(
  "http",
  0,
  "Run detail is unavailable and the request returned no diagnostic details.",
);

export function RunDetailFailure({
  phase,
  error,
  onRetry,
}: {
  phase: AsyncPhase;
  error: ApiError | null;
  onRetry: () => void;
}) {
  if (phase !== "error") return null;
  return (
    <ErrorState
      error={error ?? MISSING_DETAIL_ERROR}
      onRetry={onRetry}
      context="Run detail."
    />
  );
}

export function RunDetail() {
  const { activeRunId, detail, stats, hasNoRun, reloadAll } = useRuns();
  const encoded = activeRunId ? encodeURIComponent(activeRunId) : null;

  const validation = useApi<Record<string, unknown>>(
    encoded ? `/v1/runs/${encoded}/validation` : null,
    [activeRunId],
  );

  const manifest = detail.data?.manifest ?? null;
  const status =
    detail.data?.validation_status ?? stats.data?.validation_status ?? null;
  const scale = stats.data?.scale;

  const stages = pickStages(detail.data?.stages, stats.data?.stages);

  const warnings = [
    ...toStringArray(detail.data?.warnings),
    ...toStringArray(stats.data?.warnings),
  ];

  const exportHref = encoded ? `${API_BASE_URL}/v1/runs/${encoded}/export` : null;

  return (
    <main className="page run-page">
      <PageIntro
        kicker="05 · Run detail"
        title="One run, in full."
        lead="A run is immutable. Everything below is what the artefact recorded: the stage rail with row counts, the manifest that pins the inputs, and the validation report that says what was checked."
        aside={
          exportHref ? (
            <Button variant="outline" onClick={() => window.open(exportHref, "_blank")}>
              <Download size={15} aria-hidden="true" /> Export manifest and artefacts
            </Button>
          ) : null
        }
      />

      {hasNoRun ? (
        <NoRunState what="run detail" onReload={reloadAll} />
      ) : null}

      <RunDetailFailure
        phase={detail.phase}
        error={detail.error}
        onRetry={detail.reload}
      />

      {!hasNoRun && detail.phase !== "error" ? (
        <>
          <Panel
            title="PFLOW stage rail"
            description="Per-stage status and row counts, exactly as the run recorded them."
            actions={<ValidationStamp status={status} modelTime={formatText(detail.data?.created_at ?? null)} compact />}
          >
            {detail.phase === "loading" ? <LoadingState label="Reading run state" /> : null}
            {stages.length === 0 ? (
              <p className="muted">
                This run published no stage records, so the rail cannot be drawn. A run
                with no stage record has not demonstrated that any stage completed.
              </p>
            ) : null}
            {stages.length > 0 ? (
              <StageRail scale={scale} stages={stages} />
            ) : null}

            {stages.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">Stage</TableHead>
                    <TableHead scope="col">Status</TableHead>
                    <TableHead scope="col">Rows</TableHead>
                    <TableHead scope="col">Duration</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stages.map((stage, index) => (
                    <TableRow key={`${stage.stage ?? index}`}>
                      <TableCell>{formatText(stage.stage)}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="status-badge">
                          <span aria-hidden="true" className="status-glyph">
                            {statusGlyph(String(stage.status ?? ""))}
                          </span>
                          {formatText(stage.status)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {stage.rows === null || stage.rows === undefined
                          ? "not available"
                          : formatCount(stage.rows)}
                      </TableCell>
                      <TableCell>{formatDuration(stage.seconds ?? null)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : null}
          </Panel>

          <section className="run-grid">
            <Panel title="Manifest" description="The immutable inputs this run was built from.">
              {manifest ? (
                <dl className="kv">
                  <div>
                    <dt>Run</dt>
                    <dd className="mono">{formatText(manifest.run_id ?? activeRunId)}</dd>
                  </div>
                  <div>
                    <dt>Created</dt>
                    <dd>{formatTimestamp(manifest.created_at ?? null)}</dd>
                  </div>
                  <div>
                    <dt>Validation status</dt>
                    <dd>{formatText(manifest.validation_status ?? status)}</dd>
                  </div>
                  <div>
                    <dt>Licence registry</dt>
                    <dd className="mono">
                      {formatText(manifest.licence_registry_version ?? null)}
                    </dd>
                  </div>
                  <div>
                    <dt>Network version</dt>
                    <dd className="mono">{formatText(manifest.network_version ?? null)}</dd>
                  </div>
                  <div>
                    <dt>Source versions</dt>
                    <dd>{formatCount((manifest.source_versions ?? []).length || null)}</dd>
                  </div>
                  <div>
                    <dt>Outputs</dt>
                    <dd>{formatCount((manifest.outputs ?? []).length || null)}</dd>
                  </div>
                </dl>
              ) : (
                <p className="muted">
                  This run published no manifest, so its inputs cannot be pinned. Without a
                  manifest a result cannot be reproduced or challenged.
                </p>
              )}
            </Panel>

            <Panel title="Warnings" description="Carried by the run, shown verbatim.">
              {warnings.length === 0 ? (
                <p className="muted">
                  The run recorded no warnings. A run with no warnings is a claim, not a
                  guarantee.
                </p>
              ) : (
                <ul className="warning-list">
                  {warnings.map((warning, index) => (
                    <li key={`${warning}-${index}`}>
                      <FileWarning size={15} aria-hidden="true" />
                      <span>{warning}</span>
                    </li>
                  ))}
                </ul>
              )}
              <ValidationStatusNote status={status} />
            </Panel>
          </section>

          <Panel
            title="Validation report"
            description="Every check with its threshold and result. A check that was not run is shown as not run."
          >
            {validation.phase === "loading" ? <LoadingState label="Reading validation report" /> : null}
            {validation.phase === "error" && validation.error ? (
              <ErrorState error={validation.error} onRetry={validation.reload} />
            ) : null}
            {validation.phase === "missing" ? (
              <p className="muted">
                This run published no validation report. HTTP 404 for a validation report
                is not a passing result.
              </p>
            ) : null}
            {validation.phase === "ready" ? <ValidationChecks report={validation.data ?? {}} /> : null}
          </Panel>

          <section className="run-foot">
            <p className="muted mono">
              run {activeRunId ?? "none"} · created{" "}
              {formatTimestamp(
                detail.data?.created_at ?? stats.data?.created_at ?? null,
              )}
            </p>
            <p className="muted">
              The API serves no person-level trajectory set. A single trip lookup is the
              finest granularity the contract allows, and this site does not request one.
            </p>
          </section>
        </>
      ) : null}
    </main>
  );
}

function pickStages(
  fromDetail: StageRecord[] | null | undefined,
  fromStats: StageRecord[] | null | undefined,
): StageRecord[] {
  if (Array.isArray(fromDetail) && fromDetail.length > 0) return fromDetail;
  if (Array.isArray(fromStats)) return fromStats;
  return [];
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        const text = record.message ?? record.warning ?? record.text;
        if (typeof text === "string") return text;
        return JSON.stringify(record);
      }
      return String(item);
    })
    .filter((text) => text.trim().length > 0);
}

function ValidationChecks({ report }: { report: Record<string, unknown> }) {
  const checks = validationChecks(report);

  if (checks.length === 0) {
    return (
      <p className="muted">
        The report contains no individual checks. An empty report cannot be read as a
        successful one.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Check</TableHead>
          <TableHead scope="col">Result</TableHead>
          <TableHead scope="col">Threshold</TableHead>
          <TableHead scope="col">Outcome</TableHead>
          <TableHead scope="col">Notes</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {checks.map((check, index) => {
          const name = String(check.name ?? check.check ?? `check ${index + 1}`);
          const passed =
            typeof check.passed === "boolean"
              ? check.passed
              : normaliseStatus(String(check.status ?? "")) === "pass";
          const notRun = check.passed === null && check.result === undefined;
          return (
            <TableRow key={`${name}-${index}`}>
              <TableCell>{name}</TableCell>
              <TableCell>{formatText(check.result as string | null)}</TableCell>
              <TableCell>{formatText(check.threshold as string | null)}</TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={`status-badge ${passed ? "status-approved" : "status-rejected"}`}
                >
                  <span aria-hidden="true" className="status-glyph">
                    {notRun ? "○" : passed ? "✓" : "✕"}
                  </span>
                  {notRun ? "not run" : passed ? "pass" : "fail"}
                </Badge>
              </TableCell>
              <TableCell className="cell-sub">{formatText(check.notes as string | null)}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
