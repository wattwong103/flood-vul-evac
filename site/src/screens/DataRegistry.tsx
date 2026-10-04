/**
 * Data Registry — `GET /v1/sources`.
 *
 * A dataset only reaches the pipeline when it is accessible to anyone *and*
 * explicitly reusable. Non-approved states are marked with a glyph and a
 * sentence as well as colour, and the reason a row is gated is shown.
 */

import { useMemo, useState } from "react";
import { ExternalLink, ShieldCheck } from "lucide-react";
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
import { ErrorState, LoadingState, PageIntro } from "@/components/primitives";
import { useApi } from "@/hooks/useApi";
import { asSourceList } from "@/lib/client";
import {
  isSourceStatus,
  SOURCE_STATUS_COPY,
  SOURCE_STATUSES,
  type SourceRecord,
  type SourceStatus,
} from "@/lib/api";
import { formatText, normaliseStatus } from "@/lib/format";

type Filter = "all" | SourceStatus;

export function DataRegistry() {
  const registry = useApi<unknown>("/v1/sources", []);
  const [filter, setFilter] = useState<Filter>("all");

  const sources = useMemo(() => asSourceList(registry.data), [registry.data]);

  const counts = useMemo(() => {
    const tally: Record<SourceStatus, number> = { approved: 0, verify: 0, rejected: 0 };
    for (const source of sources) {
      const status = normaliseStatus(source.status);
      if (isSourceStatus(status)) tally[status] += 1;
    }
    return tally;
  }, [sources]);

  const visible = useMemo(
    () =>
      filter === "all"
        ? sources
        : sources.filter((source) => {
            const status = normaliseStatus(source.status);
            return isSourceStatus(status) ? status === filter : false;
          }),
    [sources, filter],
  );

  return (
    <main className="page registry-page">
      <PageIntro
        kicker="03 · Evidence ledger"
        title="Every layer earns its place."
        lead="Public access and explicit reuse permission are both required. If either is missing the dataset stays out of the pipeline, and the registry says so."
      />

      <div className="registry-toolbar">
        <div className="chip-row" role="group" aria-label="Filter the registry by licence state">
          <Button
            size="sm"
            variant={filter === "all" ? "default" : "outline"}
            aria-pressed={filter === "all"}
            onClick={() => setFilter("all")}
          >
            all · {sources.length}
          </Button>
          {SOURCE_STATUSES.map((status) => (
            <Button
              key={status}
              size="sm"
              variant={filter === status ? "default" : "outline"}
              aria-pressed={filter === status}
              onClick={() => setFilter(status)}
            >
              <span aria-hidden="true">{SOURCE_STATUS_COPY[status].glyph}</span>{" "}
              {SOURCE_STATUS_COPY[status].label} · {counts[status]}
            </Button>
          ))}
        </div>
        <p className="muted">
          Served by <span className="mono">GET /v1/sources</span>
        </p>
      </div>

      {registry.phase === "loading" ? <LoadingState label="Reading the source registry" /> : null}
      {registry.phase === "error" && registry.error ? (
        <ErrorState error={registry.error} onRetry={registry.reload} context="Source registry." />
      ) : null}

      {registry.phase === "ready" && sources.length === 0 ? (
        <p className="state-block empty" role="status">
          <span>
            <strong>The registry is empty.</strong>
            <p>
              The API is reachable but has published no source records. No layer can be
              shown until a source passes the access and licence gate.
            </p>
          </span>
        </p>
      ) : null}

      {sources.length > 0 ? (
        <div className="registry-wrap">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Status</TableHead>
                <TableHead scope="col">Agency / dataset</TableHead>
                <TableHead scope="col">Model role</TableHead>
                <TableHead scope="col">Access</TableHead>
                <TableHead scope="col">Licence</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Resource link</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((source, index) => (
                <RegistryRow key={sourceKey(source, index)} source={source} />
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      <section className="policy-grid">
        <article>
          <ShieldCheck size={22} aria-hidden="true" />
          <h2>The two-part gate</h2>
          <p>
            A source moves to approved only when it is accessible to anyone and carries
            explicit permission for reuse. Approval is per dataset, not per agency.
          </p>
        </article>
        <article>
          <h2>Three states, not two</h2>
          <p>
            <b>Verify</b> is a real state: public, but the licence or access terms are not
            clear enough to ingest. It is not a softer approved.
          </p>
        </article>
        <article>
          <h2>Provenance per run</h2>
          <p>
            Every run records the source version, retrieval time, request parameters and a
            licence snapshot, so a result can be traced to the exact terms it used.
          </p>
        </article>
      </section>
    </main>
  );
}

function sourceKey(source: SourceRecord, index: number): string {
  return source.source_id ?? `${source.agency ?? "?"}/${source.dataset ?? index}`;
}

function RegistryRow({ source }: { source: SourceRecord }) {
  const raw = normaliseStatus(source.status);
  const status: SourceStatus | null = isSourceStatus(raw) ? raw : null;
  const copy = status ? SOURCE_STATUS_COPY[status] : null;
  const role = source.role ?? source.model_role ?? source.use ?? null;
  const url = source.resource_url ?? null;
  const notes = source.notes ?? null;

  return (
    <TableRow className={status === "approved" ? "row-approved" : "row-gated"}>
      <TableCell>
        <Badge
          variant="outline"
          className={`status-badge status-${status ?? "unknown"}`}
        >
          <span aria-hidden="true" className="status-glyph">
            {copy?.glyph ?? "?"}
          </span>
          {copy?.label ?? `unrecognised status: ${formatText(source.status)}`}
        </Badge>
      </TableCell>
      <TableCell>
        <strong>{formatText(source.agency)}</strong>
        <span className="cell-sub">{formatText(source.dataset)}</span>
      </TableCell>
      <TableCell>
        <span className="cell-sub">{formatText(role)}</span>
        {source.spatial_resolution || source.temporal_resolution ? (
          <span className="cell-sub muted">
            {formatText(source.spatial_resolution)} · {formatText(source.temporal_resolution)}
          </span>
        ) : null}
      </TableCell>
      <TableCell>
        <span className="cell-sub">{formatText(source.format)}</span>
        <span className="cell-sub muted">
          {formatText(source.authentication ?? null)} ·{" "}
          {formatText(source.live_or_historical ?? null)}
        </span>
      </TableCell>
      <TableCell>
        <span className="cell-sub">{formatText(source.licence)}</span>
        {copy && status !== "approved" ? (
          <span className="cell-sub cell-gate">{copy.sentence}</span>
        ) : null}
        {notes ? <span className="cell-sub muted">{notes}</span> : null}
        {source.reviewed_at || source.reviewer ? (
          <span className="cell-sub muted">
            reviewed {formatText(source.reviewed_at ?? null)}
            {source.reviewer ? ` · ${source.reviewer}` : ""}
          </span>
        ) : null}
      </TableCell>
      <TableCell>
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open ${formatText(source.dataset)} resource`}
            className="row-link"
          >
            <ExternalLink size={16} aria-hidden="true" />
          </a>
        ) : (
          <span className="muted">no URL</span>
        )}
      </TableCell>
    </TableRow>
  );
}
